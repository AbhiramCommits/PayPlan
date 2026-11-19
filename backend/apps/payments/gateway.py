"""Payment gateway abstraction.

The domain never imports Stripe directly.  ``settings.PAYMENT_GATEWAY`` selects
the adapter, and tests/local development use ``FakeGateway`` so the entire test
suite runs with zero network access.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class GatewayResult:
    ref: str
    status: str  # "SUCCEEDED" | "FAILED"
    failure_code: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCEEDED"


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, amount_cents: int, idempotency_key: str, metadata: dict | None = None):
        """Charge ``amount_cents`` once for ``idempotency_key``."""


class FakeGateway(PaymentGateway):
    """Deterministic local gateway.

    Amounts ending in ``01`` fail with ``card_declined``; amounts ending in
    ``02`` fail with ``insufficient_funds``; everything else succeeds.  Tests
    can also inject an explicit queue of failure codes.
    """

    name = "fake"

    def __init__(self, failures: list[str] | None = None, fail_all: str | None = None):
        self._failures = list(failures or [])
        self._fail_all = fail_all
        self.charges: list[dict] = []
        self._lock = threading.Lock()

    def charge(self, amount_cents: int, idempotency_key: str, metadata: dict | None = None):
        with self._lock:
            self.charges.append(
                {
                    "amount_cents": amount_cents,
                    "idempotency_key": idempotency_key,
                    "metadata": dict(metadata or {}),
                }
            )
            failure_code = None
            if self._failures:
                failure_code = self._failures.pop(0)
            elif self._fail_all:
                failure_code = self._fail_all
            else:
                suffix = f"{amount_cents:02d}"[-2:]
                if suffix == "01":
                    failure_code = "card_declined"
                elif suffix == "02":
                    failure_code = "insufficient_funds"

        if failure_code:
            return GatewayResult(
                ref=f"fake_fail_{uuid.uuid4().hex[:20]}",
                status="FAILED",
                failure_code=failure_code,
            )
        return GatewayResult(ref=f"fake_{uuid.uuid4().hex[:24]}", status="SUCCEEDED")

    @property
    def charge_count(self) -> int:
        with self._lock:
            return len(self.charges)


class StripeGateway(PaymentGateway):
    """Stripe PaymentIntent adapter.  Test mode only by design."""

    name = "stripe"

    def __init__(self, api_key: str | None = None):
        import stripe

        self.stripe = stripe
        self.api_key = api_key or settings.STRIPE_SECRET_KEY
        if not self.api_key:
            raise ImproperlyConfigured("STRIPE_SECRET_KEY is required for StripeGateway")
        if not self.api_key.startswith("sk_test_"):
            raise ImproperlyConfigured("PayPlan only allows Stripe test-mode keys (sk_test_...)")
        self.stripe.api_key = self.api_key

    def charge(self, amount_cents: int, idempotency_key: str, metadata: dict | None = None):
        try:
            intent = self.stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                payment_method="pm_card_visa",
                confirm=True,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                idempotency_key=idempotency_key,
                metadata=dict(metadata or {}),
            )
        except self.stripe.CardError as exc:
            return GatewayResult(
                ref=getattr(exc, "user_message", "") or "card_error",
                status="FAILED",
                failure_code=getattr(exc, "code", None) or "card_declined",
            )
        except self.stripe.StripeError:
            return GatewayResult(ref="stripe_error", status="FAILED", failure_code="gateway_error")

        if intent.status in {"succeeded", "processing"}:
            return GatewayResult(ref=intent.id, status="SUCCEEDED")
        return GatewayResult(ref=intent.id, status="FAILED", failure_code=f"intent_{intent.status}")


def get_gateway() -> PaymentGateway:
    backend = (settings.PAYMENT_GATEWAY or "fake").lower()
    if backend == "fake":
        return FakeGateway()
    if backend == "stripe":
        return StripeGateway()
    raise ImproperlyConfigured(f"Unknown PAYMENT_GATEWAY: {backend!r}")
