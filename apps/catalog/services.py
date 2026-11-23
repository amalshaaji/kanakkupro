from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.catalog.models import CatalogItem
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission

EDITABLE_FIELDS = (
    "name",
    "kind",
    "sku",
    "description",
    "unit",
    "price",
    "hsn_sac",
    "tax_treatment",
    "tax_rate",
)


def create_catalog_item(*, tenant, actor, values, correlation_id=""):
    with transaction.atomic():
        _require_catalog_permission(tenant=tenant, actor=actor)
        fields = _editable_values(values)
        item = CatalogItem(tenant=tenant, created_by=actor, updated_by=actor, **fields)
        item.full_clean()
        item.save()
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
        for field, value in _editable_values(values).items():
            setattr(item, field, value)
        item.updated_by = actor
        item.full_clean()
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


def _editable_values(values):
    fields = {field: values[field] for field in EDITABLE_FIELDS}
    for field in ("price", "tax_rate"):
        if isinstance(fields[field], (float, bool)):
            raise ValidationError({field: "Use an exact decimal value."})
    return fields


def _require_catalog_permission(*, tenant, actor):
    membership = TenantMembership.objects.filter(
        tenant=tenant,
        user=actor,
        status=TenantMembership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    ).first()
    if not membership_has_permission(membership, "catalog.manage"):
        raise PermissionDenied
