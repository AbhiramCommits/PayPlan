from django.contrib import admin

from apps.ops.models import OpsAuditLog


@admin.register(OpsAuditLog)
class OpsAuditLogAdmin(admin.ModelAdmin):
    list_display = ["id", "actor", "member", "action", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["actor__username", "member__external_id"]
    readonly_fields = ["actor", "member", "action", "before", "after", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
