"""In-process portfolio simulation.

Runs the real checkout, payment, dunning, reminder, and rollup code against the
configured database, then rolls the whole transaction back so the command is
repeatable and never pollutes development data.
"""

from __future__ import annotations

import csv
import random
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Member
from apps.catalog.models import Product
from apps.payments.gateway import SeededRandomGateway
from apps.payments.models import Payment, PaymentStatus
from apps.payments.tasks import run_dunning, run_scheduled_charges, send_due_reminders
from apps.plans.models import (
    Installment,
    InstallmentPlan,
    InstallmentStatus,
    PlanRollup,
    PlanStatus,
)
from apps.plans.services import CheckoutDeclined, checkout
from apps.plans.tasks import nightly_rollup

SIM_PRODUCTS = [
    ("SIM-HEADPHONES", "Studio Headphones", 18_900),
    ("SIM-LAPTOP", "14-inch Laptop", 129_900),
    ("SIM-SOFA", "Modular Sofa", 89_000),
    ("SIM-PHONE", "Smartphone", 74_900),
    ("SIM-SHOES", "Running Shoes", 12_500),
    ("SIM-TV", "55-inch TV", 54_900),
]


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


class Command(BaseCommand):
    help = "Simulate a PayPlan portfolio end-to-end and write results artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--members", type=int, default=500)
        parser.add_argument("--days", type=int, default=120)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--results-dir", default=str(settings.BASE_DIR / "results"))

    def handle(self, *args, **options):
        members_count = options["members"]
        days = options["days"]
        seed = options["seed"]
        output_dir = Path(options["results_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # The simulation prints its own report; keep per-charge task logs out of it.
        import logging

        logging.getLogger("apps").setLevel(logging.WARNING)

        started = time.perf_counter()
        rng = random.Random(seed)
        sim_start = timezone.localdate() - timedelta(days=days - 1)
        sim_end = sim_start + timedelta(days=days - 1)
        gateway = SeededRandomGateway(
            seed=seed,
            first_failure_rate=getattr(settings, "SIM_FIRST_FAILURE_RATE", 0.10),
            retry_failure_rate=getattr(settings, "SIM_RETRY_FAILURE_RATE", 0.35),
        )

        with transaction.atomic():
            members = self._seed_members(members_count, seed, rng)
            products = self._seed_products()

            orders_by_day = defaultdict(list)
            for member in members:
                for _ in range(rng.choice([1, 1, 2])):
                    order_day = rng.randint(0, max(days - 45, 1))
                    orders_by_day[order_day].append(member)

            plans_created = 0
            declined = 0
            for day_offset in range(days):
                day = sim_start + timedelta(days=day_offset)
                now = datetime.combine(day, dt_time(10, 0), tzinfo=UTC)

                for member in orders_by_day.get(day_offset, []):
                    product = rng.choice(products)
                    try:
                        checkout(
                            member,
                            product,
                            qty=1,
                            n=rng.choice([4, 4, 6, 8]),
                            cadence=rng.choice(["BIWEEKLY", "MONTHLY"]),
                            start_date=day,
                        )
                        plans_created += 1
                    except CheckoutDeclined:
                        declined += 1

                send_due_reminders(now=now)
                run_scheduled_charges(now=now, gateway=gateway)
                run_dunning(now=now, gateway=gateway)
                nightly_rollup(day=day)

                if days >= 40 and (day_offset + 1) % 20 == 0:
                    self.stdout.write(f"  simulated {day_offset + 1}/{days} days")

            metrics = self._collect_metrics(
                members, sim_start, sim_end, plans_created, declined, gateway
            )
            rollups = list(
                PlanRollup.objects.filter(date__gte=sim_start, date__lte=sim_end).order_by("date")
            )
            runtime = time.perf_counter() - started

            self._write_simulation(
                output_dir / "simulation.txt", metrics, runtime, members_count, days, seed
            )
            self._write_rollups(output_dir / "rollups.csv", rollups)

            # Keep the developer database untouched; artifacts are already on disk.
            transaction.set_rollback(True)

        self._print_report(metrics, runtime, members_count, days, seed)

    # ------------------------------------------------------------------ seeding
    def _seed_members(self, count, seed, rng):
        User = get_user_model()
        prefix = f"sim{seed}_"
        users = [
            User(username=f"{prefix}{index}", email=f"{prefix}{index}@sim.payplan.local")
            for index in range(count)
        ]
        User.objects.bulk_create(users, batch_size=500)
        created_users = list(User.objects.filter(username__startswith=prefix).order_by("id"))
        members = [
            Member(
                user=user,
                base_limit_cents=rng.randint(300_000, 800_000),
                risk_tier=rng.choice(["PRIME", "NEAR_PRIME", "SUBPRIME"]),
            )
            for user in created_users[:count]
        ]
        Member.objects.bulk_create(members, batch_size=500)
        return list(Member.objects.filter(user__username__startswith=prefix).order_by("id"))

    def _seed_products(self):
        products = []
        for sku, name, price in SIM_PRODUCTS:
            product, _ = Product.objects.update_or_create(
                sku=sku, defaults={"name": name, "price_cents": price, "active": True}
            )
            products.append(product)
        return products

    # ------------------------------------------------------------------ metrics
    def _collect_metrics(self, members, sim_start, sim_end, plans_created, declined, gateway):
        member_ids = [m.id for m in members]
        plans = InstallmentPlan.objects.filter(member_id__in=member_ids)
        installments = Installment.objects.filter(
            plan__member_id__in=member_ids, due_date__lte=sim_end
        )
        billed_cents = installments.aggregate(total=Sum("amount_cents"))["total"] or 0
        paid = list(installments.filter(status=InstallmentStatus.PAID))
        on_time = sum(
            1
            for inst in paid
            if inst.paid_at and timezone.localtime(inst.paid_at).date() <= inst.due_date
        )
        collected_cents = (
            Payment.objects.filter(
                member_id__in=member_ids, status=PaymentStatus.SUCCEEDED
            ).aggregate(total=Sum("amount_cents"))["total"]
            or 0
        )
        retries = Payment.objects.filter(member_id__in=member_ids, attempt_no__gt=1)
        retry_count = retries.count()
        recovered = retries.filter(status=PaymentStatus.SUCCEEDED).count()
        delinquent_plans = plans.filter(status=PlanStatus.DELINQUENT).count()
        plans_with_late = (
            plans.filter(installments__status=InstallmentStatus.LATE).distinct().count()
        )
        limit_changes = []
        limit_pcts = []
        for member in members:
            latest = member.spending_limits.order_by("-id").first()
            if latest:
                change = latest.limit_cents - member.base_limit_cents
                limit_changes.append(change)
                limit_pcts.append(
                    change / member.base_limit_cents if member.base_limit_cents else 0
                )
        avg_change = int(sum(limit_changes) / len(limit_changes)) if limit_changes else 0
        avg_pct = (sum(limit_pcts) / len(limit_pcts) * 100) if limit_pcts else 0

        return {
            "plans_created": plans_created,
            "declined_orders": declined,
            "installments_billed": installments.count(),
            "billed_cents": billed_cents,
            "collected_cents": collected_cents,
            "on_time_rate": (on_time / len(paid) * 100) if paid else 0.0,
            "delinquency_rate": (
                max(delinquent_plans, plans_with_late) / plans_created * 100
                if plans_created
                else 0.0
            ),
            "dunning_recovery_rate": (recovered / retry_count * 100) if retry_count else 0.0,
            "retry_attempts": retry_count,
            "avg_limit_change_cents": avg_change,
            "avg_limit_change_pct": avg_pct,
            "gateway_attempts": gateway.charges,
            "sim_start": sim_start,
            "sim_end": sim_end,
        }

    # ------------------------------------------------------------------- output
    def _write_simulation(self, path, metrics, runtime, members_count, days, seed):
        lines = [
            "PayPlan portfolio simulation",
            "============================",
            f"Config:            {members_count} members / {days} days / seed {seed}",
            f"Window:            {metrics['sim_start']} .. {metrics['sim_end']}",
            f"Runtime:           {runtime:.2f}s",
            "",
            "Metric                          Value",
            "---------------------------------------------------------",
            f"Plans created                   {metrics['plans_created']:,}",
            f"Orders declined for limit       {metrics['declined_orders']:,}",
            f"Installments billed             {metrics['installments_billed']:,}",
            f"Total billed                    {money(metrics['billed_cents'])}",
            f"Total collected                 {money(metrics['collected_cents'])}",
            f"On-time payment rate            {metrics['on_time_rate']:.2f}%",
            f"Delinquency rate                {metrics['delinquency_rate']:.2f}%",
            f"Dunning recovery rate           {metrics['dunning_recovery_rate']:.2f}%",
            f"Retry attempts                  {metrics['retry_attempts']:,}",
            f"Average limit change            {money(metrics['avg_limit_change_cents'])} "
            f"({metrics['avg_limit_change_pct']:+.2f}%)",
            f"Gateway attempts                {metrics['gateway_attempts']:,}",
            "",
            "Command: python backend/manage.py simulate_portfolio "
            f"--members {members_count} --days {days} --seed {seed}",
            "Per-day rollups: results/rollups.csv",
        ]
        path.write_text("\n".join(lines) + "\n")

    def _write_rollups(self, path, rollups):
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "date",
                    "active_plans",
                    "delinquent_plans",
                    "billed_cents",
                    "collected_cents",
                    "on_time_rate",
                    "dunning_recovery_rate",
                ]
            )
            for rollup in rollups:
                writer.writerow(
                    [
                        rollup.date.isoformat(),
                        rollup.active_plans,
                        rollup.delinquent_plans,
                        rollup.billed_cents,
                        rollup.collected_cents,
                        f"{rollup.on_time_rate:.4f}",
                        f"{rollup.dunning_recovery_rate:.4f}",
                    ]
                )

    def _print_report(self, metrics, runtime, members_count, days, seed):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("PayPlan portfolio simulation"))
        self.stdout.write(f"  {members_count} members / {days} days / seed {seed}")
        self.stdout.write(f"  plans created:            {metrics['plans_created']:,}")
        self.stdout.write(f"  installments billed:      {metrics['installments_billed']:,}")
        self.stdout.write(f"  total billed:             {money(metrics['billed_cents'])}")
        self.stdout.write(f"  total collected:          {money(metrics['collected_cents'])}")
        self.stdout.write(f"  on-time payment rate:     {metrics['on_time_rate']:.2f}%")
        self.stdout.write(f"  delinquency rate:         {metrics['delinquency_rate']:.2f}%")
        self.stdout.write(f"  dunning recovery rate:    {metrics['dunning_recovery_rate']:.2f}%")
        self.stdout.write(
            f"  avg spending-limit change:{money(metrics['avg_limit_change_cents'])} "
            f"({metrics['avg_limit_change_pct']:+.2f}%)"
        )
        self.stdout.write(f"  wall-clock runtime:       {runtime:.2f}s")
        self.stdout.write("  wrote results/simulation.txt and results/rollups.csv")
