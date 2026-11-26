"""Business-owned pilot preparation. Never grants operator admission approval."""

import re

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404

from apps.audit.services import record_event
from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.payments.models import Payment
from apps.sales.models import Invoice, SellerProfile
from apps.sales.selectors import with_balances
from apps.tenants.models import PilotCheck, PilotFeedback, TenantMembership
from apps.tenants.permissions import membership_has_permission


def require_pilot_access(tenant, actor, *, lock=False):
    memberships = TenantMembership.objects
    if lock:
        memberships = memberships.select_for_update()
    member = memberships.filter(
        tenant=tenant, user=actor, status="active", tenant__status="active"
    ).first()
    if not membership_has_permission(member, "team.manage"):
        raise PermissionDenied


def pilot_progress(tenant, actor):
    require_pilot_access(tenant, actor)
    checks = [
        (
            "Verified account",
            EmailAddress.objects.filter(
                user=actor, email__iexact=actor.email, verified=True
            ).exists(),
            "account_email",
        ),
        (
            "Invoice settings",
            SellerProfile.objects.filter(tenant=tenant).exists(),
            "sales:settings",
        ),
        (
            "First customer",
            Customer.objects.filter(tenant=tenant, status="active").exists(),
            "customers:list",
        ),
        (
            "First catalog item",
            CatalogItem.objects.filter(tenant=tenant, active=True).exists(),
            "catalog:list",
        ),
        (
            "First issued invoice",
            Invoice.objects.filter(
                tenant=tenant, kind="invoice", state="issued"
            ).exists(),
            "sales:list",
        ),
        (
            "First recorded payment",
            Payment.objects.filter(tenant=tenant, reversal__isnull=True).exists(),
            "sales:list",
        ),
        (
            "First fully paid invoice",
            with_balances(
                Invoice.objects.filter(tenant=tenant, kind="invoice", state="issued")
            )
            .filter(adjusted_total__gt=0, received_amount__gt=0, outstanding_amount=0)
            .exists(),
            "sales:list",
        ),
    ]
    confirmed = set(
        PilotCheck.objects.filter(tenant=tenant, confirmed=True).values_list(
            "code", flat=True
        )
    )
    manual = [
        {"code": code, "label": label, "confirmed": code in confirmed}
        for code, label in PilotCheck.Code.choices
    ]
    completed = sum(bool(done) for _, done, _ in checks) + len(confirmed)
    total = len(checks) + len(manual)
    first = (
        Invoice.objects.filter(tenant=tenant, kind="invoice", state="issued")
        .order_by("issued_at")
        .first()
    )
    return {
        "setup_checks": [
            {"label": label, "complete": done, "route": route}
            for label, done, route in checks
        ],
        "manual_checks": manual,
        "completed": completed,
        "total": total,
        "percent": round(completed * 100 / total),
        "business_checks_complete": completed == total,
        "first_invoice_minutes": round(
            max(0, (first.issued_at - tenant.created_at).total_seconds()) / 60, 1
        )
        if first
        else None,
        "open_high_issues": PilotFeedback.objects.filter(
            tenant=tenant, kind="issue", severity="high"
        )
        .exclude(status="resolved")
        .count(),
    }


@transaction.atomic
def confirm_check(*, tenant, actor, code, confirmed, request_id=""):
    require_pilot_access(tenant, actor, lock=True)
    if code not in PilotCheck.Code.values or not isinstance(confirmed, bool):
        raise ValidationError("Choose a valid pilot check.")
    check, _ = PilotCheck.objects.update_or_create(
        tenant=tenant,
        code=code,
        defaults={"confirmed": confirmed, "reviewed_by": actor},
    )
    record_event(
        tenant=tenant,
        actor=actor,
        action="pilot.check_reviewed",
        entity_type="pilot_check",
        entity_id=check.pk,
        correlation_id=request_id,
        metadata={"code": code, "confirmed": confirmed},
    )
    return check


@transaction.atomic
def submit_feedback(*, tenant, actor, values, request_id=""):
    require_pilot_access(tenant, actor, lock=True)
    if set(values) - {"kind", "severity", "description", "request_id"}:
        raise ValidationError("Choose valid feedback fields.")
    values = {**values, "description": values.get("description", "").strip()}
    if len(values["description"]) > 2000:
        raise ValidationError("Keep feedback within 2,000 characters.")
    reference = values.get("request_id", "")
    if reference and not re.fullmatch(r"[a-f0-9]{32}", reference):
        raise ValidationError("Use a valid support reference.")
    feedback = PilotFeedback(tenant=tenant, submitted_by=actor, **values)
    feedback.full_clean()
    feedback.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="pilot.feedback_submitted",
        entity_type="pilot_feedback",
        entity_id=feedback.pk,
        correlation_id=request_id,
        metadata={"kind": feedback.kind, "severity": feedback.severity},
    )
    return feedback


@transaction.atomic
def update_feedback(*, tenant, actor, feedback_id, status, request_id=""):
    require_pilot_access(tenant, actor, lock=True)
    if status not in PilotFeedback.Status.values:
        raise ValidationError("Choose a valid feedback status.")
    feedback = (
        PilotFeedback.objects.select_for_update()
        .filter(pk=feedback_id, tenant=tenant)
        .first()
    )
    if feedback is None:
        raise Http404
    previous = feedback.status
    if previous == status:
        return feedback
    feedback.status = status
    feedback.save(update_fields=["status", "updated_at"])
    record_event(
        tenant=tenant,
        actor=actor,
        action="pilot.feedback_status_changed",
        entity_type="pilot_feedback",
        entity_id=feedback.pk,
        correlation_id=request_id,
        metadata={"from": previous, "to": status},
    )
    return feedback
