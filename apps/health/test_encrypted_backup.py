import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from scripts.encrypted_backup import (
    BUCKET,
    MAX_BUCKET_BYTES,
    backup,
    check_storage,
    main,
    omit_upload_continue,
    safe_provider_failure,
)


def storage_client():
    client = MagicMock()
    client.get_bucket_acl.return_value = {"Grants": []}
    client.get_object_lock_configuration.return_value = {
        "ObjectLockConfiguration": {
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": 30}},
        }
    }
    client.get_paginator.return_value.paginate.return_value = [{"Versions": []}]
    client.put_object.return_value = {"VersionId": "synthetic-version"}
    client.get_object_retention.return_value = {
        "Retention": {
            "Mode": "COMPLIANCE",
            "RetainUntilDate": datetime.now(UTC) + timedelta(days=31),
        }
    }
    return client


def test_storage_refuses_public_unprotected_and_over_budget_buckets():
    client = storage_client()
    assert check_storage(client) == 0
    client.get_bucket_acl.return_value = {"Grants": [{"Grantee": {"Type": "Group"}}]}
    with pytest.raises(ValueError):
        check_storage(client)
    client.get_bucket_acl.return_value = {"Grants": []}
    client.get_object_lock_configuration.return_value = {}
    with pytest.raises(ValueError):
        check_storage(client)
    client = storage_client()
    client.get_paginator.return_value.paginate.return_value = [
        {"Versions": [{"Size": MAX_BUCKET_BYTES}]}
    ]
    with pytest.raises(ValueError):
        check_storage(client)


def test_backup_uploads_only_ciphertext_and_checks_download_and_retention():
    client = storage_client()
    env = {
        "BACKUP_DATABASE_URL": "postgresql://user:private@db.example/db?sslmode=require",
        "BACKUP_AGE_RECIPIENT": "age1" + "q" * 58,
        "AWS_SECRET_ACCESS_KEY": "bucket-private",
        "PATH": "/usr/bin",
    }
    encrypted = b"age-encryption.org/v1\nsynthetic-ciphertext"
    paths = []

    def tool(args, tool_env):
        assert "AWS_SECRET_ACCESS_KEY" not in tool_env
        if "--format=custom" in args:
            path = Path(args[args.index("--file") + 1])
            assert path.stat().st_mode & 0o777 == 0o600
            path.write_bytes(b"synthetic-private-database")
            paths.append(path)
        elif "--encrypt" in args:
            assert "PGPASSWORD" not in tool_env
            Path(args[args.index("--output") + 1]).write_bytes(encrypted)

    client.head_object.return_value = {"ContentLength": len(encrypted)}
    client.get_object.return_value = {"Body": io.BytesIO(encrypted)}

    def upload(**kwargs):
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["Body"].read() == encrypted
        assert kwargs["ContentLength"] == len(encrypted)
        return {"VersionId": "synthetic-version"}

    client.put_object.side_effect = upload
    with patch("scripts.encrypted_backup.command", side_effect=tool):
        result = backup(env, client)
    assert result["status"] == "uploaded_and_verified"
    assert result["restore_verified"] is False
    assert all(not path.exists() for path in paths)
    assert "private" not in str(result)
    client.delete_object.assert_not_called()

    client.get_object.return_value = {"Body": io.BytesIO(b"corrupt")}
    with patch("scripts.encrypted_backup.command", side_effect=tool):
        with pytest.raises(RuntimeError, match="digest mismatch"):
            backup(env, client)


def test_backup_refuses_plaintext_database_and_missing_recipient_before_dump():
    with patch("scripts.encrypted_backup.command") as tool:
        with pytest.raises(ValueError, match="TLS"):
            backup(
                {"BACKUP_DATABASE_URL": "postgresql://user@db.example/db"}, MagicMock()
            )
        with pytest.raises(ValueError, match="recipient"):
            backup(
                {"BACKUP_DATABASE_URL": "postgresql://u@db/d?sslmode=require"},
                MagicMock(),
            )
    tool.assert_not_called()


