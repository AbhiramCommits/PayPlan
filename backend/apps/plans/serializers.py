from rest_framework import serializers

from apps.accounts.models import Member
from apps.catalog.models import Product
from apps.plans.models import Installment, InstallmentPlan, Order


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "sku", "name", "price_cents", "active"]


class InstallmentSerializer(serializers.ModelSerializer):
    remaining_cents = serializers.IntegerField(read_only=True)
    days_late = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = [
            "id",
            "sequence",
            "due_date",
            "amount_cents",
            "amount_paid_cents",
            "remaining_cents",
            "status",
            "paid_at",
            "days_late",
        ]

    def get_days_late(self, obj):
        from django.utils import timezone

        if obj.status in ("PAID", "WAIVED") or obj.due_date >= timezone.localdate():
            return 0
        return obj.days_late(timezone.localdate())


class OrderSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "product", "qty", "total_cents", "status", "created_at"]


class PlanSummarySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="order.product.name", read_only=True)
    paid_count = serializers.SerializerMethodField()
    total_count = serializers.IntegerField(source="num_installments", read_only=True)
    next_due_date = serializers.SerializerMethodField()

    class Meta:
        model = InstallmentPlan
        fields = [
            "id",
            "product_name",
            "principal_cents",
            "num_installments",
            "cadence",
            "status",
            "start_date",
            "paid_count",
            "total_count",
            "next_due_date",
        ]

    def get_paid_count(self, obj):
        installments = list(obj.installments.all())
        return sum(1 for i in installments if i.status == "PAID")

    def get_next_due_date(self, obj):
        dates = [i.due_date for i in obj.installments.all() if i.status not in ("PAID", "WAIVED")]
        return min(dates) if dates else None


class PlanDetailSerializer(PlanSummarySerializer):
    installments = InstallmentSerializer(many=True, read_only=True)
    order = OrderSerializer(read_only=True)

    class Meta(PlanSummarySerializer.Meta):
        fields = PlanSummarySerializer.Meta.fields + ["installments", "order"]


class CheckoutSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(active=True))
    qty = serializers.IntegerField(min_value=1, default=1)
    num_installments = serializers.IntegerField(min_value=4, max_value=8)
    cadence = serializers.ChoiceField(choices=["BIWEEKLY", "MONTHLY"], default="BIWEEKLY")
    start_date = serializers.DateField(required=False)

    def validate_product(self, value):
        if not value.active:
            raise serializers.ValidationError("Product is not available.")
        return value


class CheckoutResponseSerializer(serializers.Serializer):
    order = OrderSerializer()
    plan = PlanDetailSerializer()
    member = serializers.SerializerMethodField()


class CustomerSerializer(serializers.ModelSerializer):
    """Used by ops endpoints to show the member alongside their plans."""

    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Member
        fields = ["id", "external_id", "display_name", "status", "risk_tier"]
