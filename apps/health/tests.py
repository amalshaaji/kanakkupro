import json
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase

from apps.health.views import live, ready


class HealthCheckTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/health/")
        self.request.request_id = "request-id-123"

    @patch("apps.health.views.connection")
    def test_liveness_does_not_depend_on_database(self, database):
        response = live(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {"status": "ok", "request_id": "request-id-123"},
        )
        database.cursor.assert_not_called()

    @patch("apps.health.views.connection")
    def test_readiness_requires_database_query(self, database):
        cursor = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = cursor
        database.cursor.return_value = context_manager
        cursor.fetchone.return_value = (1,)

        response = ready(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["status"], "ok")
        cursor.execute.assert_called_once_with("SELECT 1")

    @patch("apps.health.views.connection")
    def test_readiness_hides_database_error_details(self, database):
        database.cursor.side_effect = OperationalError("secret")
        response = ready(self.request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["status"], "unavailable")
        self.assertNotIn("secret", response.content.decode())
