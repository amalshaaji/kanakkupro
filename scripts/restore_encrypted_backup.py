"""Verify an encrypted backup and restore only into an empty local drill database."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from scripts.encrypted_backup import MAX_FILE_BYTES
from scripts.restore_drill import assert_empty_target, client_env, run, snapshot


def guard_target(url, env):
    params = conninfo_to_dict(url)
    if params.get("host") not in {"127.0.0.1", "::1", "localhost"} or not re.fullmatch(
        r"test_restore_[0-9a-f]{32}", params.get("dbname", "")
    ):
        raise ValueError("Use an empty local test_restore_UUID drill database.")
    allowed = {
        "host",
        "port",
        "dbname",
        "user",
        "password",
        "sslmode",
        "connect_timeout",
        "application_name",
    }
    if set(params) - allowed or any(
        env.get(key) or os.environ.get(key)
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
    ):
        raise ValueError("Restore refuses PostgreSQL host/service overrides.")
    return params


def restore_encrypted(
    env,
    encrypted_path,
    identity_path,
    expected_sha256,
    *,
    pg_bin="",
    age_bin="age",
    expected_manifest=None,
    report=lambda stage: None,
):
    started = time.monotonic()
    report("input_validation")
    target = env.get("RESTORE_DATABASE_URL", "")
    params = guard_target(target, env)
    encrypted, identity = Path(encrypted_path), Path(identity_path)
    if not encrypted.is_file() or not 0 < encrypted.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("Backup must be a nonempty, size-bounded local file.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Supply the verified backup's SHA-256 digest.")
    report("ciphertext_verification")
    with encrypted.open("rb") as content:
        ciphertext = content.read(MAX_FILE_BYTES + 1)
    if not 0 < len(ciphertext) <= MAX_FILE_BYTES:
        raise ValueError("Backup changed or exceeded the size limit.")
    actual = hashlib.sha256(ciphertext).hexdigest()
    if actual != expected_sha256:
        raise ValueError("Encrypted backup digest mismatch; no restore attempted.")
    if not identity.is_file() or stat.S_IMODE(identity.stat().st_mode) & 0o077:
        raise ValueError(
            "Use a private recovery identity file (mode 0600 or stricter)."
        )
    report("empty_target_verification")
    assert_empty_target(target)
    # Do not give age or offline Django commands the source database/B2 secrets.
    minimal = {key: env[key] for key in ("PATH", "HOME", "TMPDIR") if key in env}
    offline = {
        **minimal,
        "DATABASE_URL": target,
        "DJANGO_SETTINGS_MODULE": "config.settings.restore",
    }
    pg_restore = str(Path(pg_bin) / "pg_restore") if pg_bin else "pg_restore"
    with tempfile.TemporaryDirectory(prefix="kanakku-encrypted-restore-") as folder:
        private_ciphertext = Path(folder) / "source.dump.age"
        private_ciphertext.write_bytes(ciphertext)
        private_ciphertext.chmod(0o600)
        plain = Path(folder) / "database.dump"
        plain.touch(mode=0o600)
        report("decryption")
        run(
            [
                age_bin,
                "--decrypt",
                "--identity",
                str(identity),
                "--output",
                str(plain),
                str(private_ciphertext),
            ],
            minimal,
        )
        report("archive_validation")
        run([pg_restore, "--list", str(plain)], minimal)
        # Recheck immediately before the transactional restore. Never use --clean.
        assert_empty_target(target)
        report("database_restore")
        run(
            [
                pg_restore,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                params["dbname"],
                str(plain),
            ],
            client_env(target, minimal),
        )
        report("migration_verification")
        run([sys.executable, "manage.py", "migrate", "--check"], offline)
        report("manifest_verification")
        restored = snapshot(target, offline)
        if expected_manifest is not None and restored != expected_manifest:
            raise ValueError("Restored manifest differs from the supplied checkpoint.")
    return {
        "status": "restored_and_verified",
        "ciphertext_sha256": actual,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "manifest": restored,
        "source_manifest_compared": expected_manifest is not None,
        "plaintext_removed": True,
        "target_cleanup_required": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-target", action="store_true", required=True)
    parser.add_argument("--encrypted-file", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--expected-manifest")
    parser.add_argument("--pg-bin", default="")
    parser.add_argument("--age-bin", default="age")
    args = parser.parse_args()
    stage = "input_validation"

    def report(value):
        nonlocal stage
        stage = value
        print(json.dumps({"stage": stage}), flush=True)

    try:
        expected = (
            json.loads(Path(args.expected_manifest).read_text())
            if args.expected_manifest
            else None
        )
        result = restore_encrypted(
            dict(os.environ),
            args.encrypted_file,
            args.identity_file,
            args.sha256,
            pg_bin=args.pg_bin,
            age_bin=args.age_bin,
            expected_manifest=expected,
            report=report,
        )
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print(
            f"Encrypted restore verification failed at stage: {stage}. "
            "No credentials or provider details printed. The target was not cleared; "
            "inspect the isolated target before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
