"""Production settings with secure transport and cookie defaults."""

import os

from django.core.exceptions import ImproperlyConfigured

from config.production_validation import validate_production_environment

validate_production_environment(os.environ)

from .base import *  # noqa: E402, F403

DEBUG = False
DEPLOYMENT_ENVIRONMENT = "production"
os.environ.setdefault("APP_ENV", "production")
if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY must be set in production.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")
if not EMAIL_BACKEND or EMAIL_BACKEND.endswith("console.EmailBackend"):  # noqa: F405
    raise ImproperlyConfigured(
        "Configure a production EMAIL_BACKEND before enabling account email flows."
    )

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": os.environ.get("DATABASE_CACHE_TABLE", "django_cache"),
        "OPTIONS": {
            "MAX_ENTRIES": int(os.environ.get("AUTH_CACHE_MAX_ENTRIES", "100000")),
            "CULL_FREQUENCY": 3,
        },
    }
}

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False
# Preload enrollment is intentionally deferred until the domain/TLS rollout
# is verified. Keep all other Django deployment warnings visible.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.environ.get("TRUST_X_FORWARDED_PROTO", "False").lower() == "true"
    else None
)
