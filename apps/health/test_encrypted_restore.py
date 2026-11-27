import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.restore_encrypted_backup import guard_target, main, restore_encrypted

TARGET = "postgresql://operator:private@127.0.0.1:55432/test_restore_" + "a" * 32
MANIFEST = {"version": 1, "tables": {"sales.Invoice": {"count": 2}}}


@pytest.fixture
def recovery_files(tmp_path):
    encrypted = tmp_path / "backup.age"
    encrypted.write_bytes(b"synthetic-ciphertext")
    identity = tmp_path / "identity.txt"
    identity.write_text("synthetic-private-identity")
    identity.chmod(0o600)
    return encrypted, identity, hashlib.sha256(encrypted.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "url",
    [
        TARGET.replace("127.0.0.1", "db.example.test"),
        TARGET.replace("test_restore_", "production_"),
        TARGET + "?hostaddr=192.0.2.1",
        TARGET + "?service=production",
    ],
)
def test_restore_guard_rejects_hosted_targets_and_connection_overrides(url):
    with pytest.raises(ValueError):
        guard_target(url, {})


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_restore_guard_rejects_ambient_host_or_service_override(monkeypatch, key):
    monkeypatch.setenv(key, "private-production-override")
    with pytest.raises(ValueError):
        guard_target(TARGET, {})


def test_wrong_checksum_never_connects_or_decrypts(recovery_files):
    encrypted, identity, _ = recovery_files
    with (
        patch("scripts.restore_encrypted_backup.assert_empty_target") as empty,
        patch("scripts.restore_encrypted_backup.run") as command,
    ):
        with pytest.raises(ValueError, match="digest mismatch"):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, "0" * 64
            )
    empty.assert_not_called()
    command.assert_not_called()


def test_oversized_input_or_unprotected_identity_never_connects(recovery_files):
    encrypted, identity, digest = recovery_files
    with patch("scripts.restore_encrypted_backup.assert_empty_target") as empty:
        with patch("scripts.restore_encrypted_backup.MAX_FILE_BYTES", 2):
            with pytest.raises(ValueError, match="size-bounded"):
                restore_encrypted(
                    {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, digest
                )
        identity.chmod(0o644)
        with pytest.raises(ValueError, match="private recovery identity"):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, digest
            )
    empty.assert_not_called()


def test_nonempty_target_is_never_cleared_or_decrypted(recovery_files):
    encrypted, identity, digest = recovery_files
    with (
        patch(
            "scripts.restore_encrypted_backup.assert_empty_target",
            side_effect=RuntimeError,
        ),
        patch("scripts.restore_encrypted_backup.run") as command,
    ):
        with pytest.raises(RuntimeError):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, digest
            )
    command.assert_not_called()


@pytest.mark.parametrize("expected", [MANIFEST, None])
def test_success_restores_verified_bytes_offline_and_removes_plaintext(
    recovery_files, expected
):
    encrypted, identity, digest = recovery_files
    original = encrypted.read_bytes()
    plain_paths, commands = [], []

    def empty(target):
        assert target == TARGET
        # A changed download after hashing cannot substitute the restored bytes.
        encrypted.write_bytes(b"changed-after-hash")

    def command(args, env):
        commands.append(args)
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "BACKUP_DATABASE_URL" not in env
        assert "SECRET_KEY" not in env
        assert "--clean" not in args
        if "--decrypt" in args:
            assert "DATABASE_URL" not in env
            assert Path(args[-1]).read_bytes() == original
            plain = Path(args[args.index("--output") + 1])
            assert plain.stat().st_mode & 0o777 == 0o600
            plain.write_bytes(b"PGDMP-synthetic")
            plain_paths.append(plain)
        elif "--single-transaction" in args:
            assert "--exit-on-error" in args
            assert env["PGHOST"] == "127.0.0.1"
        elif "manage.py" in args:
            assert env["DJANGO_SETTINGS_MODULE"] == "config.settings.restore"
        return ""

    with (
        patch(
            "scripts.restore_encrypted_backup.assert_empty_target", side_effect=empty
        ) as verify_empty,
        patch("scripts.restore_encrypted_backup.run", side_effect=command),
        patch("scripts.restore_encrypted_backup.snapshot", return_value=MANIFEST),
    ):
        result = restore_encrypted(
            {
                "RESTORE_DATABASE_URL": TARGET,
                "AWS_SECRET_ACCESS_KEY": "private-b2",
                "BACKUP_DATABASE_URL": "private-source",
                "SECRET_KEY": "private-session",
            },
            encrypted,
            identity,
            digest,
            expected_manifest=expected,
        )
    assert verify_empty.call_count == 2
    assert result["status"] == "restored_and_verified"
    assert result["source_manifest_compared"] is (expected is not None)
    assert result["target_cleanup_required"] is True
    assert any("--single-transaction" in args for args in commands)
    assert any("--check" in args for args in commands)
    assert all(not path.exists() and not path.parent.exists() for path in plain_paths)
    assert identity.read_text() == "synthetic-private-identity"


