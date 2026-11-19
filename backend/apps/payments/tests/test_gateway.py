from types import SimpleNamespace

import pytest
import stripe
from django.core.exceptions import ImproperlyConfigured

from apps.payments.gateway import FakeGateway, StripeGateway, get_gateway


def test_fake_gateway_success_and_deterministic_failures():
    gateway = FakeGateway()
    assert gateway.charge(1000, "k1").succeeded
    declined = gateway.charge(1001, "k2")
    assert not declined.succeeded
    assert declined.failure_code == "card_declined"
    insufficient = gateway.charge(1202, "k3")
    assert insufficient.failure_code == "insufficient_funds"
    assert gateway.charge_count == 3
    assert [c["idempotency_key"] for c in gateway.charges] == ["k1", "k2", "k3"]


def test_fake_gateway_failure_queue_is_consumed_in_order():
    gateway = FakeGateway(failures=["card_declined", "insufficient_funds"])
    assert gateway.charge(5000, "a").failure_code == "card_declined"
    assert gateway.charge(5000, "b").failure_code == "insufficient_funds"
    assert gateway.charge(5000, "c").succeeded
    assert gateway.charge_count == 3


def test_fake_gateway_fail_all():
    gateway = FakeGateway(fail_all="network_down")
    result = gateway.charge(999, "k")
    assert result.status == "FAILED"
    assert result.failure_code == "network_down"


def test_gateway_selection_from_settings(settings):
    settings.PAYMENT_GATEWAY = "fake"
    assert isinstance(get_gateway(), FakeGateway)
    settings.PAYMENT_GATEWAY = "nonsense"
    with pytest.raises(ImproperlyConfigured):
        get_gateway()


def test_stripe_gateway_requires_test_key(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_abc"
    StripeGateway()  # ok
    with pytest.raises(ImproperlyConfigured):
        StripeGateway(api_key="sk_live_abc")


def test_stripe_gateway_success(monkeypatch):
    calls = {}

    def fake_create(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(id="pi_test_123", status="succeeded")

    monkeypatch.setattr(stripe.PaymentIntent, "create", fake_create)
    gateway = StripeGateway(api_key="sk_test_xyz")
    result = gateway.charge(2500, "idem-1", {"payment_id": 7})

    assert result.succeeded
    assert result.ref == "pi_test_123"
    assert calls["amount"] == 2500
    assert calls["idempotency_key"] == "idem-1"
    assert calls["currency"] == "usd"
    assert calls["metadata"] == {"payment_id": 7}


def test_stripe_gateway_maps_card_error(monkeypatch):
    def fake_create(**kwargs):
        raise stripe.CardError("declined", None, "card_declined")

    monkeypatch.setattr(stripe.PaymentIntent, "create", fake_create)
    gateway = StripeGateway(api_key="sk_test_xyz")
    result = gateway.charge(2501, "idem-2")
    assert result.status == "FAILED"
    assert result.failure_code == "card_declined"


def test_stripe_gateway_maps_stripe_error(monkeypatch):
    def fake_create(**kwargs):
        raise stripe.APIConnectionError("down")

    monkeypatch.setattr(stripe.PaymentIntent, "create", fake_create)
    gateway = StripeGateway(api_key="sk_test_xyz")
    result = gateway.charge(2500, "idem-3")
    assert result.status == "FAILED"
    assert result.failure_code == "gateway_error"


def test_stripe_gateway_requires_action_is_failed(monkeypatch):
    monkeypatch.setattr(
        stripe.PaymentIntent,
        "create",
        lambda **kwargs: SimpleNamespace(id="pi_req", status="requires_action"),
    )
    gateway = StripeGateway(api_key="sk_test_xyz")
    result = gateway.charge(2500, "idem-4")
    assert result.status == "FAILED"
    assert result.failure_code == "intent_requires_action"
