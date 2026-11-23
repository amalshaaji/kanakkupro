from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.catalog.models import CatalogItem
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission

EDITABLE_FIELDS = ("name", "kind", "sku", "description", "unit")


def create_catalog_item(*, tenant, actor, values):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        fields = {field: values[field] for field in EDITABLE_FIELDS}
        return CatalogItem.objects.create(
            tenant=tenant, created_by=actor, updated_by=actor, **fields
        )


def update_catalog_item(*, tenant, actor, item_id, values):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        item = CatalogItem.objects.select_for_update().get(pk=item_id, tenant=tenant)
        for field in EDITABLE_FIELDS:
            setattr(item, field, values[field])
        item.updated_by = actor
        item.save(update_fields=[*EDITABLE_FIELDS, "updated_by", "updated_at"])
    return item


def set_catalog_item_active(*, tenant, actor, item_id, active):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        item = CatalogItem.objects.select_for_update().get(pk=item_id, tenant=tenant)
        item.active = active
        item.updated_by = actor
        item.save(update_fields=["active", "updated_by", "updated_at"])
    return item


def _require_catalog_permission(*, tenant, actor):
    membership = TenantMembership.objects.filter(
        tenant=tenant,
        user=actor,
        status=TenantMembership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    ).first()
    if not membership_has_permission(membership, "catalog.manage"):
        raise PermissionDenied
