from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.core.exceptions import ValidationError

from apps.tenants.models import Invitation, Tenant


class AccessibleFormMixin:
    def full_clean(self):
        super().full_clean()
        for name in self.fields:
            bound_field = self[name]
            described_by = []
            if bound_field.help_text:
                described_by.append(f"{bound_field.id_for_label}_helptext")
            if bound_field.errors:
                described_by.append(f"{bound_field.id_for_label}_errors")
                bound_field.field.widget.attrs["aria-invalid"] = "true"
            else:
                bound_field.field.widget.attrs.pop("aria-invalid", None)
            if described_by:
                bound_field.field.widget.attrs["aria-describedby"] = " ".join(
                    described_by
                )
            else:
                bound_field.field.widget.attrs.pop("aria-describedby", None)


class TenantCreateForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["name", "country", "currency", "timezone"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "autocomplete": "organization",
                    "class": "input input-bordered w-full",
                }
            ),
            "country": forms.TextInput(
                attrs={
                    "autocomplete": "country",
                    "class": "input input-bordered w-full",
                }
            ),
            "currency": forms.TextInput(
                attrs={"autocomplete": "off", "class": "input input-bordered w-full"}
            ),
            "timezone": forms.TextInput(
                attrs={"autocomplete": "off", "class": "input input-bordered w-full"}
            ),
        }

    def clean_country(self):
        country = self.cleaned_data["country"].strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise ValidationError("Enter a two-letter country code.")
        return country

    def clean_currency(self):
        currency = self.cleaned_data["currency"].strip().upper()
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValidationError("Enter a three-letter currency code.")
        return currency

    def clean_timezone(self):
        timezone_name = self.cleaned_data["timezone"].strip()
        try:
            ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValidationError("Enter a valid IANA time zone.") from error
        return timezone_name


class InvitationCreateForm(AccessibleFormMixin, forms.ModelForm):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "class": "input input-bordered w-full"}
        )
    )
    role = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = self._meta.model._meta.get_field("role").choices

    class Meta:
        model = Invitation
        fields = ["email", "role"]

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
