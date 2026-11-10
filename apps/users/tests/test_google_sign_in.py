import logging

import pytest
from django.db import IntegrityError
from oauth2_provider.models import AccessToken

from apps.users import google, oauth
from apps.users.google import Verification
from apps.users.models import Identity, User
from apps.users.tests.conftest import GOOGLE_CLIENT_ID, jwks, make_id_token
from apps.users.tokens import access_token_for, link_identity
from tests.contract import assert_matches_contract

pytestmark = pytest.mark.django_db


@pytest.fixture
def rsa_key(google_keys):
    return google_keys[0]


@pytest.fixture
def google_certs(certs, rsa_key, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    certs.answer(jwks((rsa_key, "k1")))
    return certs


@pytest.fixture
def id_token(rsa_key):
    def id_token(key=None, **claims):
        return make_id_token(key or rsa_key, **claims)

    return id_token


def post_token(client, **params):
    response = client.post("/oauth/token", {k: v for k, v in params.items() if v is not None})
    assert_matches_contract(response, "post", "/oauth/token")
    return response


@pytest.fixture
def google_sign_in(client, web_client, google_certs):
    def sign_in(token, client_id=web_client.client_id):
        return post_token(client, grant_type="google_id_token", client_id=client_id, id_token=token)

    return sign_in


@pytest.fixture
def password_sign_in(client, web_client):
    def sign_in(email, password="password"):
        return post_token(
            client,
            grant_type="password",
            client_id=web_client.client_id,
            username=email,
            password=password,
        )

    return sign_in


def refresh(client, web_client, refresh_token):
    return post_token(
        client,
        grant_type="refresh_token",
        client_id=web_client.client_id,
        refresh_token=refresh_token,
    )


def test_creates_a_user_with_a_google_identity_for_an_unknown_verified_email(
    google_sign_in, id_token
):
    response = google_sign_in(id_token(email="New.Person@Example.com"))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "refresh_token", "created_at"}
    assert body["expires_in"] == 3600
    user = User.objects.get(email="new.person@example.com")
    identity = user.identities.get()
    assert (identity.provider, identity.uid) == ("google", "google-1")
    assert access_token_for(body["access_token"]).user == user


@pytest.fixture
def person(make_user):
    return make_user("person@example.com")


def test_links_google_to_the_password_user_and_cancels_all_earlier_access(
    client, web_client, person, google_sign_in, password_sign_in, id_token
):
    devices = [password_sign_in(person.email).json() for _ in range(2)]
    legacy_token = person.authentication_token

    response = google_sign_in(id_token(email="Person@Example.COM"))

    assert response.status_code == 200
    assert User.objects.count() == 1
    identity = person.identities.get()
    assert (identity.provider, identity.uid) == ("google", "google-1")
    for pair in devices:
        assert access_token_for(pair["access_token"]) is None
        refused = refresh(client, web_client, pair["refresh_token"])
        assert refused.status_code == 400
        assert refused.json()["error"] == "invalid_grant"

    refused = password_sign_in(person.email)
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_grant"
    legacy_sign_in = client.post(
        "/api/v1/sign_in",
        {"email": person.email, "password": "password"},
        content_type="application/json",
    )
    assert legacy_sign_in.status_code == 401
    me = client.get(
        "/api/v1/me", headers={"X-User-Email": person.email, "X-User-Token": legacy_token}
    )
    assert me.status_code == 401

    assert access_token_for(response.json()["access_token"]).user == person


def test_keeps_one_user_and_one_identity_whatever_the_capitals(person, google_sign_in, id_token):
    for email in ["PERSON@EXAMPLE.COM", "person@example.com"]:
        assert google_sign_in(id_token(email=email)).status_code == 200

    assert list(User.objects.all()) == [person]
    assert Identity.objects.get().user == person


def test_leaves_password_tokens_and_legacy_token_working_when_google_is_refused(
    person, google_sign_in, password_sign_in, id_token
):
    earlier = password_sign_in(person.email).json()
    legacy_token = person.authentication_token

    assert google_sign_in(id_token(email_verified=False)).json()["error"] == "invalid_grant"

    assert access_token_for(earlier["access_token"]) is not None
    assert password_sign_in(person.email).status_code == 200
    person.refresh_from_db()
    assert person.authentication_token == legacy_token
    assert Identity.objects.count() == 0


def test_refuses_an_unknown_client_before_the_google_token_is_looked_at(
    person, google_sign_in, password_sign_in, id_token, google_certs
):
    response = google_sign_in(id_token(), client_id="unknown-client")

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    assert Identity.objects.count() == 0
    assert google_certs.calls == 0
    assert password_sign_in(person.email).status_code == 200


