import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.production_validation import validate_production_environment


class ProductionValidationTests(SimpleTestCase):
    def setUp(self):
        self.env = {
            "SECRET_KEY": (
                "ci-only-secret-0123456789-abcdefghijklmnopqrstuvwxyz-"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            ),
            "ALLOWED_HOSTS": "erp.example.test",
            "DATABASE_URL": (
                "postgresql://user:localhost-password@database.example.test/app"
                "?sslmode=verify-full"
            ),
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.example.test",
            "DEFAULT_FROM_EMAIL": "no-reply@example.test",
            "MFA_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
            "SECURE_HSTS_SECONDS": "3600",
            "CSRF_TRUSTED_ORIGINS": "https://erp.example.test",
        }

    def test_complete_configuration_is_accepted(self):
        validate_production_environment(self.env)

    def test_unsafe_production_configuration_is_rejected_without_exposing_secrets(self):
        cases = (
            {"SECRET_KEY": "unsafe"},
            {"SECRET_KEY": "x" * 60},
            {"ALLOWED_HOSTS": "*"},
            {"ALLOWED_HOSTS": "https://erp.example.test"},
            {"DATABASE_URL": ""},
            {"DATABASE_URL": "postgresql://user:secret@host/app?sslmode=disable"},
            {"DATABASE_URL": "postgresql://user:secret@host/app?sslmode=prefer"},
            {
                "DATABASE_URL": "postgresql://user:secret@host/app?sslmode=require&sslmode=disable"
            },
            {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
            {"EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend"},
            {"EMAIL_HOST": ""},
            {"EMAIL_USE_TLS": "False", "EMAIL_USE_SSL": "False"},
            {"DEFAULT_FROM_EMAIL": ""},
            {"CSRF_TRUSTED_ORIGINS": "http://erp.example.test"},
            {"CSRF_TRUSTED_ORIGINS": "https://erp.example.test/path"},
            {"MFA_ENCRYPTION_KEYS": ""},
            {"MFA_ENCRYPTION_KEYS": "secret"},
            {"TRUST_X_FORWARDED_PROTO": "maybe"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    validate_production_environment({**self.env, **overrides})
                self.assertNotIn("user:secret", str(raised.exception))

    def inspect_settings(self, **overrides):
        code = (
            "import django;django.setup();from django.conf import settings;"
            "import json;print(json.dumps({'proxy':settings.SECURE_PROXY_SSL_HEADER,"
            "'sslmode':settings.DATABASES['default']['OPTIONS']['sslmode'],"
            "'pooled':settings.DATABASES['default'].get('DISABLE_SERVER_SIDE_CURSORS',False)}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                **self.env,
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                **overrides,
            },
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_proxy_headers_are_opt_in_and_stronger_tls_is_preserved(self):
        values = self.inspect_settings()
        self.assertIsNone(values["proxy"])
        self.assertEqual(values["sslmode"], "verify-full")
        self.assertFalse(values["pooled"])
        values = self.inspect_settings(TRUST_X_FORWARDED_PROTO="True")
        self.assertEqual(values["proxy"], ["HTTP_X_FORWARDED_PROTO", "https"])

    def test_pooler_detection_uses_hostname_not_password(self):
        values = self.inspect_settings(
            DATABASE_URL="postgresql://user:password-pooler@database.example.test/app?sslmode=require"
        )
        self.assertFalse(values["pooled"])
        values = self.inspect_settings(
            DATABASE_URL="postgresql://user:password@database-pooler.example.test/app?sslmode=require"
        )
        self.assertTrue(values["pooled"])

    def test_django_deployment_checks_pass_with_verified_https_configuration(self):
        result = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "check",
                "--deploy",
                "--fail-level",
                "WARNING",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                **self.env,
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
