import uuid

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Customer(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="customers"
    )
    name = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    billing_address = models.TextField(max_length=1000, blank=True)
    country = models.CharField(max_length=2, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_customers",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_customers",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["tenant", "name"], name="customer_tenant_name_idx"),
            models.Index(
                fields=["tenant", "status"], name="customer_tenant_status_idx"
            ),
            models.Index(
                fields=["tenant", "created_at"], name="customer_tenant_created_idx"
            ),
        ]

    def __str__(self):
        return self.company_name or self.name
