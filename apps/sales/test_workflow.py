import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from pypdf import PdfReader

from apps.audit.models import AuditEvent
from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.payments.models import Payment, PaymentReversal
from apps.payments.services import record_payment, reverse_payment
from apps.sales.models import FinancialCommand, Invoice, InvoiceLine, InvoiceSequence
from apps.sales.pdf import deny_resource_fetch, render_invoice_pdf
from apps.sales.selectors import financial_summary, invoice_financials
from apps.sales.services import (
    issue_invoice,
    save_draft,
    save_seller_profile,
    today_for,
)
from apps.tenants.models import Tenant, TenantMembership


class FinancialFixtures:
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner@example.com")
        self.tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        self.membership = TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role="owner"
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Aster Labs",
            country="IN",
            billing_address="12 River Road, Mumbai, Maharashtra 400001",
        )
        self.item = CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Consulting",
            kind="service",
            unit="hour",
            price=Decimal("100"),
            hsn_sac="998314",
            tax_treatment="taxable",
            tax_rate=Decimal("18"),
        )
        self.today = today_for(self.tenant)
        self.profile = save_seller_profile(
            tenant=self.tenant,
            actor=self.owner,
            values={
                "legal_name": "Northwind Pvt Ltd",
                "address": "1 Main Road, Mumbai 400001",
                "gstin": "27AAPFU0939F1ZV",
                "state_code": "27",
                "payment_instructions": "Use invoice number as reference.",
                "signatory": "Finance manager",
            },
        )
        self.client.force_login(self.owner)

    def header(self, **overrides):
        return {
            "customer_id": self.customer.pk,
            "kind": "invoice",
            "issue_date": self.today,
            "due_date": self.today,
            "buyer_gstin": "",
            "buyer_state": "27",
            "place_of_supply": "27",
            "supply_type": "intra_state",
            "delivery_address": self.customer.billing_address,
            "supported_supply": True,
            **overrides,
        }

    def line(self, **overrides):
        return {
            "item_id": self.item.pk,
            "quantity": "1",
            "unit_price": "100",
            "discount": "0",
            **overrides,
        }

    def draft(self, *, data=None, lines=None, key=None):
        return save_draft(
            tenant=self.tenant,
            actor=self.owner,
            data=data or self.header(),
            lines=lines or [self.line()],
            key=key or uuid.uuid4(),
        )

    def issue(self, invoice=None, key=None):
        invoice = invoice or self.draft()
        return issue_invoice(
            tenant=self.tenant,
            actor=self.owner,
            invoice_id=invoice.pk,
            revision=invoice.revision,
            key=key or uuid.uuid4(),
        )

    def pay(self, invoice, amount="50.00", key=None):
        return record_payment(
            tenant=self.tenant,
            actor=self.owner,
            invoice_id=invoice.pk,
            values={
                "amount": amount,
                "date": self.today,
                "method": "bank",
                "reference": "test-reference",
            },
            key=key or uuid.uuid4(),
        )

    def note(self, parent, kind="credit_note", quantity="0.25"):
        line = self.line(quantity=quantity)
        if kind == "credit_note":
            line["source_line_id"] = parent.lines.first().pk
        return self.draft(
            data=self.header(kind=kind, parent_id=parent.pk, reason="Price correction"),
            lines=[line],
        )


