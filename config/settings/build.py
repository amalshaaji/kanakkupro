"""Static asset collection only. Never use to serve application requests."""

from .base import *  # noqa: F403

SECRET_KEY = "build-only-placeholder-never-used-for-serving-application-requests"
ALLOWED_HOSTS = ["localhost"]
