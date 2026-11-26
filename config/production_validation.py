from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured


def validate_production_environment(env):
    """Fail before importing settings; errors must never echo secret values."""
    secret = env.get("SECRET_KEY", "")
    if (
        len(secret) < 50
        or len(set(secret)) < 5
        or secret.startswith("django-insecure-")
    ):
        raise ImproperlyConfigured("Set a strong SECRET_KEY of at least 50 characters.")
    hosts = [
        host.strip() for host in env.get("ALLOWED_HOSTS", "").split(",") if host.strip()
    ]
    if not hosts or any("*" in host or "/" in host or "://" in host for host in hosts):
        raise ImproperlyConfigured(
            "Set explicit ALLOWED_HOSTS without URLs or wildcards."
        )
    try:
        database = urlsplit(env.get("DATABASE_URL", ""))
        sslmode = parse_qs(database.query).get("sslmode", [])
        valid = (
            database.scheme in {"postgres", "postgresql"}
            and database.hostname
            and database.path.strip("/")
            and sslmode in (["require"], ["verify-ca"], ["verify-full"])
        )
    except ValueError:
        valid = False
    if not valid:
        raise ImproperlyConfigured(
            "Set an explicit PostgreSQL DATABASE_URL with "
            "sslmode=require or certificate verification."
        )
    backend = env.get("EMAIL_BACKEND", "")
    if not backend or backend in {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }:
        raise ImproperlyConfigured("Configure a real production EMAIL_BACKEND.")
    if backend in {
        "django.core.mail.backends.smtp.EmailBackend",
        "apps.accounts.delivery.SafeSMTPBackend",
    }:
        if not env.get("EMAIL_HOST"):
            raise ImproperlyConfigured("Set EMAIL_HOST for the SMTP backend.")
        tls = env.get("EMAIL_USE_TLS", "True").lower() == "true"
        ssl = env.get("EMAIL_USE_SSL", "False").lower() == "true"
        if tls == ssl:
            raise ImproperlyConfigured(
                "Enable exactly one of EMAIL_USE_TLS or EMAIL_USE_SSL."
            )
    if not env.get("DEFAULT_FROM_EMAIL"):
        raise ImproperlyConfigured("Set the verified DEFAULT_FROM_EMAIL sender.")
    for origin in env.get("CSRF_TRUSTED_ORIGINS", "").split(","):
        if origin.strip():
            parsed = urlsplit(origin.strip())
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ImproperlyConfigured(
                    "Production CSRF_TRUSTED_ORIGINS must be HTTPS origins "
                    "without paths."
                )
    keys = [
        key.strip()
        for key in env.get("MFA_ENCRYPTION_KEYS", "").split(",")
        if key.strip()
    ]
    if not keys:
        raise ImproperlyConfigured("Set MFA_ENCRYPTION_KEYS for encrypted MFA secrets.")
    try:
        for key in keys:
            Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise ImproperlyConfigured(
            "MFA_ENCRYPTION_KEYS must contain valid Fernet keys."
        ) from error
    if env.get("TRUST_X_FORWARDED_PROTO", "False").lower() not in {"true", "false"}:
        raise ImproperlyConfigured("TRUST_X_FORWARDED_PROTO must be True or False.")
