import io
import json
import subprocess
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from scripts.render_start import optional_runtime_probe

from apps.audit.models import AuditEvent


@override_settings(
    RUNTIME_ALERTS_ENABLED=True,
    RUNTIME_ALERT_EMAILS=["operator@example.test"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AuditedProbeTests(TestCase):
    def test_same_probe_id_cannot_send_again_after_cache_expiry_or_restart(self):
        cache.clear()
        mail.get_connection()
        mail.outbox.clear()
        probe_id = uuid.uuid4()
        first, second = io.StringIO(), io.StringIO()
        call_command(
            "send_runtime_alert_test", send=True, probe_id=probe_id, stdout=first
        )
        cache.clear()
        call_command(
            "send_runtime_alert_test", send=True, probe_id=probe_id, stdout=second
        )
        self.assertEqual(json.loads(first.getvalue())["status"], "provider_accepted")
        self.assertEqual(json.loads(second.getvalue())["status"], "already_requested")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(AuditEvent.objects.count(), 2)
        for event in AuditEvent.objects.all():
            self.assertEqual(event.entity_id, probe_id)
            self.assertIsNone(event.tenant_id)
            self.assertNotIn("operator@example.test", json.dumps(event.metadata))


class ReleaseProbeBoundaryTests(SimpleTestCase):
    @patch("scripts.render_start.subprocess.run")
    def test_normal_startup_never_sends_a_probe(self, run):
        optional_runtime_probe({})
        run.assert_not_called()

    @patch("scripts.render_start.subprocess.run")
    def test_probe_failure_cannot_block_startup_or_print_private_output(self, run):
        run.return_value = SimpleNamespace(
            stdout="private-provider-credential", returncode=1
        )
        output = io.StringIO()
        with patch("sys.stdout", output):
            optional_runtime_probe({"RUNTIME_ALERT_PROBE_ID": str(uuid.uuid4())})
        self.assertNotIn("private-provider-credential", output.getvalue())
        self.assertIn("startup continues", output.getvalue())
        run.side_effect = subprocess.TimeoutExpired("private-command", 30)
        with patch("sys.stdout", output):
            optional_runtime_probe({"RUNTIME_ALERT_PROBE_ID": str(uuid.uuid4())})
        self.assertNotIn("private-command", output.getvalue())

    @patch("scripts.render_start.subprocess.run")
    def test_success_uses_only_safe_status_and_public_correlation_id(self, run):
        probe_id = uuid.uuid4()
        run.return_value = SimpleNamespace(
            stdout=json.dumps({"status": "provider_accepted", "private": "secret"}),
            returncode=0,
        )
        output = io.StringIO()
        with patch("sys.stdout", output):
            optional_runtime_probe({"RUNTIME_ALERT_PROBE_ID": str(probe_id)})
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "runtime_alert_probe": "provider_accepted",
                "request_id": probe_id.hex,
            },
        )
        self.assertNotIn("secret", output.getvalue())
