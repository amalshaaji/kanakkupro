from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Tenant, TenantMembership


class TenantModelTests(TestCase):
    def test_tenant_creation_uses_uuid_primary_key(self):
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")

        self.assertEqual(tenant._meta.pk.get_internal_type(), "UUIDField")
        self.assertEqual(tenant.timezone, "Asia/Kolkata")
        self.assertEqual(tenant.status, Tenant.Status.ACTIVE)

    def test_tenant_membership_links_user_and_tenant(self):
        user = get_user_model().objects.create_user(
            "owner@example.com", password="test-password"
        )
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        membership = TenantMembership.objects.create(
            tenant=tenant, user=user, role=TenantMembership.Role.OWNER
        )

        self.assertEqual(membership.tenant, tenant)
        self.assertEqual(membership.user, user)
        self.assertTrue(membership.is_active)

    def test_membership_is_unique_per_tenant_and_user(self):
        user = get_user_model().objects.create_user(
            "owner@example.com", password="test-password"
        )
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        TenantMembership.objects.create(
            tenant=tenant, user=user, role=TenantMembership.Role.OWNER
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TenantMembership.objects.create(
                    tenant=tenant, user=user, role=TenantMembership.Role.ADMIN
                )
