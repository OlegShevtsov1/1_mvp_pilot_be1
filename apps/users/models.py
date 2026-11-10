import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import MinValueValidator
from django.db import models

# Legacy token alphabet: URL-safe base64 without the look-alikes l, I, O and 0.
_FRIENDLY = str.maketrans("lIO0", "sxyz")


def friendly_token():
    return secrets.token_urlsafe(15).translate(_FRIENDLY)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **fields):
        user = self.model(email=self.normalize_email(email), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """The users table; email is the login.

    `password` holds the password hash.
    """

    # The users table has no last_login column.
    last_login = None

    email = models.EmailField(max_length=255, unique=True)
    # Nullable so users without a token don't collide on the unique index.
    reset_password_token = models.CharField(max_length=255, null=True, blank=True, unique=True)
    reset_password_sent_at = models.DateTimeField(null=True, blank=True)
    remember_created_at = models.DateTimeField(null=True, blank=True)
    authentication_token = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    projects_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        # Emails are kept stripped and lowercased; a blank legacy token is filled with a fresh
        # one no other user holds.
        self.email = (self.email or "").strip().lower()
        if not self.authentication_token:
            self.authentication_token = self._unused_token()
        super().save(*args, **kwargs)

    @classmethod
    def _unused_token(cls):
        while True:
            token = friendly_token()
            if not cls.objects.filter(authentication_token=token).exists():
                return token


class Identity(models.Model):
    """A sign-in provider account linked to a user."""

    GOOGLE = "google"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="identities")
    provider = models.CharField(max_length=255)
    uid = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "uid"], name="identity_provider_uid"),
            models.UniqueConstraint(fields=["user", "provider"], name="identity_user_provider"),
        ]


class LegacyTokenUse(models.Model):
    """How often a user authenticated with the legacy token pair on one day (ADR-0005)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="legacy_token_uses")
    used_on = models.DateField(db_index=True)
    uses_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "used_on"], name="legacy_token_use_user_day"),
        ]
