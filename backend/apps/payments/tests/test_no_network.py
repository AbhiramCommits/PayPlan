"""The API must never open an outbound network connection with the fake gateway."""

import socket

import pytest

from apps.payments.gateway import FakeGateway
from tests.factories import InstallmentPlanFactory


@pytest.mark.django_db
def test_payment_api_makes_no_outbound_network_calls(auth_client, member, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("apps.payments.views.get_gateway", lambda: gateway)

    attempted = []
    real_connect = socket.socket.connect
    loopback = {"127.0.0.1", "::1", "localhost", "db", "redis"}

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in loopback and not str(host).startswith("/"):
            attempted.append(host)
            raise AssertionError(f"outbound network call attempted to {host}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    plan = InstallmentPlanFactory(order__member=member, principal_cents=40_000, num_installments=4)
    installment = plan.installments.order_by("sequence").first()
    response = auth_client(member.user).post(
        "/api/payments/",
        {"installment": installment.id},
        format="json",
        HTTP_IDEMPOTENCY_KEY="offline-proof",
    )
    assert response.status_code == 201, response.content
    assert attempted == []
    assert gateway.charge_count == 1
