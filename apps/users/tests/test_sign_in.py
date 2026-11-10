import pytest

from apps.users import accounts
from tests.contract import assert_matches_contract

SIGN_IN = "/api/v1/sign_in"

pytestmark = pytest.mark.django_db


def sign_in(client, email, password):
    response = client.post(
        SIGN_IN, {"email": email, "password": password}, content_type="application/json"
    )
    assert_matches_contract(response, "post", SIGN_IN)
    return response


def test_signs_in_with_the_right_password(client, user):
    response = sign_in(client, user.email, "password")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] == "Signed in successfully"
    assert set(body["data"]) == {"user_id", "email", "authentication_token"}
    assert body["data"] == {
        "user_id": user.id,
        "email": user.email,
        "authentication_token": user.authentication_token,
    }


def test_refuses_invalid_credentials(client, user):
    response = sign_in(client, "wrong@example.com", "wrong_password")

    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Invalid email or password"}


def test_refuses_a_wrong_password(client, user):
    response = sign_in(client, user.email, "wrong_password")

    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Invalid email or password"}


@pytest.mark.parametrize("body", ["[]", '"text"', "1", "null"])
def test_refuses_a_body_that_is_not_an_object(client, user, body):
    response = client.post(SIGN_IN, body, content_type="application/json")

    assert_matches_contract(response, "post", SIGN_IN)
    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Invalid email or password"}


@pytest.mark.parametrize(
    "credentials",
    [
        lambda email: ([email], "password"),
        lambda email: ({"email": email}, "password"),
        lambda email: (email, ["password"]),
    ],
    ids=["email array", "email object", "password array"],
)
def test_refuses_an_email_or_password_that_is_not_a_scalar(client, user, credentials):
    assert sign_in(client, *credentials(user.email)).status_code == 401


def test_compares_a_numeric_password_as_its_text(client, make_user):
    make_user("digits@example.com", "123456")

    assert sign_in(client, "digits@example.com", 123456).status_code == 200


def test_refuses_the_eleventh_failure_from_one_source(client, user):
    for _ in range(10):
        sign_in(client, user.email, "wrong")

    response = sign_in(client, user.email, "password")

    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert response.json() == {
        "errors": ["Too many failed sign-ins from this address. Wait a minute before trying again"]
    }


class TestSignInService:
    """The legacy sign-in service; a refusal is rendered by the view as 401."""

    @pytest.fixture
    def user(self, make_user):
        return make_user("test@example.com", "password123")

    def test_finds_the_user_with_valid_credentials(self, user):
        result = accounts.sign_in({"email": user.email, "password": "password123"})

        assert result.user == user
        assert result.errors == []

    def test_fails_with_an_unknown_email(self, user):
        result = accounts.sign_in({"email": "wrong@example.com", "password": "password123"})

        assert result.user is None
        assert result.errors == ["Invalid email or password"]

    def test_fails_with_a_wrong_password_and_keeps_the_user(self, user):
        result = accounts.sign_in({"email": user.email, "password": "wrong_password"})

        assert result.user == user
        assert result.errors == ["Invalid email or password"]
