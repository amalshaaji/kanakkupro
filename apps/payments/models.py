import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q


class Payment(models.Model):
    class Method(models.TextChoices):
        BANK = "bank", "Bank transfer"
        UPI = "upi", "UPI"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    invoice = models.ForeignKey(
        "sales.Invoice", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    date = models.DateField()
    method = models.CharField(max_length=8, choices=Method.choices)
    reference = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lte=Decimal("9999999999999999.99")),
                name="payment_positive_finite",
            ),
            models.CheckConstraint(condition=Q(currency="INR"), name="payment_inr"),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "invoice", "created_at"],
                name="payment_tenant_invoice_idx",
            )
        ]


class PaymentReversal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    invoice = models.ForeignKey("sales.Invoice", on_delete=models.PROTECT)
    payment = models.OneToOneField(
        Payment, on_delete=models.PROTECT, related_name="reversal"
    )
    reason = models.TextField(max_length=1000)
    date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
