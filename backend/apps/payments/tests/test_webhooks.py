import hashlib
import hmac
import json
import time

import pytest

from apps.payments.models import PaymentStatus, WebhookEvent
from apps.plans.models import InstallmentStatus
from tests.factories import InstallmentPlanFactory, PaymentFactory


def event(event_id, event_type, ref, **object_extra):
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": {"id": ref, **object_extra}},
    }


@pytest.mark.django_db
def test_webhook_success_applies_once_and_replay_is_noop(api_client):
    plan = InstallmentPlanFactory(principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    payment = PaymentFactory(
        installment=installment,
        amount_cents=installment.amount_cents,
        status=PaymentStatus.PENDING,
        gateway_ref="pi_test_success",
    )
    payload = event("evt_1", "payment_intent.succeeded", "pi_test_success")

    first = api_client.post("/api/webhooks/stripe/", payload, format="json")
    assert first.status_code == 200, first.content
    assert first.json()["status"] == "processed"

    installment.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert installment.status == InstallmentStatus.PAID
    assert installment.amount_paid_cents == installment.amount_cents

    replay = api_client.post("/api/webhooks/stripe/", payload, format="json")
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"
    installment.refresh_from_db()
    assert installment.amount_paid_cents == installment.amount_cents
    assert WebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_webhook_failure_marks_payment_failed(api_client):
    plan = InstallmentPlanFactory(principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    payment = PaymentFactory(
        installment=installment,
        amount_cents=installment.amount_cents,
        status=PaymentStatus.PENDING,
        gateway_ref="pi_test_fail",
    )
    payload = event(
        "evt_2",
        "payment_intent.payment_failed",
        "pi_test_fail",
        last_payment_error={"code": "insufficient_funds"},
    )
    response = api_client.post("/api/webhooks/stripe/", payload, format="json")
    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert payment.failure_code == "insufficient_funds"
    installment.refresh_from_db()
    assert installment.status == InstallmentStatus.FAILED


@pytest.mark.django_db
def test_webhook_never_downgrades_a_successful_payment(api_client):
    plan = InstallmentPlanFactory(principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    payment = PaymentFactory(
        installment=installment,
        amount_cents=installment.amount_cents,
        status=PaymentStatus.SUCCEEDED,
        gateway_ref="pi_test_paid",
    )
    payload = event("evt_3", "charge.failed", "pi_test_paid")
    assert api_client.post("/api/webhooks/stripe/", payload, format="json").status_code == 200
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED


@pytest.mark.django_db
def test_webhook_unknown_reference_is_accepted_and_recorded(api_client):
    payload = event("evt_unknown", "payment_intent.succeeded", "pi_does_not_exist")
    response = api_client.post("/api/webhooks/stripe/", payload, format="json")
    assert response.status_code == 200
    assert WebhookEvent.objects.filter(provider_event_id="evt_unknown").exists()


@pytest.mark.django_db
def test_webhook_missing_event_id_is_400(api_client):
    response = api_client.post(
        "/api/webhooks/stripe/", {"type": "payment_intent.succeeded"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "payment_error"


@pytest.mark.django_db
def test_webhook_signature_verification(api_client, settings):
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_secret"
    plan = InstallmentPlanFactory(principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    PaymentFactory(
        installment=installment,
        amount_cents=installment.amount_cents,
        status=PaymentStatus.PENDING,
        gateway_ref="pi_signed",
    )
    payload = event("evt_signed", "payment_intent.succeeded", "pi_signed")
    body = json.dumps(payload)
    timestamp = int(time.time())
    signature = hmac.new(
        b"whsec_test_secret", f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    header = f"t={timestamp},v1={signature}"

    bad = api_client.post(
        "/api/webhooks/stripe/",
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=deadbeef",
    )
    assert bad.status_code == 400

    good = api_client.post(
        "/api/webhooks/stripe/",
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=header,
    )
    assert good.status_code == 200, good.content
    assert good.json()["status"] == "processed"


@pytest.mark.django_db
def test_webhook_can_reference_payment_by_metadata(api_client):
    plan = InstallmentPlanFactory(principal_cents=40_000)
    installment = plan.installments.order_by("sequence").first()
    payment = PaymentFactory(
        installment=installment,
        amount_cents=installment.amount_cents,
        status=PaymentStatus.PENDING,
        gateway_ref="",
    )
    payload = {
        "id": "evt_meta",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_meta", "metadata": {"payment_id": str(payment.id)}}},
    }
    response = api_client.post("/api/webhooks/stripe/", payload, format="json")
    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.gateway_ref == "pi_meta"


@pytest.mark.django_db
def test_webhook_stores_raw_payload(api_client):
    payload = event("evt_payload", "payment_intent.succeeded", "pi_none")
    api_client.post("/api/webhooks/stripe/", payload, format="json")
    stored = WebhookEvent.objects.get(provider_event_id="evt_payload")
    assert stored.payload["data"]["object"]["id"] == "pi_none"
    assert stored.processed_at is not None
