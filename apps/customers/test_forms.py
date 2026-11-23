from django.test import SimpleTestCase

from apps.customers.forms import CustomerForm


class CustomerFormTests(SimpleTestCase):
    def test_form_normalizes_contact_fields(self):
        form = CustomerForm(
            data={
                "name": "  Priya Nair  ",
                "company_name": "  Northwind  ",
                "email": " PRIYA@EXAMPLE.COM ",
                "phone": " +91 98765 43210 ",
                "billing_address": " Kochi ",
                "country": "in",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "Priya Nair")
        self.assertEqual(form.cleaned_data["company_name"], "Northwind")
        self.assertEqual(form.cleaned_data["email"], "priya@example.com")
        self.assertEqual(form.cleaned_data["billing_address"], "Kochi")
        self.assertEqual(form.cleaned_data["country"], "IN")

    def test_invalid_email_phone_and_country_are_rejected(self):
        form = CustomerForm(
            data={
                "name": "Priya Nair",
                "company_name": "",
                "email": "invalid-address",
                "phone": "call me maybe",
                "billing_address": "",
                "country": "India",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertIn("phone", form.errors)
        self.assertIn("country", form.errors)
