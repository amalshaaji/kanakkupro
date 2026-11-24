from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.sales.test_workflow import FinancialFixtures


class FinancialReadScalingTests(FinancialFixtures, TestCase):
    def query_count(self, route):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse(route))
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_invoice_list_and_dashboard_do_not_add_queries_per_invoice(self):
        self.issue()
        baseline = {
            route: self.query_count(route)
            for route in ("sales:list", "dashboard:index")
        }
        for _ in range(24):
            self.issue()
        for route, expected in baseline.items():
            with self.subTest(route=route):
                self.assertEqual(self.query_count(route), expected)
