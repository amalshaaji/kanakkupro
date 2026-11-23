from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import record_event
from apps.customers.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission

EDITABLE_FIELDS = (
    "name",
    "company_name",
    "email",
    "phone",
    "billing_address",
    "country",
)


def create_customer(*, tenant, actor, values, correlation_id=""):
    with transaction.atomic():
        _require_customer_permission(tenant=tenant, actor=actor)
        customer_values = {field: values[field] for field in EDITABLE_FIELDS}
        customer = Customer.objects.create(
            tenant=tenant,
            created_by=actor,
            updated_by=actor,
            **customer_values,
        )
        record_event(
            tenant=tenant,
            actor=actor,
            action="customer.created",
            entity_type="customer",
            entity_id=customer.pk,
            correlation_id=correlation_id,
        )
    return customer


def update_customer(*, tenant, actor, customer_id, values, correlation_id=""):
    with transaction.atomic():
        _require_customer_permission(tenant=tenant, actor=actor)
        customer = Customer.objects.select_for_update().get(
            pk=customer_id, tenant=tenant
        )
        for field in EDITABLE_FIELDS:
            setattr(customer, field, values[field])
        customer.updated_by = actor
        customer.save(update_fields=[*EDITABLE_FIELDS, "updated_by", "updated_at"])
        record_event(
            tenant=tenant,
            actor=actor,
            action="customer.updated",
            entity_type="customer",
            entity_id=customer.pk,
            correlation_id=correlation_id,
        )
    return customer


def set_customer_status(*, tenant, actor, customer_id, status, correlation_id=""):
    if status not in Customer.Status.values:
        raise ValueError("Invalid customer status.")
    with transaction.atomic():
        _require_customer_permission(tenant=tenant, actor=actor)
        customer = Customer.objects.select_for_update().get(
            pk=customer_id, tenant=tenant
        )
        customer.status = status
        customer.updated_by = actor
        customer.save(update_fields=["status", "updated_by", "updated_at"])
        action = (
            "customer.restored"
            if status == Customer.Status.ACTIVE
            else "customer.archived"
        )
        record_event(
            tenant=tenant,
            actor=actor,
            action=action,
            entity_type="customer",
            entity_id=customer.pk,
            correlation_id=correlation_id,
            metadata={"status": status},
        )
    return customer


def _require_customer_permission(*, tenant, actor):
    membership = TenantMembership.objects.filter(
        tenant=tenant,
        user=actor,
        status=TenantMembership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    ).first()
    if not membership_has_permission(membership, "customers.manage"):
        raise PermissionDenied
