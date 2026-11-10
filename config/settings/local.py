import os

# The local server binds to 127.0.0.1 only.
os.environ.setdefault("DJANGO_SECRET_KEY", "local-only-insecure-key")

from .base import *  # noqa: E402
