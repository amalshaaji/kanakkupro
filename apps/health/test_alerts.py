import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import Client, SimpleTestCase, override_settings
from django.urls import path

from apps.health.alerts import RuntimeAlertHandler, notify_runtime_error
from apps.health.checks import check_runtime_alert_configuration


def failing_view(request):
    raise ValueError("private-exception-message")


def unavailable_view(request):
    return HttpResponse("unavailable", status=503)


urlpatterns = [path("broken/", failing_view), path("unavailable/", unavailable_view)]


@override_settings(
    RUNTIME_ALERTS_ENABLED=True,
    RUNTIME_ALERT_EMAILS=["operator@example.test"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RuntimeAlertTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        mail.get_connection()
        mail.outbox.clear()

    def record(self):
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            "/private/source.py",
            22,
            "customer@example.test private-password %s",
            ("private-token",),
            (ValueError, ValueError("private-value"), None),
        )
        record.request_id = "a" * 32
        record.status_code = 500
        record.request = {"Authorization": "Bearer private-credential"}
        record.tenant_id = "private-business-id"
        return record

    def test_only_allowlisted_metadata_reaches_operator(self):
        self.assertEqual(notify_runtime_error(self.record()), "provider_accepted")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        event = json.loads(message.body)
        self.assertEqual(event["exception_type"], "ValueError")
        self.assertEqual(event["request_id"], "a" * 32)
        self.assertEqual(event["http_status"], 500)
        self.assertEqual(message.to, ["operator@example.test"])
        for private in (
            "private-",
            "customer@example.test",
            "/private/source.py",
            "Authorization",
        ):
            self.assertNotIn(private, message.subject + message.body)

    def test_untrusted_request_id_and_environment_are_removed(self):
        record = self.record()
        record.request_id = "private-request-token"
        with override_settings(DEPLOYMENT_ENVIRONMENT="private-environment"):
            notify_runtime_error(record)
        event = json.loads(mail.outbox[0].body)
        self.assertEqual(event["request_id"], "-")
        self.assertEqual(event["environment"], "unknown")

    def test_concurrent_errors_share_one_global_throttle(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(
                workers.map(lambda _: notify_runtime_error(self.record()), range(8))
            )
        self.assertEqual(results.count("provider_accepted"), 1)
        self.assertEqual(results.count("throttled"), 7)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(RUNTIME_ALERTS_ENABLED=False)
    @patch("apps.health.alerts.get_connection")
    def test_disabled_alerts_never_touch_cache_or_transport(self, transport):
        with patch("apps.health.alerts.cache.add") as add:
            self.assertEqual(notify_runtime_error(self.record()), "disabled")
        add.assert_not_called()
        transport.assert_not_called()

    @patch("apps.health.alerts.get_connection")
    def test_cache_outage_never_sends_unthrottled_alerts(self, transport):
        with patch("apps.health.alerts.cache.add", side_effect=RuntimeError("private")):
            self.assertEqual(notify_runtime_error(self.record()), "unavailable")
        transport.assert_not_called()

    @patch("apps.health.alerts.get_connection")
    def test_delivery_failure_is_sanitized_and_throttled(self, transport):
        transport.side_effect = RuntimeError("private-provider-credential")
        with self.assertLogs(
            "kanakkupro.runtime_alert_delivery", level="WARNING"
        ) as logs:
            self.assertEqual(notify_runtime_error(self.record()), "unavailable")
        self.assertNotIn("private-provider-credential", "".join(logs.output))
        self.assertEqual(notify_runtime_error(self.record()), "throttled")
        transport.assert_called_once()

    def test_operator_probe_never_claims_inbox_delivery(self):
        output = io.StringIO()
        call_command("send_runtime_alert_test", send=True, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "provider_accepted")
        self.assertFalse(result["inbox_delivery_verified"])
        self.assertEqual(json.loads(mail.outbox[0].body)["event"], "operator_test")
        with self.assertRaises(CommandError):
            call_command("send_runtime_alert_test", send=True, stdout=io.StringIO())

    def test_enabled_invalid_configuration_fails_deployment_check(self):
        with override_settings(RUNTIME_ALERT_EMAILS=[]):
            self.assertEqual(
                check_runtime_alert_configuration(None)[0].id, "health.E001"
            )
        with override_settings(RUNTIME_ALERT_EMAILS=["private-invalid"]):
            result = check_runtime_alert_configuration(None)
        self.assertNotIn("private-invalid", str(result))

    @override_settings(ROOT_URLCONF=__name__)
    def test_real_500_response_alert_excludes_request_and_exception_payloads(self):
        response = Client(raise_request_exception=False).get(
            "/broken/?password=private-password",
            HTTP_AUTHORIZATION="Bearer private-auth-token",
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(mail.outbox), 1)
        event = json.loads(mail.outbox[0].body)
        self.assertEqual(event["request_id"], response["X-Request-ID"])
        self.assertEqual(event["exception_type"], "ValueError")
        self.assertNotIn("private-", mail.outbox[0].body)

    @override_settings(ROOT_URLCONF=__name__)
    def test_handled_dependency_503_is_alerted_too(self):
        response = self.client.get("/unavailable/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(mail.outbox[0].body)["http_status"], 503)

    @patch(
        "apps.health.alerts.notify_runtime_error", side_effect=RuntimeError("private")
    )
    def test_unexpected_alert_error_never_replaces_application_failure(self, notify):
        RuntimeAlertHandler().emit(self.record())
