from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.ops.models import OpsAction, OpsAuditLog
from apps.plans.models import InstallmentStatus
from tests.factories import (
    InstallmentPlanFactory,
    MemberFactory,
    SpendingLimitFactory,
    UserFactory,
)


@pytest.fixture
def support_user(db):
    user = UserFactory(username="support-agent", is_staff=True)
    group, _ = Group.objects.get_or_create(name="support")
    user.groups.add(group)
    return user


@pytest.fixture
def member_with_plan(db):
    member = MemberFactory(base_limit_cents=100_000)
    SpendingLimitFactory(member=member)
    plan = InstallmentPlanFactory(order__member=member, principal_cents=40_000, num_installments=4)
    return member, plan


@pytest.mark.django_db
def test_normal_member_forbidden(auth_client, member_with_plan):
    member, plan = member_with_plan
    installment = plan.installments.first()
    client = auth_client(member.user)
    assert client.get("/api/ops/members/").status_code == 403
    assert client.get(f"/api/ops/members/{member.id}/").status_code == 403
    assert (
        client.post(f"/api/ops/installments/{installment.id}/waive/", {}, format="json").status_code
        == 403
    )
    assert (
        client.post(
            f"/api/ops/members/{member.id}/limit/", {"limit_cents": 5000}, format="json"
        ).status_code
        == 403
    )
    assert OpsAuditLog.objects.count() == 0


@pytest.mark.django_db
def test_ops_requires_authentication(api_client):
    assert api_client.get("/api/ops/members/").status_code == 401


@pytest.mark.django_db
def test_support_can_search_and_view_member(auth_client, support_user, member_with_plan):
    member, plan = member_with_plan
    client = auth_client(support_user)

    search = client.get(f"/api/ops/members/?q={str(member.external_id)[:8]}")
    assert search.status_code == 200
    assert search.json()["results"][0]["id"] == member.id
    assert search.json()["results"][0]["display_name"]

    detail = client.get(f"/api/ops/members/{member.id}/")
    assert detail.status_code == 200
    assert detail.json()["plans"][0]["id"] == plan.id
    assert detail.json()["limits"][0]["limit_cents"] == 100_000

    assert client.get("/api/ops/members/?q=nobody-matches").json()["results"] == []


@pytest.mark.django_db
def test_waive_installment_writes_audit_and_releases_power(
    auth_client, support_user, member_with_plan
):
    member, plan = member_with_plan
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(support_user)

    response = client.post(
        f"/api/ops/installments/{installment.id}/waive/",
        {"reason": "goodwill"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["installment"]["status"] == InstallmentStatus.WAIVED
    installment.refresh_from_db()
    assert installment.status == InstallmentStatus.WAIVED

    audit = OpsAuditLog.objects.get()
    assert audit.actor == support_user
    assert audit.member == member
    assert audit.action == OpsAction.WAIVE_INSTALLMENT
    assert audit.before["status"] == InstallmentStatus.SCHEDULED
    assert audit.after["status"] == InstallmentStatus.WAIVED
    assert audit.after["reason"] == "goodwill"


@pytest.mark.django_db
def test_reschedule_updates_due_date_and_audits(auth_client, support_user, member_with_plan):
    member, plan = member_with_plan
    installment = plan.installments.order_by("sequence").first()
    installment.status = InstallmentStatus.LATE
    installment.due_date = timezone.localdate() - timedelta(days=10)
    installment.save(update_fields=["status", "due_date"])
    new_date = timezone.localdate() + timedelta(days=21)
    client = auth_client(support_user)

    response = client.post(
        f"/api/ops/installments/{installment.id}/reschedule/",
        {"due_date": new_date.isoformat(), "reason": "hardship"},
        format="json",
    )
    assert response.status_code == 200
    installment.refresh_from_db()
    assert installment.due_date == new_date
    assert installment.status == InstallmentStatus.SCHEDULED
    audit = OpsAuditLog.objects.get()
    assert audit.action == OpsAction.RESCHEDULE_DUE_DATE
    assert audit.before["due_date"] != audit.after["due_date"]
    assert audit.after["reason"] == "hardship"


@pytest.mark.django_db
def test_manual_limit_adjustment_is_append_only(auth_client, support_user, member_with_plan):
    member, _plan = member_with_plan
    client = auth_client(support_user)

    response = client.post(
        f"/api/ops/members/{member.id}/limit/",
        {"limit_cents": 150_000, "reason": "verified income"},
        format="json",
    )
    assert response.status_code == 201, response.content
    latest = member.spending_limits.order_by("-id").first()
    assert latest.limit_cents == 150_000
    assert latest.reason == "MANUAL"
    assert member.spending_limits.count() == 2
    audit = OpsAuditLog.objects.get()
    assert audit.action == OpsAction.ADJUST_LIMIT
    assert audit.before["limit_cents"] == 100_000
    assert audit.after["limit_cents"] == 150_000
    assert audit.after["reason"] == "verified income"


@pytest.mark.django_db
def test_ops_validation_errors(auth_client, support_user, member_with_plan):
    member, plan = member_with_plan
    installment = plan.installments.first()
    client = auth_client(support_user)
    assert (
        client.post(
            f"/api/ops/installments/{installment.id}/reschedule/", {}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/ops/members/{member.id}/limit/", {"limit_cents": -1}, format="json"
        ).status_code
        == 400
    )
    assert client.get("/api/ops/members/999999/").status_code == 404


@pytest.mark.django_db
def test_audit_log_endpoint(auth_client, support_user, member_with_plan):
    member, plan = member_with_plan
    installment = plan.installments.first()
    client = auth_client(support_user)
    client.post(f"/api/ops/installments/{installment.id}/waive/", {}, format="json")

    response = client.get(f"/api/ops/members/{member.id}/audit/")
    assert response.status_code == 200
    assert response.json()["results"][0]["action"] == "WAIVE_INSTALLMENT"
    assert response.json()["results"][0]["actor_username"] == "support-agent"
