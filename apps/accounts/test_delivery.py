from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.delivery import EmailDeliveryMiddleware, SafeSMTPBackend


class DeliveryBoundaryTests(SimpleTestCase):
    @patch("django.core.mail.backends.smtp.EmailBackend.send_messages")
    def test_backend_hides_provider_secrets(self, send):
        from apps.accounts.delivery import EmailDeliveryUnavailable

        send.side_effect = SMTPAuthenticationError(535, b"private-provider-secret")
        with self.assertLogs("kanakkupro.email", level="ERROR") as logs:
            with self.assertRaises(EmailDeliveryUnavailable) as raised:
                SafeSMTPBackend().send_messages([object()])
        self.assertNotIn("private-provider-secret", str(raised.exception))
        self.assertNotIn("private-provider-secret", "".join(logs.output))

    def test_other_application_errors_are_not_hidden(self):
        self.assertIsNone(
            EmailDeliveryMiddleware(None).process_exception(None, ValueError())
        )


@override_settings(EMAIL_BACKEND="apps.accounts.delivery.SafeSMTPBackend")
class DeliveryFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("django.core.mail.backends.smtp.EmailBackend.send_messages")
    def test_signup_outage_preserves_unverified_account_and_returns_useful_503(
        self, send
    ):
        send.side_effect = SMTPAuthenticationError(535, b"private-provider-secret")
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "new@example.test",
                "password1": "long-password-example-42",
                "password2": "long-password-example-42",
            },
        )
        self.assertContains(
            response, "Email is temporarily unavailable", status_code=503
        )
        self.assertNotContains(response, "private-provider-secret", status_code=503)
        self.assertEqual(response["Retry-After"], "60")
        self.assertIn("no-store", response["Cache-Control"])
        user = get_user_model().objects.get(email="new@example.test")
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("django.core.mail.backends.smtp.EmailBackend.send_messages")
    def test_verified_user_can_login_while_provider_is_down(self, send):
        user = get_user_model().objects.create_user(
            "owner@example.test", password="long-password-example-42"
        )
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        response = self.client.post(
            reverse("account_login"),
            {"login": user.email, "password": "long-password-example-42"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        send.assert_not_called()


@override_settings(EMAIL_BACKEND="apps.accounts.delivery.SafeSMTPBackend")
class InvitationDeliveryTests(TransactionTestCase):
    @patch("django.core.mail.backends.smtp.EmailBackend.send_messages")
    def test_invitation_failure_keeps_saved_invitation_and_returns_recovery_page(
        self, send
    ):
        from apps.tenants.models import Invitation, Tenant, TenantMembership

        user = get_user_model().objects.create_user("owner-invite@example.test")
        tenant = Tenant.objects.create(name="Invitation test", slug="invitation-test")
        TenantMembership.objects.create(tenant=tenant, user=user, role="owner")
        self.client.force_login(user)
        send.side_effect = SMTPAuthenticationError(535, b"private-provider-secret")
        response = self.client.post(
            reverse("tenants:team"), {"email": "teammate@example.test", "role": "staff"}
        )
        self.assertContains(response, "Review invitations", status_code=503)
        self.assertEqual(Invitation.objects.filter(tenant=tenant).count(), 1)
