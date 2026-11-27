"""Disposable localhost review data only; never connect this server to Neon."""

from django.core.exceptions import ImproperlyConfigured
from scripts.pilot_review import guard_database

from .base import *  # noqa: F403
from .base import DATABASES

try:
    guard_database(DATABASES["default"])
except ValueError:
    raise ImproperlyConfigured(
        "Review settings require a local test_pilot_review_ database."
    ) from None

DEBUG = True
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
SECRET_KEY = "local-synthetic-review-only-never-use-for-deployment"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
RUNTIME_ALERTS_ENABLED = False
RUNTIME_ALERT_EMAILS = []
DEPLOYMENT_ENVIRONMENT = "test"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
