from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import record_event
from apps.catalog.models import CatalogItem
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission

EDITABLE_FIELDS = ("name", "kind", "sku", "description", "unit")


def create_catalog_item(*, tenant, actor, values, correlation_id=""):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        fields = {field: values[field] for field in EDITABLE_FIELDS}
        item = CatalogItem.objects.create(
            tenant=tenant, created_by=actor, updated_by=actor, **fields
        )
        record_event(
            tenant=tenant,
            actor=actor,
            action="catalog_item.created",
            entity_type="catalog_item",
            entity_id=item.pk,
            correlation_id=correlation_id,
            metadata={"kind": item.kind},
        )
    return item


def update_catalog_item(*, tenant, actor, item_id, values, correlation_id=""):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        item = CatalogItem.objects.select_for_update().get(pk=item_id, tenant=tenant)
        for field in EDITABLE_FIELDS:
            setattr(item, field, values[field])
        item.updated_by = actor
        item.save(update_fields=[*EDITABLE_FIELDS, "updated_by", "updated_at"])
        record_event(
            tenant=tenant,
            actor=actor,
            action="catalog_item.updated",
            entity_type="catalog_item",
            entity_id=item.pk,
            correlation_id=correlation_id,
            metadata={"kind": item.kind},
        )
    return item


def set_catalog_item_active(*, tenant, actor, item_id, active, correlation_id=""):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        item = CatalogItem.objects.select_for_update().get(pk=item_id, tenant=tenant)
        item.active = active
        item.updated_by = actor
        item.save(update_fields=["active", "updated_by", "updated_at"])
        record_event(
            tenant=tenant,
            actor=actor,
            action="catalog_item.restored" if active else "catalog_item.archived",
            entity_type="catalog_item",
            entity_id=item.pk,
            correlation_id=correlation_id,
            metadata={"active": active},
        )
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
