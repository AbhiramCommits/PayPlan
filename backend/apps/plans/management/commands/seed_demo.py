"""Idempotent demo seed used by docker compose and local development."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Member, SpendingLimit
from apps.catalog.models import Product
from apps.plans.models import InstallmentStatus
from apps.plans.services import checkout

DEMO_PRODUCTS = [
    ("SKU-HEADPHONES", "Studio Headphones", 18_900),
    ("SKU-LAPTOP", "14-inch Laptop", 129_900),
    ("SKU-SOFA", "Modular Sofa", 89_000),
    ("SKU-PHONE", "Smartphone", 74_900),
    ("SKU-SHOES", "Running Shoes", 12_500),
]


class Command(BaseCommand):
    help = "Seed demo members, products, and a few plans."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        support_group, _ = Group.objects.get_or_create(name="support")

        support_user, _ = User.objects.get_or_create(
            username="support",
            defaults={"email": "support@payplan.local", "is_staff": True},
        )
        support_user.is_staff = True
        support_user.set_password("support12345")
        support_user.save()
        support_user.groups.add(support_group)

        demo_user, _ = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@payplan.local", "first_name": "Demo", "last_name": "Member"},
        )
        demo_user.set_password("demo12345")
        demo_user.save()
        demo_member, _ = Member.objects.get_or_create(
            user=demo_user,
            defaults={"base_limit_cents": 250_000, "risk_tier": "PRIME"},
        )
        SpendingLimit.objects.get_or_create(
            member=demo_member,
            limit_cents=demo_member.base_limit_cents,
            available_cents=demo_member.base_limit_cents,
            reason="INITIAL",
        )

        products = []
        for sku, name, price in DEMO_PRODUCTS:
            product, _ = Product.objects.update_or_create(
                sku=sku, defaults={"name": name, "price_cents": price, "active": True}
            )
            products.append(product)

        if not demo_member.plans.exists():
            today = timezone.localdate()
            result = checkout(
                demo_member,
                products[0],
                qty=1,
                n=4,
                cadence="BIWEEKLY",
                start_date=today - timedelta(days=21),
            )
            first = result.plan.installments.order_by("sequence").first()
            first.status = InstallmentStatus.PAID
            first.amount_paid_cents = first.amount_cents
            first.paid_at = timezone.now() - timedelta(days=7)
            first.save(update_fields=["status", "amount_paid_cents", "paid_at"])

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded demo/demo12345 (member) and support/support12345 (support role)"
            )
        )
