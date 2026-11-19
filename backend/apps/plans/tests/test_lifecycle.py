"""End-to-end lifecycle: checkout, charges, a failure, dunning, completion, limit up."""

from datetime import date

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.payments.gateway import FakeGateway
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import process_payment
from apps.payments.tasks import run_dunning, run_scheduled_charges
from apps.plans.models import InstallmentStatus, PlanStatus
from apps.plans.services import checkout
from tests.factories import MemberFactory, ProductFactory, SpendingLimitFactory


@pytest.mark.django_db
def test_full_lifecycle_checkout_failure_recovery_completion_and_limit_increase():
    gateway = FakeGateway(failures=["card_declined"])
    with freeze_time("2026-01-01 09:00:00"):
        member = MemberFactory(base_limit_cents=100_000)
        SpendingLimitFactory(member=member)
        product = ProductFactory(price_cents=40_000)
        result = checkout(
            member,
            product,
            qty=1,
            n=4,
            cadence="BIWEEKLY",
            start_date=date(2026, 1, 1),
        )
        plan = result.plan
        installments = list(plan.installments.order_by("sequence"))
        assert [i.due_date for i in installments] == [
            date(2026, 1, 15),
            date(2026, 1, 29),
            date(2026, 2, 12),
            date(2026, 2, 26),
        ]

    # The member chooses to pay the first installment early; the card declines.
    with freeze_time("2026-01-10 09:00:00"):
        first = installments[0]
        initial_key = f"inst:{first.id}:attempt:1"
        outcome, http_status = process_payment(
            member=member,
            installment=first,
            idempotency_key=initial_key,
            gateway=gateway,
            now=timezone.now(),
        )
        assert http_status == 402
        assert outcome.payment.status == PaymentStatus.FAILED
        first.refresh_from_db()
        assert first.status == InstallmentStatus.FAILED

    # Dunning retries after one day; the payment succeeds before its due date.
    with freeze_time("2026-01-11 10:00:00"):
        recovery = run_dunning(gateway=gateway)
        assert recovery["recovered"] == 1
        first.refresh_from_db()
        assert first.status == InstallmentStatus.PAID
        assert first.paid_at.date() <= first.due_date

    # The remaining three installments charge on their due dates.
    for charge_day in (date(2026, 1, 29), date(2026, 2, 12), date(2026, 2, 26)):
        with freeze_time(f"{charge_day.isoformat()} 10:00:00"):
            result = run_scheduled_charges(gateway=gateway)
            assert result["charged"] == 1, result

    plan.refresh_from_db()
    assert plan.status == PlanStatus.COMPLETED
    assert all(i.status == InstallmentStatus.PAID for i in plan.installments.all())

    payments = Payment.objects.filter(installment__plan=plan).order_by("created_at")
    assert payments.count() == 5  # one failed attempt + four successful charges
    assert payments.filter(status=PaymentStatus.FAILED).count() == 1
    recovered = payments.get(attempt_no=2, status=PaymentStatus.SUCCEEDED)
    assert recovered.installment_id == installments[0].id
    assert gateway.charge_count == 5

    latest_limit = member.spending_limits.order_by("-id").first()
    assert latest_limit.limit_cents == 110_000
    assert latest_limit.reason == "ON_TIME_INCREASE"
    assert member.spending_limits.count() == 2
