from decimal import Decimal

from django import forms

from apps.payments.models import Payment
from apps.sales.forms import RequestKeyForm


class PaymentForm(RequestKeyForm):
    amount = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01")
    )
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    method = forms.ChoiceField(choices=Payment.Method.choices)
    reference = forms.CharField(
        max_length=200,
        required=False,
        help_text="Payment reference only. Do not enter card or account credentials.",
    )


class ReversalForm(RequestKeyForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)
