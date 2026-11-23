from django import forms
from django.core.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.common.forms import AccessibleFormMixin


class CatalogItemForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = CatalogItem
        fields = ["name", "kind", "sku", "description", "unit"]
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
        }
        help_texts = {
            "sku": "Optional. SKU values must be unique within this business.",
            "unit": "Optional, such as each, hour, or session.",
        }

    def __init__(self, *args, tenant, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)

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
