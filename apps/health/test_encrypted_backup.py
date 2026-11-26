import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scripts.encrypted_backup import BUCKET, MAX_BUCKET_BYTES, backup, check_storage


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
