import logging
from datetime import timedelta

import pytest
from django.db import OperationalError
from django.db.models import Sum
from django.utils import timezone

from apps.users.models import LegacyTokenUse
from tests.contract import assert_matches_contract

ME = "/api/v1/me"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("LEGACY_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("SMOKE_TOKEN", "smoke-test-token")


@pytest.fixture
def legacy(user):
    return {"X-User-Email": user.email, "X-User-Token": user.authentication_token}


@pytest.fixture
def access_token(user, make_access_token):
    return make_access_token(user)


@pytest.fixture
def bearer(access_token):
    return {"Authorization": f"Bearer {access_token.plaintext}"}


def me(client, headers):
    response = client.get(ME, headers=headers)
    assert_matches_contract(response, "get", ME)
    return response


def uses_total():
    return LegacyTokenUse.objects.aggregate(total=Sum("uses_count"))["total"] or 0


def test_gives_a_bearer_token_and_the_legacy_pair_the_same_access(client, user, legacy, bearer):
    via_bearer = me(client, bearer)
    via_legacy = me(client, legacy)

    assert via_bearer.status_code == 200
    assert via_legacy.status_code == 200
    assert via_bearer.json() == via_legacy.json()
    assert via_bearer.json()["data"]["user_id"] == user.id


def test_counts_each_legacy_request_but_not_bearer_or_pipeline_ones(client, user, legacy, bearer):
    for _ in range(3):
        me(client, legacy)
    assert LegacyTokenUse.objects.get(user=user, used_on=timezone.localdate()).uses_count == 3

    me(client, bearer)
    assert LegacyTokenUse.objects.count() == 1

    smoke = me(client, legacy | {"X-Smoke-Token": "smoke-test-token"})
    assert smoke.status_code == 200
    assert uses_total() == 3

    me(client, legacy | {"X-Smoke-Token": "wrong"})
    assert uses_total() == 4


def test_refuses_the_legacy_pair_when_the_legacy_path_is_off(client, legacy, monkeypatch):
    monkeypatch.setenv("LEGACY_AUTH_ENABLED", "false")

    response = me(client, legacy)

    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}
    assert LegacyTokenUse.objects.count() == 0


def test_refuses_a_revoked_bearer_without_falling_back_to_another_users_pair(
    client, make_user, access_token, bearer
):
    other = make_user()
    access_token.revoke()

    response = me(
        client,
        bearer | {"X-User-Email": other.email, "X-User-Token": other.authentication_token},
    )

    assert response.status_code == 401
    assert LegacyTokenUse.objects.count() == 0


def test_refuses_a_revoked_or_expired_bearer_without_falling_back_to_its_owners_pair(
    client, user, legacy, access_token, bearer, make_access_token
):
    access_token.revoke()
    assert me(client, bearer | legacy).status_code == 401

    expired = make_access_token(user)
    expired.expires = timezone.now() - timedelta(hours=1)
    expired.save()
    response = me(client, legacy | {"Authorization": f"Bearer {expired.plaintext}"})

    assert response.status_code == 401
    assert LegacyTokenUse.objects.count() == 0


def test_serves_a_legacy_request_and_reports_a_failed_count(
    client, user, legacy, monkeypatch, caplog
):
    def fail(*args, **kwargs):
        raise OperationalError("connection lost")

    monkeypatch.setattr("django.db.models.query.QuerySet.update", fail)

    with caplog.at_level(logging.ERROR, logger="apps.users.legacy"):
        response = me(client, legacy)

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == user.id
    failures = [r for r in caplog.records if r.name == "apps.users.legacy"]
    assert len(failures) == 1
    assert isinstance(failures[0].exc_info[1], OperationalError)


def test_refuses_an_expired_bearer_token(client, access_token, bearer):
    access_token.expires = timezone.now() - timedelta(hours=1)
    access_token.save()

    assert me(client, bearer).status_code == 401
