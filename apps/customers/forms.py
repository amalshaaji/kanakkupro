import re

from django import forms
from django.core.exceptions import ValidationError

from apps.common.forms import AccessibleFormMixin
from apps.customers.models import Customer


class CustomerForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "name",
            "company_name",
            "email",
            "phone",
            "billing_address",
            "country",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"autocomplete": "name", "class": "input input-bordered w-full"}
            ),
            "company_name": forms.TextInput(
                attrs={
                    "autocomplete": "organization",
                    "class": "input input-bordered w-full",
                }
            ),
            "email": forms.EmailInput(
                attrs={"autocomplete": "email", "class": "input input-bordered w-full"}
            ),
            "phone": forms.TextInput(
                attrs={
                    "autocomplete": "tel",
                    "class": "input input-bordered w-full",
                }
            ),
            "billing_address": forms.Textarea(
                attrs={
                    "autocomplete": "street-address",
                    "class": "textarea textarea-bordered w-full",
                    "rows": 3,
                }
            ),
            "country": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "class": "input input-bordered w-full",
                }
            ),
        }
        help_texts = {
            "name": "A person or organization name.",
            "billing_address": "Optional address text for future billing documents.",
            "country": "Optional two-letter country code, such as IN or US.",
        }
        labels = {
            "name": "Customer name",
            "company_name": "Organization",
            "billing_address": "Billing address",
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("Enter a customer name.")
        return name

    def clean_company_name(self):
        return self.cleaned_data["company_name"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if phone:
            digits = re.sub(r"\D", "", phone)
            if (
                any(character not in "+0123456789().- " for character in phone)
                or phone.count("+") > 1
                or ("+" in phone and not phone.startswith("+"))
                or len(digits) < 5
            ):
                raise ValidationError(
                    "Enter a phone number using digits and common separators."
                )
        return phone

    def clean_billing_address(self):
        return self.cleaned_data["billing_address"].strip()

    def clean_country(self):
        country = self.cleaned_data["country"].strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise ValidationError("Enter a two-letter country code.")
        return country
