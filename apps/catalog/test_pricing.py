from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.forms import CatalogItemForm
from apps.catalog.models import CatalogItem
from apps.catalog.services import create_catalog_item, update_catalog_item
from apps.tenants.models import Tenant, TenantMembership


class CatalogPricingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner@example.com")
        self.tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        self.membership = TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantMembership.Role.OWNER
        )
        self.client.force_login(self.owner)

    def values(self, **overrides):
        return {
            "name": "Consulting",
            "kind": CatalogItem.Kind.SERVICE,
            "sku": "",
            "description": "Remote consulting",
            "unit": "hour",
            "price": Decimal("1250.1234"),
            "hsn_sac": "998314",
            "tax_treatment": CatalogItem.TaxTreatment.TAXABLE,
            "tax_rate": Decimal("18.0000"),
            **overrides,
        }

    def create(self, **overrides):
        return create_catalog_item(
            tenant=self.tenant, actor=self.owner, values=self.values(**overrides)
        )

    def test_exact_price_and_tax_rate_survive_service_and_database(self):
        item = self.create(tax_rate=Decimal("5.0000"))
        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("1250.1234"))
        self.assertEqual(item.tax_rate, Decimal("5.0000"))
        self.assertTrue(item.is_invoice_ready)

    def test_form_requires_price_and_tax_classification(self):
        form = CatalogItemForm(
            self.values(price="", hsn_sac="", tax_treatment="", tax_rate=""),
            tenant=self.tenant,
        )
        self.assertFalse(form.is_valid())
        for field in ("price", "hsn_sac", "tax_treatment"):
            self.assertIn(field, form.errors)

    def test_form_rejects_invalid_price_code_and_tax_combinations(self):
        cases = (
            {"price": "-0.0001"},
            {"price": "1.23456"},
            {"price": "NaN"},
            {"hsn_sac": "9983x4"},
            {"hsn_sac": "９９８３１４"},
            {"hsn_sac": "998314\nwrong"},
            {"tax_rate": ""},
            {"tax_rate": "0"},
            {"tax_rate": "-1"},
            {"tax_treatment": "exempt", "tax_rate": "18"},
            {"tax_treatment": "unsupported"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                form = CatalogItemForm(self.values(**overrides), tenant=self.tenant)
                self.assertFalse(form.is_valid())

    def test_exempt_form_normalizes_blank_rate_to_zero(self):
        form = CatalogItemForm(
            self.values(price="0", tax_treatment="exempt", tax_rate=""),
            tenant=self.tenant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        item = create_catalog_item(
            tenant=self.tenant, actor=self.owner, values=form.cleaned_data
        )
        item.refresh_from_db()
        self.assertEqual(item.tax_rate, Decimal("0.0000"))
        self.assertEqual(item.price, Decimal("0.0000"))

    def test_legacy_item_stays_unclassified_until_edited(self):
        item = CatalogItem.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Legacy item",
            kind=CatalogItem.Kind.SERVICE,
        )
        self.assertFalse(item.is_invoice_ready)
        response = self.client.get(
            reverse("catalog:detail", kwargs={"item_id": item.pk})
        )
        self.assertContains(response, "Price or tax classification is incomplete.")
        response = self.client.post(
            reverse("catalog:update", kwargs={"item_id": item.pk}),
            self.values(price="0.1234"),
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("0.1234"))
        self.assertTrue(item.is_invoice_ready)
        self.assertTrue(
            AuditEvent.objects.filter(
                entity_id=item.pk, action="catalog_item.updated"
            ).exists()
        )

    def test_database_rejects_partial_or_invalid_financial_fields(self):
        cases = (
            {"price": Decimal("-0.0001")},
            {"tax_treatment": None},
            {"tax_treatment": "unsupported"},
            {"tax_treatment": "unsupported", "tax_rate": None},
            {"tax_rate": None},
            {"tax_rate": Decimal("0")},
            {"tax_rate": Decimal("-1")},
            {"tax_treatment": "exempt", "tax_rate": Decimal("18")},
            {"tax_treatment": "exempt", "tax_rate": None},
            {"hsn_sac": ""},
            {"hsn_sac": "not-a-code"},
            {"hsn_sac": "９９８３１４"},
            {"hsn_sac": "998314\n"},
            {"tax_treatment": None, "hsn_sac": "", "tax_rate": Decimal("0")},
            {"tax_treatment": None, "hsn_sac": "998314", "tax_rate": None},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    CatalogItem.objects.create(
                        tenant=self.tenant,
                        created_by=self.owner,
                        **self.values(**overrides),
                    )

    def test_database_rejects_numeric_nan_even_when_orm_is_bypassed(self):
        item = self.create()
        for column in ("price", "tax_rate"):
            with self.subTest(column=column):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"UPDATE catalog_catalogitem SET {column} = %s::numeric "
                            "WHERE id = %s",
                            ["NaN", item.pk],
                        )

    def test_service_validates_direct_inputs_without_partial_writes(self):
        for overrides in (
            {"price": Decimal("-1")},
            {"price": 1.2},
            {"price": "invalid"},
            {"price": Decimal("NaN")},
            {"tax_rate": 18.0},
            {"tax_rate": "invalid"},
            {"tax_rate": Decimal("NaN")},
            {"hsn_sac": "not-a-code"},
            {"tax_rate": None},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create(**overrides)
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_financial_changes_roll_back_if_audit_write_fails(self):
        item = self.create()
        with patch("apps.catalog.services.record_event", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                update_catalog_item(
                    tenant=self.tenant,
                    actor=self.owner,
                    item_id=item.pk,
                    values=self.values(price=Decimal("900")),
                )
        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("1250.1234"))

    def test_cross_tenant_price_update_is_rejected_by_view_and_service(self):
        other = Tenant.objects.create(name="Contoso", slug="contoso")
        item = CatalogItem.objects.create(
            tenant=other, created_by=self.owner, **self.values()
        )
        response = self.client.post(
            reverse("catalog:update", kwargs={"item_id": item.pk}),
            self.values(price="1"),
        )
        self.assertEqual(response.status_code, 404)
        with self.assertRaises(CatalogItem.DoesNotExist):
            update_catalog_item(
                tenant=self.tenant,
                actor=self.owner,
                item_id=item.pk,
                values=self.values(price=Decimal("1")),
            )
        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("1250.1234"))

    def test_service_rechecks_roles_and_revoked_membership(self):
        for role in (TenantMembership.Role.STAFF, TenantMembership.Role.VIEWER):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            with self.subTest(role=role), self.assertRaises(PermissionDenied):
                self.create()
        self.membership.role = TenantMembership.Role.OWNER
        self.membership.status = TenantMembership.Status.INACTIVE
        self.membership.save(update_fields=["role", "status"])
        with self.assertRaises(PermissionDenied):
            self.create()

    def test_anonymous_financial_form_is_protected(self):
        self.client.logout()
        response = self.client.post(reverse("catalog:create"), self.values())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_service_validation_error_is_rendered_on_form(self):
        with patch(
            "apps.catalog.views.create_catalog_item",
            side_effect=ValidationError("Catalog details changed. Please retry."),
        ):
            response = self.client.post(reverse("catalog:create"), self.values())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Catalog details changed. Please retry.")
