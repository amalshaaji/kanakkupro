"""Read-only PostgreSQL dump, age encryption, and verified private B2 upload."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict

from scripts.restore_drill import client_env

BUCKET = "kanakkupro-backups-29988154"
ENDPOINT = "https://s3.us-east-005.backblazeb2.com"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BUCKET_BYTES = 1024 * 1024 * 1024
SAFE_PROVIDER_CODES = frozenset(
    {
        "AccessDenied",
        "BadDigest",
        "ExpiredToken",
        "InvalidAccessKeyId",
        "InvalidArgument",
        "InvalidDigest",
        "InvalidRequest",
        "InvalidToken",
        "NotImplemented",
        "RequestTimeout",
        "ServiceUnavailable",
        "SignatureDoesNotMatch",
        "SlowDown",
    }
)
SAFE_FAILURE_KINDS = frozenset(
    {
        "ClientError",
        "ParamValidationError",
        "MissingDependencyException",
        "EndpointConnectionError",
        "ConnectionClosedError",
        "HTTPClientError",
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "SSLError",
        "FlexibleChecksumError",
        "UnsupportedChecksumAlgorithmError",
        "UnseekableStreamError",
        "NoCredentialsError",
        "PartialCredentialsError",
        "TypeError",
        "ValueError",
        "RuntimeError",
        "OSError",
        "AttributeError",
    }
)


def safe_provider_failure(error):
    """Return fixed error codes and status only, never provider response text."""
    kind = type(error).__name__
    result = {
        "failure_kind": kind if kind in SAFE_FAILURE_KINDS else "unknown",
        "provider_code": "unknown",
        "http_status": None,
    }
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return result
    detail = response.get("Error")
    code = detail.get("Code") if isinstance(detail, dict) else None
    metadata = response.get("ResponseMetadata")
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    return {
        **result,
        "provider_code": (
            code if isinstance(code, str) and code in SAFE_PROVIDER_CODES else "unknown"
        ),
        "http_status": status if type(status) is int and 400 <= status <= 599 else None,
    }


def omit_upload_continue(request, **kwargs):
    """Avoid interim-response stalls; run before signing, without changing TLS."""
    if "Expect" in request.headers:
        del request.headers["Expect"]


def command(args, env, *, stdout=subprocess.DEVNULL):
    result = subprocess.run(
        args, env=env, stdout=stdout, stderr=subprocess.PIPE, timeout=600
    )
    if result.returncode:
        raise RuntimeError("Backup tool failed; provider output withheld.")


def validate_source(url, *, allow_local=False):
    params = conninfo_to_dict(url)
    local = params.get("host") in {"localhost", "127.0.0.1", "::1"}
    if not (allow_local and local) and params.get("sslmode") not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError("Database TLS is required.")
    if not params.get("host") or not params.get("dbname"):
        raise ValueError("An explicit database host and name are required.")


def check_storage(storage, *, report=lambda stage: None):
    # B2 exposes private/allPrivate through its S3 bucket ACL API.
    report("bucket_privacy")
    acl = storage.get_bucket_acl(Bucket=BUCKET)
    for grant in acl.get("Grants", []):
        if grant.get("Grantee", {}).get("Type") == "Group":
            raise ValueError("Backup bucket must be private.")
    report("bucket_retention")
    config = storage.get_object_lock_configuration(Bucket=BUCKET)
    lock = config.get("ObjectLockConfiguration", {})
    default = lock.get("Rule", {}).get("DefaultRetention", {})
    if (
        lock.get("ObjectLockEnabled") != "Enabled"
        or default.get("Mode") != "COMPLIANCE"
        or default.get("Days", 0) < 30
    ):
        raise ValueError("Thirty-day compliance retention is required.")
    # Include noncurrent versions: they consume storage too. Never delete backups.
    report("bucket_inventory")
    total = 0
    for page in storage.get_paginator("list_object_versions").paginate(Bucket=BUCKET):
        total += sum(item["Size"] for item in page.get("Versions", []))
        if total >= MAX_BUCKET_BYTES:
            raise ValueError("Backup storage cap reached; operator review required.")
    return total


def backup(
    env,
    storage,
    *,
    pg_bin="",
    age_bin="age",
    allow_local=False,
    report=lambda stage: None,
):
    report("source_configuration")
    url = env.get("BACKUP_DATABASE_URL", "")
    validate_source(url, allow_local=allow_local)
    report("recipient_configuration")
    recipient = env.get("BACKUP_AGE_RECIPIENT", "")
    if not re.fullmatch(r"age1[0-9a-z]{58}", recipient):
        raise ValueError("A native age public recipient is required.")
    used = check_storage(storage, report=report)
    pg_dump = str(Path(pg_bin) / "pg_dump") if pg_bin else "pg_dump"
    pg_restore = str(Path(pg_bin) / "pg_restore") if pg_bin else "pg_restore"
    # Do not give database clients bucket credentials, or age database credentials.
    minimal = {k: env[k] for k in ("PATH", "HOME", "TMPDIR") if k in env}
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="kanakku-backup-") as folder:
        plain = Path(folder) / "database.dump"
        encrypted = Path(folder) / "database.dump.age"
        # Pre-create with private permissions before pg_dump opens the file.
        plain.touch(mode=0o600)
        report("database_dump")
        command(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(plain),
            ],
            client_env(url, minimal),
        )
        report("archive_validation")
        command([pg_restore, "--list", str(plain)], minimal)
        encrypted.touch(mode=0o600)
        report("encryption")
        command(
            [
                age_bin,
                "--encrypt",
                "--recipient",
                recipient,
                "--output",
                str(encrypted),
                str(plain),
            ],
            minimal,
        )
        report("storage_budget")
        size = encrypted.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES or used + size > MAX_BUCKET_BYTES:
            raise ValueError("Backup size exceeds the conservative storage budget.")
        with encrypted.open("rb") as ciphertext:
            digest = hashlib.file_digest(ciphertext, "sha256").hexdigest()
        key = f"daily/{started:%Y/%m/%d}/{started:%H%M%S}-{uuid.uuid4().hex}.dump.age"
        report("encrypted_upload")
        with encrypted.open("rb") as body:
            result = storage.put_object(
                Bucket=BUCKET,
                Key=key,
                Body=body,
                ContentLength=size,
                ContentType="application/octet-stream",
                Metadata={"sha256": digest},
            )
        report("uploaded_version")
        version = result.get("VersionId")
        if not version:
            raise RuntimeError("Uploaded object version could not be verified.")
        report("uploaded_size")
        headers = storage.head_object(Bucket=BUCKET, Key=key, VersionId=version)
        if headers.get("ContentLength") != size:
            raise RuntimeError("Uploaded object size mismatch.")
        report("uploaded_retention")
        retention = storage.get_object_retention(
            Bucket=BUCKET, Key=key, VersionId=version
        ).get("Retention", {})
        until = retention.get("RetainUntilDate")
        if (
            retention.get("Mode") != "COMPLIANCE"
            or until is None
            or (until - started).total_seconds() < 30 * 86400
        ):
            raise RuntimeError("Uploaded object retention could not be verified.")
        # Read the stored ciphertext back; an ETag alone is not a SHA-256 check.
        report("download_verification")
        response = storage.get_object(Bucket=BUCKET, Key=key, VersionId=version)
        remote = hashlib.sha256()
        stream = response["Body"]
        try:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                remote.update(chunk)
        finally:
            stream.close()
        if remote.hexdigest() != digest:
            raise RuntimeError("Downloaded ciphertext digest mismatch.")
    return {
        "status": "uploaded_and_verified",
        "key": key,
        "version": version,
        "bytes": size,
        "sha256": digest,
        "retention_days_minimum": 30,
        "restore_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", default="")
    parser.add_argument(
        "--check-storage",
        action="store_true",
        help="Check bucket access, retention and budget without a database dump.",
    )
    args = parser.parse_args()
    stage = "storage_client"

    def report_stage(value):
        nonlocal stage
        stage = value
        print(json.dumps({"stage": stage}), flush=True)

    try:
        import boto3
        from botocore.config import Config

        # Endpoint is deliberately fixed to the user-selected private bucket region.
        assert urlsplit(ENDPOINT).scheme == "https"
        storage = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name="us-east-005",
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        storage.meta.events.register("before-sign.s3.PutObject", omit_upload_continue)
        if args.check_storage:
            used = check_storage(storage, report=report_stage)
            result = {"status": "storage_verified", "used_bytes": used}
        else:
            result = backup(
                dict(os.environ), storage, pg_bin=args.pg_bin, report=report_stage
            )
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps(safe_provider_failure(error)), file=sys.stderr)
        print(
            f"Encrypted backup failed at stage: {stage}. "
            "Check private configuration, retention, storage budget and client "
            "versions. No provider details printed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
