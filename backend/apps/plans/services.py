"""Pure domain services: no HTTP, no Celery, no Stripe SDK.

Everything takes plain values or model instances and is deterministic, so the
heavy logic is unit-testable in isolation.
"""

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import LimitReason, MemberStatus, SpendingLimit
from apps.catalog.models import Product
from apps.plans.models import (
    Cadence,
    Installment,
    InstallmentPlan,
    InstallmentStatus,
    Order,
    OrderStatus,
    PlanStatus,
)


class PayPlanDomainError(Exception):
    """Base class for typed, API-safe domain errors."""

    code = "domain_error"


class InvalidPlanTerms(PayPlanDomainError):
    code = "invalid_plan_terms"


class CheckoutDeclined(PayPlanDomainError):
    """Order total exceeds the member's available spending power."""

    code = "insufficient_spending_power"

    def __init__(self, required_cents: int, available_cents: int):
        self.required_cents = required_cents
        self.available_cents = available_cents
        super().__init__(
            f"Order requires {required_cents} cents but only {available_cents} cents are available"
        )


class InactiveProduct(PayPlanDomainError):
    code = "inactive_product"


def add_months(start: date, months: int) -> date:
    """Calendar-correct month addition without dateutil."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _due_date(start_date: date, cadence: str, period: int) -> date:
    if cadence == Cadence.MONTHLY:
        return add_months(start_date, period)
    return start_date + timedelta(days=14 * period)


def generate_schedule(principal_cents: int, n: int, cadence: str, start_date: date):
    """Split ``principal_cents`` into ``n`` installments.

    The first ``principal % n`` installments receive one extra cent, so the
    schedule always sums to exactly the principal.  Money stays integer.
    """
    if not isinstance(principal_cents, int) or principal_cents <= 0:
        raise InvalidPlanTerms("principal_cents must be a positive integer")
    if n < 1:
        raise InvalidPlanTerms("n must be >= 1")
    if cadence not in (Cadence.BIWEEKLY, Cadence.MONTHLY):
        raise InvalidPlanTerms(f"unsupported cadence {cadence!r}")
    if not isinstance(start_date, date):
        raise InvalidPlanTerms("start_date must be a date")

    base, remainder = divmod(principal_cents, n)
    schedule = []
    for index in range(n):
        amount = base + (1 if index < remainder else 0)
        schedule.append((_due_date(start_date, cadence, index + 1), amount))

    # Defensive assertion: a bug here would silently leak cents.
    if sum(amount for _, amount in schedule) != principal_cents:
        raise AssertionError("schedule drifted from principal")
    return schedule


def initial_limit(member, *, available_cents=None, reason=LimitReason.INITIAL):
    """Return the latest limit row, creating an INITIAL row when none exists."""
    latest = member.spending_limits.order_by("-effective_at", "-id").first()
    if latest:
        return latest
    available = member.base_limit_cents if available_cents is None else available_cents
    return SpendingLimit.objects.create(
        member=member,
        limit_cents=member.base_limit_cents,
        available_cents=max(min(available, member.base_limit_cents), 0),
        reason=reason,
    )


def current_limit_cents(member) -> int:
    latest = member.spending_limits.order_by("-effective_at", "-id").first()
    return latest.limit_cents if latest else member.base_limit_cents


def outstanding_cents(member) -> int:
    """Principal not yet paid on active/delinquent plans."""
    total = (
        Installment.objects.filter(
            plan__member=member,
            plan__status__in=[PlanStatus.ACTIVE, PlanStatus.DELINQUENT],
        )
        .exclude(status__in=[InstallmentStatus.PAID, InstallmentStatus.WAIVED])
        .aggregate(total=Sum("amount_cents"), paid=Sum("amount_paid_cents"))
    )
    return (total["total"] or 0) - (total["paid"] or 0)


def available_spending_power(member) -> int:
    return max(current_limit_cents(member) - outstanding_cents(member), 0)


def sync_available(member) -> int:
    """Refresh the stored snapshot on the newest limit row."""
    latest = initial_limit(member)
    available = available_spending_power(member)
    if latest.available_cents != available:
        SpendingLimit.objects.filter(pk=latest.pk).update(available_cents=available)
        latest.available_cents = available
    return available


def _on_time_streak(member, as_of: date) -> int:
    """Consecutive on-time paid installments, most recent first.

    Future scheduled installments are ignored; a past-due unpaid installment
    ends the streak because the member is not currently current.
    """
    relevant = (
        Installment.objects.filter(plan__member=member, due_date__lte=as_of)
        .select_related("plan")
        .order_by("-due_date", "-sequence")
    )
    streak = 0
    for installment in relevant:
        if installment.status == InstallmentStatus.WAIVED:
            continue
        on_time = (
            installment.status == InstallmentStatus.PAID
            and installment.paid_at is not None
            and timezone.localtime(installment.paid_at).date() <= installment.due_date
        )
        if on_time:
            streak += 1
        else:
            break
    return streak


def has_serious_delinquency(member, as_of: date) -> bool:
    """True when any installment is (or was) 15+ days late."""
    for installment in Installment.objects.filter(plan__member=member).only(
        "due_date", "paid_at", "status", "amount_cents", "amount_paid_cents"
    ):
        if installment.status == InstallmentStatus.WAIVED:
            continue
        if installment.paid_at is not None:
            paid_on = timezone.localtime(installment.paid_at).date()
            if (paid_on - installment.due_date).days >= 15:
                return True
            continue
        if installment.due_date <= as_of and installment.days_late(as_of) >= 15:
            return True
    return False


def _pct_floor(cents: int) -> int:
    return int(Decimal(cents) * Decimal("0.5"))


def _apply_pct(cents: int, pct: Decimal) -> int:
    value = (Decimal(cents) * (Decimal("1") + pct)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(value)


def calculate_limit(member, as_of: date) -> tuple[int, str, int]:
    """Return (new_limit_cents, reason, streak). Deterministic from DB state."""
    base = member.base_limit_cents
    streak = _on_time_streak(member, as_of)
    increments = streak // 4
    new_limit = _apply_pct(base, Decimal("0.10") * increments)
    cap = int(math.floor(base * 2.5))
    new_limit = min(new_limit, cap)

    serious = has_serious_delinquency(member, as_of)
    if serious:
        new_limit = int(
            (Decimal(new_limit) * Decimal("0.75")).quantize(Decimal("1"), ROUND_HALF_UP)
        )
    floor = _pct_floor(base)
    new_limit = max(new_limit, floor)

    previous = current_limit_cents(member)
    if not member.spending_limits.exists():
        reason = LimitReason.INITIAL
    elif serious and new_limit < previous:
        reason = LimitReason.DELINQUENCY_DECREASE
    elif new_limit > previous:
        reason = LimitReason.ON_TIME_INCREASE
    elif new_limit < previous:
        reason = LimitReason.DELINQUENCY_DECREASE
    else:
        reason = LimitReason.MANUAL
    return new_limit, reason, streak


@transaction.atomic
def recalculate_limit(member, as_of: date | None = None) -> SpendingLimit:
    """Append a new SpendingLimit row when the policy outcome changed."""
    as_of = as_of or timezone.localdate()
    # Lock the member to serialise concurrent recalculations for the same member.
    type(member).objects.select_for_update().get(pk=member.pk)
    member.refresh_from_db(fields=["base_limit_cents"])
    new_limit, reason, _streak = calculate_limit(member, as_of)
    previous = member.spending_limits.order_by("-effective_at", "-id").first()
    available = max(new_limit - outstanding_cents(member), 0)
    if previous is None or previous.limit_cents != new_limit:
        return SpendingLimit.objects.create(
            member=member,
            limit_cents=new_limit,
            available_cents=available,
            reason=reason,
        )
    if previous.available_cents != available:
        SpendingLimit.objects.filter(pk=previous.pk).update(available_cents=available)
        previous.available_cents = available
    return previous


@dataclass(frozen=True)
class CheckoutResult:
    order: Order
    plan: InstallmentPlan


@transaction.atomic
def checkout(
    member,
    product: Product,
    qty: int,
    n: int,
    cadence: str = Cadence.BIWEEKLY,
    start_date: date | None = None,
) -> CheckoutResult:
    """Create an approved order, plan, and installment schedule atomically.

    The member row is locked so two concurrent checkouts cannot both spend the
    same available cents.  A decline raises ``CheckoutDeclined`` before any
    order row is written.
    """
    if qty < 1:
        raise InvalidPlanTerms("qty must be >= 1")
    if not (settings.PLAN_MIN_INSTALLMENTS <= n <= settings.PLAN_MAX_INSTALLMENTS):
        raise InvalidPlanTerms(
            f"n must be between {settings.PLAN_MIN_INSTALLMENTS} and "
            f"{settings.PLAN_MAX_INSTALLMENTS}"
        )
    if cadence not in (Cadence.BIWEEKLY, Cadence.MONTHLY):
        raise InvalidPlanTerms(f"unsupported cadence {cadence!r}")
    if not product.active:
        raise InactiveProduct("product is not available")
    if member.status != MemberStatus.ACTIVE:
        raise CheckoutDeclined(required_cents=0, available_cents=0)

    locked_member = type(member).objects.select_for_update().get(pk=member.pk)
    initial_limit(locked_member)
    total_cents = product.price_cents * qty
    if total_cents < n:
        raise InvalidPlanTerms("order total is too small to split across installments")

    available = available_spending_power(locked_member)
    if total_cents > available:
        raise CheckoutDeclined(required_cents=total_cents, available_cents=available)

    start_date = start_date or timezone.localdate()
    schedule = generate_schedule(total_cents, n, cadence, start_date)

    order = Order.objects.create(
        member=locked_member,
        product=product,
        qty=qty,
        total_cents=total_cents,
        status=OrderStatus.APPROVED,
    )
    plan = InstallmentPlan.objects.create(
        order=order,
        member=locked_member,
        principal_cents=total_cents,
        num_installments=n,
        cadence=cadence,
        status=PlanStatus.ACTIVE,
        start_date=start_date,
    )
    Installment.objects.bulk_create(
        [
            Installment(
                plan=plan,
                sequence=seq,
                due_date=due_date,
                amount_cents=amount,
                status=InstallmentStatus.SCHEDULED,
            )
            for seq, (due_date, amount) in enumerate(schedule, start=1)
        ]
    )
    # Reservation: derived availability now excludes the new principal.
    sync_available(locked_member)
    return CheckoutResult(order=order, plan=plan)
