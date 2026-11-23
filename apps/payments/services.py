from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.payments.models import Payment, PaymentReversal
from apps.sales.models import Invoice
from apps.sales.selectors import invoice_financials
from apps.sales.services import (
    _date,
    command_replay,
    finish_command,
    require_financial_permission,
    today_for,
)
from apps.sales.validation import exact_decimal


@transaction.atomic
def record_payment(*, tenant, actor, invoice_id, values, key, correlation_id=""):
    tenant = require_financial_permission(
        tenant=tenant, actor=actor, permission="payments.record"
    )
    key, fingerprint, previous = command_replay(
        tenant=tenant,
        operation="payment.record",
        key=key,
        payload={"invoice": invoice_id, "values": values},
    )
    if previous:
        return Payment.objects.get(tenant=tenant, pk=previous)
    invoice = Invoice.objects.select_for_update().get(tenant=tenant, pk=invoice_id)
    if invoice.state != "issued" or invoice.kind != "invoice":
        raise ValidationError("Payments can only be recorded against issued invoices.")
    amount = exact_decimal(
        values["amount"],
        places=2,
        maximum=Decimal("9999999999999999.99"),
        positive=True,
    )
    payment_date = _date(values["date"])
    if not invoice.issue_date <= payment_date <= today_for(tenant):
        raise ValidationError(
            "Payment date must be between the invoice date and today."
        )
    if amount > invoice_financials(invoice)["outstanding"]:
        raise ValidationError("Payment cannot exceed the outstanding balance.")
    payment = Payment(
        tenant=tenant,
        invoice=invoice,
        amount=amount,
        currency=invoice.currency,
        date=payment_date,
        method=values["method"],
        reference=values.get("reference", ""),
        created_by=actor,
    )
    payment.full_clean()
    payment.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="payment.recorded",
        entity_type="payment",
        entity_id=payment.pk,
        correlation_id=correlation_id,
    )
    finish_command(
        tenant=tenant,
        operation="payment.record",
        key=key,
        fingerprint=fingerprint,
        response_id=payment.pk,
    )
    return payment


@transaction.atomic
def reverse_payment(*, tenant, actor, payment_id, reason, date, key, correlation_id=""):
    tenant = require_financial_permission(
        tenant=tenant, actor=actor, permission="payments.reverse"
    )
    key, fingerprint, previous = command_replay(
        tenant=tenant,
        operation="payment.reverse",
        key=key,
        payload={"payment": payment_id, "reason": reason, "date": date},
    )
    if previous:
        return PaymentReversal.objects.get(tenant=tenant, pk=previous)
    payment = Payment.objects.select_for_update().get(tenant=tenant, pk=payment_id)
    Invoice.objects.select_for_update().get(tenant=tenant, pk=payment.invoice_id)
    reversal_date = _date(date)
    if not reason.strip():
        raise ValidationError("Enter the reason for reversing this payment.")
    if not payment.date <= reversal_date <= today_for(tenant):
        raise ValidationError(
            "Reversal date must be between the payment date and today."
        )
    if PaymentReversal.objects.filter(tenant=tenant, payment=payment).exists():
        raise ValidationError("This payment has already been reversed.")
    reversal = PaymentReversal(
        tenant=tenant,
        invoice=payment.invoice,
        payment=payment,
        reason=reason.strip(),
        date=reversal_date,
        created_by=actor,
    )
    reversal.full_clean()
    reversal.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="payment.reversed",
        entity_type="payment_reversal",
        entity_id=reversal.pk,
        correlation_id=correlation_id,
    )
    finish_command(
        tenant=tenant,
        operation="payment.reverse",
        key=key,
        fingerprint=fingerprint,
        response_id=reversal.pk,
    )
    return reversal
