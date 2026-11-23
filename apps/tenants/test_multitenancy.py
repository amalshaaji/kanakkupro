import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.tenants.middleware import ACTIVE_TENANT_SESSION_KEY
from apps.tenants.models import Invitation, Tenant, TenantMembership


class TenantSelectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        self.first = Tenant.objects.create(name="Northwind", slug="northwind")
        self.second = Tenant.objects.create(name="Contoso", slug="contoso")
        TenantMembership.objects.create(
            tenant=self.first, user=self.user, role=TenantMembership.Role.OWNER
        )
        TenantMembership.objects.create(
            tenant=self.second, user=self.user, role=TenantMembership.Role.ADMIN
        )
        self.assertTrue(
            self.client.login(email=self.user.email, password="correct-horse")
        )

    def test_session_selection_is_resolved_to_active_membership(self):
        session = self.client.session
        session[ACTIVE_TENANT_SESSION_KEY] = str(self.second.pk)
        session.save()

        response = self.client.get(reverse("dashboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contoso")
        self.assertEqual(
            self.client.session[ACTIVE_TENANT_SESSION_KEY], str(self.second.pk)
        )

    def test_revoked_active_membership_falls_back_to_remaining_membership(self):
        session = self.client.session
        session[ACTIVE_TENANT_SESSION_KEY] = str(self.first.pk)
        session.save()
        TenantMembership.objects.filter(tenant=self.first, user=self.user).update(
            status=TenantMembership.Status.INACTIVE
        )

        response = self.client.get(reverse("dashboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contoso")
        self.assertEqual(
            self.client.session[ACTIVE_TENANT_SESSION_KEY], str(self.second.pk)
        )

    def test_member_can_switch_tenant(self):
        response = self.client.post(
            reverse("tenants:switch"), {"tenant_id": str(self.second.pk)}
        )

        self.assertRedirects(response, reverse("dashboard:index"))
        dashboard = self.client.get(reverse("dashboard:index"))
        self.assertContains(dashboard, "Contoso")

    def test_switch_rejects_tenant_without_membership(self):
        stranger = get_user_model().objects.create_user(
            "stranger@example.com", password="correct-horse"
        )
        other_business = Tenant.objects.create(name="Fabrikam", slug="fabrikam")
        TenantMembership.objects.create(
            tenant=other_business,
            user=stranger,
            role=TenantMembership.Role.OWNER,
        )
        session = self.client.session
        session[ACTIVE_TENANT_SESSION_KEY] = str(self.first.pk)
        session.save()

        response = self.client.post(
            reverse("tenants:switch"), {"tenant_id": str(other_business.pk)}
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.client.session[ACTIVE_TENANT_SESSION_KEY], str(self.first.pk)
        )


class TenantOnboardingTests(TestCase):
    def test_creation_atomically_adds_owner_membership_and_active_tenant(self):
        user = get_user_model().objects.create_user(
            "founder@example.com", password="correct-horse"
        )
        self.assertTrue(self.client.login(email=user.email, password="correct-horse"))

        response = self.client.post(
            reverse("tenants:create"),
            {
                "name": "Northwind Services",
                "country": "in",
                "currency": "inr",
                "timezone": "Asia/Kolkata",
            },
        )

        self.assertRedirects(response, reverse("dashboard:index"))
        tenant = Tenant.objects.get(slug="northwind-services")
        membership = TenantMembership.objects.get(tenant=tenant, user=user)
        self.assertEqual(membership.role, TenantMembership.Role.OWNER)
        self.assertEqual(membership.status, TenantMembership.Status.ACTIVE)
        self.assertEqual(self.client.session[ACTIVE_TENANT_SESSION_KEY], str(tenant.pk))


class TenantRoleTests(TestCase):
    def test_viewer_cannot_manage_tenant_team(self):
        user = get_user_model().objects.create_user(
            "viewer@example.com", password="correct-horse"
        )
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        TenantMembership.objects.create(
            tenant=tenant, user=user, role=TenantMembership.Role.VIEWER
        )
        self.assertTrue(self.client.login(email=user.email, password="correct-horse"))

        response = self.client.get(reverse("tenants:team"))

        self.assertEqual(response.status_code, 403)


class InvitationFlowTests(TestCase):
    def create_owner(self):
        user = get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        tenant = Tenant.objects.create(name="Northwind", slug="northwind")
        TenantMembership.objects.create(
            tenant=tenant, user=user, role=TenantMembership.Role.OWNER
        )
        return user, tenant

    def send_invitation(self, invited_email="staff@example.com"):
        owner, tenant = self.create_owner()
        self.assertTrue(self.client.login(email=owner.email, password="correct-horse"))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("tenants:team"),
                {"email": invited_email, "role": TenantMembership.Role.STAFF},
            )
        self.assertRedirects(response, reverse("tenants:team"))
        invitation = Invitation.objects.get(tenant=tenant, email=invited_email)
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"/tenants/invitations/accept/([^/\s]+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        return owner, tenant, invitation, match.group(1)

    def test_invitation_is_hashed_and_post_acceptance_is_single_use(self):
        _, tenant, invitation, token = self.send_invitation()
        self.assertNotEqual(invitation.token_hash, token)

        invitee = get_user_model().objects.create_user(
            "staff@example.com", password="correct-horse"
        )
        EmailAddress.objects.create(
            user=invitee, email=invitee.email, primary=True, verified=True
        )
        self.client.logout()
        self.assertTrue(
            self.client.login(email=invitee.email, password="correct-horse")
        )
        url = reverse("tenants:accept_invitation", kwargs={"token": token})

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertFalse(
            TenantMembership.objects.filter(tenant=tenant, user=invitee).exists()
        )
        response = self.client.post(url)

        self.assertRedirects(response, reverse("dashboard:index"))
        membership = TenantMembership.objects.get(tenant=tenant, user=invitee)
        invitation.refresh_from_db()
        self.assertEqual(membership.role, TenantMembership.Role.STAFF)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.accepted_by, invitee)
        self.assertEqual(self.client.session[ACTIVE_TENANT_SESSION_KEY], str(tenant.pk))
        self.assertRedirects(self.client.get(url), reverse("dashboard:index"))

    def test_invitation_cannot_be_accepted_by_a_different_email(self):
        _, tenant, _, token = self.send_invitation()
        other_user = get_user_model().objects.create_user(
            "other@example.com", password="correct-horse"
        )
        EmailAddress.objects.create(
            user=other_user, email=other_user.email, primary=True, verified=True
        )
        self.client.logout()
        self.assertTrue(
            self.client.login(email=other_user.email, password="correct-horse")
        )

        response = self.client.post(
            reverse("tenants:accept_invitation", kwargs={"token": token})
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            TenantMembership.objects.filter(tenant=tenant, user=other_user).exists()
        )

    def test_invitation_can_be_revoked_only_from_its_tenant_team(self):
        _, tenant, invitation, _ = self.send_invitation()
        other_tenant = Tenant.objects.create(name="Contoso", slug="contoso")
        owner = get_user_model().objects.get(email="owner@example.com")
        TenantMembership.objects.create(
            tenant=other_tenant, user=owner, role=TenantMembership.Role.ADMIN
        )
        session = self.client.session
        session[ACTIVE_TENANT_SESSION_KEY] = str(other_tenant.pk)
        session.save()

        response = self.client.post(
            reverse("tenants:revoke", kwargs={"invitation_id": invitation.pk})
        )

        self.assertEqual(response.status_code, 404)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.revoked_at)

        session = self.client.session
        session[ACTIVE_TENANT_SESSION_KEY] = str(tenant.pk)
        session.save()
        response = self.client.post(
            reverse("tenants:revoke", kwargs={"invitation_id": invitation.pk})
        )
        self.assertRedirects(response, reverse("tenants:team"))
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
