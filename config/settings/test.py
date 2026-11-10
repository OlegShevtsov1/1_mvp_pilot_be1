import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key")

from .base import *  # noqa: E402

# Tests always run on in-memory SQLite, even when DATABASE_URL is set.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

APP_ENVIRONMENT = "test"
