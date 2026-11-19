"""Nightly repayment-status rollup.  One recomputable row per calendar day."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

from apps.payments.models import Payment, PaymentStatus
from apps.plans.models import (
    Installment,
    InstallmentPlan,
    InstallmentStatus,
    PlanRollup,
    PlanStatus,
)


def _day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = datetime.combine(day, time.max, tzinfo=UTC)
    return start, end


def _rate(numerator: int, denominator: int) -> Decimal:
    if not denominator:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def compute_rollup(day=None):
    day = day or timezone.localdate()
    start, end = _day_bounds(day)

    due = Installment.objects.filter(due_date=day).exclude(status=InstallmentStatus.WAIVED)
    billed_cents = sum(due.values_list("amount_cents", flat=True))
    on_time = due.filter(status=InstallmentStatus.PAID, paid_at__lte=end).count()
    billed_count = due.count()

    payments = Payment.objects.filter(
        status=PaymentStatus.SUCCEEDED, created_at__gte=start, created_at__lte=end
    )
    collected_cents = sum(payments.values_list("amount_cents", flat=True))

    retries = Payment.objects.filter(attempt_no__gt=1, created_at__gte=start, created_at__lte=end)
    retry_count = retries.count()
    recovered = retries.filter(status=PaymentStatus.SUCCEEDED).count()

    values = {
        "active_plans": InstallmentPlan.objects.filter(status=PlanStatus.ACTIVE).count(),
        "delinquent_plans": InstallmentPlan.objects.filter(status=PlanStatus.DELINQUENT).count(),
        "billed_cents": billed_cents,
        "collected_cents": collected_cents,
        "on_time_rate": _rate(on_time, billed_count),
        "dunning_recovery_rate": _rate(recovered, retry_count),
    }
    rollup, _created = PlanRollup.objects.update_or_create(date=day, defaults=values)
    return rollup


def nightly_rollup(day=None):
    """Recomputing the same day updates, never duplicates, the rollup."""
    rollup = compute_rollup(day)
    return {
        "date": rollup.date.isoformat(),
        "active_plans": rollup.active_plans,
        "delinquent_plans": rollup.delinquent_plans,
        "billed_cents": rollup.billed_cents,
        "collected_cents": rollup.collected_cents,
        "on_time_rate": str(rollup.on_time_rate),
        "dunning_recovery_rate": str(rollup.dunning_recovery_rate),
    }


@shared_task(name="plans.tasks.nightly_rollup")
def nightly_rollup_task():
    return nightly_rollup()
