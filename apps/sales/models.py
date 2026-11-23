import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.sales.validation import STATE_CHOICES, validate_gstin


def money_field():
    return models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))


class SellerProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="seller_profile"
    )
    legal_name = models.CharField(max_length=200)
    address = models.TextField(max_length=1000)
    gstin = models.CharField(max_length=15, validators=[validate_gstin])
    state_code = models.CharField(max_length=2, choices=STATE_CHOICES[1:])
    payment_instructions = models.TextField(max_length=1000, blank=True)
    signatory = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.gstin and self.gstin[:2] != self.state_code:
            raise ValidationError(
                {"state_code": "State must match the GSTIN registration."}
            )


class Invoice(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"

    class Kind(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        CREDIT = "credit_note", "Credit note"
        DEBIT = "debit_note", "Debit note"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="invoices"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="invoices"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.INVOICE)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
    )
    reason = models.TextField(max_length=1000, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT)
    number = models.CharField(max_length=16, null=True, blank=True)
    currency = models.CharField(max_length=3, default="INR")
    issue_date = models.DateField()
    due_date = models.DateField()
    place_of_supply = models.CharField(max_length=2, choices=STATE_CHOICES[1:])
    supply_type = models.CharField(
        max_length=12,
        choices=[
            ("intra_state", "Intra-State (CGST + SGST)"),
            ("inter_state", "Inter-State (IGST)"),
        ],
    )
    buyer_gstin = models.CharField(
        max_length=15, blank=True, validators=[validate_gstin]
    )
    buyer_state = models.CharField(max_length=2, choices=STATE_CHOICES[1:])
    delivery_address = models.TextField(max_length=1000)
    notes = models.TextField(max_length=1000, blank=True)
    scope_confirmed = models.BooleanField(default=False)
    seller_snapshot = models.JSONField(default=dict, blank=True)
    buyer_snapshot = models.JSONField(default=dict, blank=True)
    discount_total = money_field()
    taxable_total = money_field()
    cgst = money_field()
    sgst = money_field()
    igst = money_field()
    total = money_field()
    revision = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issued_invoices",
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "number"],
                condition=Q(number__isnull=False),
                name="uq_invoice_tenant_number",
            ),
            models.CheckConstraint(
                condition=Q(due_date__gte=F("issue_date")),
                name="invoice_due_after_issue",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="invoice", parent__isnull=True)
                    | Q(kind__in=["credit_note", "debit_note"], parent__isnull=False)
                )
                & ~Q(parent=F("id")),
                name="invoice_correction_reference",
            ),
            models.CheckConstraint(condition=Q(currency="INR"), name="invoice_v1_inr"),
            models.CheckConstraint(
                condition=Q(
                    state="draft",
                    number__isnull=True,
                    issued_at__isnull=True,
                    issued_by__isnull=True,
                )
                | Q(
                    state="issued",
                    number__isnull=False,
                    issued_at__isnull=False,
                    issued_by__isnull=False,
                ),
                name="invoice_state_consistent",
            ),
            *[
                models.CheckConstraint(
                    condition=Q(
                        **{
                            f"{field}__gte": 0,
                            f"{field}__lte": Decimal("9999999999999999.99"),
                        }
                    ),
                    name=f"invoice_{field}_finite",
                )
                for field in (
                    "discount_total",
                    "taxable_total",
                    "cgst",
                    "sgst",
                    "igst",
                    "total",
                )
            ],
            models.CheckConstraint(
                condition=Q(
                    total=F("taxable_total") + F("cgst") + F("sgst") + F("igst")
                ),
                name="invoice_totals_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "state", "issue_date"],
                name="invoice_tenant_state_date_idx",
            )
        ]

    @property
    def is_draft(self):
        return self.state == self.State.DRAFT

    @property
    def tax_total(self):
        return self.cgst + self.sgst + self.igst

    @property
    def financials(self):
        from apps.sales.selectors import invoice_financials

        return invoice_financials(self)

    @property
    def is_overdue(self):
        return (
            not self.is_draft
            and self.kind == self.Kind.INVOICE
            and self.due_date
            < timezone.now().astimezone(ZoneInfo(self.tenant.timezone)).date()
            and self.financials["outstanding"] > 0
        )

    def __str__(self):
        return self.number or f"Draft {str(self.pk)[:8]}"


class InvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("catalog.CatalogItem", on_delete=models.PROTECT)
    source_line = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credit_lines",
    )
    position = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=1000)
    unit = models.CharField(max_length=40)
    hsn_sac = models.CharField(max_length=16)
    tax_treatment = models.CharField(max_length=12)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    discount = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0")
    )
    tax_rate = models.DecimalField(max_digits=7, decimal_places=4)
    taxable_value = models.DecimalField(max_digits=18, decimal_places=4)
    taxable_amount = money_field()
    cgst = money_field()
    sgst = money_field()
    igst = money_field()
    total = money_field()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "position"], name="uq_invoice_line_position"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0, quantity__lte=Decimal("9999999999.9999")),
                name="line_quantity_positive",
            ),
            *[
                models.CheckConstraint(
                    condition=Q(
                        **{
                            f"{field}__gte": 0,
                            f"{field}__lte": Decimal("99999999999999.9999"),
                        }
                    ),
                    name=f"line_{field}_finite",
                )
                for field in (
                    "unit_price",
                    "discount",
                    "tax_rate",
                    "taxable_value",
                    "taxable_amount",
                    "cgst",
                    "sgst",
                    "igst",
                    "total",
                )
            ],
            models.CheckConstraint(
                condition=Q(
                    total=F("taxable_amount") + F("cgst") + F("sgst") + F("igst")
                ),
                name="line_totals_consistent",
            ),
        ]


class InvoiceSequence(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    financial_year = models.PositiveSmallIntegerField()
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "financial_year"], name="uq_invoice_sequence_year"
            )
        ]


class FinancialCommand(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    key = models.UUIDField()
    operation = models.CharField(max_length=32)
    fingerprint = models.CharField(max_length=64)
    response_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "operation", "key"], name="uq_financial_command_key"
            )
        ]
