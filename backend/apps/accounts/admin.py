from django.contrib import admin

from apps.accounts.models import Member, SpendingLimit


class SpendingLimitInline(admin.TabularInline):
    model = SpendingLimit
    extra = 0
    can_delete = False
    readonly_fields = ["limit_cents", "available_cents", "reason", "effective_at", "created_at"]
    ordering = ["-id"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "external_id",
        "display_name",
        "status",
        "risk_tier",
        "base_limit_cents",
        "created_at",
    ]
    list_filter = ["status", "risk_tier"]
    search_fields = ["external_id", "user__username", "user__email", "user__first_name"]
    readonly_fields = ["external_id", "created_at"]
    inlines = [SpendingLimitInline]
    raw_id_fields = ["user"]


@admin.register(SpendingLimit)
class SpendingLimitAdmin(admin.ModelAdmin):
    list_display = ["id", "member", "limit_cents", "available_cents", "reason", "effective_at"]
    list_filter = ["reason"]
    search_fields = ["member__external_id", "member__user__username"]
    readonly_fields = ["effective_at", "created_at"]
    raw_id_fields = ["member"]

    def has_delete_permission(self, request, obj=None):
        return False
