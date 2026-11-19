"""Test settings: zero outbound network access, fast hashing, local cache."""

import os

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*"]

if not os.environ.get("DATABASE_URL"):
    # Postgres is used by CI and by `make test` (docker compose db).  SQLite is a
    # convenience fallback when someone runs pytest without containers up.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
        }
    }

PAYMENT_GATEWAY = "fake"
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "payplan-test-cache",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Test suite must be fast and deterministic.
FAKE_GATEWAY_FAILURE_RATE = 0
