"""factory-boy factories for every domain model.

Import these from tests via `from tests.factories import ...`.
"""

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.models import LimitReason, Member, MemberStatus, RiskTier, SpendingLimit
from apps.catalog.models import Product
from apps.payments.models import Payment, PaymentStatus, WebhookEvent
from apps.plans.models import (
    Cadence,
    Installment,
    InstallmentPlan,
    InstallmentStatus,
    Order,
    OrderStatus,
    PlanStatus,
)
from apps.plans.services import generate_schedule


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "test-pass-123")


class MemberFactory(DjangoModelFactory):
    class Meta:
        model = Member

    user = factory.SubFactory(UserFactory)
    status = MemberStatus.ACTIVE
    risk_tier = RiskTier.NEAR_PRIME
    base_limit_cents = 100_000


class SpendingLimitFactory(DjangoModelFactory):
    class Meta:
        model = SpendingLimit

    member = factory.SubFactory(MemberFactory)
    limit_cents = factory.LazyAttribute(lambda o: o.member.base_limit_cents)
    available_cents = factory.LazyAttribute(lambda o: o.member.base_limit_cents)
    reason = LimitReason.INITIAL


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product

    sku = factory.Sequence(lambda n: f"SKU-{n:04d}")
    name = factory.Sequence(lambda n: f"Product {n}")
    price_cents = 20_000
    active = True


class OrderFactory(DjangoModelFactory):
    class Meta:
        model = Order

    member = factory.SubFactory(MemberFactory)
    product = factory.SubFactory(ProductFactory)
    qty = 1
    total_cents = factory.LazyAttribute(lambda o: o.product.price_cents * o.qty)
    status = OrderStatus.APPROVED


class InstallmentPlanFactory(DjangoModelFactory):
    class Meta:
        model = InstallmentPlan

    order = factory.SubFactory(OrderFactory)
    member = factory.LazyAttribute(lambda o: o.order.member)
    principal_cents = factory.LazyAttribute(lambda o: o.order.total_cents)
    num_installments = 4
    cadence = Cadence.BIWEEKLY
    status = PlanStatus.ACTIVE
    start_date = factory.LazyFunction(timezone.localdate)

    @factory.post_generation
    def installments(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted is not None:
            for inst in extracted:
                inst.plan = self
                inst.save()
            return
        schedule = generate_schedule(
            self.principal_cents, self.num_installments, self.cadence, self.start_date
        )
        for seq, (due_date, amount) in enumerate(schedule, start=1):
            Installment.objects.create(
                plan=self,
                sequence=seq,
                due_date=due_date,
                amount_cents=amount,
                status=InstallmentStatus.SCHEDULED,
            )


class InstallmentFactory(DjangoModelFactory):
    class Meta:
        model = Installment

    plan = factory.SubFactory(InstallmentPlanFactory)
    sequence = factory.Sequence(lambda n: n + 1)
    due_date = factory.LazyFunction(timezone.localdate)
    amount_cents = 10_000
    amount_paid_cents = 0
    status = InstallmentStatus.SCHEDULED


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    member = factory.LazyAttribute(lambda o: o.installment.plan.member)
    installment = factory.SubFactory(InstallmentFactory)
    amount_cents = factory.LazyAttribute(lambda o: o.installment.amount_cents)
    status = PaymentStatus.PENDING
    gateway_ref = factory.Sequence(lambda n: f"fake_test_{n}")
    idempotency_key = factory.Sequence(lambda n: f"test-key-{n}")
    request_fingerprint = "0" * 64
    attempt_no = 1


class WebhookEventFactory(DjangoModelFactory):
    class Meta:
        model = WebhookEvent

    provider_event_id = factory.Sequence(lambda n: f"evt_test_{n}")
    type = "payment_intent.succeeded"
    payload = factory.LazyFunction(dict)
