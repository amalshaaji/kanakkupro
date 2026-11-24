"""Restore into a confirmed empty, isolated database. Never uses --clean."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict


def client_env(url, env):
    names = {
        "dbname": "PGDATABASE",
        "host": "PGHOST",
        "port": "PGPORT",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
        "channel_binding": "PGCHANNELBINDING",
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "options": "PGOPTIONS",
        "application_name": "PGAPPNAME",
    }
    result = {key: value for key, value in env.items() if not key.startswith("PG")}
    for key, value in conninfo_to_dict(url).items():
        if key not in names:
            raise RuntimeError("Unsupported PostgreSQL client option.")
        result[names[key]] = value
    return result


def run(command, env):
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=600
    )
    if result.returncode:
        raise RuntimeError(
            "Restore verification command failed; no credentials or data are printed."
        )
    return result.stdout


def snapshot(url, env):
    return json.loads(
        run(
            [sys.executable, "manage.py", "restore_manifest", "--all-tenants"],
            {
                **env,
                "DATABASE_URL": url,
                "DJANGO_SETTINGS_MODULE": "config.settings.restore",
            },
        )
    )


def assert_empty_target(url):
    with psycopg.connect(url, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND c.relkind IN ('r','p','v','m','S')"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("Restore target must be an empty isolated database.")


def drill(env, *, pg_bin=""):
    source, target = env.get("DATABASE_URL"), env.get("RESTORE_DATABASE_URL")
    if not source or not target or source == target:
        raise RuntimeError(
            "Configure distinct source and isolated target database URLs."
        )
    assert_empty_target(target)
    before = snapshot(source, env)
    started = time.monotonic()

    def binary(name):
        return str(Path(pg_bin) / name) if pg_bin else name

    with tempfile.TemporaryDirectory(prefix="kanakku-restore-") as folder:
        backup = Path(folder) / "snapshot.dump"
        run(
            [binary("pg_dump"), "--format=custom", "--file", str(backup)],
            client_env(source, env),
        )
        os.chmod(backup, 0o600)
        if snapshot(source, env) != before:
            raise RuntimeError(
                "Source changed during the drill; retry in a quiet staging window."
            )
        run(
            [
                binary("pg_restore"),
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                conninfo_to_dict(target)["dbname"],
                str(backup),
            ],
            client_env(target, env),
        )
        # pg_restore's connection URL stays out of errors emitted by this script.
        after = snapshot(target, env)
        if after != before:
            raise RuntimeError(
                "Restored counts, digests, or migration state do not match."
            )
    return {
        "status": "verified",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "manifest": after,
        "target_cleanup_required": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-target", action="store_true", required=True)
    parser.add_argument("--pg-bin", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(drill(dict(os.environ), pg_bin=args.pg_bin), sort_keys=True))
    except Exception:
        print(
            "Restore drill failed. Verify the empty target, credentials, client "
            "version, and staging quiet window. Existing target data was not cleared.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