class InvoiceWorkflowTests(FinancialFixtures, TestCase):
    def test_html_draft_issue_and_payment_flow_ignores_forged_totals(self):
        payload = {
            "key": str(uuid.uuid4()),
            "customer": str(self.customer.pk),
            "issue_date": self.today.isoformat(),
            "due_date": self.today.isoformat(),
            "buyer_state": "27",
            "place_of_supply": "27",
            "supply_type": "intra_state",
            "delivery_address": self.customer.billing_address,
            "supported_supply": "on",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "1",
            "lines-MAX_NUM_FORMS": "100",
            "lines-0-item": str(self.item.pk),
            "lines-0-quantity": "1",
            "lines-0-unit_price": "100",
            "lines-0-discount": "0",
            "total": "1.00",
            "tenant_id": str(uuid.uuid4()),
        }
        response = self.client.post(reverse("sales:create"), payload)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.total, Decimal("118"))
        self.client.post(
            reverse("sales:issue", kwargs={"invoice_id": invoice.pk}),
            {"key": str(uuid.uuid4()), "revision": 1},
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "issued")
        response = self.client.post(
            reverse("payments:record", kwargs={"invoice_id": invoice.pk}),
            {
                "key": str(uuid.uuid4()),
                "amount": "50",
                "date": self.today.isoformat(),
                "method": "bank",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(invoice_financials(invoice)["outstanding"], Decimal("68"))

    def test_formset_limits_prevent_unbounded_line_creation(self):
        response = self.client.post(
            reverse("sales:create"),
            {
                "key": str(uuid.uuid4()),
                "lines-TOTAL_FORMS": "1000000",
                "lines-INITIAL_FORMS": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["line_forms"].non_form_errors())
        self.assertEqual(Invoice.objects.count(), 0)

    def test_invoice_list_settings_and_draft_pages_render(self):
        for route in ("sales:list", "sales:create", "sales:settings"):
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        response = self.client.get(
            reverse("sales:create"), {"kind": "credit_note", "parent": "invalid"}
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_and_csrf_protection(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("sales:list")).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("sales:create"), {}).status_code, 403)

    def test_fiscal_year_series_resets_without_reusing_numbers(self):
        from datetime import date

        march = self.issue(self.draft(data=self.header(issue_date=date(2026, 3, 31))))
        april = self.issue(self.draft(data=self.header(issue_date=date(2026, 4, 1))))
        self.assertEqual(march.number, "KP/25-26/000001")
        self.assertEqual(april.number, "KP/26-27/000001")
        with self.assertRaises(ValidationError):
            self.issue(self.draft(data=self.header(issue_date=date(2026, 3, 30))))

    def test_draft_and_payment_audit_failures_roll_back(self):
        with patch("apps.sales.services.record_event", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.draft()
        self.assertEqual(Invoice.objects.count(), 0)
        invoice = self.issue()
        with patch("apps.payments.services.record_event", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.pay(invoice)
        self.assertEqual(Payment.objects.count(), 0)

    def test_billing_scope_and_profile_validation(self):
        for data in (
            self.header(buyer_gstin="27AAPFU0939F1Z0"),
            self.header(issue_date=self.today + timedelta(days=1)),
        ):
            with self.assertRaises(ValidationError):
                self.draft(data=data)
        Customer.objects.filter(pk=self.customer.pk).update(billing_address="")
        with self.assertRaises(ValidationError):
            self.issue()

    def test_exempt_supply_uses_bill_of_supply_pdf(self):
        CatalogItem.objects.filter(pk=self.item.pk).update(
            tax_treatment="exempt", tax_rate=0
        )
        invoice = self.issue()
        pdf = PdfReader(io.BytesIO(render_invoice_pdf(invoice)))
        self.assertIn("Bill of supply", pdf.pages[0].extract_text())
        self.assertEqual(len(pdf.pages), 1)
        self.assertEqual(invoice.tax_total, 0)

    def test_staff_cannot_edit_or_issue_correction_notes(self):
        invoice = self.issue()
        note = self.note(invoice)
        self.membership.role = "staff"
        self.membership.save()
        self.assertEqual(
            self.client.get(
                reverse("sales:update", kwargs={"invoice_id": note.pk})
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            self.issue(note)

    def test_draft_discount_tax_and_issue_number(self):
        draft = self.draft(
            lines=[self.line(quantity="2", unit_price="125.1234", discount="10")]
        )
        self.assertEqual(draft.taxable_total, Decimal("240.25"))
        self.assertEqual(draft.cgst, Decimal("21.62"))
        self.assertEqual(draft.sgst, Decimal("21.62"))
        self.assertEqual(draft.total, Decimal("283.49"))
        self.assertIsNone(draft.number)
        issued = self.issue(draft)
        self.assertRegex(issued.number, r"^KP/\d{2}-\d{2}/000001$")
        self.assertEqual(len(issued.number), 15)
        self.assertEqual(issued.seller_snapshot["gstin"], self.profile.gstin)
        self.assertEqual(issued.buyer_snapshot["name"], "Aster Labs")

    def test_create_and_issue_retries_are_idempotent(self):
        create_key, issue_key = uuid.uuid4(), uuid.uuid4()
        first = self.draft(key=create_key)
        self.assertEqual(self.draft(key=create_key).pk, first.pk)
        self.issue(first, issue_key)
        self.issue(first, issue_key)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoiceSequence.objects.get().next_number, 2)
        self.assertEqual(AuditEvent.objects.filter(action="invoice.issued").count(), 1)
        with self.assertRaises(ValidationError):
            self.draft(key=create_key, lines=[self.line(quantity="2")])

    def test_draft_edit_detects_stale_revision_and_preserves_issued_details(self):
        invoice = self.draft()
        updated = save_draft(
            tenant=self.tenant,
            actor=self.owner,
            invoice_id=invoice.pk,
            revision=1,
            data=self.header(),
            lines=[self.line(unit_price="200")],
            key=uuid.uuid4(),
        )
        self.assertEqual(updated.revision, 2)
        with self.assertRaises(ValidationError):
            save_draft(
                tenant=self.tenant,
                actor=self.owner,
                invoice_id=invoice.pk,
                revision=1,
                data=self.header(),
                lines=[self.line()],
                key=uuid.uuid4(),
            )
        self.issue(updated)
        with self.assertRaises(ValidationError):
            save_draft(
                tenant=self.tenant,
                actor=self.owner,
                invoice_id=invoice.pk,
                revision=2,
                data=self.header(),
                lines=[self.line()],
                key=uuid.uuid4(),
            )

    def test_historical_customer_catalog_and_seller_snapshots_are_stable(self):
        invoice = self.issue()
        Customer.objects.filter(pk=self.customer.pk).update(
            name="Changed", billing_address="Different address"
        )
        CatalogItem.objects.filter(pk=self.item.pk).update(
            name="Changed item", price=Decimal("999"), tax_rate=Decimal("5")
        )
        self.profile.legal_name = "Changed seller"
        self.profile.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.buyer_snapshot["name"], "Aster Labs")
        self.assertEqual(invoice.seller_snapshot["legal_name"], "Northwind Pvt Ltd")
        self.assertEqual(invoice.lines.get().description, "Consulting")
        self.assertEqual(invoice.total, Decimal("118.00"))

    def test_interstate_igst_requires_explicit_place_of_supply(self):
        invoice = self.issue(
            self.draft(
                data=self.header(place_of_supply="32", supply_type="inter_state")
            )
        )
        self.assertEqual(invoice.igst, Decimal("18"))
        self.assertEqual(invoice.cgst, 0)
        with self.assertRaises(ValidationError):
            self.issue(self.draft(data=self.header(place_of_supply="32")))

    def test_invalid_financial_inputs_and_forged_ids_are_rejected(self):
        other = Tenant.objects.create(name="Other", slug="other")
        hidden_customer = Customer.objects.create(
            tenant=other, created_by=self.owner, name="Hidden"
        )
        hidden_item = CatalogItem.objects.create(
            tenant=other, created_by=self.owner, name="Hidden", kind="service"
        )
        for line in (
            self.line(quantity="-1"),
            self.line(unit_price=1.5),
            self.line(unit_price="NaN"),
            self.line(discount="101"),
            self.line(item_id=hidden_item.pk),
        ):
            with self.subTest(line=line), self.assertRaises(ValidationError):
                self.draft(lines=[line])
        with self.assertRaises(ValidationError):
            self.draft(data=self.header(customer_id=hidden_customer.pk))
        with self.assertRaises(ValidationError):
            self.draft(data=self.header(supported_supply=False))
        self.assertEqual(Invoice.objects.count(), 0)

    def test_issuance_and_sequence_roll_back_when_audit_fails(self):
        draft = self.draft()
        with patch("apps.sales.services.record_event", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.issue(draft)
        draft.refresh_from_db()
        self.assertTrue(draft.is_draft)
        self.assertFalse(InvoiceSequence.objects.exists())
        self.assertEqual(FinancialCommand.objects.count(), 1)

    def test_database_rejects_issued_document_and_line_mutation_or_deletion(self):
        invoice = self.issue()
        for statement, params in (
            ("UPDATE sales_invoice SET notes='tamper' WHERE id=%s", [invoice.pk]),
            ("DELETE FROM sales_invoice WHERE id=%s", [invoice.pk]),
            (
                "UPDATE sales_invoiceline SET description='tamper' WHERE invoice_id=%s",
                [invoice.pk],
            ),
            ("DELETE FROM sales_invoiceline WHERE invoice_id=%s", [invoice.pk]),
        ):
            with (
                self.subTest(statement=statement),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                with connection.cursor() as cursor:
                    cursor.execute(statement, params)

    def test_database_rejects_cross_tenant_customer_and_line_references(self):
        draft = self.draft()
        other = Tenant.objects.create(name="Other", slug="other")
        hidden = Customer.objects.create(
            tenant=other, created_by=self.owner, name="Hidden"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.objects.filter(pk=draft.pk).update(customer=hidden)
        with self.assertRaises(IntegrityError), transaction.atomic():
            InvoiceLine.objects.filter(invoice=draft).update(tenant=other)

    def test_viewer_and_revoked_membership_cannot_write(self):
        self.membership.role = "viewer"
        self.membership.save()
        self.assertEqual(self.client.post(reverse("sales:create")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.draft()
        self.membership.role, self.membership.status = "owner", "inactive"
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            self.draft()

    def test_cross_tenant_invoice_and_pdf_are_hidden(self):
        invoice = self.issue()
        other_user = get_user_model().objects.create_user("other@example.com")
        other = Tenant.objects.create(name="Other", slug="other")
        TenantMembership.objects.create(tenant=other, user=other_user, role="owner")
        self.client.force_login(other_user)
        for route in ("sales:detail", "sales:update", "sales:pdf", "sales:issue"):
            url = reverse(route, kwargs={"invoice_id": invoice.pk})
            response = (
                self.client.post(url)
                if route == "sales:issue"
                else self.client.get(url)
            )
            self.assertEqual(response.status_code, 404)

    def test_pdf_contains_stored_totals_and_blocks_resource_fetches(self):
        invoice = self.issue()
        response = self.client.get(
            reverse("sales:pdf", kwargs={"invoice_id": invoice.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        text = " ".join(
            page.extract_text()
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        for expected in (
            invoice.number,
            "Aster Labs",
            "Northwind Pvt Ltd",
            "118.00",
            "998314",
        ):
            self.assertIn(expected, text)
        for url in (
            "https://example.com",
            "http://127.0.0.1/",
            "file:///etc/passwd",
            "data:text/plain,secret",
        ):
            with self.assertRaises(ValueError):
                deny_resource_fetch(url)

    def test_pdf_handles_multiple_pages_and_repeats_headers(self):
        invoice = self.issue(
            self.draft(
                lines=[self.line(description=f"Consulting line {n}") for n in range(70)]
            )
        )
        pdf = PdfReader(io.BytesIO(render_invoice_pdf(invoice)))
        self.assertGreater(len(pdf.pages), 1)
        self.assertIn("Description", pdf.pages[1].extract_text())
        self.assertIn("8260.00", " ".join(page.extract_text() for page in pdf.pages))

    def test_mixed_exempt_and_taxable_document_cannot_be_issued(self):
        exempt = CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Exempt",
            kind="service",
            unit="hour",
            price=10,
            hsn_sac="998314",
            tax_treatment="exempt",
            tax_rate=0,
        )
        with self.assertRaises(ValidationError):
            self.issue(self.draft(lines=[self.line(), self.line(item_id=exempt.pk)]))


class PaymentWorkflowTests(FinancialFixtures, TestCase):
    def test_cross_tenant_payment_reversal_and_summary_isolation(self):
        invoice = self.issue()
        payment = self.pay(invoice)
        other = Tenant.objects.create(name="Other", slug="other")
        other_user = get_user_model().objects.create_user("other@example.com")
        TenantMembership.objects.create(tenant=other, user=other_user, role="owner")
        with self.assertRaises(Payment.DoesNotExist):
            reverse_payment(
                tenant=other,
                actor=other_user,
                payment_id=payment.pk,
                reason="Forged",
                date=self.today,
                key=uuid.uuid4(),
            )
        self.assertEqual(financial_summary(other)["invoiced"], 0)
        self.assertEqual(financial_summary(other)["receipts"], 0)
        self.client.force_login(other_user)
        self.assertEqual(
            self.client.get(
                reverse("payments:reverse", kwargs={"payment_id": payment.pk})
            ).status_code,
            404,
        )

    def test_database_blocks_oversized_and_cross_tenant_payments(self):
        invoice = self.issue()
        other = Tenant.objects.create(name="Other", slug="other")
        for tenant, amount in ((self.tenant, Decimal("119")), (other, Decimal("1"))):
            with (
                self.subTest(tenant=tenant),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                Payment.objects.create(
                    tenant=tenant,
                    invoice=invoice,
                    amount=amount,
                    date=self.today,
                    method="cash",
                    created_by=self.owner,
                )

    def test_payment_reversal_requires_reason_and_preserves_ledger(self):
        payment = self.pay(self.issue())
        with self.assertRaises(ValidationError):
            reverse_payment(
                tenant=self.tenant,
                actor=self.owner,
                payment_id=payment.pk,
                reason=" ",
                date=self.today,
                key=uuid.uuid4(),
            )
        self.assertEqual(PaymentReversal.objects.count(), 0)

    def test_partial_final_and_reversed_payments_reconcile(self):
        invoice = self.issue()
        first = self.pay(invoice)
        self.assertEqual(invoice_financials(invoice)["status"], "Partially paid")
        self.pay(invoice, "68.00")
        self.assertEqual(invoice_financials(invoice)["status"], "Paid")
        reversal_key = uuid.uuid4()
        reversal = reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=first.pk,
            reason="Wrong transfer",
            date=self.today,
            key=reversal_key,
        )
        retry = reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=first.pk,
            reason="Wrong transfer",
            date=self.today,
            key=reversal_key,
        )
        self.assertEqual(reversal.pk, retry.pk)
        self.assertEqual(invoice_financials(invoice)["outstanding"], Decimal("50"))
        totals = financial_summary(self.tenant)
        self.assertEqual(totals["invoiced"], Decimal("118"))
        self.assertEqual(totals["receipts"], Decimal("68"))
        self.assertEqual(totals["receivables"], Decimal("50"))

    def test_overpayments_invalid_amounts_dates_and_duplicate_keys(self):
        invoice = self.issue()
        key = uuid.uuid4()
        self.assertEqual(self.pay(invoice, key=key).pk, self.pay(invoice, key=key).pk)
        for amount in ("69", "0", "-1", "NaN", "1.001", 1.5):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.pay(invoice, amount)
        with self.assertRaises(ValidationError):
            self.pay(invoice, "51", key)
        with self.assertRaises(ValidationError):
            record_payment(
                tenant=self.tenant,
                actor=self.owner,
                invoice_id=invoice.pk,
                values={
                    "amount": "1",
                    "date": self.today + timedelta(days=1),
                    "method": "cash",
                },
                key=uuid.uuid4(),
            )
        self.assertEqual(Payment.objects.count(), 1)

    def test_payments_and_reversals_cannot_be_updated_or_deleted(self):
        payment = self.pay(self.issue())
        reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=payment.pk,
            reason="Error",
            date=self.today,
            key=uuid.uuid4(),
        )
        for table in ("payments_payment", "payments_paymentreversal"):
            for sql in (f"DELETE FROM {table}", f"UPDATE {table} SET date=date"):
                with (
                    self.subTest(sql=sql),
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        cursor.execute(sql)

    def test_staff_can_post_but_cannot_reverse(self):
        invoice = self.issue()
        self.membership.role = "staff"
        self.membership.save()
        payment = self.pay(invoice)
        with self.assertRaises(PermissionDenied):
            reverse_payment(
                tenant=self.tenant,
                actor=self.owner,
                payment_id=payment.pk,
                reason="Error",
                date=self.today,
                key=uuid.uuid4(),
            )

    def test_corrections_update_balance_without_editing_original(self):
        invoice = self.issue()
        credit = self.issue(self.note(invoice))
        self.assertEqual(credit.total, Decimal("29.50"))
        self.assertEqual(invoice_financials(invoice)["outstanding"], Decimal("88.50"))
        self.issue(self.note(invoice, kind="debit_note", quantity="0.5"))
        self.assertEqual(invoice_financials(invoice)["outstanding"], Decimal("147.50"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("118"))
        self.assertEqual(financial_summary(self.tenant)["invoiced"], Decimal("147.50"))

    def test_credit_cannot_exceed_original_line_or_unpaid_balance(self):
        invoice = self.issue()
        self.pay(invoice, "100")
        with self.assertRaises(ValidationError):
            self.issue(self.note(invoice))
        second = self.issue()
        self.issue(self.note(second, quantity="0.75"))
        with self.assertRaises(ValidationError):
            self.issue(self.note(second, quantity="0.5"))

    def test_dashboard_is_scoped_and_customer_has_invoice_history(self):
        invoice = self.issue()
        self.pay(invoice)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(
            response.context["financial_summary"]["receivables"], Decimal("68")
        )
        response = self.client.get(
            reverse("customers:detail", kwargs={"customer_id": self.customer.pk})
        )
        self.assertContains(response, invoice.number)


class FinancialConcurrencyTests(FinancialFixtures, TransactionTestCase):
    def concurrent(self, functions):
        barrier = Barrier(len(functions))

        def worker(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(worker, functions))

    def test_concurrent_issuance_has_unique_consecutive_numbers(self):
        drafts = [self.draft(), self.draft()]
        numbers = self.concurrent(
            [lambda draft=draft: self.issue(draft).number for draft in drafts]
        )
        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(
            sorted(number[-6:] for number in numbers), ["000001", "000002"]
        )

    def test_concurrent_payments_cannot_overpay(self):
        invoice = self.issue()

        def pay():
            try:
                self.pay(invoice, "80")
                return True
            except ValidationError:
                return False

        self.assertEqual(sorted(self.concurrent([pay, pay])), [False, True])
        self.assertEqual(invoice_financials(invoice)["outstanding"], Decimal("38"))

    def test_concurrent_duplicate_payment_posts_once(self):
        invoice, key = self.issue(), uuid.uuid4()
        ids = self.concurrent([lambda: self.pay(invoice, key=key).pk] * 2)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Payment.objects.count(), 1)
