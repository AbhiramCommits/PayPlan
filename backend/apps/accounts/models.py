import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class MemberStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    CLOSED = "CLOSED", "Closed"


class RiskTier(models.TextChoices):
    PRIME = "PRIME", "Prime"
    NEAR_PRIME = "NEAR_PRIME", "Near prime"
    SUBPRIME = "SUBPRIME", "Subprime"


class LimitReason(models.TextChoices):
    INITIAL = "INITIAL", "Initial"
    ON_TIME_INCREASE = "ON_TIME_INCREASE", "On-time increase"
    DELINQUENCY_DECREASE = "DELINQUENCY_DECREASE", "Delinquency decrease"
    MANUAL = "MANUAL", "Manual adjustment"


class Member(models.Model):
    """A PayPlan customer, one per Django auth user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="member"
    )
    external_id = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=16, choices=MemberStatus.choices, default=MemberStatus.ACTIVE
    )
    risk_tier = models.CharField(
        max_length=16, choices=RiskTier.choices, default=RiskTier.NEAR_PRIME
    )
    base_limit_cents = models.BigIntegerField(default=100_000, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="member_status_created_idx"),
        ]

    def __str__(self):
        return f"Member {self.external_id}"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username


class SpendingLimitQuerySet(models.QuerySet):
    def latest_first(self):
        return self.order_by("-effective_at", "-id")


class SpendingLimit(models.Model):
    """Append-only limit history.

    A new row is written whenever the limit policy changes.  ``available_cents``
    is a maintained snapshot of ``limit_cents - outstanding principal``; it is
    refreshed in place as reservations are created and released, while
    ``limit_cents`` itself is never rewritten.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="spending_limits")
    limit_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    available_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    effective_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=32, choices=LimitReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SpendingLimitQuerySet.as_manager()

    class Meta:
        ordering = ["-effective_at", "-id"]
        indexes = [
            models.Index(fields=["member", "-effective_at"], name="limit_member_effective_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(limit_cents__gte=0), name="spending_limit_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(available_cents__gte=0), name="available_limit_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(available_cents__lte=models.F("limit_cents")),
                name="available_limit_within_limit",
            ),
        ]

    def __str__(self):
        return f"{self.member_id}:{self.limit_cents}c ({self.reason})"
