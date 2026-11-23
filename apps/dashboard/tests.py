from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class DashboardAccessTests(TestCase):
    def test_home_page_is_public(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)

    def test_dashboard_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("dashboard:index"))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('dashboard:index')}",
        )

    def test_authenticated_user_can_open_dashboard(self):
        get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        self.assertTrue(
            self.client.login(email="owner@example.com", password="correct-horse")
        )

        response = self.client.get(reverse("dashboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back")
