"""Time-travel tests: reminders, scheduled charges, dunning, and rollups."""

from datetime import date

import pytest
from freezegun import freeze_time

from apps.payments.gateway import FakeGateway
from apps.payments.models import Notification, Payment, PaymentStatus
from apps.payments.tasks import (
    retry_failed_payment,
    run_dunning,
    run_scheduled_charges,
    send_due_reminders,
)
from apps.plans.models import InstallmentStatus, PlanStatus
from apps.plans.tasks import nightly_rollup
from tests.factories import InstallmentPlanFactory, MemberFactory, SpendingLimitFactory


@pytest.mark.django_db
def test_due_reminders_are_idempotent_per_installment_template_day():
    with freeze_time("2026-01-01 09:00:00"):
        plan = InstallmentPlanFactory(num_installments=4, start_date=date(2025, 12, 18))
        installments = list(plan.installments.order_by("sequence"))
        # sequence 1 due Jan 1 (today); sequence 2 moved to Jan 4 (T-3).
        installments[1].due_date = date(2026, 1, 4)
        installments[1].save(update_fields=["due_date"])

        first = send_due_reminders()
        second = send_due_reminders()

        assert first["notifications"] == 2
        assert second["notifications"] == 0
        assert Notification.objects.count() == 2
        templates = set(Notification.objects.values_list("template", flat=True))
        assert templates == {"due_today", "due_soon"}
        assert Notification.objects.filter(sent_at__date=date(2026, 1, 1)).count() == 2


@pytest.mark.django_db
def test_scheduled_charges_run_once_and_dunning_recovers_next_day():
    gateway = FakeGateway(failures=["card_declined"])
    with freeze_time("2026-01-01 09:00:00"):
        plan = InstallmentPlanFactory(
            order__member=MemberFactory(base_limit_cents=100_000),
            num_installments=4,
            start_date=date(2025, 12, 18),
        )
        first = plan.installments.order_by("sequence").first()

        result = run_scheduled_charges(gateway=gateway)
        assert result == {"charged": 0, "failed": 1, "skipped": 0}
        again = run_scheduled_charges(gateway=gateway)
        assert again["charged"] == 0 and again["failed"] == 0
        assert Payment.objects.filter(installment=first).count() == 1
        first.refresh_from_db()
        assert first.status == InstallmentStatus.FAILED

        # Same day a retry must defer: 1d backoff not elapsed.
        assert (
            retry_failed_payment(Payment.objects.get(installment=first).id, gateway=gateway)[
                "status"
            ]
            == "deferred"
        )

    with freeze_time("2026-01-02 10:00:00"):
        result = run_dunning(gateway=gateway)
        assert result["recovered"] == 1
        first.refresh_from_db()
        assert first.status == InstallmentStatus.PAID
        assert first.paid_at.date() > first.due_date  # recovered late, not on-time
        attempts = list(
            Payment.objects.filter(installment=first)
            .order_by("attempt_no")
            .values_list("attempt_no", "status")
        )
        assert attempts == [(1, "FAILED"), (2, "SUCCEEDED")]
        assert gateway.charge_count == 2

        # Running dunning again on the same day changes nothing.
        assert run_dunning(gateway=gateway)["candidates"] == 0
        assert Payment.objects.filter(installment=first).count() == 2


@pytest.mark.django_db
def test_dunning_backoff_1_3_7_days_then_delinquent_and_limit_cut():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    gateway = FakeGateway(fail_all="card_declined")

    with freeze_time("2026-01-01 09:00:00"):
        plan = InstallmentPlanFactory(
            order__member=member,
            num_installments=4,
            start_date=date(2025, 12, 14),  # first due Dec 28, 2025
        )
        first = plan.installments.order_by("sequence").first()
        run_scheduled_charges(gateway=gateway)
        first.refresh_from_db()
        assert first.status == InstallmentStatus.FAILED

    paid_attempts = {}
    for day in range(2, 13):
        with freeze_time(f"2026-01-{day:02d} 10:00:00"):
            run_dunning(gateway=gateway)
            for attempt in Payment.objects.filter(installment=first):
                paid_attempts[attempt.attempt_no] = attempt.created_at.date()

    first.refresh_from_db()
    plan.refresh_from_db()
    assert set(paid_attempts) == {1, 2, 3, 4}
    assert paid_attempts[2] == date(2026, 1, 2)
    assert paid_attempts[3] == date(2026, 1, 5)  # +3 days
    assert paid_attempts[4] == date(2026, 1, 12)  # +7 days
    assert first.status == InstallmentStatus.LATE
    assert plan.status == PlanStatus.DELINQUENT
    last_limit = member.spending_limits.order_by("-id").first()
    assert last_limit.limit_cents == 75_000
    assert last_limit.reason == "DELINQUENCY_DECREASE"


@pytest.mark.django_db
def test_scheduled_charge_success_is_idempotent_and_rollup_numbers_match():
    with freeze_time("2026-02-01 09:00:00"):
        InstallmentPlanFactory(
            num_installments=2, principal_cents=20_000, start_date=date(2026, 1, 18)
        )
        gateway = FakeGateway()

        assert run_scheduled_charges(gateway=gateway) == {
            "charged": 1,
            "failed": 0,
            "skipped": 0,
        }
        assert run_scheduled_charges(gateway=gateway) == {
            "charged": 0,
            "failed": 0,
            "skipped": 0,
        }
        assert Payment.objects.filter(status=PaymentStatus.SUCCEEDED).count() == 1

        rollup = nightly_rollup(day=date(2026, 2, 1))
        assert rollup["active_plans"] == 1
        assert rollup["delinquent_plans"] == 0
        assert rollup["billed_cents"] == 10_000
        assert rollup["collected_cents"] == 10_000
        assert rollup["on_time_rate"] == "1.0000"

        nightly_rollup(day=date(2026, 2, 1))
        assert PlanRollupCount() == 1


@pytest.mark.django_db
def test_rollup_counts_dunning_recovery():
    gateway = FakeGateway(failures=["card_declined"])
    with freeze_time("2026-01-01 09:00:00"):
        plan = InstallmentPlanFactory(num_installments=4, start_date=date(2025, 12, 18))
        installment = plan.installments.order_by("sequence").first()
        run_scheduled_charges(gateway=gateway)
        nightly_rollup(day=date(2026, 1, 1))

    with freeze_time("2026-01-02 10:00:00"):
        run_dunning(gateway=gateway)
        rollup = nightly_rollup(day=date(2026, 1, 2))
        assert rollup["dunning_recovery_rate"] == "1.0000"
        assert rollup["billed_cents"] == 0
        assert rollup["collected_cents"] == installment.amount_cents

    stale = retry_failed_payment(
        Payment.objects.filter(installment=installment).first().id, gateway=gateway
    )
    assert stale["status"] == "not_failed"


def PlanRollupCount():
    from apps.plans.models import PlanRollup

    return PlanRollup.objects.count()
