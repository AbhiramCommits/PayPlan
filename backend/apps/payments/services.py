"""Payment orchestration: idempotency, settlement, and webhook application."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Member
from apps.payments.gateway import PaymentGateway, get_gateway
from apps.payments.models import Payment, PaymentStatus, WebhookEvent
from apps.plans.models import Installment, InstallmentStatus, PlanStatus
from apps.plans.services import recalculate_limit, sync_available

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    code = "payment_error"


class MissingIdempotencyKey(PaymentError):
    code = "missing_idempotency_key"


class IdempotencyConflict(PaymentError):
    code = "idempotency_conflict"

    def __init__(self, existing_payment_id: int):
        self.existing_payment_id = existing_payment_id
        super().__init__("Idempotency-Key was already used with a different request body")


class InstallmentSettled(PaymentError):
    code = "installment_settled"


class InvalidPaymentAmount(PaymentError):
    code = "invalid_payment_amount"


class PaymentNotFound(PaymentError):
    code = "payment_not_found"


@dataclass(frozen=True)
class PaymentOutcome:
    payment: Payment
    replayed: bool


def fingerprint(member_id: int, installment_id: int | None, amount_cents: int | None) -> str:
    payload = {
        "member_id": member_id,
        "installment_id": installment_id,
        "amount_cents": amount_cents,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def serialize_payment(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "installment": payment.installment_id,
        "amount_cents": payment.amount_cents,
        "status": payment.status,
        "gateway_ref": payment.gateway_ref,
        "attempt_no": payment.attempt_no,
        "failure_code": payment.failure_code,
        "created_at": payment.created_at.isoformat(),
    }


def _settle_installment(installment: Installment, amount_cents: int, now):
    """Apply a successful charge exactly once (caller holds the row lock)."""
    already = installment.amount_paid_cents
    new_paid = min(already + amount_cents, installment.amount_cents)
    if new_paid == already:
        return False
    installment.amount_paid_cents = new_paid
    if new_paid >= installment.amount_cents:
        installment.status = InstallmentStatus.PAID
        installment.paid_at = now
    else:
        installment.status = InstallmentStatus.DUE
    installment.save(update_fields=["amount_paid_cents", "status", "paid_at"])
    return True


def _finalize_plan_if_complete(plan, now):
    if plan.installments.exclude(
        status__in=[InstallmentStatus.PAID, InstallmentStatus.WAIVED]
    ).exists():
        return False
    plan.status = PlanStatus.COMPLETED
    plan.save(update_fields=["status"])
    recalculate_limit(plan.member, as_of=timezone.localtime(now).date())
    return True


def mark_payment_succeeded(payment_id: int, now=None, gateway_ref: str | None = None):
    """Idempotently settle a payment and its installment."""
    now = now or timezone.now()
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment
        installment = None
        if payment.installment_id:
            installment = Installment.objects.select_for_update().get(pk=payment.installment_id)
        payment.status = PaymentStatus.SUCCEEDED
        payment.failure_code = ""
        if gateway_ref:
            payment.gateway_ref = gateway_ref
        payment.save(update_fields=["status", "failure_code", "gateway_ref", "updated_at"])
        if installment is not None:
            _settle_installment(installment, payment.amount_cents, now)
            sync_available(payment.member)
            _finalize_plan_if_complete(installment.plan, now)
        return payment


def mark_payment_failed(payment_id: int, failure_code: str):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment
        if payment.status == PaymentStatus.FAILED:
            return payment
        payment.status = PaymentStatus.FAILED
        payment.failure_code = failure_code or "gateway_error"
        payment.save(update_fields=["status", "failure_code", "updated_at"])
        if payment.installment_id:
            installment = Installment.objects.select_for_update().get(pk=payment.installment_id)
            if not installment.is_settled:
                installment.status = InstallmentStatus.FAILED
                installment.save(update_fields=["status"])
        return payment


def _enqueue_dunning(payment_id: int):
    """Hand the failure to Celery without making the API response depend on it."""
    try:
        from apps.payments.tasks import retry_failed_payment_task as retry_failed_payment

        retry_failed_payment.delay(payment_id)
    except Exception:  # pragma: no cover - broker down / task not wired yet
        logger.warning("could not enqueue dunning for payment %s", payment_id, exc_info=True)


def process_payment(
    *,
    member: Member,
    installment: Installment,
    idempotency_key: str,
    amount_cents: int | None = None,
    gateway: PaymentGateway | None = None,
    now=None,
    enqueue_dunning: bool = True,
) -> tuple[PaymentOutcome, int]:
    """Create at most one charge per idempotency key.

    Returns ``(outcome, http_status)``.  The installment row is locked before
    the second idempotency lookup, so concurrent requests with the same key
    serialise and only one gateway charge happens.
    """
    if not idempotency_key:
        raise MissingIdempotencyKey("Idempotency-Key header is required")
    now = now or timezone.now()
    gateway = gateway or get_gateway()
    request_fp = fingerprint(member.id, installment.id, amount_cents)

    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.request_fingerprint != request_fp:
            raise IdempotencyConflict(existing.id)
        return PaymentOutcome(existing, replayed=True), _status_for(existing)

    try:
        with transaction.atomic():
            locked = (
                Installment.objects.select_for_update()
                .select_related("plan", "plan__member")
                .get(pk=installment.pk)
            )
            if locked.plan.member_id != member.id:
                raise PaymentNotFound("installment does not belong to this member")

            existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                if existing.request_fingerprint != request_fp:
                    raise IdempotencyConflict(existing.id)
                return PaymentOutcome(existing, replayed=True), _status_for(existing)

            if locked.is_settled:
                raise InstallmentSettled("installment is already settled")
            remaining = locked.remaining_cents
            charge_amount = remaining if amount_cents is None else amount_cents
            if charge_amount <= 0 or charge_amount > remaining:
                raise InvalidPaymentAmount(f"amount must be between 1 and {remaining} cents")

            attempt_no = Payment.objects.filter(installment=locked).count() + 1
            payment = Payment.objects.create(
                member=member,
                installment=locked,
                amount_cents=charge_amount,
                status=PaymentStatus.PENDING,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fp,
                attempt_no=attempt_no,
                created_at=now,
            )

            try:
                result = gateway.charge(
                    charge_amount,
                    idempotency_key,
                    metadata={
                        "payment_id": payment.id,
                        "member_id": member.id,
                        "installment_id": locked.id,
                    },
                )
            except Exception:  # gateway/network failure must not lose the attempt
                logger.exception("gateway raised for payment %s", payment.id)
                payment.status = PaymentStatus.FAILED
                payment.failure_code = "gateway_error"
                payment.save(update_fields=["status", "failure_code", "updated_at"])
                locked.status = InstallmentStatus.FAILED
                locked.save(update_fields=["status"])
                if enqueue_dunning:
                    transaction.on_commit(lambda: _enqueue_dunning(payment.id))
                return PaymentOutcome(payment, replayed=False), 502

            if result.succeeded:
                payment.status = PaymentStatus.SUCCEEDED
                payment.gateway_ref = result.ref
                payment.save(update_fields=["status", "gateway_ref", "updated_at"])
                _settle_installment(locked, charge_amount, now)
                sync_available(member)
                _finalize_plan_if_complete(locked.plan, now)
                return PaymentOutcome(payment, replayed=False), 201

            payment.status = PaymentStatus.FAILED
            payment.failure_code = result.failure_code or "gateway_error"
            payment.gateway_ref = result.ref
            payment.save(update_fields=["status", "failure_code", "gateway_ref", "updated_at"])
            locked.status = InstallmentStatus.FAILED
            locked.save(update_fields=["status"])
            if enqueue_dunning:
                transaction.on_commit(lambda: _enqueue_dunning(payment.id))
            return PaymentOutcome(payment, replayed=False), 402
    except IntegrityError as exc:
        # Uniqueness constraint won the race; replay the committed row.
        existing = Payment.objects.get(idempotency_key=idempotency_key)
        if existing.request_fingerprint != request_fp:
            raise IdempotencyConflict(existing.id) from exc
        return PaymentOutcome(existing, replayed=True), _status_for(existing)


class PaymentGatewayError(PaymentError):
    code = "gateway_error"


def _status_for(payment: Payment) -> int:
    if payment.status == PaymentStatus.SUCCEEDED:
        return 200
    if payment.status == PaymentStatus.FAILED:
        return 402
    return 202


def apply_webhook_event(event: dict, now=None) -> WebhookEvent:
    """Persist and apply a provider event exactly once."""
    now = now or timezone.now()
    event_id = event.get("id")
    if not event_id:
        raise PaymentError("webhook event is missing an id")
    event_type = event.get("type", "")
    allowed = {
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "charge.succeeded",
        "charge.failed",
    }
    if event_type not in allowed:
        webhook, _created = WebhookEvent.objects.get_or_create(
            provider_event_id=event_id,
            defaults={"type": event_type, "payload": event, "processed_at": now},
        )
        return webhook

    webhook, created = WebhookEvent.objects.get_or_create(
        provider_event_id=event_id,
        defaults={"type": event_type, "payload": event},
    )
    if not created and webhook.processed_at is not None:
        return webhook  # replay is a no-op

    obj = event.get("data", {}).get("object", {})
    gateway_ref = obj.get("id") or obj.get("payment_intent") or ""
    payment_id = (obj.get("metadata") or {}).get("payment_id")

    payment = None
    if payment_id:
        payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None and gateway_ref:
        payment = Payment.objects.filter(gateway_ref=gateway_ref).first()

    if payment is not None:
        if event_type in {"payment_intent.succeeded", "charge.succeeded"}:
            mark_payment_succeeded(payment.id, now=now, gateway_ref=gateway_ref or None)
        else:
            failure = (
                (obj.get("last_payment_error") or {}).get("code")
                or obj.get("failure_code")
                or "card_declined"
            )
            mark_payment_failed(payment.id, failure)

    WebhookEvent.objects.filter(pk=webhook.pk).update(processed_at=now)
    webhook.processed_at = now
    return webhook
