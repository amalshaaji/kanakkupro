import io
import json
from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from django.core.mail.backends.smtp import EmailBackend
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.sales.test_workflow import FinancialFixtures


class EmailTransportTests(SimpleTestCase):
    @patch("apps.health.management.commands.check_email_transport.get_connection")
    def test_probe_authenticates_but_never_sends(self, get_connection):
        backend = EmailBackend(
            host="smtp.example.test",
            username="test-user",
            password="private-value",
            use_tls=True,
            use_ssl=False,
        )
        get_connection.return_value = backend
        output = io.StringIO()
        with (
            patch.object(backend, "open") as opened,
            patch.object(backend, "close"),
            patch.object(backend, "send_messages") as send,
        ):
            call_command("check_email_transport", stdout=output)
        opened.assert_called_once()
        send.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["delivery_verified"])
        self.assertNotIn("private-value", output.getvalue())

    @patch("apps.health.management.commands.check_email_transport.get_connection")
    def test_probe_sanitizes_auth_errors_and_refuses_plaintext(self, get_connection):
        backend = EmailBackend(
            host="smtp.example.test",
            username="test-user",
            password="private-value",
            use_tls=True,
            use_ssl=False,
        )
        get_connection.return_value = backend
        output = io.StringIO()
        with (
            patch.object(
                backend,
                "open",
                side_effect=SMTPAuthenticationError(535, b"private-value"),
            ),
            patch.object(backend, "close"),
        ):
            with self.assertRaises(CommandError) as raised:
                call_command("check_email_transport", stdout=output)
        self.assertNotIn("private-value", str(raised.exception) + output.getvalue())
        self.assertEqual(
            json.loads(output.getvalue())["smtp"], "authentication_rejected"
        )
        backend.use_tls = False
        with patch.object(backend, "open") as opened:
            with self.assertRaises(CommandError):
                call_command("check_email_transport")
        opened.assert_not_called()


class PilotStatusTests(FinancialFixtures, TestCase):
    def test_status_report_is_read_only_and_does_not_grant_admission(self):
        from apps.tenants.models import PilotCheck

        output = io.StringIO()
        call_command(
            "pilot_status",
            tenant=str(self.tenant.pk),
            reviewer=str(self.owner.pk),
            stdout=output,
        )
        result = json.loads(output.getvalue())
        self.assertFalse(result["operator_admission_verified"])
        self.assertEqual(PilotCheck.objects.count(), 0)
        self.assertNotIn(self.owner.email, output.getvalue())
        self.membership.status = "inactive"
        self.membership.save(update_fields=["status"])
        with self.assertRaises(CommandError):
            call_command(
                "pilot_status", tenant=str(self.tenant.pk), reviewer=str(self.owner.pk)
            )
