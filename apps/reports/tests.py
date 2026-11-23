import csv
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.tenants.models import Tenant, TenantMembership


class OperationalReportTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        self.tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantMembership.Role.OWNER
        )
        self.assertTrue(
            self.client.login(email=self.owner.email, password="correct-horse")
        )

    def test_report_counts_are_scoped_to_the_active_tenant(self):
        Customer.objects.create(
            tenant=self.tenant, created_by=self.owner, name="Northwind Customer"
        )
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        Customer.objects.create(
            tenant=other_tenant, created_by=self.owner, name="Other Customer"
        )
        CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Consulting",
            kind=CatalogItem.Kind.SERVICE,
        )

        response = self.client.get(reverse("reports:home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Other Customer")
        self.assertEqual(response.context["customer_counts"]["total"], 1)
        self.assertEqual(response.context["catalog_counts"]["total"], 1)

    def test_customer_csv_export_is_tenant_scoped(self):
        Customer.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="=SUM(1,1)",
            email="customer@example.com",
        )
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        Customer.objects.create(
            tenant=other_tenant,
            created_by=self.owner,
            name="Other Customer",
            email="other@example.com",
        )

        response = self.client.get(reverse("reports:export_customers"))
        data = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("'=SUM(1,1)", data)
        self.assertIn("customer@example.com", data)
        self.assertNotIn("Other Customer", data)

    def test_viewer_can_open_reports_but_cannot_export(self):
        viewer = get_user_model().objects.create_user(
            "viewer@example.com", password="correct-horse"
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=viewer, role=TenantMembership.Role.VIEWER
        )
        self.client.logout()
        self.assertTrue(self.client.login(email=viewer.email, password="correct-horse"))

        report = self.client.get(reverse("reports:home"))
        export = self.client.get(reverse("reports:export_customers"))

        self.assertEqual(report.status_code, 200)
        self.assertContains(
            report, "Exports are available to Owners, Admins, and Managers."
        )
        self.assertEqual(export.status_code, 403)

    def test_catalog_csv_preserves_financial_precision_and_tenant_scope(self):
        CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Taxable service",
            kind=CatalogItem.Kind.SERVICE,
            price=Decimal("1250.1234"),
            hsn_sac="998314",
            tax_treatment=CatalogItem.TaxTreatment.TAXABLE,
            tax_rate=Decimal("18.0000"),
        )
        CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Legacy service",
            kind=CatalogItem.Kind.SERVICE,
        )
        other = Tenant.objects.create(name="Contoso", slug="contoso")
        CatalogItem.objects.create(
            tenant=other,
            created_by=self.owner,
            name="Other tenant service",
            kind=CatalogItem.Kind.SERVICE,
        )
        response = self.client.get(reverse("reports:export_catalog"))
        rows = list(
            csv.DictReader(
                io.StringIO(b"".join(response.streaming_content).decode("utf-8"))
            )
        )
        self.assertEqual(len(rows), 2)
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Taxable service"]["price"], "1250.1234")
        self.assertEqual(by_name["Taxable service"]["currency"], "INR")
        self.assertEqual(by_name["Taxable service"]["hsn_sac"], "998314")
        self.assertEqual(by_name["Taxable service"]["tax_treatment"], "taxable")
        self.assertEqual(by_name["Taxable service"]["tax_rate_percent"], "18.0000")
        self.assertEqual(by_name["Legacy service"]["price"], "")
        self.assertEqual(by_name["Legacy service"]["tax_rate_percent"], "")


class AuditActivityReportTests(TestCase):
    def test_activity_list_does_not_leak_another_tenants_events(self):
        owner = get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        TenantMembership.objects.create(
            tenant=tenant, user=owner, role=TenantMembership.Role.OWNER
        )
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        AuditEvent.objects.create(
            tenant=tenant,
            actor=owner,
            action="customer.created",
            entity_type="customer",
        )
        AuditEvent.objects.create(
            tenant=other_tenant,
            actor=owner,
            action="catalog_item.updated",
            entity_type="catalog_item",
        )
        self.assertTrue(self.client.login(email=owner.email, password="correct-horse"))

        response = self.client.get(reverse("reports:home"))

        self.assertContains(response, "customer.created")
        self.assertNotContains(response, "catalog_item.updated")
