from rest_framework import serializers

from apps.accounts.models import Member, SpendingLimit
from apps.ops.models import OpsAuditLog
from apps.plans.serializers import PlanSummarySerializer


class OpsMemberSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    limit_cents = serializers.SerializerMethodField()
    available_cents = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            "id",
            "external_id",
            "display_name",
            "email",
            "status",
            "risk_tier",
            "base_limit_cents",
            "limit_cents",
            "available_cents",
        ]

    def get_limit_cents(self, obj):
        from apps.plans.services import current_limit_cents

        return current_limit_cents(obj)

    def get_available_cents(self, obj):
        from apps.plans.services import available_spending_power

        return available_spending_power(obj)


class OpsLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpendingLimit
        fields = ["id", "limit_cents", "available_cents", "effective_at", "reason"]


class OpsMemberDetailSerializer(OpsMemberSerializer):
    plans = serializers.SerializerMethodField()
    limits = serializers.SerializerMethodField()

    class Meta(OpsMemberSerializer.Meta):
        fields = OpsMemberSerializer.Meta.fields + ["plans", "limits"]

    def get_plans(self, obj):
        from apps.plans.models import InstallmentPlan

        plans = (
            InstallmentPlan.objects.filter(member=obj)
            .select_related("order", "order__product")
            .prefetch_related("installments")
            .order_by("-created_at")
        )
        return PlanSummarySerializer(plans, many=True).data

    def get_limits(self, obj):
        return OpsLimitSerializer(obj.spending_limits.order_by("-id")[:20], many=True).data


class OpsAuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = OpsAuditLog
        fields = [
            "id",
            "actor",
            "actor_username",
            "member",
            "action",
            "before",
            "after",
            "created_at",
        ]


class WaiveSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class RescheduleSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AdjustLimitSerializer(serializers.Serializer):
    limit_cents = serializers.IntegerField(min_value=0, max_value=100_000_000)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
