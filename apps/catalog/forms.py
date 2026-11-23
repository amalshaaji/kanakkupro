from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.common.forms import AccessibleFormMixin


class CatalogItemForm(AccessibleFormMixin, forms.ModelForm):
    price = forms.DecimalField(
        label="Unit price",
        help_text="Per unit, with up to four decimal places.",
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "step": "0.0001"}
        ),
    )
    tax_rate = forms.DecimalField(
        label="GST rate (%)",
        help_text="Enter the applicable percentage selected for this item.",
        max_digits=7,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "step": "0.0001"}
        ),
    )

    class Meta:
        model = CatalogItem
        fields = [
            "name",
            "kind",
            "sku",
            "description",
            "unit",
            "price",
            "hsn_sac",
            "tax_treatment",
            "tax_rate",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "kind": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "sku": forms.TextInput(
                attrs={"autocomplete": "off", "class": "input input-bordered w-full"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "textarea textarea-bordered w-full",
                    "rows": 4,
                }
            ),
            "unit": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "hsn_sac": forms.TextInput(
                attrs={"inputmode": "numeric", "class": "input input-bordered w-full"}
            ),
            "tax_treatment": forms.Select(
                attrs={"class": "select select-bordered w-full"}
            ),
        }
        help_texts = {
            "sku": "Optional. SKU values must be unique within this business.",
            "unit": "Optional, such as each, hour, or session.",
            "hsn_sac": "Enter the HSN or SAC code selected for this item.",
            "tax_treatment": "Confirm the tax treatment for this item.",
        }
        labels = {"hsn_sac": "HSN/SAC code"}

    def __init__(self, *args, tenant, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        self.fields["price"].label = f"Unit price ({tenant.currency})"
        self.fields["hsn_sac"].required = True
        self.fields["tax_treatment"].required = True

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("Enter a product or service name.")
        return name

    def clean_sku(self):
        sku = (self.cleaned_data["sku"] or "").strip()
        if not sku:
            return None
        duplicates = CatalogItem.objects.filter(tenant=self.tenant, sku__iexact=sku)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("This SKU is already used in this business.")
        return sku

    def clean_description(self):
        return (self.cleaned_data["description"] or "").strip()

    def clean_unit(self):
        return (self.cleaned_data["unit"] or "").strip()

    def clean_hsn_sac(self):
        code = (self.cleaned_data["hsn_sac"] or "").strip()
        if not code or not code.isascii() or not code.isdigit():
            raise ValidationError("Enter the numeric HSN or SAC code for this item.")
        return code

    def clean(self):
        cleaned = super().clean()
        treatment = cleaned.get("tax_treatment")
        rate = cleaned.get("tax_rate")
        if treatment == CatalogItem.TaxTreatment.TAXABLE:
            if rate is None:
                self.add_error("tax_rate", "Enter the applicable GST rate.")
            elif rate <= 0:
                self.add_error("tax_rate", "Taxable items need a positive GST rate.")
        elif treatment == CatalogItem.TaxTreatment.EXEMPT:
            if rate not in (None, Decimal("0")):
                self.add_error("tax_rate", "Exempt items must have a zero GST rate.")
            else:
                cleaned["tax_rate"] = Decimal("0")
        return cleaned
