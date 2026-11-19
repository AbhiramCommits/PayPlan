import json

from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.gateway import get_gateway
from apps.payments.models import Payment, WebhookEvent
from apps.payments.serializers import PaymentCreateSerializer, PaymentSerializer
from apps.payments.services import (
    IdempotencyConflict,
    InstallmentSettled,
    InvalidPaymentAmount,
    MissingIdempotencyKey,
    PaymentError,
    PaymentOutcome,
    apply_webhook_event,
    process_payment,
    serialize_payment,
)
from apps.plans.models import Installment


def _error(code: str, message: str, http_status: int, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http_status)


def _payment_response(outcome: PaymentOutcome, http_status: int):
    body = {
        "payment": serialize_payment(outcome.payment),
        "replayed": outcome.replayed,
    }
    if outcome.payment.status == "FAILED":
        body["error"] = {
            "code": "payment_failed",
            "message": "The gateway declined this charge.",
            "failure_code": outcome.payment.failure_code,
        }
    return Response(body, status=http_status)


class PaymentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer
    filterset_fields = ["status", "installment"]
    ordering_fields = ["created_at", "amount_cents"]
    ordering = ["-created_at"]

    def get_queryset(self):
        member = getattr(self.request.user, "member", None)
        if member is None:
            return Payment.objects.none()
        return Payment.objects.filter(member=member).select_related(
            "installment", "installment__plan", "installment__plan__order__product"
        )

    def create(self, request):
        member = getattr(request.user, "member", None)
        if member is None:
            return _error("no_member_profile", "No member profile for this user.", 404)

        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return _error(
                "missing_idempotency_key",
                "An Idempotency-Key header is required for payments.",
                status.HTTP_400_BAD_REQUEST,
            )

        installment = get_object_or_404(
            Installment,
            pk=serializer.validated_data["installment"],
            plan__member=member,
        )

        try:
            outcome, http_status = process_payment(
                member=member,
                installment=installment,
                idempotency_key=idempotency_key,
                amount_cents=serializer.validated_data.get("amount_cents"),
                gateway=get_gateway(),
            )
        except MissingIdempotencyKey as exc:
            return _error(exc.code, str(exc), 400)
        except IdempotencyConflict as exc:
            return _error(
                exc.code,
                str(exc),
                409,
                existing_payment_id=exc.existing_payment_id,
            )
        except InstallmentSettled as exc:
            return _error(exc.code, str(exc), 409)
        except InvalidPaymentAmount as exc:
            return _error(exc.code, str(exc), 400)
        except PaymentError as exc:
            return _error(exc.code, str(exc), 502)

        return _payment_response(outcome, http_status)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """Stripe-compatible webhook receiver.

    Verification happens when ``STRIPE_WEBHOOK_SECRET`` is configured.  Events
    are deduped on ``provider_event_id``; replaying an event is a no-op.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from django.conf import settings

        payload = request.body
        signature = request.headers.get("Stripe-Signature", "")
        secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

        if secret:
            import stripe

            try:
                event = stripe.Webhook.construct_event(payload, signature, secret)
            except (ValueError, stripe.SignatureVerificationError):
                return _error("invalid_signature", "Invalid Stripe signature.", 400)
            if hasattr(event, "to_dict_recursive"):
                event = event.to_dict_recursive()
        else:
            try:
                event = json.loads(payload or b"{}")
            except json.JSONDecodeError:
                return _error("invalid_payload", "Body must be JSON.", 400)

        try:
            existing_processed = WebhookEvent.objects.filter(
                provider_event_id=event.get("id"), processed_at__isnull=False
            ).exists()
            webhook = apply_webhook_event(event)
        except PaymentError as exc:
            return _error(exc.code, str(exc), 400)

        return Response(
            {
                "status": "duplicate" if existing_processed else "processed",
                "event_id": webhook.provider_event_id,
            }
        )
