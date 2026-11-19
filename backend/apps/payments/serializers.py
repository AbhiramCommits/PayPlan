from rest_framework import serializers

from apps.payments.models import Payment, WebhookEvent


class PaymentSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="installment.plan.order.product.name", read_only=True, default=""
    )
    plan_id = serializers.IntegerField(source="installment.plan_id", read_only=True, default=None)

    class Meta:
        model = Payment
        fields = [
            "id",
            "installment",
            "plan_id",
            "product_name",
            "amount_cents",
            "status",
            "gateway_ref",
            "attempt_no",
            "failure_code",
            "created_at",
        ]


class PaymentCreateSerializer(serializers.Serializer):
    installment = serializers.IntegerField(min_value=1)
    amount_cents = serializers.IntegerField(min_value=1, required=False)


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = ["id", "provider_event_id", "type", "processed_at", "created_at"]
