"""Fixtures available to every test under backend/ (apps and tests)."""

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


@pytest.fixture
def member(db):
    from tests.factories import MemberFactory, SpendingLimitFactory

    m = MemberFactory()
    SpendingLimitFactory(member=m)
    return m


@pytest.fixture
def other_member(db):
    from tests.factories import MemberFactory, SpendingLimitFactory

    m = MemberFactory()
    SpendingLimitFactory(member=m)
    return m
