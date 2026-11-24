import time

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, hotp_value
from cryptography.fernet import Fernet, InvalidToken
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.mfa import EncryptedMFAAdapter
from apps.accounts.security import ADMIN_MFA_SESSION_KEY
from apps.audit.models import AuditEvent

SECRET = "JBSWY3DPEHPK3PXP"  # Disposable test authenticator only.


class MFAEncryptionTests(SimpleTestCase):
    def test_round_trip_is_encrypted_and_wrong_keys_fail_closed(self):
        key = Fernet.generate_key().decode()
        with override_settings(MFA_ENCRYPTION_KEYS=[key]):
            adapter = EncryptedMFAAdapter()
            encrypted = adapter.encrypt(SECRET)
            self.assertNotIn(SECRET, encrypted)
            self.assertEqual(adapter.decrypt(encrypted), SECRET)
            with self.assertRaises(ImproperlyConfigured):
                adapter.decrypt(SECRET)
        with override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            with self.assertRaises(ImproperlyConfigured):
                adapter.decrypt(encrypted)

    def test_rotation_reads_previous_key_and_encrypts_with_primary_key(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        adapter = EncryptedMFAAdapter()
        with override_settings(MFA_ENCRYPTION_KEYS=[old]):
            encrypted = adapter.encrypt(SECRET)
        with override_settings(MFA_ENCRYPTION_KEYS=[new, old]):
            self.assertEqual(adapter.decrypt(encrypted), SECRET)
            updated = adapter.encrypt(SECRET).removeprefix("fernet:v1:").encode()
        self.assertEqual(Fernet(new.encode()).decrypt(updated).decode(), SECRET)
        with self.assertRaises(InvalidToken):
            Fernet(old.encode()).decrypt(updated)

    @override_settings(MFA_ENCRYPTION_KEYS=[], DEPLOYMENT_ENVIRONMENT="production")
    def test_production_cannot_use_development_encryption_fallback(self):
        with self.assertRaises(ImproperlyConfigured):
            EncryptedMFAAdapter().encrypt(SECRET)


class AdminSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            "admin@example.com", "test-password-123!"
        )
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True
        )
        self.client.force_login(self.user)

    def activate(self):
        return TOTP.activate(self.user, SECRET).instance

    def reauthenticate(self):
        code = format_hotp_value(hotp_value(SECRET, int(time.time()) // 30))
        response = self.client.post(
            reverse("mfa_reauthenticate"),
            {"code": code, "next": reverse("admin:index")},
        )
        self.assertEqual(response.status_code, 302)
        return response

    def test_password_only_session_is_sent_to_mfa_enrollment(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("mfa_activate_totp"), response.url)

    def test_enrolled_admin_requires_current_session_mfa(self):
        self.activate()
        response = self.client.get(reverse("admin:index"))
        self.assertIn(reverse("mfa_reauthenticate"), response.url)
        self.reauthenticate()
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        event = AuditEvent.objects.get(action="platform_admin.access")
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertEqual(event.metadata["view"], "admin:index")
        self.assertIsNone(event.tenant_id)
        self.assertEqual(event.correlation_id, response["X-Request-ID"])

    def test_password_login_does_not_complete_before_mfa_challenge(self):
        self.activate()
        self.client.logout()
        response = self.client.post(
            reverse("account_login"),
            {"login": self.user.email, "password": "test-password-123!"},
        )
        self.assertIn(reverse("mfa_authenticate"), response.url)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.post(reverse("mfa_authenticate"), {"code": "invalid-code"})
        self.assertNotIn("_auth_user_id", self.client.session)
        code = format_hotp_value(hotp_value(SECRET, int(time.time()) // 30))
        response = self.client.post(reverse("mfa_authenticate"), {"code": code})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_expired_mfa_and_other_user_grant_cannot_unlock_admin(self):
        auth = self.activate()
        for grant in (
            {
                "user": str(self.user.pk),
                "at": time.time() - 1000,
                "authenticator": auth.pk,
            },
            {"user": "other-user", "at": time.time(), "authenticator": auth.pk},
            {
                "user": str(self.user.pk),
                "at": time.time() + 1000,
                "authenticator": auth.pk,
            },
        ):
            with self.subTest(grant=grant):
                session = self.client.session
                session[ADMIN_MFA_SESSION_KEY] = grant
                session.save()
                response = self.client.get(reverse("admin:index"))
                self.assertIn(reverse("mfa_reauthenticate"), response.url)

    def test_unverified_admin_email_is_denied(self):
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        response = self.client.get(reverse("admin:index"))
        self.assertIn(reverse("account_email"), response.url)

    def test_staff_cannot_remove_totp_and_authenticator_admin_is_unregistered(self):
        auth = self.activate()
        self.assertFalse(EncryptedMFAAdapter().can_delete_authenticator(auth))
        self.assertFalse(admin.site.is_registered(Authenticator))
        auth.refresh_from_db()
        self.assertTrue(auth.data["secret"].startswith("fernet:v1:"))
        self.assertNotIn(SECRET, str(auth.data))

    def test_admin_logout_preserves_actor_in_audit_after_session_is_cleared(self):
        self.activate()
        self.reauthenticate()
        response = self.client.post(reverse("admin:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        event = AuditEvent.objects.get(action="platform_admin.access")
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertEqual(event.metadata["view"], "admin:logout")

    def test_nonstaff_and_anonymous_users_cannot_use_admin_password_form(self):
        self.client.logout()
        response = self.client.post(
            reverse("admin:login"),
            {"username": self.user.email, "password": "test-password-123!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response.url)
        ordinary = get_user_model().objects.create_user("ordinary@example.com")
        self.client.force_login(ordinary)
        self.assertEqual(self.client.get(reverse("admin:login")).status_code, 403)

    def test_security_events_do_not_contain_codes_or_secrets(self):
        self.activate()
        self.reauthenticate()
        event = AuditEvent.objects.get(action="security.mfa_used")
        self.assertEqual(event.metadata, {"type": "totp"})
        self.assertNotIn(SECRET, str(event.metadata))

    def test_account_security_and_authenticated_business_responses_are_private(self):
        response = self.client.get(reverse("mfa_index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(reverse("home"))
        self.assertIn("private", response["Cache-Control"])
        self.client.logout()
        response = self.client.get(reverse("account_login"))
        self.assertIn("no-store", response["Cache-Control"])
