import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS = [
    host
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "oauth2_provider",
    "apps.common",
    "corsheaders",
    "apps.users",
    "apps.projects",
    "apps.tasks",
    "apps.errors",
    "apps.admin_smoke",
]

MIDDLEWARE = [
    "apps.errors.cors.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# The default Sentry environment.
APP_ENVIRONMENT = "development"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {},
    },
]

DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_USER_MODEL = "users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "static/"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.users.authentication.DualSchemeAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "apps.common.exceptions.exception_handler",
}

ACCESS_TOKEN_LIFETIME = 3600

OAUTH2_PROVIDER = {
    "OAUTH2_SERVER_CLASS": "apps.users.oauth.Server",
    "OAUTH2_VALIDATOR_CLASS": "apps.users.oauth.Validator",
    "OAUTH2_BACKEND_CLASS": "apps.users.oauth.Backend",
    "ACCESS_TOKEN_EXPIRE_SECONDS": ACCESS_TOKEN_LIFETIME,
    # A refresh token is refused 30 days after it was issued; DOT counts from the access token's
    # expiry, an hour after issue.
    "REFRESH_TOKEN_EXPIRE_SECONDS": 30 * 24 * 3600 - ACCESS_TOKEN_LIFETIME,
    "ROTATE_REFRESH_TOKEN": True,
    # Only SHA-256 hashes of both tokens are stored.
    "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": True,
    "DEFAULT_SCOPES": [],
}

# Rate limits count here and in a per-process fallback (apps.common.rate_limit). LocMemCache
# counts per process: with several workers, point CACHES at a shared backend for exact limits.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Proxies whose X-Forwarded-For is believed: loopback, unique-local and private ranges.
TRUSTED_PROXIES = [
    "127.0.0.0/8",
    "::1",
    "fc00::/7",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]

SPECTACULAR_SETTINGS = {"TITLE": "Projects and Tasks API", "VERSION": "v1"}

# CORS. The allowed origins come from CORS_ALLOWED_ORIGINS in the environment, read per request
# by apps.errors.cors, not from the setting of the same name.
CORS_ALLOW_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
CORS_EXPOSE_HEADERS = ("Retry-After",)
CORS_ALLOW_CREDENTIALS = False
CORS_PREFLIGHT_MAX_AGE = 7200