def test_decryption_failure_removes_private_scratch_without_touching_target(
    recovery_files,
):
    encrypted, identity, digest = recovery_files
    paths = []

    def failed(args, env):
        plain = Path(args[args.index("--output") + 1])
        plain.write_bytes(b"private-partial-plaintext")
        paths.append(plain)
        raise RuntimeError("private-provider-error")

    with (
        patch("scripts.restore_encrypted_backup.assert_empty_target"),
        patch("scripts.restore_encrypted_backup.run", side_effect=failed) as command,
    ):
        with pytest.raises(RuntimeError):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, digest
            )
    assert command.call_count == 1
    assert all(not path.exists() for path in paths)
    assert encrypted.exists() and identity.exists()


def test_target_becoming_nonempty_blocks_the_restore(recovery_files):
    encrypted, identity, digest = recovery_files
    with (
        patch(
            "scripts.restore_encrypted_backup.assert_empty_target",
            side_effect=[None, RuntimeError("target changed")],
        ),
        patch("scripts.restore_encrypted_backup.run", return_value="") as command,
    ):
        with pytest.raises(RuntimeError, match="target changed"):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET}, encrypted, identity, digest
            )
    assert all(
        "--single-transaction" not in call.args[0] for call in command.call_args_list
    )


def test_mismatched_checkpoint_is_not_reported_as_verified(recovery_files):
    encrypted, identity, digest = recovery_files
    with (
        patch("scripts.restore_encrypted_backup.assert_empty_target"),
        patch("scripts.restore_encrypted_backup.run", return_value="") as command,
        patch("scripts.restore_encrypted_backup.snapshot", return_value=MANIFEST),
    ):
        with pytest.raises(ValueError, match="differs"):
            restore_encrypted(
                {"RESTORE_DATABASE_URL": TARGET},
                encrypted,
                identity,
                digest,
                expected_manifest={"version": 1, "tables": {}},
            )
    plain = next(
        Path(call.args[0][call.args[0].index("--output") + 1])
        for call in command.call_args_list
        if "--decrypt" in call.args[0]
    )
    assert not plain.exists() and not plain.parent.exists()


def test_cli_failure_never_prints_exception_or_credentials(recovery_files, capsys):
    encrypted, identity, digest = recovery_files
    with (
        patch.object(
            sys,
            "argv",
            [
                "restore_encrypted_backup",
                "--confirm-isolated-target",
                "--encrypted-file",
                str(encrypted),
                "--identity-file",
                str(identity),
                "--sha256",
                digest,
            ],
        ),
        patch(
            "scripts.restore_encrypted_backup.restore_encrypted",
            side_effect=RuntimeError("private-credential"),
        ),
    ):
        assert main() == 1
    output = capsys.readouterr()
    assert "input_validation" in output.err
    assert "private-credential" not in output.out + output.err
