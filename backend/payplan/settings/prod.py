"""Production settings.  Every secret is required from the environment."""

from .base import *  # noqa: F401,F403

DEBUG = False

if SECRET_KEY == "insecure-dev-only-change-me":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["localhost", "127.0.0.1", "api", "web"]:  # noqa: F405
    raise RuntimeError("ALLOWED_HOSTS must be configured in production")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "stripe")
if PAYMENT_GATEWAY == "stripe" and not STRIPE_SECRET_KEY:  # noqa: F405
    raise RuntimeError("STRIPE_SECRET_KEY is required when PAYMENT_GATEWAY=stripe")

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
