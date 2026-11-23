import uuid
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.forms import formset_factory

from apps.catalog.models import CatalogItem
from apps.common.forms import AccessibleFormMixin
from apps.customers.models import Customer
from apps.sales.models import Invoice, InvoiceLine, SellerProfile
from apps.sales.validation import STATE_CHOICES, validate_gstin


class StyledForm(AccessibleFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field.widget.attrs["class"] = (
                "select select-bordered w-full"
                if isinstance(field.widget, forms.Select)
                else "textarea textarea-bordered w-full"
                if isinstance(field.widget, forms.Textarea)
                else "checkbox"
                if isinstance(field.widget, forms.CheckboxInput)
                else "input input-bordered w-full"
            )
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3


class RequestKeyForm(StyledForm):
    key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class InvoiceForm(RequestKeyForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, required=False)
    customer = forms.ModelChoiceField(queryset=Customer.objects.none())
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    buyer_gstin = forms.CharField(
        max_length=15,
        required=False,
        label="Buyer GSTIN",
        validators=[validate_gstin],
        help_text="Leave empty for an unregistered consumer.",
    )
    buyer_state = forms.ChoiceField(choices=STATE_CHOICES, label="Buyer billing state")
    place_of_supply = forms.ChoiceField(
        choices=STATE_CHOICES,
        help_text=(
            "Select the legally determined place of supply. "
            "It is not inferred from the buyer address."
        ),
    )
    supply_type = forms.ChoiceField(
        choices=Invoice._meta.get_field("supply_type").choices
    )
    delivery_address = forms.CharField(
        max_length=1000,
        widget=forms.Textarea,
        help_text="Domestic delivery address, including the state and postal code.",
    )
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea)
    reason = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea,
        label="Correction reason",
    )
    supported_supply = forms.BooleanField(
        label="I confirm this is an ordinary domestic supply under the V1 rules.",
        help_text=(
            "V1 excludes reverse charge, SEZ, exports/imports, e-invoicing "
            "mandates, and intra-UT supplies requiring UTGST. Obtain tax "
            "review for special place-of-supply cases."
        ),
    )

    def __init__(self, *args, tenant, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            tenant=tenant, status="active"
        )
        if parent:
            for field in (
                "customer",
                "buyer_gstin",
                "buyer_state",
                "place_of_supply",
                "supply_type",
                "delivery_address",
            ):
                self.fields[field].disabled = True
            self.fields["customer"].queryset = Customer.objects.filter(
                tenant=tenant, pk=parent.customer_id
            )
            self.fields["reason"].required = True

    def payload(self, *, kind, parent=None):
        fields = (
            "issue_date",
            "due_date",
            "buyer_gstin",
            "buyer_state",
            "place_of_supply",
            "supply_type",
            "delivery_address",
            "notes",
            "reason",
        )
        data = {field: self.cleaned_data[field] for field in fields}
        data.update(
            customer_id=self.cleaned_data["customer"].pk,
            kind=kind,
            parent_id=parent.pk if parent else None,
        )
        data["supported_supply"] = self.cleaned_data["supported_supply"]
        return data


class LineForm(StyledForm):
    item = forms.ModelChoiceField(queryset=CatalogItem.objects.none(), required=False)
    source_line = forms.ModelChoiceField(
        queryset=InvoiceLine.objects.none(), required=False, label="Line to credit"
    )
    description = forms.CharField(
        max_length=1000,
        required=False,
        help_text="Optional description override; otherwise the catalog name is used.",
    )
    quantity = forms.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        initial=Decimal("1"),
    )
    unit_price = forms.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        help_text="Leave empty to use the catalog price. Prices exclude tax.",
    )
    discount = forms.DecimalField(
        max_digits=16,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        initial=Decimal("0"),
        label="Line discount",
        help_text="Fixed amount before GST, not a percentage.",
    )

    def __init__(self, *args, tenant, kind="invoice", parent=None, **kwargs):
        self.kind = kind
        super().__init__(*args, **kwargs)
        if kind == "credit_note":
            self.fields.pop("item")
            self.fields.pop("description")
            self.fields["source_line"].required = True
            self.fields["source_line"].queryset = (
                InvoiceLine.objects.filter(tenant=tenant, invoice__state="issued")
                .filter(
                    Q(invoice=parent)
                    | Q(invoice__parent=parent, invoice__kind="debit_note")
                )
                .select_related("invoice")
            )
            self.fields["source_line"].label_from_instance = lambda line: (
                f"{line.invoice.number}: {line.description} "
                f"({line.quantity} {line.unit})"
            )
        else:
            self.fields.pop("source_line")
            self.fields["item"].required = True
            self.fields["item"].queryset = CatalogItem.objects.filter(
                tenant=tenant,
                active=True,
                price__isnull=False,
                tax_rate__isnull=False,
                tax_treatment__isnull=False,
            )

    def payload(self):
        data = self.cleaned_data
        return {
            "item_id": data["item"].pk if data.get("item") else None,
            "source_line_id": data["source_line"].pk
            if data.get("source_line")
            else None,
            "description": data.get("description", ""),
            "quantity": data["quantity"],
            "unit_price": data["unit_price"],
            "discount": data.get("discount") or Decimal("0"),
        }


LineFormSet = formset_factory(
    LineForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=100,
    validate_max=True,
    absolute_max=100,
)


class IssueForm(RequestKeyForm):
    revision = forms.IntegerField(widget=forms.HiddenInput)


class SellerProfileForm(AccessibleFormMixin, forms.ModelForm):
    regular_seller = forms.BooleanField(
        label=(
            "This is a regular GST-registered business. "
            "I have reviewed whether this workflow is applicable."
        )
    )

    class Meta:
        model = SellerProfile
        fields = [
            "legal_name",
            "address",
            "gstin",
            "state_code",
            "payment_instructions",
            "signatory",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "payment_instructions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "checkbox"
                if isinstance(field.widget, forms.CheckboxInput)
                else "select select-bordered w-full"
                if isinstance(field.widget, forms.Select)
                else "textarea textarea-bordered w-full"
                if isinstance(field.widget, forms.Textarea)
                else "input input-bordered w-full"
            )
