"""Settings shared by local, test, and production environments."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "apps.accounts.apps.AccountsConfig",
    "apps.tenants.apps.TenantsConfig",
    "apps.customers.apps.CustomersConfig",
    "apps.dashboard.apps.DashboardConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.tenants.middleware.ActiveTenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/kanakkupro"
)
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=0 if "-pooler" in DATABASE_URL else 60,
        ssl_require=not DEBUG and "localhost" not in DATABASE_URL,
    )
}
if "-pooler" in DATABASE_URL:
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "home"

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = False
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_SESSION_REMEMBER = False
ACCOUNT_RATE_LIMITS = {
    "login": "10/m/ip",
    "login_failed": "5/5m/key",
    "reset_password": "5/m/ip,3/m/key",
    "reset_password_from_key": "10/m/ip",
    "signup": "5/m/ip",
    "confirm_email": "1/3m/key",
}

PASSWORD_RESET_TIMEOUT = 60 * 60
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "KankkuPro <noreply@example.com>"
)
TENANT_INVITATION_TTL_DAYS = int(os.environ.get("TENANT_INVITATION_TTL_DAYS", "7"))

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "kankku-local-auth-rate-limits",
    }
}
