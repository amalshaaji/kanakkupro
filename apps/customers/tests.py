from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer
from apps.tenants.models import Tenant, TenantMembership


class CustomerManagementTests(TestCase):
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

    def customer(self, *, tenant=None, name="Northwind Customer"):
        return Customer.objects.create(
            tenant=tenant or self.tenant,
            created_by=self.owner,
            name=name,
        )

    def test_customer_creation_is_scoped_and_records_actor(self):
        response = self.client.post(
            reverse("customers:create"),
            {
                "name": "  Priya Nair  ",
                "company_name": "Northwind Services",
                "email": "PRIYA@example.com",
                "phone": "+91 98765 43210",
                "billing_address": "  Kochi, Kerala  ",
                "country": "in",
            },
        )

        customer = Customer.objects.get(email="priya@example.com")
        self.assertRedirects(
            response, reverse("customers:detail", kwargs={"customer_id": customer.pk})
        )
        self.assertEqual(customer.tenant, self.tenant)
        self.assertEqual(customer.name, "Priya Nair")
        self.assertEqual(customer.billing_address, "Kochi, Kerala")
        self.assertEqual(customer.country, "IN")
        self.assertEqual(customer.created_by, self.owner)
        self.assertEqual(customer.updated_by, self.owner)

    def test_customer_list_search_is_tenant_scoped(self):
        visible = self.customer(name="Aster Labs")
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        hidden = self.customer(tenant=other_tenant, name="Aster Global")

        response = self.client.get(reverse("customers:list"), {"q": "Aster"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, visible.name)
        self.assertNotContains(response, hidden.name)

    def test_forged_customer_id_from_another_tenant_is_not_found(self):
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        other_customer = self.customer(tenant=other_tenant)

        response = self.client.get(
            reverse("customers:detail", kwargs={"customer_id": other_customer.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_customer_can_be_archived_and_restored_without_deletion(self):
        customer = self.customer()
        archive_url = reverse(
            "customers:set_status",
            kwargs={"customer_id": customer.pk, "status": Customer.Status.INACTIVE},
        )
        response = self.client.post(archive_url)

        self.assertRedirects(
            response, reverse("customers:detail", kwargs={"customer_id": customer.pk})
        )
        customer.refresh_from_db()
        self.assertEqual(customer.status, Customer.Status.INACTIVE)
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())
        self.assertNotContains(
            self.client.get(reverse("customers:list")), customer.name
        )
        self.assertContains(
            self.client.get(reverse("customers:list"), {"status": "all"}),
            customer.name,
        )

        restore_url = reverse(
            "customers:set_status",
            kwargs={"customer_id": customer.pk, "status": Customer.Status.ACTIVE},
        )
        self.client.post(restore_url)
        customer.refresh_from_db()
        self.assertEqual(customer.status, Customer.Status.ACTIVE)

    def test_viewer_can_read_but_cannot_create_customers(self):
        viewer = get_user_model().objects.create_user(
            "viewer@example.com", password="correct-horse"
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=viewer, role=TenantMembership.Role.VIEWER
        )
        self.client.logout()
        self.assertTrue(self.client.login(email=viewer.email, password="correct-horse"))

        list_response = self.client.get(reverse("customers:list"))
        create_response = self.client.post(
            reverse("customers:create"), {"name": "Unauthorized"}
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(create_response.status_code, 403)
        self.assertFalse(Customer.objects.filter(name="Unauthorized").exists())
