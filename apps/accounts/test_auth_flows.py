import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse


class SignupAndEmailVerificationTests(TestCase):
    def test_signup_requires_email_confirmation_before_login(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "new-owner@example.com",
                "password1": "a-long-and-strong-password-42",
                "password2": "a-long-and-strong-password-42",
            },
        )

        user = get_user_model().objects.get(email="new-owner@example.com")
        email_address = EmailAddress.objects.get(user=user, email=user.email)
        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(email_address.verified)
        self.assertEqual(len(mail.outbox), 1)

        self.client.post(
            reverse("account_login"),
            {"login": user.email, "password": "a-long-and-strong-password-42"},
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_confirmation_get_does_not_verify_but_post_does(self):
        self.client.post(
            reverse("account_signup"),
            {
                "email": "new-owner@example.com",
                "password1": "a-long-and-strong-password-42",
                "password2": "a-long-and-strong-password-42",
            },
        )
        email_address = EmailAddress.objects.get(email="new-owner@example.com")
        match = re.search(
            r"/accounts/confirm-email/([^/\s]+)", mail.outbox[0].body
        )
        self.assertIsNotNone(match)
        confirm_url = reverse("account_confirm_email", kwargs={"key": match.group(1)})

        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        email_address.refresh_from_db()
        self.assertFalse(email_address.verified)

        response = self.client.post(confirm_url)
        self.assertIn(response.status_code, (200, 302))
        email_address.refresh_from_db()
        self.assertTrue(email_address.verified)


class LoginAndPasswordResetTests(TestCase):
    def create_verified_user(self, email="owner@example.com"):
        user = get_user_model().objects.create_user(
            email, password="a-long-and-strong-password-42"
        )
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        return user

    def test_allauth_login_and_post_logout(self):
        user = self.create_verified_user()

        response = self.client.post(
            reverse("account_login"),
            {"login": user.email, "password": "a-long-and-strong-password-42"},
        )
        self.assertRedirects(response, reverse("dashboard:index"))
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("account_logout"))
        self.assertIn(response.status_code, (200, 302))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_reset_email_can_change_password(self):
        user = self.create_verified_user()
        response = self.client.post(
            reverse("account_reset_password"), {"email": user.email}
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertEqual(len(mail.outbox), 1)

        reset_match = re.search(
            r"http://testserver(?P<path>/accounts/password/reset/key/[^\s]+)",
            mail.outbox[0].body,
        )
        self.assertIsNotNone(reset_match)
        reset_path = reset_match.group("path").rstrip(".,)")
        response = self.client.get(reset_path)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reset_path,
            {
                "password1": "a-different-strong-password-73",
                "password2": "a-different-strong-password-73",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        user.refresh_from_db()
        self.assertTrue(user.check_password("a-different-strong-password-73"))
        self.assertFalse(user.check_password("a-long-and-strong-password-42"))


class AuthenticationRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(
        ACCOUNT_RATE_LIMITS={"login": "10/m/ip", "login_failed": "1/5m/key"}
    )
    def test_failed_login_attempts_are_throttled_by_email(self):
        get_user_model().objects.create_user(
            "owner@example.com", password="a-long-and-strong-password-42"
        )
        credentials = {"login": "owner@example.com", "password": "wrong-password"}

        first_response = self.client.post(reverse("account_login"), credentials)
        second_response = self.client.post(reverse("account_login"), credentials)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)
