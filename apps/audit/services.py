from apps.audit.models import AuditEvent


def record_event(
    *,
    tenant,
    actor,
    action,
    entity_type,
    entity_id=None,
    correlation_id="",
    metadata=None,
):
    """Write a minimal audit record inside the caller's transaction."""
    return AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        metadata=metadata or {},
    )
