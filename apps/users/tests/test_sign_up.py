import pytest
from oauth2_provider.models import AccessToken

from apps.users import accounts
from apps.users.models import User
from apps.users.tokens import IssuedTokens, access_token_for
from tests.contract import assert_matches_contract

USERS = "/api/v1/users"
TAKEN = "Email already belongs to an account. Sign in instead, with Google sign-in or your password"
WAIT = "Too many sign-ups from this address. Wait an hour before trying again"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "web-client-test")
    monkeypatch.delenv("SMOKE_TOKEN", raising=False)


def sign_up(
    client, email, password="password123", confirmation=None, source="203.0.113.7", headers=None
):
    confirmation = password if confirmation is None else confirmation
    response = client.post(
        USERS,
        {"user": {"email": email, "password": password, "password_confirmation": confirmation}},
        content_type="application/json",
        headers=headers or {},
        REMOTE_ADDR=source,
    )
    assert_matches_contract(response, "post", USERS)
    return response


def sign_up_five_times(client, source="203.0.113.7"):
    for i in range(5):
        response = sign_up(client, f"counted-{i}@example.com", source=source)
    assert response.status_code == 201


class TestAC02:
    def test_signs_the_device_in_with_its_own_token_pair(self, client, web_client):
        response = sign_up(client, "new@example.com")

        assert response.status_code == 201
        assert User.objects.count() == 1
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "User created successfully"
        data = body["data"]
        assert set(data) == {
            "user_id",
            "email",
            "authentication_token",
            "access_token",
            "refresh_token",
            "expires_in",
        }
        user = User.objects.get(email="new@example.com")
        assert data["user_id"] == user.id
        assert data["email"] == user.email
        assert data["authentication_token"] == user.authentication_token
        assert data["expires_in"] == 3600

        token = access_token_for(data["access_token"])
        assert token is not None
        assert token.user == user
        assert token.application == web_client

        refreshed = client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "client_id": web_client.client_id,
                "refresh_token": data["refresh_token"],
            },
        )
        assert refreshed.status_code == 200

    def test_returns_the_legacy_fields_only_without_a_web_client(self, client, monkeypatch):
        monkeypatch.delenv("OAUTH_CLIENT_ID")

        response = sign_up(client, "legacy@example.com")

        assert response.status_code == 201
        assert set(response.json()["data"]) == {"user_id", "email", "authentication_token"}
        assert AccessToken.objects.count() == 0


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"email": "not-an-email"}, "Email is invalid"),
        (
            {"email": "short@example.com", "password": "short"},
            "Password is too short (minimum is 6 characters)",
        ),
        (
            {"email": "mismatch@example.com", "confirmation": "different123"},
            "Password confirmation doesn't match Password",
        ),
    ],
    ids=["malformed email", "short password", "mismatched confirmation"],
)
def test_ac03_refuses_and_names_the_field(client, web_client, fields, message):
    response = sign_up(client, **fields)

    assert response.status_code == 422
    assert message in response.json()["errors"]
    assert User.objects.count() == 0
    assert AccessToken.objects.count() == 0


def test_ac04_refuses_a_taken_email_and_says_to_sign_in(client, make_user):
    make_user("taken@example.com")

    response = sign_up(client, "TAKEN@example.com")

    assert response.status_code == 422
    assert response.json()["errors"] == [TAKEN]
    assert User.objects.count() == 1


def test_answers_an_invalid_request_with_every_message(client):
    response = sign_up(client, "invalid-email", password="short", confirmation="not-matching")

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "User could not be created",
        "errors": [
            "Email is invalid",
            "Password confirmation doesn't match Password",
            "Password is too short (minimum is 6 characters)",
        ],
    }


@pytest.mark.parametrize("body", [{}, [], '"text"', {"user": "x"}, {"user": []}, {"user": {}}])
def test_answers_a_request_without_user_as_parameter_missing(client, body):
    response = client.post(USERS, body, content_type="application/json")

    assert response.status_code == 422
    assert response.json() == {"status": 422, "error": "Unprocessable Content"}


def test_drops_an_email_or_password_that_is_not_a_scalar_as_strong_params_do(client):
    response = sign_up(client, ["array@example.com"], password={"text": "password123"})

    assert response.status_code == 422
    assert response.json()["errors"] == [
        "Email can't be blank",
        "Password can't be blank",
    ]


def test_measures_a_numeric_password_as_its_text(client, web_client):
    response = sign_up(client, "digits@example.com", password=12345)

    assert response.status_code == 422
    assert response.json()["errors"] == ["Password is too short (minimum is 6 characters)"]


