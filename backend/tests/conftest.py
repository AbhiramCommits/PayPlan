import pytest


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client():
    from rest_framework.test import APIClient

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
