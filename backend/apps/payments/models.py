from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Member
from apps.plans.models import Installment


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    REFUNDED = "REFUNDED", "Refunded"


class Payment(models.Model):
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="payments")
    installment = models.ForeignKey(
        Installment,
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    amount_cents = models.BigIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    gateway_ref = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=255, unique=True)
    request_fingerprint = models.CharField(max_length=64)
    attempt_no = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    failure_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["member", "status"], name="payment_member_status_idx"),
            models.Index(fields=["installment", "status"], name="payment_inst_status_idx"),
            models.Index(fields=["created_at"], name="payment_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(condition=Q(attempt_no__gte=1), name="payment_attempt_positive"),
        ]

    def __str__(self):
        return f"Payment {self.pk} {self.status} {self.amount_cents}c"


class WebhookEvent(models.Model):
    provider_event_id = models.CharField(max_length=128, unique=True)
    type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Webhook {self.provider_event_id} ({self.type})"


class Notification(models.Model):
    """A reminder/dunning notification placeholder (no outbound email)."""

    CHANNEL_EMAIL = "EMAIL"
    CHANNEL_SMS = "SMS"
    CHANNEL_CHOICES = [(CHANNEL_EMAIL, "Email"), (CHANNEL_SMS, "SMS")]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="notifications")
    installment = models.ForeignKey(
        Installment,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, default=CHANNEL_EMAIL)
    template = models.CharField(max_length=64)
    sent_at = models.DateTimeField(default=timezone.now)
    dedupe_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at", "-id"]
        indexes = [
            models.Index(fields=["member", "template"], name="notification_member_tpl_idx"),
        ]

    def __str__(self):
        return f"{self.template} -> {self.member_id}"