class TestAC04b:
    def assert_wait_refusal(self, response):
        assert response.status_code == 429
        assert response["Retry-After"] == "3600"
        assert response.json() == {
            "status": "error",
            "message": "User could not be created",
            "errors": [WAIT],
        }

    def test_refuses_the_sixth_sign_up_in_an_hour_from_one_source(self, client):
        sign_up_five_times(client)

        self.assert_wait_refusal(sign_up(client, "sixth@example.com"))
        assert not User.objects.filter(email="sixth@example.com").exists()

    def test_counts_refused_sign_ups_too(self, client):
        for i in range(5):
            response = sign_up(client, f"bad-{i}")
        assert response.status_code == 422

        self.assert_wait_refusal(sign_up(client, "valid@example.com"))
        assert not User.objects.filter(email="valid@example.com").exists()

    def test_keeps_other_sources_open(self, client):
        sign_up_five_times(client)

        assert sign_up(client, "elsewhere@example.com", source="198.51.100.1").status_code == 201

    def test_lets_the_deploy_smoke_through_with_smoke_token(self, client, monkeypatch):
        monkeypatch.setenv("SMOKE_TOKEN", "smoke-test-token")
        sign_up_five_times(client)

        smoke = sign_up(client, "smoke@example.com", headers={"X-Smoke-Token": "smoke-test-token"})
        assert smoke.status_code == 201

        impostor = sign_up(client, "impostor@example.com", headers={"X-Smoke-Token": "wrong"})
        self.assert_wait_refusal(impostor)

    def test_never_exempts_a_sign_up_while_smoke_token_is_unset(self, client):
        sign_up_five_times(client)

        self.assert_wait_refusal(
            sign_up(client, "blank@example.com", headers={"X-Smoke-Token": ""})
        )

    def test_refuses_after_five_sign_ups_from_the_default_source(self, client):
        """429: five sign-ups without an explicit address, then a sixth."""
        for i in range(5):
            client.post(
                USERS,
                {
                    "user": {
                        "email": f"counted-{i}@example.com",
                        "password": "password",
                        "password_confirmation": "password",
                    }
                },
                content_type="application/json",
            )

        response = client.post(
            USERS,
            {
                "user": {
                    "email": "one-too-many@example.com",
                    "password": "password",
                    "password_confirmation": "password",
                }
            },
            content_type="application/json",
        )

        assert_matches_contract(response, "post", USERS)
        self.assert_wait_refusal(response)
        assert not User.objects.filter(email="one-too-many@example.com").exists()


class TestView:
    """The sign-up view, with the service replaced."""

    def test_renders_the_created_user_and_token_fields(self, client, user, monkeypatch):
        tokens = IssuedTokens("a", "r", 3600)
        monkeypatch.setattr(
            accounts, "sign_up", lambda data: accounts.SignUp(user=user, tokens=tokens)
        )

        response = sign_up(client, "new@example.com")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "User created successfully"
        assert body["data"] == {
            "user_id": user.id,
            "email": user.email,
            "authentication_token": user.authentication_token,
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 3600,
        }

    def test_renders_the_service_errors(self, client, monkeypatch):
        monkeypatch.setattr(
            accounts, "sign_up", lambda data: accounts.SignUp(errors=["Invalid email format"])
        )

        response = sign_up(client, "invalid", password="short", confirmation="mismatch")

        assert response.status_code == 422
        assert response.json() == {
            "status": "error",
            "message": "User could not be created",
            "errors": ["Invalid email format"],
        }


def payload(**fields):
    return {
        "user": {
            "email": "test@example.com",
            "password": "password123",
            "password_confirmation": "password123",
        }
        | fields
    }


class TestSignUpService:
    def test_creates_a_user_with_the_email(self):
        result = accounts.sign_up(payload())

        assert result.errors == []
        assert result.user.email == "test@example.com"
        assert User.objects.count() == 1

    def test_creates_no_user_with_invalid_parameters(self):
        result = accounts.sign_up(
            payload(email="invalid_email", password="pass", password_confirmation="different")
        )

        assert result.errors
        assert result.user is None
        assert User.objects.count() == 0

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"email": "not-an-email"}, "Email is invalid"),
            (
                {"password": "short", "password_confirmation": "short"},
                "Password is too short (minimum is 6 characters)",
            ),
            (
                {"password_confirmation": "different123"},
                "Password confirmation doesn't match Password",
            ),
        ],
        ids=["malformed email", "short password", "mismatched confirmation"],
    )
    def test_names_the_field_and_creates_no_user(self, fields, message):
        result = accounts.sign_up(payload(**({"email": "one@example.com"} | fields)))

        assert message in result.errors
        assert User.objects.count() == 0

    def test_holds_the_token_pair_when_the_web_client_is_configured(self, web_client):
        result = accounts.sign_up(payload())

        assert result.tokens is not None
        assert result.tokens.expires_in == 3600
        assert AccessToken.objects.filter(user=result.user).count() == 1

    def test_has_no_tokens_without_a_web_client(self, monkeypatch):
        monkeypatch.delenv("OAUTH_CLIENT_ID")

        assert accounts.sign_up(payload()).tokens is None

    def test_creates_the_user_without_tokens_when_no_application_has_the_uid(self, monkeypatch):
        monkeypatch.setenv("OAUTH_CLIENT_ID", "no-such-client")

        result = accounts.sign_up(payload())

        assert result.tokens is None
        assert User.objects.count() == 1