def test_signs_a_linked_user_in_again_without_ending_their_other_devices(google_sign_in, id_token):
    first = google_sign_in(id_token()).json()
    response = google_sign_in(id_token())

    assert response.status_code == 200
    owner = access_token_for(first["access_token"]).user
    assert AccessToken.objects.filter(user=owner).count() == 2


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda id_token, stranger: id_token(email_verified=False), id="unverified"),
        pytest.param(lambda id_token, stranger: id_token(key=stranger), id="unpublished-key"),
        pytest.param(lambda id_token, stranger: id_token(exp=1), id="expired"),
        pytest.param(lambda id_token, stranger: None, id="missing"),
        pytest.param(lambda id_token, stranger: "garbage", id="not-a-token"),
    ],
)
def test_refuses_a_google_sign_in_that_did_not_complete(
    google_sign_in, id_token, google_keys, make_token
):
    response = google_sign_in(make_token(id_token, google_keys[2]))

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert User.objects.count() == 0
    assert AccessToken.objects.count() == 0
    assert Identity.objects.count() == 0


# A racing link must land before the grant reads the user: the grant reads the user under its
# row lock, so the link is run just before that read.
def test_refuses_a_password_sign_in_when_the_link_removed_the_password_first(
    person, password_sign_in, monkeypatch
):
    monkeypatch.setattr(
        google, "verify_id_token", lambda token: Verification(email=person.email, uid="google-1")
    )
    validate_user = oauth.Validator.validate_user
    linked = []

    def link_first(self, *args, **kwargs):
        linked.append(google.google_sign_in("id-token"))
        return validate_user(self, *args, **kwargs)

    monkeypatch.setattr(oauth.Validator, "validate_user", link_first)

    response = password_sign_in(person.email)

    assert linked[0].user == person
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def verified(monkeypatch, verification):
    monkeypatch.setattr(google, "verify_id_token", lambda token: verification)


def test_service_refuses_with_the_verifier_error_and_creates_or_links_nothing(person, monkeypatch):
    verified(monkeypatch, Verification(error="email_not_verified"))

    result = google.google_sign_in("id-token")

    assert result.error == "email_not_verified"
    assert result.user is None
    assert User.objects.count() == 1
    assert Identity.objects.count() == 0


def test_service_refuses_a_user_linked_to_another_google_account_and_keeps_their_access(
    person, monkeypatch, make_access_token
):
    identity = Identity.objects.create(user=person, provider=Identity.GOOGLE, uid="google-other")
    token = make_access_token(person)
    verified(monkeypatch, Verification(email="person@example.com", uid="google-1"))

    result = google.google_sign_in("id-token")

    assert result.error == "already_linked"
    assert result.user is None
    assert list(person.identities.all()) == [identity]
    assert AccessToken.objects.filter(pk=token.pk).exists()


def test_service_refuses_reports_and_persists_nothing_when_the_user_cannot_be_saved(
    person, monkeypatch, caplog
):
    verified(monkeypatch, Verification(email="person@example.com", uid="google-1"))
    monkeypatch.setattr(google, "_find_by_email", lambda email: None)

    with caplog.at_level(logging.WARNING, logger="apps.users.google"):
        result = google.google_sign_in("id-token")

    assert result.error == "not_saved"
    assert result.user is None
    assert User.objects.count() == 1
    assert Identity.objects.count() == 0
    assert "Google sign-in not saved: IntegrityError" in caplog.messages


def test_service_reports_a_database_collision_without_the_email_it_names(
    person, monkeypatch, caplog
):
    verified(monkeypatch, Verification(email="person@example.com", uid="google-1"))

    def collide(user, uid):
        raise IntegrityError(
            "duplicate key value violates unique constraint DETAIL: "
            "Key (email)=(person@example.com) already exists."
        )

    monkeypatch.setattr(google, "link_identity", collide)

    with caplog.at_level(logging.WARNING):
        result = google.google_sign_in("id-token")

    assert result.error == "not_saved"
    assert result.user is None
    assert caplog.messages == ["Google sign-in not saved: IntegrityError"]
    assert all(record.exc_info is None for record in caplog.records)
    assert "person@example.com" not in caplog.text


def test_link_identity_cancels_the_password_every_token_and_the_legacy_token(
    user, make_user, make_access_token
):
    tokens = [make_access_token(user), make_access_token(user)]
    other_users_token = make_access_token(make_user())
    legacy_token = user.authentication_token

    link_identity(user, "google-1")

    identity = user.identities.get()
    assert (identity.provider, identity.uid) == ("google", "google-1")
    assert not AccessToken.objects.filter(pk__in=[token.pk for token in tokens]).exists()
    assert len({token.application_id for token in tokens}) == 2
    assert AccessToken.objects.filter(pk=other_users_token.pk).exists()
    user.refresh_from_db()
    assert not user.check_password("password")
    assert user.authentication_token
    assert user.authentication_token != legacy_token


def test_link_identity_links_and_cancels_nothing_when_the_user_cannot_be_saved(
    user, make_access_token, monkeypatch
):
    token = make_access_token(user)
    legacy_token = user.authentication_token

    def fail(self, *args, **kwargs):
        raise IntegrityError("cannot save")

    monkeypatch.setattr(User, "save", fail)

    with pytest.raises(IntegrityError):
        link_identity(user, "google-1")

    monkeypatch.undo()
    assert Identity.objects.count() == 0
    assert AccessToken.objects.filter(pk=token.pk).exists()
    stored = User.objects.get(pk=user.pk)
    assert stored.check_password("password")
    assert stored.authentication_token == legacy_token
