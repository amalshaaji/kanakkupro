import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.payments.services import reverse_payment
from apps.reports.financial import financial_report
from apps.sales.test_workflow import FinancialFixtures
from apps.tenants.models import Tenant


class FinancialReportTests(FinancialFixtures, TestCase):
    def test_sales_and_receipts_reconcile_with_corrections(self):
        invoice = self.issue()
        payment = self.pay(invoice, "50")
        self.issue(self.note(invoice))
        report = financial_report(self.tenant, {})
        self.assertEqual(report["period_sales"], Decimal("88.50"))
        self.assertEqual(report["period_net_receipts"], Decimal("50.00"))
        self.assertEqual(list(report["customer_sales"])[0]["total"], Decimal("88.50"))
        reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=payment.pk,
            reason="Duplicate",
            date=self.today,
            key=uuid.uuid4(),
        )
        report = financial_report(self.tenant, {})
        self.assertEqual(report["period_net_receipts"], Decimal("0.00"))
        self.assertEqual(report["reversals"].count(), 1)

    def test_reversal_in_later_period_does_not_erase_earlier_receipt(self):
        invoice = self.issue()
        payment = self.pay(invoice, "50")
        later = self.today + timedelta(days=1)
        # Service rejects future dates; freeze its business clock for this scenario.
        from unittest.mock import patch

        with patch("apps.payments.services.today_for", return_value=later):
            reverse_payment(
                tenant=self.tenant,
                actor=self.owner,
                payment_id=payment.pk,
                reason="Correction",
                date=later,
                key=uuid.uuid4(),
            )
        early = financial_report(self.tenant, {"end": self.today})
        late = financial_report(self.tenant, {"start": later})
        self.assertEqual(early["period_net_receipts"], Decimal("50.00"))
        self.assertEqual(late["period_net_receipts"], Decimal("-50.00"))

    def test_report_is_scoped_and_rejects_invalid_dates(self):
        self.issue()
        other = Tenant.objects.create(name="Other", slug="other-report")
        self.assertEqual(financial_report(other, {})["documents"].count(), 0)
        self.assertEqual(
            self.client.get(reverse("reports:financial"), {"start": "bad"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                reverse("reports:financial"),
                {"start": "2026-11-02", "end": "2026-11-01"},
            ).status_code,
            400,
        )
        response = self.client.get(reverse("reports:financial"))
        self.assertContains(response, "Payment history")
        self.assertContains(response, "Aster Labs")

    def test_report_ignores_forged_tenant_and_filters_dates(self):
        self.issue()
        response = self.client.get(
            reverse("reports:financial"),
            {
                "start": (self.today + timedelta(days=1)).isoformat(),
                "tenant_id": "forged",
            },
        )
        self.assertEqual(response.context["period_sales"], Decimal("0.00"))
        self.assertNotContains(response, "Aster Labs")

    def test_report_queries_remain_bounded_as_records_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.issue()
        with CaptureQueriesContext(connection) as one:
            self.client.get(reverse("reports:financial"))
        for _ in range(25):
            self.issue()
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(reverse("reports:financial"))
        self.assertEqual(len(one), len(many))
        self.assertContains(response, "dpage=2")
        self.assertEqual(len(response.context["documents"]), 25)

    def test_export_dates_and_permissions(self):
        self.issue()
        response = self.client.get(reverse("reports:export_financial"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("118.00", b"".join(response.streaming_content).decode())
        self.membership.role = "viewer"
        self.membership.save(update_fields=["role"])
        self.assertEqual(
            self.client.get(reverse("reports:export_financial")).status_code, 403
        )
        self.membership.status = "revoked"
        self.membership.save(update_fields=["status"])
        self.assertNotEqual(
            self.client.get(reverse("reports:financial")).status_code, 200
        )
