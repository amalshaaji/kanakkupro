from django.test import SimpleTestCase

from apps.tenants.forms import TenantCreateForm


class AccessibleFormTests(SimpleTestCase):
    def test_invalid_form_fields_link_errors_to_the_input(self):
        form = TenantCreateForm(
            data={
                "name": "Northwind",
                "country": "IND",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
            }
        )

        self.assertFalse(form.is_valid())
        country_attrs = form["country"].field.widget.attrs
        self.assertEqual(country_attrs["aria-invalid"], "true")
        self.assertEqual(country_attrs["aria-describedby"], "id_country_errors")

    def test_valid_fields_do_not_claim_to_have_an_error(self):
        form = TenantCreateForm(
            data={
                "name": "Northwind",
                "country": "IN",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
            }
        )

        self.assertTrue(form.is_valid())
        self.assertNotIn("aria-invalid", form["country"].field.widget.attrs)
