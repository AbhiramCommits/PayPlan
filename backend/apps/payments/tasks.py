"""Celery beat tasks: reminders, scheduled charges, and dunning.

Every function accepts an explicit ``now``/``gateway`` so tests can time-travel
with freezegun and the portfolio simulation can run the same code in-process.
All tasks are safe to run twice on the same day.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payments.gateway import get_gateway
from apps.payments.models import Notification, Payment, PaymentStatus
from apps.payments.services import process_payment
from apps.plans.models import Installment, InstallmentStatus, PlanStatus
from apps.plans.services import recalculate_limit

logger = logging.getLogger(__name__)


def _date(now):
    return timezone.localtime(now).date()


def send_due_reminders(now=None):
    """One notification per installment/template/day, for T-3 and T-0."""
    now = now or timezone.now()
    today = _date(now)
    targets = []
    for offset, template in ((settings.REMINDER_LEAD_DAYS, "due_soon"), (0, "due_today")):
        day = today + timedelta(days=offset)
        for installment in Installment.objects.filter(
            due_date=day,
            status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.DUE],
        ).select_related("plan"):
            targets.append((installment, template))

    created = 0
    for installment, template in targets:
        _notification, was_created = Notification.objects.get_or_create(
            dedupe_key=f"inst:{installment.id}:{template}:{today.isoformat()}",
            defaults={
                "member_id": installment.plan.member_id,
                "installment": installment,
                "channel": Notification.CHANNEL_EMAIL,
                "template": template,
                "sent_at": now,
            },
        )
        created += int(was_created)
    return {"notifications": created}


def run_scheduled_charges(now=None, gateway=None):
    """Charge every installment due today or earlier.

    Uses ``inst:{id}:attempt:{n}`` so a second run on the same day is a no-op.
    """
    now = now or timezone.now()
    today = _date(now)
    gateway = gateway or get_gateway()
    due = (
        Installment.objects.filter(
            due_date__lte=today,
            status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.DUE],
            plan__status=PlanStatus.ACTIVE,
        )
        .select_related("plan", "plan__member")
        .order_by("due_date", "id")
    )

    charged = failed = skipped = 0
    for installment in due:
        attempt_no = Payment.objects.filter(installment=installment).count() + 1
        key = f"inst:{installment.id}:attempt:{attempt_no}"
        if Payment.objects.filter(idempotency_key=key).exists():
            skipped += 1
            continue
        outcome, http_status = process_payment(
            member=installment.plan.member,
            installment=installment,
            idempotency_key=key,
            gateway=gateway,
            now=now,
        )
        if outcome.payment.status == PaymentStatus.SUCCEEDED:
            charged += 1
        else:
            failed += 1
        logger.info(
            "scheduled charge installment=%s status=%s http=%s",
            installment.id,
            outcome.payment.status,
            http_status,
        )
    return {"charged": charged, "failed": failed, "skipped": skipped}


def _finalize_delinquency(installment, now):
    with transaction.atomic():
        locked = (
            Installment.objects.select_for_update().select_related("plan").get(pk=installment.pk)
        )
        if locked.is_settled:
            return
        locked.status = InstallmentStatus.LATE
        locked.save(update_fields=["status"])
        plan = locked.plan
        if plan.status != PlanStatus.COMPLETED:
            plan.status = PlanStatus.DELINQUENT
            plan.save(update_fields=["status"])
        recalculate_limit(plan.member, as_of=_date(now))


def retry_failed_payment(payment_id, now=None, gateway=None):
    """Attempt the next dunning retry, respecting 1d/3d/7d backoff.

    Called immediately after a failure (defers), by beat through ``run_dunning``,
    and scheduled with ``apply_async(countdown=...)`` in production.
    """
    now = now or timezone.now()
    gateway = gateway or get_gateway()
    try:
        payment = Payment.objects.select_related("installment", "member").get(pk=payment_id)
    except Payment.DoesNotExist:
        return {"status": "missing"}

    if payment.status != PaymentStatus.FAILED:
        return {"status": "not_failed"}
    if payment.installment is None or payment.installment.is_settled:
        return {"status": "settled"}

    # Only the newest failed attempt is eligible; older rows are superseded.
    latest = (
        Payment.objects.filter(installment=payment.installment)
        .order_by("-attempt_no", "-created_at")
        .first()
    )
    if latest.id != payment.id:
        return {"status": "superseded"}

    if latest.attempt_no > settings.DUNNING_MAX_RETRIES:
        _finalize_delinquency(latest.installment, now)
        return {"status": "delinquent", "payment_id": latest.id}

    delay_days = settings.DUNNING_BACKOFF_DAYS[min(latest.attempt_no, 3) - 1]
    due_at = latest.created_at + timedelta(days=delay_days)
    if now < due_at:
        if not settings.CELERY_TASK_ALWAYS_EAGER:
            retry_failed_payment_task.apply_async(
                args=[latest.id], countdown=max(int((due_at - now).total_seconds()), 1)
            )
        return {"status": "deferred", "retry_at": due_at.isoformat()}

    key = f"inst:{latest.installment_id}:attempt:{latest.attempt_no + 1}"
    if Payment.objects.filter(idempotency_key=key).exists():
        return {"status": "already_attempted"}

    outcome, _http = process_payment(
        member=latest.member,
        installment=latest.installment,
        idempotency_key=key,
        gateway=gateway,
        now=now,
        enqueue_dunning=False,
    )
    new_payment = outcome.payment
    if new_payment.status == PaymentStatus.SUCCEEDED:
        return {"status": "recovered", "attempt_no": new_payment.attempt_no}
    if new_payment.attempt_no > settings.DUNNING_MAX_RETRIES:
        _finalize_delinquency(new_payment.installment, now)
        return {"status": "delinquent", "attempt_no": new_payment.attempt_no}
    return {"status": "failed", "attempt_no": new_payment.attempt_no}


def run_dunning(now=None, gateway=None):
    """Find the latest failed attempt per installment and retry those due."""
    now = now or timezone.now()
    gateway = gateway or get_gateway()
    latest_by_installment = {}
    failed = (
        Payment.objects.filter(
            status=PaymentStatus.FAILED,
            installment__isnull=False,
        )
        .exclude(installment__status__in=[InstallmentStatus.PAID, InstallmentStatus.WAIVED])
        .order_by("installment_id", "-attempt_no", "-created_at")
    )
    for payment in failed:
        latest_by_installment.setdefault(payment.installment_id, payment)

    results = []
    for payment in latest_by_installment.values():
        results.append(retry_failed_payment(payment.id, now=now, gateway=gateway))
    recovered = sum(1 for r in results if r["status"] == "recovered")
    delinquent = sum(1 for r in results if r["status"] == "delinquent")
    return {
        "candidates": len(results),
        "recovered": recovered,
        "delinquent": delinquent,
        "deferred": sum(1 for r in results if r["status"] == "deferred"),
    }


@shared_task(name="payments.tasks.send_due_reminders")
def send_due_reminders_task():
    return send_due_reminders()


@shared_task(name="payments.tasks.run_scheduled_charges")
def run_scheduled_charges_task():
    return run_scheduled_charges()


@shared_task(name="payments.tasks.run_dunning")
def run_dunning_task():
    return run_dunning()


@shared_task(name="payments.tasks.retry_failed_payment")
def retry_failed_payment_task(payment_id):
    return retry_failed_payment(payment_id)
