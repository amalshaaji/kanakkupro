import os
import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase
from scripts.render_start import RELEASE_LOCK, main, missing_configuration, release
from scripts.restore_drill import assert_empty_target, client_env, drill


class ReleaseTests(SimpleTestCase):
    @patch("scripts.render_start.release")
    @patch("scripts.render_start.sys.stderr")
    def test_missing_configuration_stops_before_connecting(self, stderr, start):
        with patch.dict(os.environ, {"SECRET_KEY": "private-value"}, clear=True):
            self.assertEqual(main(), 1)
        start.assert_not_called()
        output = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("DATABASE_URL", output)
        self.assertIn("MFA_ENCRYPTION_KEYS", output)
        self.assertNotIn("private-value", output)

    def test_smtp_configuration_requires_host(self):
        env = dict.fromkeys(
            ["DATABASE_URL", "SECRET_KEY", "MFA_ENCRYPTION_KEYS", "DEFAULT_FROM_EMAIL"],
            "present",
        )
        env["EMAIL_BACKEND"] = "django.core.mail.backends.smtp.EmailBackend"
        self.assertEqual(missing_configuration(env), ["EMAIL_HOST"])
        env["EMAIL_HOST"] = "smtp.example.test"
        self.assertEqual(missing_configuration(env), [])

    @patch("scripts.render_start.subprocess.run")
    @patch("scripts.render_start.psycopg.connect")
    def test_release_serializes_commands_and_uses_direct_endpoint(self, connect, run):
        connection = connect.return_value.__enter__.return_value
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        env = {
            "DATABASE_URL": "postgresql://u:p@db-pooler.test/app?sslmode=require",
            "MIGRATION_DATABASE_URL": "postgresql://u:p@db.test/app?sslmode=require",
        }
        release(env)
        self.assertEqual(
            [call.args[0][2] for call in run.call_args_list],
            ["check", "migrate", "createcachetable", "migrate"],
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["DATABASE_URL"], env["MIGRATION_DATABASE_URL"]
        )
        connection.execute.assert_any_call(
            "SELECT pg_advisory_lock(%s)", [RELEASE_LOCK]
        )
        connection.execute.assert_any_call(
            "SELECT pg_advisory_unlock(%s)", [RELEASE_LOCK]
        )

    @patch("scripts.render_start.subprocess.run")
    @patch("scripts.render_start.psycopg.connect")
    def test_failed_release_unlocks_and_stops_without_exposing_child_output(
        self, connect, run
    ):
        run.return_value = subprocess.CompletedProcess([], 1, "secret", "secret")
        with self.assertRaises(RuntimeError) as raised:
            release({"DATABASE_URL": "postgresql://u:p@db.test/app?sslmode=require"})
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(run.call_count, 1)
        connect.return_value.__enter__.return_value.execute.assert_any_call(
            "SELECT pg_advisory_unlock(%s)", [RELEASE_LOCK]
        )

    @patch("scripts.render_start.psycopg.connect")
    def test_poolers_and_plaintext_connections_are_rejected_before_connect(
        self, connect
    ):
        for url in (
            "postgresql://u:p@db-pooler.test/app?sslmode=require",
            "postgresql://u:p@db.test/app?sslmode=disable",
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                release({"DATABASE_URL": url})
        connect.assert_not_called()

    @patch("scripts.render_start.psycopg.connect")
    def test_migration_endpoint_cannot_point_at_another_database(self, connect):
        with self.assertRaises(RuntimeError):
            release(
                {
                    "DATABASE_URL": "postgresql://u:p@stage-pooler.test/app?sslmode=require",
                    "MIGRATION_DATABASE_URL": "postgresql://u:p@production.test/app?sslmode=require",
                }
            )
        connect.assert_not_called()


class RestoreSafetyTests(SimpleTestCase):
    @patch("scripts.restore_drill.psycopg.connect")
    def test_restore_refuses_nonempty_targets(self, connect):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        with self.assertRaises(RuntimeError):
            assert_empty_target("postgresql://local/test")

    @patch("scripts.restore_drill.assert_empty_target")
    def test_identical_or_missing_database_urls_are_rejected(self, empty):
        for env in ({}, {"DATABASE_URL": "same", "RESTORE_DATABASE_URL": "same"}):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                drill(env)
        empty.assert_not_called()

    def test_client_credentials_are_passed_through_environment(self):
        env = client_env(
            "postgresql://alice:secret@host.test:5432/restored?sslmode=require",
            {"PGHOST": "wrong", "PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(env["PGDATABASE"], "restored")
        self.assertEqual(env["PGPASSWORD"], "secret")
        self.assertEqual(env["PGHOST"], "host.test")
        self.assertEqual(env["PGSSLMODE"], "require")

    @patch("scripts.restore_drill.snapshot")
    @patch("scripts.restore_drill.assert_empty_target")
    @patch("scripts.restore_drill.run")
    def test_changed_source_aborts_before_restore(self, run, empty, snapshot):
        snapshot.side_effect = [{"version": 1}, {"version": 2}]

        def dump(command, env):
            from pathlib import Path

            Path(command[command.index("--file") + 1]).write_bytes(b"test")
            return ""

        run.side_effect = dump
        with self.assertRaises(RuntimeError):
            drill(
                {
                    "DATABASE_URL": "postgresql://host/source",
                    "RESTORE_DATABASE_URL": "postgresql://host/target",
                }
            )
        self.assertEqual(run.call_count, 1)
