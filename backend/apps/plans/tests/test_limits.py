"""Spending-limit rules: +10% per 4 on-time, -25% on 15+ day delinquency."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import LimitReason, SpendingLimit
from apps.plans.models import InstallmentStatus
from apps.plans.services import (
    available_spending_power,
    calculate_limit,
    recalculate_limit,
)
from tests.factories import (
    InstallmentPlanFactory,
    MemberFactory,
    SpendingLimitFactory,
)


def mark_paid(installment, days_early=1):
    paid_date = installment.due_date - timedelta(days=days_early)
    installment.status = InstallmentStatus.PAID
    installment.amount_paid_cents = installment.amount_cents
    installment.paid_at = timezone.make_aware(datetime.combine(paid_date, time(12)))
    installment.save(update_fields=["status", "amount_paid_cents", "paid_at"])


def past_plan(member, *, periods=8, start_offset=140):
    return InstallmentPlanFactory(
        order__member=member,
        num_installments=periods,
        start_date=timezone.localdate() - timedelta(days=start_offset),
    )


@pytest.mark.django_db
def test_four_on_time_installments_raise_limit_ten_percent():
    member = MemberFactory(base_limit_cents=100_000)
    limit = SpendingLimitFactory(member=member)
    plan = past_plan(member, periods=4)
    installments = list(plan.installments.order_by("sequence"))
    for inst in installments:
        mark_paid(inst)

    new = recalculate_limit(member)

    assert limit.limit_cents == 100_000
    assert new.limit_cents == 110_000
    assert new.reason == LimitReason.ON_TIME_INCREASE
    assert SpendingLimit.objects.filter(member=member).count() == 2


@pytest.mark.django_db
def test_eight_on_time_installments_raise_twenty_percent_and_history_is_append_only():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    first_plan = past_plan(member, periods=4)
    for inst in first_plan.installments.order_by("sequence"):
        mark_paid(inst)
    first = recalculate_limit(member)
    second_plan = past_plan(member, periods=4)
    for inst in second_plan.installments.order_by("sequence"):
        mark_paid(inst)
    second = recalculate_limit(member)

    assert first.limit_cents == 110_000
    assert second.limit_cents == 120_000
    assert SpendingLimit.objects.filter(member=member).count() == 3
    # The earlier rows are untouched.
    first.refresh_from_db()
    assert first.limit_cents == 110_000
    assert first.reason == LimitReason.ON_TIME_INCREASE


@pytest.mark.django_db
def test_fifteen_day_late_installment_triggers_twenty_five_percent_cut():
    member = MemberFactory(base_limit_cents=200_000)
    SpendingLimitFactory(member=member, limit_cents=200_000, available_cents=200_000)
    plan = past_plan(member, periods=4, start_offset=-2)
    inst = plan.installments.order_by("sequence").first()
    inst.due_date = timezone.localdate() - timedelta(days=15)
    inst.status = InstallmentStatus.LATE
    inst.save(update_fields=["due_date", "status"])

    new = recalculate_limit(member)

    assert new.limit_cents == 150_000
    assert new.reason == LimitReason.DELINQUENCY_DECREASE


@pytest.mark.django_db
def test_fourteen_days_late_is_not_serious():
    member = MemberFactory(base_limit_cents=200_000)
    SpendingLimitFactory(member=member, limit_cents=200_000, available_cents=200_000)
    plan = past_plan(member, periods=4, start_offset=-2)
    inst = plan.installments.order_by("sequence").first()
    # Due 14 days ago exactly.
    inst.due_date = timezone.localdate() - timedelta(days=14)
    inst.status = InstallmentStatus.LATE
    inst.save(update_fields=["due_date", "status"])

    new = recalculate_limit(member)

    assert new.limit_cents == 200_000
    assert new.pk == member.spending_limits.get().pk
    assert SpendingLimit.objects.filter(member=member).count() == 1


@pytest.mark.django_db
def test_limit_never_below_half_of_base():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member, limit_cents=80_000, available_cents=80_000)

    limit, _reason, _streak = calculate_limit(member, timezone.localdate())
    assert limit >= 50_000


@pytest.mark.django_db
def test_limit_is_capped_at_two_and_a_half_times_base():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member, limit_cents=100_000)
    for _ in range(3):
        plan = past_plan(member, periods=24, start_offset=400)
        for inst in plan.installments.order_by("sequence"):
            mark_paid(inst)

    new = recalculate_limit(member)

    assert new.limit_cents == 250_000


@pytest.mark.django_db
def test_waived_installments_do_not_break_streak():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    plan = past_plan(member, periods=4, start_offset=70)
    installments = list(plan.installments.order_by("sequence"))
    installments[-1].status = InstallmentStatus.WAIVED
    installments[-1].amount_paid_cents = 0
    installments[-1].save(update_fields=["status"])
    for inst in installments[:3]:
        mark_paid(inst)

    # Only 3 on-time payments — no increase yet.
    assert recalculate_limit(member).limit_cents == 100_000


@pytest.mark.django_db
def test_reservation_reduces_available_and_payment_releases_it():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    plan = InstallmentPlanFactory(order__member=member, principal_cents=40_000, num_installments=4)
    from apps.plans.services import sync_available

    assert available_spending_power(member) == 60_000
    sync_available(member)
    assert member.spending_limits.first().available_cents == 60_000

    first = plan.installments.order_by("sequence").first()
    first.amount_paid_cents = first.amount_cents
    first.status = InstallmentStatus.PAID
    first.save(update_fields=["amount_paid_cents", "status"])
    assert available_spending_power(member) == 60_000 + first.amount_cents


@pytest.mark.django_db
def test_recalc_writes_initial_row_when_none_exists():
    member = MemberFactory(base_limit_cents=90_000)
    new = recalculate_limit(member)
    assert new.reason == LimitReason.INITIAL
    assert new.limit_cents == 90_000
    assert SpendingLimit.objects.filter(member=member).count() == 1


@pytest.mark.django_db
def test_percentage_math_is_integer_cents():
    member = MemberFactory(base_limit_cents=33_333)
    limit, _reason, _streak = calculate_limit(member, timezone.localdate())
    assert isinstance(limit, int)
    assert limit == 33_333
    assert Decimal(limit) == Decimal("33333")
