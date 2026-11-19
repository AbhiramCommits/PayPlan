from django.contrib import admin

from apps.payments.models import Notification, Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "member",
        "installment",
        "amount_cents",
        "status",
        "attempt_no",
        "failure_code",
        "created_at",
    ]
    list_filter = ["status", "failure_code", "created_at"]
    search_fields = [
        "member__external_id",
        "gateway_ref",
        "idempotency_key",
        "installment__plan__member__external_id",
    ]
    readonly_fields = [
        "gateway_ref",
        "idempotency_key",
        "request_fingerprint",
        "attempt_no",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["member", "installment"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["provider_event_id", "type", "processed_at", "created_at"]
    list_filter = ["type"]
    search_fields = ["provider_event_id"]
    readonly_fields = ["provider_event_id", "type", "payload", "processed_at", "created_at"]

    def has_add_permission(self, request):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "member", "installment", "channel", "template", "sent_at"]
    list_filter = ["channel", "template"]
    search_fields = ["member__external_id", "dedupe_key"]
    readonly_fields = ["dedupe_key", "sent_at", "created_at"]

    def has_add_permission(self, request):
        return False
