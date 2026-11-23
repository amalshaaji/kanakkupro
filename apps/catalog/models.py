import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.tenants.models import Tenant


class CatalogItem(models.Model):
    class Kind(models.TextChoices):
        PRODUCT = "product", "Product"
        SERVICE = "service", "Service"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="catalog_items"
    )
    sku = models.CharField(max_length=64, null=True, blank=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.TextField(max_length=1000, blank=True)
    unit = models.CharField(max_length=40, blank=True)
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
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "name"], name="catalog_tenant_name_idx"),
            models.Index(fields=["tenant", "active"], name="catalog_tenant_active_idx"),
            models.Index(
                fields=["tenant", "created_at"], name="catalog_tenant_created_idx"
            ),
        ]

    def __str__(self):
        return self.name
