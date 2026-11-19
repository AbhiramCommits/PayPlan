from rest_framework import serializers

from apps.accounts.models import Member, SpendingLimit
from apps.plans.models import InstallmentStatus, PlanStatus
from apps.plans.services import available_spending_power, current_limit_cents


class SpendingLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpendingLimit
        fields = ["id", "limit_cents", "available_cents", "effective_at", "reason"]


class MemberSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Member
        fields = ["id", "external_id", "display_name", "status", "risk_tier", "base_limit_cents"]


class MemberMeSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    limit_cents = serializers.SerializerMethodField()
    available_cents = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)

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
            "next_due_date",
            "roles",
        ]

    def get_limit_cents(self, obj):
        return current_limit_cents(obj)

    def get_available_cents(self, obj):
        return available_spending_power(obj)

    def get_next_due_date(self, obj):
        from apps.plans.models import Installment

        return (
            Installment.objects.filter(
                plan__member=obj,
                plan__status__in=[PlanStatus.ACTIVE, PlanStatus.DELINQUENT],
            )
            .exclude(status__in=[InstallmentStatus.PAID, InstallmentStatus.WAIVED])
            .order_by("due_date")
            .values_list("due_date", flat=True)
            .first()
        )

    def get_roles(self, obj):
        roles = {"member"}
        user = obj.user
        if user.is_superuser or user.is_staff:
            roles.add("staff")
        if user.groups.filter(name="support").exists():
            roles.add("support")
        return sorted(roles)
