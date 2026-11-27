"""Serialized, additive staging release followed by the WSGI process."""

import json
import os
import re
import subprocess
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

import psycopg

RELEASE_LOCK = 762440619


class ReleaseError(RuntimeError):
    """Only application-controlled, credential-free diagnostic text."""


def command_failure(command, stderr):
    # Extract only known field names/check IDs, never exception text or values.
    fields = [
        key
        for key in (
            "SECRET_KEY",
            "ALLOWED_HOSTS",
            "DATABASE_URL",
            "EMAIL_BACKEND",
            "EMAIL_HOST",
            "EMAIL_USE_TLS",
            "EMAIL_USE_SSL",
            "DEFAULT_FROM_EMAIL",
            "CSRF_TRUSTED_ORIGINS",
            "MFA_ENCRYPTION_KEYS",
            "TRUST_X_FORWARDED_PROTO",
            "RUNTIME_ALERTS_ENABLED",
            "RUNTIME_ALERT_EMAILS",
        )
        if re.search(r"\b" + key + r"\b", stderr)
    ]
    checks = sorted(set(re.findall(r"\b(?:security|health)\.[WE]\d{3}\b", stderr)))
    hints = ", ".join(fields + checks) or "no safe diagnostic available"
    return ReleaseError(f"Release command failed: {command}; inspect {hints}.")


def missing_configuration(env):
    required = [
        "DATABASE_URL",
        "SECRET_KEY",
        "MFA_ENCRYPTION_KEYS",
        "EMAIL_BACKEND",
        "DEFAULT_FROM_EMAIL",
    ]
    if env.get("EMAIL_BACKEND") == "django.core.mail.backends.smtp.EmailBackend":
        required.append("EMAIL_HOST")
    return [key for key in required if not env.get(key, "").strip()]


def release(env):
    url = env.get("MIGRATION_DATABASE_URL") or env.get("DATABASE_URL", "")
    host = urlsplit(url).hostname or ""
    if not host or "-pooler" in host:
        raise ReleaseError("Configure a direct MIGRATION_DATABASE_URL for releases.")
    app = urlsplit(env.get("DATABASE_URL", ""))
    app_host = (app.hostname or "").split(".")
    app_host[0] = app_host[0].removesuffix("-pooler")
    if ".".join(app_host) != host or app.path != urlsplit(url).path:
        raise ReleaseError(
            "Application and migration endpoints must address the same Neon database."
        )
    if parse_qs(urlsplit(url).query).get("sslmode") not in (
        ["require"],
        ["verify-ca"],
        ["verify-full"],
    ):
        raise ReleaseError("Release connections must require TLS.")
    child_env = {**env, "DATABASE_URL": url}
    # Keep the dedicated session alive across child commands. A transaction-
    # pooled endpoint cannot safely hold a session advisory lock.
    print("Release stage: connecting to database.", flush=True)
    with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:
        print("Release stage: acquiring migration lock.", flush=True)
        conn.execute("SET lock_timeout = '60s'")
        conn.execute("SELECT pg_advisory_lock(%s)", [RELEASE_LOCK])
        try:
            for args in (
                ["check", "--deploy", "--fail-level", "WARNING"],
                ["migrate", "--noinput"],
                ["createcachetable"],
                ["migrate", "--check"],
            ):
                print(f"Release stage: {args[0]}.", flush=True)
                result = subprocess.run(
                    [sys.executable, "manage.py", *args],
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode:
                    raise command_failure(args[0], result.stderr or "")
                print(f"Release command completed: {args[0]}", flush=True)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", [RELEASE_LOCK])


def main():
    missing = missing_configuration(os.environ)
    if missing:
        print(
            "Staging configuration is missing: "
            + ", ".join(missing)
            + ". Set these in Render Environment; web server was not started.",
            file=sys.stderr,
        )
        return 1
    try:
        release(dict(os.environ))
    except ReleaseError as error:
        print(str(error), file=sys.stderr)
        return 1
    except psycopg.Error:
        print(
            "Database connection/lock failed; check Neon DATABASE_URL, password, "
            "hostname (no backslashes), TLS, and database availability.",
            file=sys.stderr,
        )
        return 1
    except subprocess.TimeoutExpired:
        print(
            "Release command timed out; inspect database locks and migrations.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        # Driver/child error text may include connection or SMTP details.
        print(
            "Staging release failed; web server was not started. "
            "Check configuration and database connectivity.",
            file=sys.stderr,
        )
        return 1
    optional_runtime_probe(dict(os.environ))
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "gunicorn",
            "config.wsgi:application",
            "--config",
            "gunicorn.conf.py",
        ],
    )


def optional_runtime_probe(env):
    """An explicitly requested, audited one-attempt probe cannot block startup."""
    requested = env.get("RUNTIME_ALERT_PROBE_ID", "").strip()
    if not requested:
        return
    try:
        probe_id = uuid.UUID(requested)
        result = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "send_runtime_alert_test",
                "--send",
                "--probe-id",
                str(probe_id),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        status = data.get("status")
        if status not in {
            "provider_accepted",
            "already_requested",
            "throttled",
            "disabled",
            "unconfigured",
            "unavailable",
        }:
            status = "unavailable"
        print(
            json.dumps({"runtime_alert_probe": status, "request_id": probe_id.hex}),
            flush=True,
        )
    except Exception:
        print(
            "Runtime alert probe unavailable; application startup continues.",
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(main())
