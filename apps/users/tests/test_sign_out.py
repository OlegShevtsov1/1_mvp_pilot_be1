import pytest

from tests.contract import assert_matches_contract

SIGN_OUT = "/api/v1/sign_out"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _legacy_on(monkeypatch):
    monkeypatch.delenv("LEGACY_AUTH_ENABLED", raising=False)


@pytest.fixture
def device(client, user, web_client):
    def sign_in():
        response = client.post(
            "/oauth/token",
            {
                "grant_type": "password",
                "client_id": web_client.client_id,
                "username": user.email,
                "password": "password",
            },
        )
        assert response.status_code == 200
        return response.json()

    return sign_in


def refresh(client, web_client, refresh_token):
    return client.post(
        "/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": web_client.client_id,
            "refresh_token": refresh_token,
        },
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def legacy(user, token=None):
    return {"X-User-Email": user.email, "X-User-Token": token or user.authentication_token}


def sign_out(client, headers=None):
    response = client.post(SIGN_OUT, headers=headers or {})
    assert_matches_contract(response, "post", SIGN_OUT)
    return response


def me(client, headers):
    response = client.get("/api/v1/me", headers=headers)
    assert_matches_contract(response, "get", "/api/v1/me")
    return response


def assert_not_authorized(response):
    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}


def test_ends_this_devices_tokens_while_another_device_keeps_working(client, web_client, device):
    device_a = device()
    device_b = device()

    response = sign_out(client, bearer(device_a["access_token"]))
    assert response.status_code == 204
    assert response.content == b""

    assert_not_authorized(me(client, bearer(device_a["access_token"])))
    refused = refresh(client, web_client, device_a["refresh_token"])
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_grant"

    assert me(client, bearer(device_b["access_token"])).status_code == 200
    assert refresh(client, web_client, device_b["refresh_token"]).status_code == 200


def test_leaves_the_legacy_token_working_after_a_bearer_sign_out(client, user, device):
    legacy_token = user.authentication_token

    assert sign_out(client, bearer(device()["access_token"])).status_code == 204

    assert me(client, legacy(user, legacy_token)).status_code == 200
    user.refresh_from_db()
    assert user.authentication_token == legacy_token


def test_rotates_the_legacy_token_for_every_device(client, user):
    old_token = user.authentication_token

    response = sign_out(client, legacy(user, old_token))
    assert response.status_code == 204
    assert response.content == b""

    assert_not_authorized(me(client, legacy(user, old_token)))
    user.refresh_from_db()
    assert user.authentication_token
    assert user.authentication_token != old_token

    signed_in = client.post(
        "/api/v1/sign_in",
        {"email": user.email, "password": "password"},
        content_type="application/json",
    )
    new_token = signed_in.json()["data"]["authentication_token"]
    user.refresh_from_db()
    assert new_token == user.authentication_token
    assert me(client, legacy(user, new_token)).status_code == 200


def test_keeps_bearer_devices_working_after_a_legacy_sign_out(client, user, device):
    pair = device()

    assert sign_out(client, legacy(user)).status_code == 204

    assert me(client, bearer(pair["access_token"])).status_code == 200


def test_refuses_an_unauthenticated_sign_out(client, user, make_access_token):
    legacy_token = user.authentication_token

    assert_not_authorized(sign_out(client))

    assert_not_authorized(sign_out(client, legacy(user, "wrong")))
    user.refresh_from_db()
    assert user.authentication_token == legacy_token

    revoked = make_access_token(user)
    revoked.revoke()
    assert_not_authorized(sign_out(client, bearer(revoked.plaintext)))


def test_signed_out_device_is_refused_while_the_other_works(client, device):
    """204 signs out device A only."""
    device_a = device()
    device_b = device()

    assert sign_out(client, bearer(device_a["access_token"])).status_code == 204

    assert me(client, bearer(device_a["access_token"])).status_code == 401
    assert me(client, bearer(device_b["access_token"])).status_code == 200
