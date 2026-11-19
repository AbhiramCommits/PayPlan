from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import Member


class OrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"
    FULFILLED = "FULFILLED", "Fulfilled"


class Cadence(models.TextChoices):
    BIWEEKLY = "BIWEEKLY", "Biweekly"
    MONTHLY = "MONTHLY", "Monthly"


class PlanStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    DELINQUENT = "DELINQUENT", "Delinquent"
    CANCELLED = "CANCELLED", "Cancelled"


class InstallmentStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    DUE = "DUE", "Due"
    PAID = "PAID", "Paid"
    LATE = "LATE", "Late"
    FAILED = "FAILED", "Failed"
    WAIVED = "WAIVED", "Waived"


class Order(models.Model):
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="orders")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="orders")
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    total_cents = models.BigIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["member", "status"], name="order_member_status_idx"),
            models.Index(fields=["created_at"], name="order_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(qty__gte=1), name="order_qty_positive"),
            models.CheckConstraint(
                condition=Q(total_cents__gte=0), name="order_total_non_negative"
            ),
        ]

    def __str__(self):
        return f"Order {self.pk} {self.status} {self.total_cents}c"


class InstallmentPlan(models.Model):
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="plan")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="plans")
    principal_cents = models.BigIntegerField(validators=[MinValueValidator(1)])
    num_installments = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    cadence = models.CharField(max_length=16, choices=Cadence.choices, default=Cadence.BIWEEKLY)
    status = models.CharField(max_length=16, choices=PlanStatus.choices, default=PlanStatus.ACTIVE)
    start_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["member", "status"], name="plan_member_status_idx"),
            models.Index(fields=["start_date"], name="plan_start_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(principal_cents__gt=0), name="plan_principal_positive"
            ),
            models.CheckConstraint(
                condition=Q(num_installments__gte=1) & Q(num_installments__lte=24),
                name="plan_installment_count_sane",
            ),
        ]

    def __str__(self):
        return f"Plan {self.pk} {self.status} {self.principal_cents}c"

    @property
    def paid_count(self):
        return sum(1 for i in self.installments.all() if i.status == InstallmentStatus.PAID)

    @property
    def outstanding_cents(self):
        return sum(i.remaining_cents for i in self.installments.all())


class Installment(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name="installments")
    sequence = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    due_date = models.DateField()
    amount_cents = models.BigIntegerField(validators=[MinValueValidator(1)])
    amount_paid_cents = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    status = models.CharField(
        max_length=16, choices=InstallmentStatus.choices, default=InstallmentStatus.SCHEDULED
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["plan", "sequence"]
        indexes = [
            models.Index(fields=["status", "due_date"], name="installment_status_due_idx"),
            models.Index(fields=["due_date"], name="installment_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["plan", "sequence"], name="unique_installment_seq"),
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0), name="installment_amount_positive"
            ),
            models.CheckConstraint(
                condition=Q(amount_paid_cents__gte=0), name="installment_paid_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(amount_paid_cents__lte=F("amount_cents")),
                name="installment_paid_not_over_amount",
            ),
        ]

    def __str__(self):
        return f"Plan {self.plan_id} #{self.sequence} ({self.status})"

    @property
    def remaining_cents(self):
        if self.status in (InstallmentStatus.PAID, InstallmentStatus.WAIVED):
            return 0
        return max(self.amount_cents - self.amount_paid_cents, 0)

    @property
    def is_settled(self):
        return self.status in (InstallmentStatus.PAID, InstallmentStatus.WAIVED)

    def days_late(self, as_of):
        if self.due_date >= as_of:
            return 0
        return (as_of - self.due_date).days


class PlanRollup(models.Model):
    """One row per calendar day, recomputable and safe to rerun."""

    date = models.DateField(unique=True)
    active_plans = models.IntegerField(default=0)
    delinquent_plans = models.IntegerField(default=0)
    billed_cents = models.BigIntegerField(default=0)
    collected_cents = models.BigIntegerField(default=0)
    on_time_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    dunning_recovery_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Rollup {self.date}"
