"""Test settings. Database configuration remains PostgreSQL-only."""

from .base import *  # noqa: F403

SECRET_KEY = SECRET_KEY or "test-only-key-not-used-outside-test-settings"  # noqa: F405
ALLOWED_HOSTS = ["testserver", "localhost"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
