import pytest

from apps.payments.gateway import FakeGateway
from apps.payments.models import Payment, PaymentStatus
from apps.plans.models import InstallmentStatus, PlanStatus
from tests.factories import InstallmentPlanFactory


@pytest.fixture
def gateway(monkeypatch):
    gw = FakeGateway()
    monkeypatch.setattr("apps.payments.views.get_gateway", lambda: gw)
    return gw


def make_plan(member, principal_cents=40_000):
    return InstallmentPlanFactory(
        order__member=member, principal_cents=principal_cents, num_installments=4
    )


def pay(client, installment, key, amount=None):
    body = {"installment": installment.id}
    if amount is not None:
        body["amount_cents"] = amount
    return client.post("/api/payments/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


@pytest.mark.django_db
def test_payment_succeeds_and_replay_is_free(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(member.user)

    first = pay(client, installment, "idem-success")
    assert first.status_code == 201, first.content
    assert first.json()["payment"]["status"] == "SUCCEEDED"
    assert first.json()["replayed"] is False
    ref = first.json()["payment"]["gateway_ref"]

    installment.refresh_from_db()
    assert installment.status == InstallmentStatus.PAID
    assert installment.amount_paid_cents == installment.amount_cents

    replay = pay(client, installment, "idem-success")
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["payment"]["id"] == first.json()["payment"]["id"]
    assert replay.json()["payment"]["gateway_ref"] == ref
    assert Payment.objects.filter(idempotency_key="idem-success").count() == 1
    assert gateway.charge_count == 1


@pytest.mark.django_db
def test_same_key_different_body_is_409(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(member.user)

    assert pay(client, installment, "idem-body").status_code == 201
    conflict = pay(client, installment, "idem-body", amount=1234)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert Payment.objects.count() == 1
    assert gateway.charge_count == 1


@pytest.mark.django_db
def test_missing_idempotency_key_is_400(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    response = auth_client(member.user).post(
        "/api/payments/", {"installment": installment.id}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_idempotency_key"
    assert gateway.charge_count == 0


@pytest.mark.django_db
def test_partial_payment_then_remainder(auth_client, member, gateway):
    plan = make_plan(member, principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(member.user)

    partial = pay(client, installment, "idem-partial", amount=4000)
    assert partial.status_code == 201
    installment.refresh_from_db()
    assert installment.amount_paid_cents == 4000
    assert installment.status == InstallmentStatus.DUE
    assert installment.paid_at is None

    rest = pay(client, installment, "idem-rest")
    assert rest.status_code == 201
    installment.refresh_from_db()
    assert installment.amount_paid_cents == installment.amount_cents
    assert installment.status == InstallmentStatus.PAID
    assert gateway.charge_count == 2


@pytest.mark.django_db
def test_payment_decline_records_attempt_and_failure(auth_client, member, gateway):
    plan = make_plan(member, principal_cents=404)  # 101 cents per installment
    installment = plan.installments.order_by("sequence").first()
    response = pay(auth_client(member.user), installment, "idem-decline")

    assert response.status_code == 402
    body = response.json()
    assert body["payment"]["status"] == "FAILED"
    assert body["payment"]["failure_code"] == "card_declined"
    assert body["payment"]["attempt_no"] == 1
    installment.refresh_from_db()
    assert installment.status == InstallmentStatus.FAILED
    assert installment.amount_paid_cents == 0
    assert gateway.charge_count == 1


@pytest.mark.django_db
def test_insufficient_funds_failure_code(auth_client, member, gateway):
    plan = make_plan(member, principal_cents=408)  # 102 cents per installment
    installment = plan.installments.order_by("sequence").first()
    response = pay(auth_client(member.user), installment, "idem-nsf")
    assert response.status_code == 402
    assert response.json()["payment"]["failure_code"] == "insufficient_funds"


@pytest.mark.django_db
def test_gateway_exception_is_recorded_not_raised(auth_client, member, monkeypatch):
    class BoomGateway(FakeGateway):
        def charge(self, *args, **kwargs):
            raise RuntimeError("gateway down")

    monkeypatch.setattr("apps.payments.views.get_gateway", lambda: BoomGateway())
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    response = pay(auth_client(member.user), installment, "idem-boom")

    assert response.status_code == 502
    payment = Payment.objects.get(idempotency_key="idem-boom")
    assert payment.status == PaymentStatus.FAILED
    assert payment.failure_code == "gateway_error"


@pytest.mark.django_db
def test_already_settled_installment_rejects_new_key(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(member.user)
    assert pay(client, installment, "idem-first").status_code == 201
    second = pay(client, installment, "idem-second")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "installment_settled"


@pytest.mark.django_db
def test_amount_over_remaining_is_400(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    response = pay(auth_client(member.user), installment, "idem-over", amount=99_999)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_payment_amount"
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_cross_member_payment_is_404(auth_client, member, other_member, gateway):
    plan = make_plan(other_member)
    installment = plan.installments.order_by("sequence").first()
    response = pay(auth_client(member.user), installment, "idem-cross")
    assert response.status_code == 404
    assert Payment.objects.count() == 0
    assert gateway.charge_count == 0


@pytest.mark.django_db
def test_payment_history_is_member_scoped_and_filterable(auth_client, member, gateway):
    plan = make_plan(member)
    installment = plan.installments.order_by("sequence").first()
    client = auth_client(member.user)
    pay(client, installment, "idem-history")

    listing = client.get("/api/payments/?status=SUCCEEDED")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["results"][0]["installment"] == installment.id
    assert listing.json()["results"][0]["product_name"]

    assert client.get("/api/payments/?status=FAILED").json()["count"] == 0


@pytest.mark.django_db
def test_final_payment_completes_plan(auth_client, member, gateway):
    plan = make_plan(member)
    client = auth_client(member.user)
    for idx, installment in enumerate(plan.installments.order_by("sequence")):
        response = pay(client, installment, f"idem-plan-{idx}")
        assert response.status_code == 201

    plan.refresh_from_db()
    assert plan.status == PlanStatus.COMPLETED
