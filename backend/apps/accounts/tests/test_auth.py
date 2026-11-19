"""Auth surface tests: token obtain/refresh and permission boundaries."""

import pytest

from tests.factories import MemberFactory, SpendingLimitFactory


@pytest.mark.django_db
def test_jwt_token_obtain_and_refresh(api_client):
    member = MemberFactory()
    SpendingLimitFactory(member=member)
    token_response = api_client.post(
        "/api/auth/token/",
        {"username": member.user.username, "password": "test-pass-123"},
        format="json",
    )
    assert token_response.status_code == 200
    tokens = token_response.json()
    assert tokens["access"]
    assert tokens["refresh"]

    me = api_client.get("/api/members/me/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert me.status_code == 200
    assert me.json()["id"] == member.id

    refreshed = api_client.post(
        "/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json"
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access"]


@pytest.mark.django_db
def test_jwt_rejects_bad_credentials_and_bad_tokens(api_client, member):
    bad = api_client.post(
        "/api/auth/token/",
        {"username": member.user.username, "password": "wrong-password"},
        format="json",
    )
    assert bad.status_code == 401

    anonymous = api_client.get("/api/members/me/", HTTP_AUTHORIZATION="Bearer not-a-token")
    assert anonymous.status_code == 401


@pytest.mark.django_db
def test_expired_or_forged_token_is_rejected(api_client, member):
    response = api_client.get(
        "/api/members/me/",
        HTTP_AUTHORIZATION="Bearer eyJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIn0.forged",
    )
    assert response.status_code == 401
