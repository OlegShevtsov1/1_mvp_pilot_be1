from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from oauth2_provider.models import AccessToken

from apps.users.models import Identity, LegacyTokenUse, User


@pytest.mark.django_db
def test_create_user_hashes_the_password(django_user_model):
    user = django_user_model.objects.create_user("a@example.com", "secret1")

    assert user.check_password("secret1")
    assert user.password != "secret1"
    assert user.projects_count == 0
    assert django_user_model.USERNAME_FIELD == "email"


@pytest.mark.django_db
def test_email_is_unique(django_user_model):
    django_user_model.objects.create_user("a@example.com", "secret1")

    with pytest.raises(IntegrityError):
        django_user_model.objects.create_user("a@example.com", "secret2")


@pytest.mark.django_db
def test_users_without_a_reset_password_token_do_not_collide(django_user_model):
    first = django_user_model.objects.create_user("a@example.com", "secret1")
    second = django_user_model.objects.create_user("b@example.com", "secret2")

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.reset_password_token is None
    assert second.reset_password_token is None


# User, identity and legacy token use models. Sign-up validations live in
# apps.users.accounts.sign_up_errors and are tested with sign-up.


@pytest.mark.django_db
def test_a_user_gets_a_legacy_authentication_token(user):
    assert len(user.authentication_token) == 20


@pytest.mark.django_db
def test_a_blank_legacy_token_is_regenerated_on_save(user):
    old = user.authentication_token
    user.authentication_token = None
    user.save()

    user.refresh_from_db()
    assert user.authentication_token
    assert user.authentication_token != old


@pytest.mark.django_db
def test_a_new_token_never_collides_with_another_users(user, make_user, monkeypatch):
    from apps.users import models

    tokens = iter([user.authentication_token, "fresh-token-00000000"])
    monkeypatch.setattr(models, "friendly_token", lambda: next(tokens))

    assert make_user().authentication_token == "fresh-token-00000000"


@pytest.mark.django_db
def test_checks_the_password(user):
    assert user.check_password("password")
    assert not user.check_password("wrong_password")


@pytest.mark.django_db
def test_a_google_user_has_no_password_and_a_lowercased_email():
    user = User(email=" Google.User@Example.com ", password="")
    user.save()
    Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-new")

    user.refresh_from_db()
    assert user.password == ""
    assert not user.check_password("")
    assert user.email == "google.user@example.com"


@pytest.mark.django_db
def test_saves_a_persisted_user_whose_password_is_not_touched(user):
    stored = User.objects.get(pk=user.pk)
    stored.email = "updated@example.com"
    stored.save()

    stored.refresh_from_db()
    assert stored.email == "updated@example.com"
    assert stored.check_password("password")


@pytest.mark.django_db
def test_refuses_the_old_password_once_a_linked_users_password_is_cleared(user):
    Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-1")
    user.password = ""
    user.save()

    user.refresh_from_db()
    assert not user.check_password("password")


@pytest.mark.django_db
def test_destroy_removes_the_tokens_identity_and_legacy_use_rows(user, make_access_token):
    make_access_token(user)
    Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-1")
    LegacyTokenUse.objects.create(user=user, used_on=date.today(), uses_count=1)

    user.delete()

    assert AccessToken.objects.count() == 0
    assert Identity.objects.count() == 0
    assert LegacyTokenUse.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["provider", "uid"])
def test_identity_needs_provider_and_uid(user, field):
    identity = Identity(user=user, provider=Identity.GOOGLE, uid="google-uid-1")
    setattr(identity, field, "")

    with pytest.raises(ValidationError) as error:
        identity.full_clean()
    assert field in error.value.message_dict


@pytest.mark.django_db
def test_identity_belongs_to_a_user():
    with pytest.raises(ValidationError) as error:
        Identity(provider=Identity.GOOGLE, uid="google-uid-1").full_clean()
    assert "user" in error.value.message_dict


@pytest.mark.django_db
def test_identity_uid_is_unique_per_provider(user, make_user):
    Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-1")

    with pytest.raises(IntegrityError):
        Identity.objects.create(user=make_user(), provider=Identity.GOOGLE, uid="google-uid-1")


@pytest.mark.django_db
def test_identity_provider_is_unique_per_user(user):
    Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-1")

    with pytest.raises(IntegrityError):
        Identity.objects.create(user=user, provider=Identity.GOOGLE, uid="google-uid-2")


@pytest.mark.django_db
def test_legacy_token_use_needs_a_user_and_a_day():
    with pytest.raises(ValidationError) as error:
        LegacyTokenUse(uses_count=1).full_clean()
    assert {"user", "used_on"} <= set(error.value.message_dict)


@pytest.mark.django_db
def test_legacy_token_use_is_unique_per_user_and_day(user):
    LegacyTokenUse.objects.create(user=user, used_on=date.today(), uses_count=1)

    with pytest.raises(IntegrityError):
        LegacyTokenUse.objects.create(user=user, used_on=date.today(), uses_count=1)


@pytest.mark.django_db
@pytest.mark.parametrize(("uses_count", "valid"), [(0, True), (3, True), (-1, False)])
def test_legacy_token_use_count_is_a_non_negative_integer(user, uses_count, valid):
    use = LegacyTokenUse(user=user, used_on=date.today(), uses_count=uses_count)

    if valid:
        use.full_clean()
    else:
        with pytest.raises(ValidationError):
            use.full_clean()
