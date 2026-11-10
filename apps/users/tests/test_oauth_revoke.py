import pytest
from oauth2_provider.models import AccessToken, RefreshToken

from tests.contract import assert_matches_contract

pytestmark = pytest.mark.django_db


def revoke(client, **params):
    response = client.post("/oauth/revoke", params)
    assert response.status_code == 200
    assert_matches_contract(response, "post", "/oauth/revoke")
    assert response.json() == {}
    return response


@pytest.fixture
def pair(client, user, web_client):
    return client.post(
        "/oauth/token",
        {
            "grant_type": "password",
            "client_id": web_client.client_id,
            "username": user.email,
            "password": "password",
        },
    ).json()


def refresh_status(client, web_client, refresh_token):
    return client.post(
        "/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": web_client.client_id,
            "refresh_token": refresh_token,
        },
    ).status_code


def test_revokes_an_access_token(client, user, web_client, make_access_token):
    token = make_access_token(user, application=web_client)

    revoke(client, client_id=web_client.client_id, token=token.plaintext)

    assert not AccessToken.objects.filter(pk=token.pk).exists()
    headers = {"Authorization": f"Bearer {token.plaintext}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_revoking_an_access_token_ends_its_refresh_token(client, web_client, pair):
    revoke(client, client_id=web_client.client_id, token=pair["access_token"])

    assert refresh_status(client, web_client, pair["refresh_token"]) == 400


def test_revokes_a_refresh_token_and_its_access_token(client, web_client, pair):
    revoke(client, client_id=web_client.client_id, token=pair["refresh_token"])

    assert RefreshToken.objects.get().revoked is not None
    assert not AccessToken.objects.exists()
    assert refresh_status(client, web_client, pair["refresh_token"]) == 400


def test_answers_200_for_an_unknown_token(client, web_client, pair):
    revoke(client, client_id=web_client.client_id, token="unknown")
    revoke(client)

    assert AccessToken.objects.count() == 1


def test_accepts_a_json_body(client, web_client, pair):
    response = client.post(
        "/oauth/revoke",
        {"client_id": web_client.client_id, "token": pair["access_token"]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert not AccessToken.objects.exists()


def test_answers_a_malformed_json_body_with_bad_request_and_revokes_nothing(
    client, web_client, pair
):
    response = client.post("/oauth/revoke", b'{"token": ', content_type="application/json")

    assert response.status_code == 400
    assert response.json() == {"status": 400, "error": "Bad Request"}
    assert AccessToken.objects.count() == 1
