from django.contrib import admin

from apps.plans.models import (
    Installment,
    InstallmentPlan,
    Order,
    PlanRollup,
)


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    can_delete = False
    fields = [
        "sequence",
        "due_date",
        "amount_cents",
        "amount_paid_cents",
        "status",
        "paid_at",
    ]
    ordering = ["sequence"]
    readonly_fields = [
        "sequence",
        "due_date",
        "amount_cents",
        "amount_paid_cents",
        "status",
        "paid_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "member", "product", "qty", "total_cents", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["member__external_id", "member__user__username", "product__sku"]
    raw_id_fields = ["member", "product"]


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "member",
        "principal_cents",
        "num_installments",
        "cadence",
        "status",
        "start_date",
        "created_at",
    ]
    list_filter = ["status", "cadence"]
    search_fields = ["member__external_id", "member__user__username"]
    readonly_fields = ["created_at"]
    inlines = [InstallmentInline]
    raw_id_fields = ["order", "member"]


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "plan",
        "sequence",
        "due_date",
        "amount_cents",
        "amount_paid_cents",
        "status",
    ]
    list_filter = ["status", "due_date"]
    search_fields = ["plan__member__external_id"]
    raw_id_fields = ["plan"]


@admin.register(PlanRollup)
class PlanRollupAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "active_plans",
        "delinquent_plans",
        "billed_cents",
        "collected_cents",
        "on_time_rate",
        "dunning_recovery_rate",
    ]
    list_filter = ["date"]
    readonly_fields = ["date", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
