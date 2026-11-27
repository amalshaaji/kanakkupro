"""Test settings. Database configuration remains PostgreSQL-only."""

from . import base as base_settings
from .base import *  # noqa: F403

SECRET_KEY = SECRET_KEY or "test-only-key-not-used-outside-test-settings"  # noqa: F405
ALLOWED_HOSTS = ["testserver", "localhost"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEPLOYMENT_ENVIRONMENT = "test"
RUNTIME_ALERTS_ENABLED = False
RUNTIME_ALERT_EMAILS = []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MIDDLEWARE = [
    item
    for item in base_settings.MIDDLEWARE
    if item != "whitenoise.middleware.WhiteNoiseMiddleware"
]
