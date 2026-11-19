import pytest

from apps.plans.models import InstallmentStatus
from tests.factories import InstallmentPlanFactory, ProductFactory, SpendingLimitFactory


@pytest.mark.django_db
def test_endpoints_require_authentication(api_client):
    for url in ["/api/plans/", "/api/installments/", "/api/members/me/"]:
        assert api_client.get(url).status_code == 401
    assert api_client.post("/api/checkout/", {}).status_code == 401


@pytest.mark.django_db
def test_member_me_returns_limit_and_available(auth_client, member):
    client = auth_client(member.user)
    response = client.get("/api/members/me/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == member.id
    assert body["base_limit_cents"] == 100_000
    assert body["limit_cents"] == 100_000
    assert body["available_cents"] == 100_000
    assert "member" in body["roles"]


@pytest.mark.django_db
def test_checkout_via_api_then_list_plans(auth_client, member):
    product = ProductFactory(price_cents=20_000)
    client = auth_client(member.user)
    response = client.post(
        "/api/checkout/",
        {"product": product.id, "qty": 1, "num_installments": 4, "cadence": "BIWEEKLY"},
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    plan_id = body["plan"]["id"]
    assert body["plan"]["num_installments"] == 4
    assert len(body["plan"]["installments"]) == 4
    assert body["member"]["available_cents"] == 80_000

    listing = client.get("/api/plans/")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["results"][0]["id"] == plan_id

    detail = client.get(f"/api/plans/{plan_id}/")
    assert detail.status_code == 200
    assert len(detail.json()["installments"]) == 4


@pytest.mark.django_db
def test_over_limit_api_returns_402(auth_client, member):
    product = ProductFactory(price_cents=90_000)
    client = auth_client(member.user)
    response = client.post(
        "/api/checkout/",
        {"product": product.id, "qty": 2, "num_installments": 4},
        format="json",
    )
    assert response.status_code == 402, response.content
    body = response.json()
    assert body["error"]["code"] == "insufficient_spending_power"
    assert body["error"]["required_cents"] == 180_000
    assert body["error"]["available_cents"] == 100_000


@pytest.mark.django_db
def test_installments_can_be_filtered_by_status(auth_client, member):
    plan = InstallmentPlanFactory(order__member=member, principal_cents=40_000)
    first = plan.installments.order_by("sequence").first()
    first.status = InstallmentStatus.PAID
    first.amount_paid_cents = first.amount_cents
    first.save(update_fields=["status", "amount_paid_cents"])
    client = auth_client(member.user)

    paid = client.get("/api/installments/?status=PAID")
    scheduled = client.get("/api/installments/?status=SCHEDULED")
    assert paid.status_code == 200
    assert paid.json()["count"] == 1
    assert paid.json()["results"][0]["id"] == first.id
    assert scheduled.json()["count"] == 3


@pytest.mark.django_db
def test_cross_member_plan_access_is_404(auth_client, member, other_member):
    theirs = InstallmentPlanFactory(order__member=other_member, principal_cents=40_000)
    SpendingLimitFactory(member=other_member)
    client = auth_client(member.user)

    assert client.get(f"/api/plans/{theirs.id}/").status_code == 404
    assert client.get("/api/plans/").json()["count"] == 0
    assert client.get("/api/installments/").json()["count"] == 0
    # Their own plan remains visible to them.
    assert auth_client(other_member.user).get(f"/api/plans/{theirs.id}/").status_code == 200


@pytest.mark.django_db
def test_checkout_requires_valid_body(auth_client, member):
    client = auth_client(member.user)
    assert client.post("/api/checkout/", {}, format="json").status_code == 400
    product = ProductFactory(price_cents=1000)
    response = client.post(
        "/api/checkout/",
        {"product": product.id, "qty": 1, "num_installments": 20},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_user_without_member_profile_gets_404(auth_client, django_user_model):
    user = django_user_model.objects.create_user(username="orphan", password="x")
    response = auth_client(user).get("/api/members/me/")
    assert response.status_code == 404
