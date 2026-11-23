import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.tenants.models import Tenant


class CatalogItem(models.Model):
    class Kind(models.TextChoices):
        PRODUCT = "product", "Product"
        SERVICE = "service", "Service"

    class TaxTreatment(models.TextChoices):
        TAXABLE = "taxable", "Taxable"
        EXEMPT = "exempt", "Exempt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="catalog_items"
    )
    sku = models.CharField(max_length=64, null=True, blank=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.TextField(max_length=1000, blank=True)
    unit = models.CharField(max_length=40, blank=True)
    price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    hsn_sac = models.CharField(
        max_length=16,
        blank=True,
        default="",
        validators=[RegexValidator(r"\A[0-9]+\Z", "Enter a numeric HSN or SAC code.")],
    )
    tax_treatment = models.CharField(
        max_length=12,
        choices=TaxTreatment.choices,
        null=True,
        blank=True,
        default=None,
    )
    tax_rate = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True
    )
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_catalog_items",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_items",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                F("tenant"),
                Lower("sku"),
                condition=Q(sku__isnull=False) & ~Q(sku=""),
                name="uq_catalog_tenant_sku_ci",
            ),
            models.CheckConstraint(
                # PostgreSQL orders numeric NaN above finite values. Include the
                # field's upper bound so nonnegative checks cannot admit NaN.
                condition=Q(price__isnull=True)
                | Q(price__gte=0, price__lte=Decimal("9999999999.9999")),
                name="catalog_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(tax_treatment__isnull=True, tax_rate__isnull=True, hsn_sac="")
                    | (
                        Q(tax_treatment__isnull=False, tax_rate__isnull=False)
                        & Q(hsn_sac__regex=r"\A[0-9]+\Z")
                        & (
                            Q(
                                tax_treatment="taxable",
                                tax_rate__gt=0,
                                tax_rate__lte=Decimal("999.9999"),
                            )
                            | Q(tax_treatment="exempt", tax_rate=0)
                        )
                    )
                ),
                name="catalog_tax_fields_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "name"], name="catalog_tenant_name_idx"),
            models.Index(fields=["tenant", "active"], name="catalog_tenant_active_idx"),
            models.Index(
                fields=["tenant", "created_at"], name="catalog_tenant_created_idx"
            ),
        ]

    @property
    def is_invoice_ready(self):
        return (
            self.price is not None
            and bool(self.hsn_sac)
            and self.tax_treatment is not None
            and self.tax_rate is not None
        )

    def clean(self):
        super().clean()
        if (
            isinstance(self.price, Decimal)
            and self.price.is_finite()
            and self.price < 0
        ):
            raise ValidationError({"price": "Price cannot be negative."})
        if not self.tax_treatment:
            if self.tax_rate is not None or self.hsn_sac:
                raise ValidationError(
                    "Set the HSN/SAC and tax treatment together with the tax rate."
                )
            return
        if not self.hsn_sac:
            raise ValidationError({"hsn_sac": "Enter the item's HSN/SAC code."})
        if self.tax_treatment == self.TaxTreatment.TAXABLE:
            if self.tax_rate is None or (
                isinstance(self.tax_rate, Decimal)
                and self.tax_rate.is_finite()
                and self.tax_rate <= 0
            ):
                raise ValidationError(
                    {"tax_rate": "Enter a positive GST rate for taxable items."}
                )
        elif self.tax_treatment == self.TaxTreatment.EXEMPT:
            if self.tax_rate not in (None, 0):
                raise ValidationError(
                    {"tax_rate": "Exempt items must have a zero rate."}
                )
            self.tax_rate = 0

    def __str__(self):
        return self.name