def test_failed_encryption_never_uploads():
    client = storage_client()
    env = {
        "BACKUP_DATABASE_URL": "postgresql://u@db/d?sslmode=require",
        "BACKUP_AGE_RECIPIENT": "age1" + "q" * 58,
    }
    with patch("scripts.encrypted_backup.command", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            backup(env, client)
    client.put_object.assert_not_called()


def test_upload_hook_preserves_payload_integrity_headers():
    request = SimpleNamespace(
        headers={
            "Expect": "100-continue",
            "Content-Length": "9",
            "Content-MD5": "synthetic-digest",
            "x-amz-content-sha256": "synthetic-hash",
        }
    )
    omit_upload_continue(request)
    assert request.headers == {
        "Content-Length": "9",
        "Content-MD5": "synthetic-digest",
        "x-amz-content-sha256": "synthetic-hash",
    }
    omit_upload_continue(request)


def test_actual_backup_sdk_omits_continue_before_network():
    boto3 = pytest.importorskip("boto3", reason="SDK is installed by backup workflow")
    from botocore.config import Config

    class Prepared(Exception):
        pass

    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-east-005.backblazeb2.com",
        region_name="us-east-005",
        aws_access_key_id="synthetic-only",
        aws_secret_access_key="synthetic-only",
        verify=True,
        config=Config(request_checksum_calculation="when_required"),
    )
    client.meta.events.register("before-sign.s3.PutObject", omit_upload_continue)

    def intercept(request, **kwargs):
        assert request.url.startswith("https://s3.us-east-005.backblazeb2.com/")
        assert "Expect" not in request.headers
        assert int(request.headers["Content-Length"]) == 9
        assert request.body.read() == b"synthetic"
        raise Prepared()

    client.meta.events.register("before-send.s3.PutObject", intercept)
    with pytest.raises(Prepared):
        client.put_object(
            Bucket=BUCKET,
            Key="never-uploaded",
            Body=io.BytesIO(b"synthetic"),
            ContentLength=9,
        )


@pytest.mark.parametrize(
    ("operation", "stage"),
    [
        ("get_bucket_acl", "bucket_privacy"),
        ("get_object_lock_configuration", "bucket_retention"),
        ("get_paginator", "bucket_inventory"),
    ],
)
def test_storage_failure_reports_stage_before_dump_or_upload(operation, stage):
    client = storage_client()
    getattr(client, operation).side_effect = RuntimeError("private provider detail")
    stages = []
    with patch("scripts.encrypted_backup.command") as tool:
        with pytest.raises(RuntimeError):
            backup(
                {
                    "BACKUP_DATABASE_URL": "postgresql://u@db/d?sslmode=require",
                    "BACKUP_AGE_RECIPIENT": "age1" + "q" * 58,
                },
                client,
                report=stages.append,
            )
    assert stages[-1] == stage
    tool.assert_not_called()
    client.put_object.assert_not_called()


def test_cli_reports_failed_stage_without_provider_details(capsys):
    def failed_backup(env, storage, *, report, **kwargs):
        report("bucket_retention")
        raise RuntimeError("private-provider-response secret-database-password")

    with (
        patch.dict(
            "sys.modules",
            {"boto3": MagicMock(), "botocore.config": MagicMock()},
        ),
        patch("sys.argv", ["encrypted_backup"]),
        patch("scripts.encrypted_backup.backup", side_effect=failed_backup),
    ):
        assert main() == 1
    output = capsys.readouterr()
    assert '"stage": "bucket_retention"' in output.out
    assert "failed at stage: bucket_retention" in output.err
    assert "private-provider-response" not in output.out + output.err
    assert "secret-database-password" not in output.out + output.err


def test_cli_storage_check_needs_no_database_secret_and_never_uploads(capsys):
    client = storage_client()
    boto3 = MagicMock()
    boto3.client.return_value = client
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.dict("sys.modules", {"boto3": boto3, "botocore.config": MagicMock()}),
        patch("sys.argv", ["encrypted_backup", "--check-storage"]),
        patch("scripts.encrypted_backup.backup") as dump,
        patch("scripts.encrypted_backup.command") as tool,
    ):
        assert main() == 0
    output = capsys.readouterr()
    assert '"status": "storage_verified"' in output.out
    assert not output.err
    client.meta.events.register.assert_called_once_with(
        "before-sign.s3.PutObject", omit_upload_continue
    )
    dump.assert_not_called()
    tool.assert_not_called()
    client.put_object.assert_not_called()


def test_provider_failure_exposes_only_allowlisted_code_and_http_status():
    error = RuntimeError("private-provider-response secret-database-password")
    error.response = {
        "Error": {"Code": "AccessDenied", "Message": "private-provider-response"},
        "ResponseMetadata": {"HTTPStatusCode": 403, "private": "secret"},
    }
    assert safe_provider_failure(error) == {
        "failure_kind": "RuntimeError",
        "provider_code": "AccessDenied",
        "http_status": 403,
    }
    error.response["Error"]["Code"] = "secret-database-password"
    error.response["ResponseMetadata"]["HTTPStatusCode"] = "private-secret"
    assert safe_provider_failure(error) == {
        "failure_kind": "RuntimeError",
        "provider_code": "unknown",
        "http_status": None,
    }
    error.response = None
    assert safe_provider_failure(error) == {
        "failure_kind": "RuntimeError",
        "provider_code": "unknown",
        "http_status": None,
    }
