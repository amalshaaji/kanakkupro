"""Isolated HTTP acceptance journey. Mail stays in memory; no live data is used."""

import io
import re
import uuid
from decimal import Decimal

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.sales.models import Invoice
from apps.sales.selectors import financial_summary
from apps.sales.services import today_for
from apps.tenants.models import Tenant, TenantMembership


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PilotAcceptanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)

    def post(self, client, url, values):
        response = client.post(
            url, {**values, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
        )
        self.assertEqual(
            response.status_code,
            302,
            str(response.context["form"].errors)
            if response.context and "form" in response.context
            else "",
        )
        return response

    def signup(self, client, email):
        client.get(reverse("account_signup"))
        password = "Quartz-Cedar-Lantern-53!"
        self.post(
            client,
            reverse("account_signup"),
            {"email": email, "password1": password, "password2": password},
        )
        user = get_user_model().objects.get(email=email)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        token = re.search(
            r"/accounts/confirm-email/([^/\s]+)", mail.outbox[-1].body
        ).group(1)
        url = reverse("account_confirm_email", args=[token])
        client.get(url)
        self.post(client, url, {})
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        client.get(reverse("account_login"))
        self.post(
            client, reverse("account_login"), {"login": email, "password": password}
        )
        return user

    def journey(self):
        owner = self.signup(self.client, "pilot-owner@example.test")
        self.post(
            self.client,
            reverse("tenants:create"),
            {
                "name": "Acceptance business",
                "country": "IN",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
            },
        )
        tenant = Tenant.objects.get(name="Acceptance business")
        self.assertTrue(
            TenantMembership.objects.filter(
                tenant=tenant, user=owner, role="owner"
            ).exists()
        )
        self.post(
            self.client,
            reverse("customers:create"),
            {
                "name": "Pilot customer",
                "country": "IN",
                "billing_address": "12 River Road, Mumbai 400001",
            },
        )
        customer = Customer.objects.get(tenant=tenant)
        self.post(
            self.client,
            reverse("catalog:create"),
            {
                "name": "Pilot consulting",
                "kind": "service",
                "unit": "hour",
                "price": "100",
                "hsn_sac": "998314",
                "tax_treatment": "taxable",
                "tax_rate": "18",
            },
        )
        item = CatalogItem.objects.get(tenant=tenant)
        self.post(
            self.client,
            reverse("sales:settings"),
            {
                "legal_name": "Acceptance business",
                "address": "1 Main Road, Mumbai 400001",
                "gstin": "27AAPFU0939F1ZV",
                "state_code": "27",
                "signatory": "Test operator",
                "payment_instructions": "Synthetic test only",
                "regular_seller": "on",
            },
        )
        today = today_for(tenant).isoformat()
        self.post(
            self.client,
            reverse("sales:create"),
            {
                "key": str(uuid.uuid4()),
                "customer": str(customer.pk),
                "issue_date": today,
                "due_date": today,
                "buyer_state": "27",
                "place_of_supply": "27",
                "supply_type": "intra_state",
                "delivery_address": customer.billing_address,
                "supported_supply": "on",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "1",
                "lines-MAX_NUM_FORMS": "100",
                "lines-0-item": str(item.pk),
                "lines-0-quantity": "1",
                "lines-0-unit_price": "100",
                "lines-0-discount": "0",
            },
        )
        invoice = Invoice.objects.get(tenant=tenant)
        self.post(
            self.client,
            reverse("sales:issue", args=[invoice.pk]),
            {"key": str(uuid.uuid4()), "revision": invoice.revision},
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("118.00"))
        payment_url = reverse("payments:record", args=[invoice.pk])
        self.post(
            self.client,
            payment_url,
            {"key": str(uuid.uuid4()), "amount": "50", "date": today, "method": "bank"},
        )
        self.assertEqual(financial_summary(tenant)["receivables"], Decimal("68.00"))
        self.post(
            self.client,
            payment_url,
            {"key": str(uuid.uuid4()), "amount": "68", "date": today, "method": "bank"},
        )
        summary = financial_summary(tenant)
        self.assertEqual(summary["receipts"], Decimal("118.00"))
        self.assertEqual(summary["receivables"], Decimal("0.00"))
        report = self.client.get(reverse("reports:financial"))
        self.assertEqual(report.context["period_sales"], Decimal("118.00"))
        self.assertEqual(report.context["period_net_receipts"], Decimal("118.00"))
        guide = self.client.get(reverse("dashboard:pilot"))
        self.assertEqual(guide.context["completed"], 7)
        self.assertContains(guide, "Preparation mode")
        with self.captureOnCommitCallbacks(execute=True):
            self.post(
                self.client,
                reverse("tenants:team"),
                {"email": "pilot-viewer@example.test", "role": "viewer"},
            )
        invitation = re.search(
            r"/tenants/invitations/accept/([^/\s]+)", mail.outbox[-1].body
        ).group(1)
        viewer = Client(enforce_csrf_checks=True)
        self.signup(viewer, "pilot-viewer@example.test")
        accept_url = reverse("tenants:accept_invitation", args=[invitation])
        viewer.get(accept_url)
        self.post(viewer, accept_url, {})
        self.assertEqual(
            viewer.post(
                reverse("customers:create"),
                {
                    "name": "Denied",
                    "csrfmiddlewaretoken": viewer.cookies["csrftoken"].value,
                },
            ).status_code,
            403,
        )
        unrelated = Tenant.objects.create(name="Unrelated", slug="unrelated-acceptance")
        hidden = Customer.objects.create(
            tenant=unrelated, created_by=owner, name="Private other business"
        )
        self.assertEqual(
            self.client.get(reverse("customers:detail", args=[hidden.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("tenants:switch"),
                {
                    "tenant_id": str(unrelated.pk),
                    "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value,
                },
            ).status_code,
            404,
        )
        return invoice

    def test_owner_to_payment_acceptance(self):
        self.journey()

    def test_acceptance_pdf_matches_issued_invoice(self):
        invoice = self.journey()
        response = self.client.get(reverse("sales:pdf", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("no-store", response["Cache-Control"])
        text = "\n".join(
            page.extract_text()
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        self.assertIn(invoice.number, text)
        self.assertIn("Pilot customer", text)
        self.assertIn("118.00", text)
