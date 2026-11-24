"""Serialized, additive staging release followed by the WSGI process."""

import os
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import psycopg

RELEASE_LOCK = 762440619


def release(env):
    url = env.get("MIGRATION_DATABASE_URL") or env.get("DATABASE_URL", "")
    host = urlsplit(url).hostname or ""
    if not host or "-pooler" in host:
        raise RuntimeError("Configure a direct MIGRATION_DATABASE_URL for releases.")
    app = urlsplit(env.get("DATABASE_URL", ""))
    app_host = (app.hostname or "").split(".")
    app_host[0] = app_host[0].removesuffix("-pooler")
    if ".".join(app_host) != host or app.path != urlsplit(url).path:
        raise RuntimeError(
            "Application and migration endpoints must address the same Neon database."
        )
    if parse_qs(urlsplit(url).query).get("sslmode") not in (
        ["require"],
        ["verify-ca"],
        ["verify-full"],
    ):
        raise RuntimeError("Release connections must require TLS.")
    child_env = {**env, "DATABASE_URL": url}
    # Keep the dedicated session alive across child commands. A transaction-
    # pooled endpoint cannot safely hold a session advisory lock.
    with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:
        conn.execute("SET lock_timeout = '60s'")
        conn.execute("SELECT pg_advisory_lock(%s)", [RELEASE_LOCK])
        try:
            for args in (
                ["check", "--deploy", "--fail-level", "WARNING"],
                ["migrate", "--noinput"],
                ["createcachetable"],
                ["migrate", "--check"],
            ):
                result = subprocess.run(
                    [sys.executable, "manage.py", *args],
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode:
                    raise RuntimeError(f"Release command failed: {args[0]}.")
                print(f"Release command completed: {args[0]}", flush=True)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", [RELEASE_LOCK])


def main():
    try:
        release(dict(os.environ))
    except Exception:
        # Driver/child error text may include connection or SMTP details.
        print(
            "Staging release failed; web server was not started. "
            "Check configuration and database connectivity.",
            file=sys.stderr,
        )
        return 1
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


if __name__ == "__main__":
    sys.exit(main())
