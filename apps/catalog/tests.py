from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import CatalogItem
from apps.tenants.models import Tenant, TenantMembership


class CatalogManagementTests(TestCase):
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

    def item(self, *, tenant=None, name="Consulting", sku=None):
        return CatalogItem.objects.create(
            tenant=tenant or self.tenant,
            created_by=self.owner,
            name=name,
            kind=CatalogItem.Kind.SERVICE,
            sku=sku,
        )

    def test_create_item_with_price_and_tax_setup_and_record_actor(self):
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        response = self.client.post(
            reverse("catalog:create"),
            {
                "tenant_id": str(other_tenant.pk),
                "name": "  Monthly support  ",
                "kind": CatalogItem.Kind.SERVICE,
                "sku": "SUPPORT-01",
                "description": "  Remote support  ",
                "unit": " hour ",
                "price": "1250.2500",
                "hsn_sac": "998314",
                "tax_treatment": CatalogItem.TaxTreatment.TAXABLE,
                "tax_rate": "18.0000",
            },
            follow=True,
        )

        item = CatalogItem.objects.get(sku="SUPPORT-01")
        self.assertRedirects(
            response, reverse("catalog:detail", kwargs={"item_id": item.pk})
        )
        self.assertEqual(item.tenant, self.tenant)
        self.assertEqual(item.name, "Monthly support")
        self.assertEqual(item.description, "Remote support")
        self.assertEqual(item.unit, "hour")
        self.assertEqual(item.created_by, self.owner)
        self.assertEqual(str(item.price), "1250.2500")
        self.assertEqual(item.tax_treatment, CatalogItem.TaxTreatment.TAXABLE)
        self.assertTrue(item.is_invoice_ready)
        event = AuditEvent.objects.get(entity_id=item.pk)
        self.assertEqual(event.action, "catalog_item.created")
        self.assertEqual(len(event.correlation_id), 32)

    def test_catalog_search_is_tenant_scoped(self):
        visible = self.item(name="Aster Consulting")
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        hidden = self.item(tenant=other_tenant, name="Aster Global")

        response = self.client.get(reverse("catalog:list"), {"q": "Aster"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, visible.name)
        self.assertNotContains(response, hidden.name)

    def test_sku_is_unique_case_insensitively_per_tenant(self):
        self.item(name="Consulting", sku="Consulting")

        response = self.client.post(
            reverse("catalog:create"),
            {
                "name": "Another service",
                "kind": CatalogItem.Kind.SERVICE,
                "sku": "consulting",
                "description": "",
                "unit": "",
                "price": "100.0000",
                "hsn_sac": "998314",
                "tax_treatment": CatalogItem.TaxTreatment.TAXABLE,
                "tax_rate": "18.0000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This SKU is already used in this business.")
        self.assertEqual(CatalogItem.objects.count(), 1)

        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        other_item = self.item(tenant=other_tenant, name="Other consulting")
        other_item.sku = "CONSULTING"
        other_item.save(update_fields=["sku"])
        self.assertEqual(
            CatalogItem.objects.filter(
                tenant=other_tenant, sku__iexact="consulting"
            ).count(),
            1,
        )

    def test_forged_item_id_from_another_tenant_is_not_found(self):
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        other_item = self.item(tenant=other_tenant)

        response = self.client.get(
            reverse("catalog:detail", kwargs={"item_id": other_item.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_staff_can_view_catalog_but_cannot_manage_items(self):
        staff = get_user_model().objects.create_user(
            "staff@example.com", password="correct-horse"
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=staff, role=TenantMembership.Role.STAFF
        )
        self.client.logout()
        self.assertTrue(self.client.login(email=staff.email, password="correct-horse"))

        list_response = self.client.get(reverse("catalog:list"))
        create_response = self.client.post(
            reverse("catalog:create"),
            {"name": "Unauthorized", "kind": CatalogItem.Kind.PRODUCT},
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(create_response.status_code, 403)
        self.assertFalse(CatalogItem.objects.filter(name="Unauthorized").exists())

    def test_catalog_item_can_be_archived_and_restored(self):
        item = self.item()
        archive_url = reverse(
            "catalog:set_active", kwargs={"item_id": item.pk, "active": "false"}
        )
        response = self.client.post(archive_url)

        self.assertRedirects(
            response, reverse("catalog:detail", kwargs={"item_id": item.pk})
        )
        item.refresh_from_db()
        self.assertFalse(item.active)
        self.assertTrue(CatalogItem.objects.filter(pk=item.pk).exists())

        self.client.post(
            reverse("catalog:set_active", kwargs={"item_id": item.pk, "active": "true"})
        )
        item.refresh_from_db()
        self.assertTrue(item.active)
