from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.payments.models import Payment
from apps.sales.models import Invoice

MONEY = DecimalField(max_digits=18, decimal_places=2)
ZERO = Value(Decimal("0.00"), output_field=MONEY)


def with_balances(queryset):
    def correction_sum(kind):
        return Coalesce(
            Subquery(
                Invoice.objects.filter(
                    tenant_id=OuterRef("tenant_id"),
                    parent_id=OuterRef("pk"),
                    state="issued",
                    kind=kind,
                )
                .order_by()
                .values("parent_id")
                .annotate(value=Sum("total"))
                .values("value")[:1],
                output_field=MONEY,
            ),
            ZERO,
        )

    receipts = (
        Payment.objects.filter(
            tenant_id=OuterRef("tenant_id"),
            invoice_id=OuterRef("pk"),
            reversal__isnull=True,
        )
        .order_by()
        .values("invoice_id")
        .annotate(value=Sum("amount"))
        .values("value")[:1]
    )
    return (
        queryset.annotate(
            credited_amount=correction_sum("credit_note"),
            debited_amount=correction_sum("debit_note"),
            received_amount=Coalesce(Subquery(receipts, output_field=MONEY), ZERO),
        )
        .annotate(
            adjusted_total=ExpressionWrapper(
                F("total") + F("debited_amount") - F("credited_amount"),
                output_field=MONEY,
            ),
        )
        .annotate(
            outstanding_amount=ExpressionWrapper(
                F("adjusted_total") - F("received_amount"), output_field=MONEY
            ),
        )
    )


def invoice_financials(invoice):
    if not hasattr(invoice, "outstanding_amount"):
        invoice = with_balances(
            Invoice.objects.filter(tenant_id=invoice.tenant_id)
        ).get(pk=invoice.pk)
    if invoice.is_draft:
        status = "Draft"
    elif invoice.adjusted_total == 0:
        status = "Credited"
    elif invoice.outstanding_amount == 0:
        status = "Paid"
    elif invoice.received_amount > 0:
        status = "Partially paid"
    else:
        status = "Issued"
    return {
        "credits": invoice.credited_amount,
        "debits": invoice.debited_amount,
        "adjusted_total": invoice.adjusted_total,
        "received": invoice.received_amount,
        "outstanding": invoice.outstanding_amount,
        "status": status,
    }


def financial_summary(tenant):
    invoices = with_balances(
        Invoice.objects.filter(tenant=tenant, state="issued", kind="invoice")
    )
    totals = invoices.aggregate(
        invoiced=Coalesce(Sum("adjusted_total"), ZERO),
        receipts=Coalesce(Sum("received_amount"), ZERO),
        receivables=Coalesce(Sum("outstanding_amount"), ZERO),
    )
    today = timezone.now().astimezone(ZoneInfo(tenant.timezone)).date()
    totals["overdue"] = invoices.filter(
        due_date__lt=today, outstanding_amount__gt=0
    ).aggregate(value=Coalesce(Sum("outstanding_amount"), ZERO))["value"]
    totals["overdue_count"] = invoices.filter(
        due_date__lt=today, outstanding_amount__gt=0
    ).count()
    totals["draft_count"] = Invoice.objects.filter(tenant=tenant, state="draft").count()
    return totals
