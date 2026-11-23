from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.permissions import tenant_permission_required
from apps.payments.forms import PaymentForm, ReversalForm
from apps.payments.models import Payment
from apps.payments.services import record_payment, reverse_payment
from apps.sales.models import Invoice
from apps.sales.services import today_for


@login_required
@require_POST
@tenant_permission_required("payments.record")
def record(request, invoice_id):
    invoice = get_object_or_404(
        Invoice, tenant=request.tenant, pk=invoice_id, state="issued", kind="invoice"
    )
    form = PaymentForm(request.POST)
    if form.is_valid():
        try:
            record_payment(
                tenant=request.tenant,
                actor=request.user,
                invoice_id=invoice.pk,
                values={
                    field: form.cleaned_data[field]
                    for field in ("amount", "date", "method", "reference")
                },
                key=form.cleaned_data["key"],
                correlation_id=request.request_id,
            )
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, "Payment recorded.")
            return redirect("sales:detail", invoice_id=invoice.pk)
    return render(
        request,
        "payments/form.html",
        {"form": form, "invoice": invoice, "heading": "Record payment"},
        status=422,
    )


@login_required
@tenant_permission_required("payments.reverse")
def reverse(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related("invoice"), tenant=request.tenant, pk=payment_id
    )
    form = ReversalForm(
        request.POST or None, initial={"date": today_for(request.tenant)}
    )
    if request.method == "POST" and form.is_valid():
        try:
            reverse_payment(
                tenant=request.tenant,
                actor=request.user,
                payment_id=payment.pk,
                reason=form.cleaned_data["reason"],
                date=form.cleaned_data["date"],
                key=form.cleaned_data["key"],
                correlation_id=request.request_id,
            )
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(
                request, "Payment reversed. The original entry remains in the ledger."
            )
            return redirect("sales:detail", invoice_id=payment.invoice_id)
    return render(
        request,
        "payments/form.html",
        {
            "form": form,
            "invoice": payment.invoice,
            "heading": "Reverse payment",
            "payment": payment,
        },
    )
