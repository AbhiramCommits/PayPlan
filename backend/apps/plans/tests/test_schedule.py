from datetime import date

import pytest

from apps.plans.models import Cadence
from apps.plans.services import InvalidPlanTerms, add_months, generate_schedule


def test_schedule_sums_exactly_for_every_principal_and_term():
    """Property-style: no rounding drift for 1..5000 cents and 2..12 periods."""
    start = date(2026, 1, 15)
    for principal in range(1, 5001):
        for n in range(2, 13):
            for cadence in (Cadence.BIWEEKLY, Cadence.MONTHLY):
                schedule = generate_schedule(principal, n, cadence, start)
                assert len(schedule) == n
                assert sum(amount for _, amount in schedule) == principal
                assert all(amount >= 0 for _, amount in schedule)
                due_dates = [due for due, _ in schedule]
                assert due_dates == sorted(due_dates)
                assert len(set(due_dates)) == n


def test_schedule_front_loads_remainder_cent():
    schedule = generate_schedule(1001, 4, Cadence.BIWEEKLY, date(2026, 1, 1))
    assert [amount for _, amount in schedule] == [251, 250, 250, 250]
    assert sum(a for _, a in schedule) == 1001


def test_biweekly_and_monthly_due_dates():
    biweekly = generate_schedule(400, 2, Cadence.BIWEEKLY, date(2026, 1, 1))
    assert [d for d, _ in biweekly] == [date(2026, 1, 15), date(2026, 1, 29)]

    monthly = generate_schedule(400, 3, Cadence.MONTHLY, date(2026, 1, 31))
    assert [d for d, _ in monthly] == [
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_add_months_clamps_end_of_month():
    assert add_months(date(2025, 12, 31), 2) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


@pytest.mark.parametrize(
    "principal,n,cadence",
    [
        (0, 4, "BIWEEKLY"),
        (-100, 4, "BIWEEKLY"),
        (1000, 0, "BIWEEKLY"),
        (1000, 4, "WEEKLY"),
        (1000, 4, "biweekly"),
    ],
)
def test_invalid_terms_are_rejected(principal, n, cadence):
    with pytest.raises(InvalidPlanTerms):
        generate_schedule(principal, n, cadence, date(2026, 1, 1))


def test_schedule_is_deterministic():
    a = generate_schedule(99_999, 7, Cadence.MONTHLY, date(2026, 3, 1))
    b = generate_schedule(99_999, 7, Cadence.MONTHLY, date(2026, 3, 1))
    assert a == b
    assert b[0][0] == date(2026, 4, 1)
    assert b[-1][0] == date(2026, 10, 1)
    assert sum(v for _, v in b) == 99_999
