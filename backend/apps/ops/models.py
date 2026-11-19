from django.conf import settings
from django.db import models

from apps.accounts.models import Member


class OpsAction(models.TextChoices):
    WAIVE_INSTALLMENT = "WAIVE_INSTALLMENT", "Waive installment"
    RESCHEDULE_DUE_DATE = "RESCHEDULE_DUE_DATE", "Reschedule due date"
    ADJUST_LIMIT = "ADJUST_LIMIT", "Adjust spending limit"


class OpsAuditLog(models.Model):
    """Append-only record of every support action."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ops_actions"
    )
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="ops_audit_logs")
    action = models.CharField(max_length=32, choices=OpsAction.choices)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["member", "created_at"], name="ops_audit_member_created_idx"),
            models.Index(fields=["actor", "created_at"], name="ops_audit_actor_created_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.member_id} by {self.actor_id}"
