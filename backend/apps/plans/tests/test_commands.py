"""Smoke tests for the two operational management commands."""

import csv
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.accounts.models import Member
from apps.catalog.models import Product
from apps.plans.models import InstallmentPlan


@pytest.mark.django_db
def test_seed_demo_is_idempotent():
    out = StringIO()
    call_command("seed_demo", stdout=out)
    call_command("seed_demo", stdout=out)

    assert Member.objects.filter(user__username="demo").count() == 1
    assert InstallmentPlan.objects.count() == 1
    assert Product.objects.count() == 5
    assert Group.objects.filter(name="support").exists()
    assert "Seeded demo/demo12345" in out.getvalue()


@pytest.mark.django_db
def test_simulation_writes_artifacts_and_rolls_back(tmp_path):
    out = StringIO()
    call_command(
        "simulate_portfolio",
        members=4,
        days=8,
        seed=3,
        results_dir=str(tmp_path),
        stdout=out,
    )

    simulation = (tmp_path / "simulation.txt").read_text()
    assert "PayPlan portfolio simulation" in simulation
    assert "Plans created" in simulation
    assert "500 members" not in simulation

    with (tmp_path / "rollups.csv").open() as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "date"
    assert len(rows) == 9  # header + 8 simulated days

    assert "PayPlan portfolio simulation" in out.getvalue()
    # The command rolls its transaction back, so no simulation members persist.
    assert not Member.objects.filter(user__username__startswith="sim3_").exists()
    assert InstallmentPlan.objects.count() == 0
