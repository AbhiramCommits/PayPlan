"""Concurrency proof: ten parallel requests, same key -> exactly one charge."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from apps.payments.gateway import FakeGateway
from apps.payments.models import Payment, PaymentStatus
from apps.plans.models import InstallmentStatus
from tests.factories import InstallmentPlanFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-level locking concurrency proof requires PostgreSQL",
)
def test_ten_parallel_requests_with_same_key_charge_once(member, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("apps.payments.views.get_gateway", lambda: gateway)
    plan = InstallmentPlanFactory(order__member=member, principal_cents=40_000, num_installments=4)
    installment = plan.installments.order_by("sequence").first()
    user_id = member.user_id
    barrier = threading.Barrier(10)
    results = []
    results_lock = threading.Lock()

    def worker(_index):
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model

            user = get_user_model().objects.get(pk=user_id)
            client = APIClient()
            client.force_authenticate(user=user)
            barrier.wait(timeout=10)
            response = client.post(
                "/api/payments/",
                {"installment": installment.id},
                format="json",
                HTTP_IDEMPOTENCY_KEY="parallel-key",
            )
            with results_lock:
                results.append(response.status_code)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(worker, range(10)))

    assert sorted(results).count(201) == 1
    assert sorted(results).count(200) == 9
    assert Payment.objects.filter(idempotency_key="parallel-key").count() == 1
    payment = Payment.objects.get(idempotency_key="parallel-key")
    assert payment.status == PaymentStatus.SUCCEEDED
    assert gateway.charge_count == 1
    installment.refresh_from_db()
    assert installment.status == InstallmentStatus.PAID
    assert installment.amount_paid_cents == installment.amount_cents
