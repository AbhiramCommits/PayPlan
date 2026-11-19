from datetime import date, timedelta

import pytest

from apps.accounts.models import LimitReason, SpendingLimit
from apps.plans.models import (
    Cadence,
    InstallmentStatus,
    Order,
    OrderStatus,
    PlanStatus,
)
from apps.plans.services import (
    CheckoutDeclined,
    InactiveProduct,
    InvalidPlanTerms,
    available_spending_power,
    checkout,
)
from tests.factories import MemberFactory, ProductFactory, SpendingLimitFactory


@pytest.mark.django_db
def test_checkout_creates_order_plan_and_exact_schedule():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=20_000)

    result = checkout(member, product, qty=2, n=4, cadence=Cadence.BIWEEKLY)

    assert result.order.status == OrderStatus.APPROVED
    assert result.order.total_cents == 40_000
    assert result.plan.status == PlanStatus.ACTIVE
    assert result.plan.principal_cents == 40_000
    installments = list(result.plan.installments.order_by("sequence"))
    assert len(installments) == 4
    assert sum(i.amount_cents for i in installments) == 40_000
    assert [i.status for i in installments] == [InstallmentStatus.SCHEDULED] * 4
    assert installments[0].due_date == date.today() + timedelta(days=14)


@pytest.mark.django_db
def test_over_limit_checkout_declines_without_persisting_anything():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=60_000)

    with pytest.raises(CheckoutDeclined) as excinfo:
        checkout(member, product, qty=2, n=4)

    assert excinfo.value.code == "insufficient_spending_power"
    assert excinfo.value.required_cents == 120_000
    assert excinfo.value.available_cents == 100_000
    assert Order.objects.count() == 0
    assert available_spending_power(member) == 100_000


@pytest.mark.django_db
def test_second_checkout_respects_reserved_spending_power():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=60_000)

    checkout(member, product, qty=1, n=4)
    assert available_spending_power(member) == 40_000

    with pytest.raises(CheckoutDeclined):
        checkout(member, product, qty=1, n=4)


@pytest.mark.django_db
def test_checkout_creates_initial_limit_when_missing():
    member = MemberFactory(base_limit_cents=80_000)
    product = ProductFactory(price_cents=10_000)
    checkout(member, product, qty=1, n=4)
    limit = member.spending_limits.get()
    assert limit.reason == LimitReason.INITIAL
    assert limit.limit_cents == 80_000
    assert limit.available_cents == 70_000


@pytest.mark.django_db
@pytest.mark.parametrize("n", [3, 9])
def test_checkout_rejects_out_of_range_installments(n):
    member = MemberFactory()
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=10_000)
    with pytest.raises(InvalidPlanTerms):
        checkout(member, product, qty=1, n=n)


@pytest.mark.django_db
def test_checkout_rejects_inactive_product():
    member = MemberFactory()
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=10_000, active=False)
    with pytest.raises(InactiveProduct):
        checkout(member, product, qty=1, n=4)


@pytest.mark.django_db
def test_spending_limit_history_available_snapshot_matches():
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    product = ProductFactory(price_cents=25_000)
    checkout(member, product, qty=1, n=4)

    latest = SpendingLimit.objects.filter(member=member).order_by("-id").first()
    assert latest.available_cents == 75_000
    assert latest.limit_cents == 100_000
