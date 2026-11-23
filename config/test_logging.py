import json
import logging
from unittest import TestCase

from config.logging import RequestContextFilter, SafeJsonFormatter


class StructuredLoggingTests(TestCase):
    def test_framework_log_message_does_not_emit_unsafe_message_text(self):
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            12,
            "Failed path: %s",
            ("/tenants/invitations/secret-token/",),
            None,
        )
        RequestContextFilter().filter(record)

        payload = json.loads(SafeJsonFormatter().format(record))

        self.assertEqual(payload["message"], "framework_log")
        self.assertNotIn("secret-token", json.dumps(payload))
        self.assertIn("timestamp", payload)
        self.assertIn("environment", payload)
