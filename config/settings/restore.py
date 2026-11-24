"""Offline operator commands only; no network service or outbound mail."""

from .base import *  # noqa: F403

SECRET_KEY = "offline-restore-verification-only-never-use-for-a-web-server"
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
ALLOWED_HOSTS = []
