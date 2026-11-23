from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase


class UserModelTests(TestCase):
    def test_user_creation_normalizes_email_and_hashes_password(self):
        user = get_user_model().objects.create_user(
            "Owner@Example.COM", password="a-strong-test-password"
        )

        self.assertEqual(user.email, "owner@example.com")
        self.assertTrue(user.check_password("a-strong-test-password"))
        self.assertTrue(user.has_usable_password())

    def test_email_uniqueness_is_case_insensitive_in_the_database(self):
        user_model = get_user_model()
        user_model.objects.create_user("owner@example.com", password="password")
        other_user = user_model.objects.create_user(
            "other@example.com", password="password"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user_model.objects.filter(pk=other_user.pk).update(
                    email="OWNER@EXAMPLE.COM"
                )

    def test_user_can_authenticate_with_email_and_password(self):
        user_model = get_user_model()
        user_model.objects.create_user("owner@example.com", password="correct-horse")

        user = user_model.objects.get_by_natural_key("OWNER@EXAMPLE.COM")

        self.assertTrue(user.check_password("correct-horse"))
