"""Local development settings."""

import secrets

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(48)  # noqa: F405
ALLOWED_HOSTS = ALLOWED_HOSTS or ["127.0.0.1", "localhost"]  # noqa: F405
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
