"""Date-filtered document and cash movement reports; never rewrite ledger history."""

from django.db.models import Case, F, Sum, When
from django.db.models.functions import Coalesce

from apps.payments.models import Payment, PaymentReversal
from apps.sales.models import Invoice
from apps.sales.selectors import MONEY, ZERO


def in_period(queryset, field, period):
    for key, lookup in (("start", "gte"), ("end", "lte")):
        if period.get(key):
            queryset = queryset.filter(**{f"{field}__{lookup}": period[key]})
    return queryset


def financial_report(tenant, period):
    documents = in_period(
        Invoice.objects.filter(tenant=tenant, state="issued"), "issue_date", period
    ).annotate(
        signed_total=Case(
            When(kind="credit_note", then=-F("total")),
            default=F("total"),
            output_field=MONEY,
        )
    )
    payments = in_period(Payment.objects.filter(tenant=tenant), "date", period)
    reversals = in_period(PaymentReversal.objects.filter(tenant=tenant), "date", period)
    sales = documents.aggregate(total=Coalesce(Sum("signed_total"), ZERO))["total"]
    receipts = payments.aggregate(total=Coalesce(Sum("amount"), ZERO))["total"]
    reversed_amount = reversals.aggregate(total=Coalesce(Sum("payment__amount"), ZERO))[
        "total"
    ]
    customers = (
        documents.values("customer_id", "customer__name")
        .annotate(total=Sum("signed_total"))
        .order_by("-total", "customer_id")
    )
    return {
        "documents": documents.select_related("customer").order_by(
            "-issue_date", "-id"
        ),
        "payments": payments.select_related("invoice", "invoice__customer").order_by(
            "-date", "-id"
        ),
        "reversals": reversals.select_related("payment", "invoice").order_by(
            "-date", "-id"
        ),
        "customer_sales": customers,
        "period_sales": sales,
        "period_receipts": receipts,
        "period_reversals": reversed_amount,
        "period_net_receipts": receipts - reversed_amount,
    }
