import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from oauth2_provider.models import AccessToken, RefreshToken

from apps.users.oauth import OAUTH_ERROR_DESCRIPTIONS
from apps.users.tests.conftest import GOOGLE_CLIENT_ID, jwks, make_id_token
from tests.contract import assert_matches_contract

pytestmark = pytest.mark.django_db

FAILED_SIGN_IN_MESSAGE = (
    "Too many failed sign-ins from this address. Wait a minute before trying again"
)


def sha256(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def token_request(client, **params):
    response = client.post("/oauth/token", {k: v for k, v in params.items() if v is not None})
    assert_matches_contract(response, "post", "/oauth/token")
    return response


@pytest.fixture
def sign_in(client, user, web_client):
    def sign_in(password="password", client_id=web_client.client_id, email=user.email):
        return token_request(
            client, grant_type="password", client_id=client_id, username=email, password=password
        )

    return sign_in


@pytest.fixture
def refresh(client, web_client):
    def refresh(refresh_token):
        return token_request(
            client,
            grant_type="refresh_token",
            client_id=web_client.client_id,
            refresh_token=refresh_token,
        )

    return refresh


def authenticates(client, access_token):
    return client.get("/api/v1/me", headers={"Authorization": f"Bearer {access_token}"})


def test_gives_this_device_its_own_pair_while_another_keeps_its_access(client, user, sign_in):
    other_device = sign_in().json()
    response = sign_in()
    this_device = response.json()

    assert response.status_code == 200
    assert set(this_device) == {
        "access_token",
        "token_type",
        "expires_in",
        "refresh_token",
        "created_at",
    }
    assert this_device["token_type"] == "Bearer"
    assert this_device["expires_in"] == 3600
    assert isinstance(this_device["created_at"], int)
    assert this_device["access_token"] != other_device["access_token"]
    assert authenticates(client, other_device["access_token"]).status_code == 200
    assert AccessToken.objects.filter(user=user).count() == 2


def test_password_grant_keeps_another_device_working(client, user, web_client, make_access_token):
    other_device = make_access_token(user, application=web_client)

    response = token_request(
        client,
        grant_type="password",
        client_id=web_client.client_id,
        username=user.email,
        password="password",
    )

    assert response.status_code == 200
    assert response.json()["access_token"] != other_device.plaintext
    assert authenticates(client, other_device.plaintext).status_code == 200


def test_signs_in_with_the_email_in_another_letter_case(sign_in, user):
    assert sign_in(email=user.email.upper()).status_code == 200


def test_accepts_a_json_body(client, user, web_client):
    response = client.post(
        "/oauth/token",
        {
            "grant_type": "password",
            "client_id": web_client.client_id,
            "username": user.email,
            "password": "password",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert_matches_contract(response, "post", "/oauth/token")


def test_answers_a_malformed_json_body_with_bad_request(client):
    response = client.post("/oauth/token", b'{"grant_type": ', content_type="application/json")

    assert response.status_code == 400
    assert response.json() == {"status": 400, "error": "Bad Request"}
    assert not AccessToken.objects.exists()


def test_refuses_a_wrong_password_with_invalid_grant_and_issues_no_token(sign_in):
    response = sign_in(password="wrong-password")

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_grant",
        "error_description": OAUTH_ERROR_DESCRIPTIONS["invalid_grant"],
    }
    assert response.json()["error_description"] == (
        "The provided authorization grant is invalid, expired, revoked, does not match the "
        "redirection URI used in the authorization request, or was issued to another client."
    )
    assert AccessToken.objects.count() == 0


@pytest.mark.parametrize("client_id", ["unknown-client", None])
def test_refuses_an_unknown_or_missing_client_id_with_invalid_client(sign_in, client_id):
    response = sign_in(client_id=client_id)

    assert response.status_code == 401
    assert response.json() == {
        "error": "invalid_client",
        "error_description": (
            "Client authentication failed due to unknown client, no client authentication "
            "included, or unsupported authentication method."
        ),
    }
    assert AccessToken.objects.count() == 0


def test_replaces_the_pair_on_refresh_and_revokes_the_old_one_at_once(client, sign_in, refresh):
    old_pair = sign_in().json()
    response = refresh(old_pair["refresh_token"])
    new_pair = response.json()

    assert response.status_code == 200
    assert new_pair["access_token"] != old_pair["access_token"]
    assert new_pair["refresh_token"] != old_pair["refresh_token"]
    assert not AccessToken.objects.filter(token_checksum=sha256(old_pair["access_token"])).exists()
    assert authenticates(client, old_pair["access_token"]).status_code == 401

    reused = refresh(old_pair["refresh_token"])
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"


def test_refuses_a_refresh_token_30_days_old(clock, sign_in, refresh):
    clock.travel_to(datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=UTC))
    pair = sign_in().json()
    clock.travel(timedelta(days=30))

    response = refresh(pair["refresh_token"])

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_accepts_a_refresh_token_younger_than_30_days_and_restarts_the_window(
    clock, sign_in, refresh
):
    pair = sign_in().json()
    clock.travel(timedelta(days=29))
    response = refresh(pair["refresh_token"])
    assert response.status_code == 200

    clock.travel(timedelta(days=29))
    assert refresh(response.json()["refresh_token"]).status_code == 200


def test_refuses_a_revoked_refresh_token(client, sign_in, refresh, web_client):
    pair = sign_in().json()
    client.post(
        "/oauth/revoke", {"client_id": web_client.client_id, "token": pair["refresh_token"]}
    )

    response = refresh(pair["refresh_token"])

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_stores_sha256_hashes_of_the_access_and_refresh_tokens_not_the_secrets(sign_in):
    pair = sign_in().json()
    access = AccessToken.objects.get()
    refresh_row = RefreshToken.objects.get()

    assert access.token == ""
    assert access.token_checksum == sha256(pair["access_token"])
    assert refresh_row.token == ""
    assert refresh_row.token_checksum == sha256(pair["refresh_token"])


def test_revokes_an_access_token_at_oauth_revoke(client, sign_in, web_client):
    pair = sign_in().json()

    response = client.post(
        "/oauth/revoke", {"client_id": web_client.client_id, "token": pair["access_token"]}
    )

    assert response.status_code == 200
    assert_matches_contract(response, "post", "/oauth/revoke")
    assert not AccessToken.objects.exists()
    assert authenticates(client, pair["access_token"]).status_code == 401


def test_offers_only_be_grants_with_no_authorization_or_introspection_endpoints(client, web_client):
    response = token_request(
        client, grant_type="client_credentials", client_id=web_client.client_id
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": "unsupported_grant_type",
        "error_description": (
            "The authorization grant type is not supported by the authorization server."
        ),
    }

    assert client.get("/oauth/authorize").status_code == 404
    assert client.post("/oauth/introspect").status_code == 404


def test_signs_in_with_a_google_id_token_for_a_new_email(
    client, web_client, google_keys, certs, monkeypatch, django_user_model
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    certs.answer(jwks((google_keys[0], "k1")))

    response = token_request(
        client,
        grant_type="google_id_token",
        client_id=web_client.client_id,
        id_token=make_id_token(google_keys[0], sub="google-1", email="new.person@example.com"),
    )

    assert response.status_code == 200
    assert django_user_model.objects.filter(email="new.person@example.com").exists()
    assert response.json()["access_token"]


def test_refuses_the_eleventh_failed_sign_in_with_retry_after(sign_in):
    for _ in range(10):
        assert sign_in(password="wrong").status_code == 400

    response = sign_in(password="wrong")

    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert response.json() == {"errors": [FAILED_SIGN_IN_MESSAGE]}
