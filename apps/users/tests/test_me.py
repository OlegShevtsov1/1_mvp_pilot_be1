import pytest

from tests.contract import assert_matches_contract


@pytest.mark.django_db
def test_returns_the_profile_of_a_bearer_token_owner(client, user, make_access_token):
    token = make_access_token(user)

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token.plaintext}"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "User profile",
        "data": {"user_id": user.id, "email": user.email},
    }
    assert_matches_contract(response, "get", "/api/v1/me")


@pytest.mark.django_db
def test_returns_the_profile_of_a_legacy_pair_owner(client, user):
    response = client.get(
        "/api/v1/me",
        headers={"X-User-Email": user.email, "X-User-Token": user.authentication_token},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"user_id": user.id, "email": user.email}
    assert_matches_contract(response, "get", "/api/v1/me")


@pytest.mark.django_db
def test_refuses_wrong_legacy_headers(client):
    response = client.get(
        "/api/v1/me", headers={"X-User-Email": "wrong@example.com", "X-User-Token": "wrong_token"}
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}
    assert_matches_contract(response, "get", "/api/v1/me")
