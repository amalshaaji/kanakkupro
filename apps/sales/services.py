import hashlib
import json
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.sales.calculations import calculate_line_gst
from apps.sales.models import (
    FinancialCommand,
    Invoice,
    InvoiceLine,
    InvoiceSequence,
    SellerProfile,
)
from apps.sales.validation import STATES, UTGST_STATES, exact_decimal, validate_gstin
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission

PAISE = Decimal("0.01")
FOUR = Decimal("0.0001")
MAX_LINES = 100
HEADER_FIELDS = (
    "issue_date",
    "due_date",
    "place_of_supply",
    "supply_type",
    "buyer_gstin",
    "buyer_state",
    "delivery_address",
    "notes",
    "reason",
)


def require_financial_permission(*, tenant, actor, permission):
    """Lock tenant before membership and document rows in every financial writer.

    Serializing writes per workspace makes the first sequence allocation and
    idempotency lookup safe, including two requests for different invoices.
    """
    try:
        tenant = Tenant.objects.select_for_update().get(
            pk=tenant.pk, status=Tenant.Status.ACTIVE
        )
    except Tenant.DoesNotExist as error:
        raise PermissionDenied from error
    membership = (
        TenantMembership.objects.select_for_update()
        .filter(tenant=tenant, user=actor, user__is_active=True, status="active")
        .first()
    )
    if not membership_has_permission(membership, permission):
        raise PermissionDenied
    return tenant


def today_for(tenant):
    return timezone.now().astimezone(ZoneInfo(tenant.timezone)).date()


def _request_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def command_replay(*, tenant, operation, key, payload):
    try:
        key = uuid.UUID(str(key))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError(
            "A valid request key is required. Reload the form."
        ) from error
    fingerprint = _request_fingerprint(payload)
    previous = FinancialCommand.objects.filter(
        tenant=tenant, operation=operation, key=key
    ).first()
    if previous and previous.fingerprint != fingerprint:
        raise ValidationError(
            "This request key was already used for different details. Reload the form."
        )
    return key, fingerprint, previous.response_id if previous else None


def finish_command(*, tenant, operation, key, fingerprint, response_id):
    FinancialCommand.objects.create(
        tenant=tenant,
        operation=operation,
        key=key,
        fingerprint=fingerprint,
        response_id=response_id,
    )


@transaction.atomic
def save_seller_profile(*, tenant, actor, values, correlation_id=""):
    tenant = require_financial_permission(
        tenant=tenant, actor=actor, permission="business.manage"
    )
    if tenant.country != "IN" or tenant.currency != "INR":
        raise ValidationError("Invoice V1 requires an India workspace using INR.")
    profile = SellerProfile.objects.filter(tenant=tenant).first() or SellerProfile(
        tenant=tenant
    )
    for field in (
        "legal_name",
        "address",
        "gstin",
        "state_code",
        "payment_instructions",
        "signatory",
    ):
        setattr(profile, field, values[field].strip())
    profile.full_clean()
    profile.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="seller_profile.updated",
        entity_type="seller_profile",
        entity_id=profile.pk,
        correlation_id=correlation_id,
    )
    return profile


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as error:
        raise ValidationError("Enter a valid date.") from error


def _header(invoice, data, tenant):
    invoice.scope_confirmed = data.get("supported_supply") is True
    if not invoice.scope_confirmed:
        raise ValidationError("Confirm the supported domestic supply scope.")
    invoice.issue_date = _date(data["issue_date"])
    invoice.due_date = _date(data["due_date"])
    for field in HEADER_FIELDS[2:]:
        setattr(invoice, field, str(data.get(field, "")).strip())
    invoice.buyer_gstin = invoice.buyer_gstin.upper()
    if invoice.buyer_gstin:
        validate_gstin(invoice.buyer_gstin)
        if invoice.buyer_gstin[:2] != invoice.buyer_state:
            raise ValidationError("Buyer state must match the buyer GSTIN.")
    if invoice.issue_date > today_for(tenant):
        raise ValidationError("Invoices cannot be dated in the future.")
    if invoice.parent_id:
        parent = invoice.parent
        if parent.state != "issued" or parent.kind != "invoice":
            raise ValidationError("Corrections must reference an issued invoice.")
        if not invoice.reason:
            raise ValidationError("Enter a reason for the correction.")
        if invoice.issue_date < parent.issue_date:
            raise ValidationError("A correction cannot predate its invoice.")
        for field in (
            "place_of_supply",
            "supply_type",
            "buyer_gstin",
            "buyer_state",
            "delivery_address",
        ):
            setattr(invoice, field, getattr(parent, field))


def _line(invoice, raw, position):
    if invoice.kind == "credit_note":
        source = (
            InvoiceLine.objects.select_related("invoice")
            .filter(
                tenant_id=invoice.tenant_id,
                pk=raw.get("source_line_id"),
                invoice__state="issued",
            )
            .filter(invoice_id=invoice.parent_id)
            .first()
        )
        if source is None:
            # Debit-note lines can also be credited, within the same root invoice.
            source = (
                InvoiceLine.objects.select_related("invoice")
                .filter(
                    tenant_id=invoice.tenant_id,
                    pk=raw.get("source_line_id"),
                    invoice__parent_id=invoice.parent_id,
                    invoice__kind="debit_note",
                    invoice__state="issued",
                )
                .first()
            )
        if source is None:
            raise ValidationError(
                "Choose an original invoice or debit-note line to credit."
            )
        item = source.item
        description, unit, code = source.description, source.unit, source.hsn_sac
        treatment, rate = source.tax_treatment, source.tax_rate
        default_price = source.unit_price
    else:
        source = None
        try:
            item = CatalogItem.objects.get(
                pk=raw.get("item_id"), tenant_id=invoice.tenant_id, active=True
            )
        except (CatalogItem.DoesNotExist, ValidationError, ValueError) as error:
            raise ValidationError(
                "Choose an active item from this business."
            ) from error
        if not item.is_invoice_ready:
            raise ValidationError(
                "Complete the item's price and GST classification first."
            )
        item.full_clean()
        description = str(raw.get("description") or item.name).strip()
        unit = item.unit or ("service" if item.kind == "service" else "")
        if not unit:
            raise ValidationError(
                "Set a unit for goods in the catalog before invoicing."
            )
        code, treatment, rate, default_price = (
            item.hsn_sac,
            item.tax_treatment,
            item.tax_rate,
            item.price,
        )
    quantity = exact_decimal(raw.get("quantity"), positive=True)
    price = exact_decimal(
        raw.get("unit_price")
        if raw.get("unit_price") not in (None, "")
        else default_price
    )
    discount = exact_decimal(
        raw.get("discount", "0"), places=2, maximum=Decimal("99999999999999.99")
    )
    with localcontext() as context:
        context.prec = 48
        gross = (quantity * price).quantize(FOUR, rounding=ROUND_HALF_UP)
        if discount > gross:
            raise ValidationError(
                "Line discount cannot exceed quantity times unit price."
            )
        taxable = gross - discount
        tax = calculate_line_gst(
            taxable_value=taxable, rate_percent=rate, supply_type=invoice.supply_type
        )
        amount = taxable.quantize(PAISE, rounding=ROUND_HALF_UP)
    line = InvoiceLine(
        tenant_id=invoice.tenant_id,
        invoice=invoice,
        item=item,
        source_line=source,
        position=position,
        description=description,
        unit=unit,
        hsn_sac=code,
        tax_treatment=treatment,
        quantity=quantity,
        unit_price=price,
        discount=discount,
        tax_rate=rate,
        taxable_value=taxable,
        taxable_amount=amount,
        cgst=tax.cgst,
        sgst=tax.sgst,
        igst=tax.igst,
        total=amount + tax.total,
    )
    # Invoice has not been inserted for new drafts, so validate the relation
    # and all other field values after saving the header below.
    return line


@transaction.atomic
def save_draft(
    *,
    tenant,
    actor,
    data,
    lines,
    key,
    invoice_id=None,
    revision=None,
    correlation_id="",
):
    permission = (
        "invoices.correct"
        if data.get("kind", "invoice") != "invoice"
        else "invoices.manage"
    )
    tenant = require_financial_permission(
        tenant=tenant, actor=actor, permission=permission
    )
    if tenant.country != "IN" or tenant.currency != "INR":
        raise ValidationError("Invoice V1 requires an India workspace using INR.")
    operation = "invoice.update" if invoice_id else "invoice.create"
    payload = {
        "data": data,
        "lines": lines,
        "invoice": invoice_id,
        "revision": revision,
    }
    key, fingerprint, previous = command_replay(
        tenant=tenant, operation=operation, key=key, payload=payload
    )
    if previous:
        return Invoice.objects.get(tenant=tenant, pk=previous)
    if invoice_id:
        invoice = Invoice.objects.select_for_update().get(tenant=tenant, pk=invoice_id)
        if not invoice.is_draft:
            raise ValidationError(
                "Issued documents cannot be edited. Create a linked correction note."
            )
        if invoice.revision != revision:
            raise ValidationError(
                "This draft changed in another session. Reload before saving."
            )
        if invoice.kind != data.get("kind", "invoice"):
            raise ValidationError("The document type cannot be changed.")
        invoice.revision += 1
    else:
        invoice = Invoice(
            tenant=tenant, created_by=actor, kind=data.get("kind", "invoice")
        )
        if invoice.kind not in Invoice.Kind.values:
            raise ValidationError("Unsupported document type.")
        if invoice.kind != "invoice":
            invoice.parent = Invoice.objects.get(
                tenant=tenant, pk=data.get("parent_id"), state="issued", kind="invoice"
            )
    if invoice.parent_id:
        invoice.customer = invoice.parent.customer
    else:
        try:
            invoice.customer = Customer.objects.get(
                tenant=tenant, pk=data.get("customer_id"), status="active"
            )
        except (Customer.DoesNotExist, ValidationError, ValueError) as error:
            raise ValidationError(
                "Choose an active customer from this business."
            ) from error
    _header(invoice, data, tenant)
    if not 1 <= len(lines) <= MAX_LINES:
        raise ValidationError(f"Include between 1 and {MAX_LINES} lines.")
    calculated = [
        _line(invoice, raw, position) for position, raw in enumerate(lines, start=1)
    ]
    invoice.discount_total = sum(
        (line.discount.quantize(PAISE, rounding=ROUND_HALF_UP) for line in calculated),
        Decimal("0"),
    )
    for field, line_field in (
        ("taxable_total", "taxable_amount"),
        ("cgst", "cgst"),
        ("sgst", "sgst"),
        ("igst", "igst"),
        ("total", "total"),
    ):
        setattr(
            invoice,
            field,
            sum((getattr(line, line_field) for line in calculated), Decimal("0")),
        )
    invoice.full_clean()
    invoice.save()
    InvoiceLine.objects.filter(tenant=tenant, invoice=invoice).delete()
    for line in calculated:
        line.full_clean()
        line.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="invoice.draft_saved",
        entity_type="invoice",
        entity_id=invoice.pk,
        correlation_id=correlation_id,
    )
    finish_command(
        tenant=tenant,
        operation=operation,
        key=key,
        fingerprint=fingerprint,
        response_id=invoice.pk,
    )
    return invoice


def _validate_credit(invoice):
    from apps.sales.selectors import invoice_financials

    if invoice.total > invoice_financials(invoice.parent)["outstanding"]:
        raise ValidationError(
            "A credit cannot exceed the unpaid balance. "
            "Refunds require a separate workflow."
        )
    proposed = {}
    for line in invoice.lines.select_related("source_line"):
        if not line.source_line_id:
            raise ValidationError("Every credit line must reference an issued line.")
        proposed.setdefault(line.source_line_id, []).append(line)
    for source_id, lines in proposed.items():
        source = lines[0].source_line
        previous = InvoiceLine.objects.filter(
            tenant_id=invoice.tenant_id,
            source_line_id=source_id,
            invoice__state="issued",
            invoice__kind="credit_note",
        ).aggregate(
            **{
                field: Sum(field)
                for field in ("quantity", "taxable_value", "cgst", "sgst", "igst")
            }
        )
        for field in previous:
            used = previous[field] or Decimal("0")
            if used + sum(getattr(line, field) for line in lines) > getattr(
                source, field
            ):
                raise ValidationError(
                    "Credit quantities and taxes cannot exceed the original line "
                    "after earlier credits."
                )


@transaction.atomic
def issue_invoice(*, tenant, actor, invoice_id, revision, key, correlation_id=""):
    tenant = require_financial_permission(
        tenant=tenant, actor=actor, permission="invoices.issue"
    )
    key, fingerprint, previous = command_replay(
        tenant=tenant,
        operation="invoice.issue",
        key=key,
        payload={"invoice": invoice_id, "revision": revision},
    )
    if previous:
        return Invoice.objects.get(tenant=tenant, pk=previous)
    invoice = (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("customer", "parent")
        .get(tenant=tenant, pk=invoice_id)
    )
    if invoice.kind != "invoice":
        require_financial_permission(
            tenant=tenant, actor=actor, permission="invoices.correct"
        )
    if not invoice.is_draft or invoice.revision != revision:
        raise ValidationError(
            "This document is already issued or changed. Reload the page."
        )
    if tenant.country != "IN" or tenant.currency != "INR" or invoice.currency != "INR":
        raise ValidationError("Invoice V1 requires an India workspace using INR.")
    if (
        not invoice.scope_confirmed
        or invoice.issue_date > today_for(tenant)
        or invoice.total <= 0
        or not invoice.lines.exists()
    ):
        raise ValidationError(
            "Issue a positive-value document with lines, "
            "a valid issue date, and confirmed supply scope."
        )
    if invoice.parent_id:
        parent = Invoice.objects.select_for_update().get(
            tenant=tenant, pk=invoice.parent_id
        )
        invoice.seller_snapshot = parent.seller_snapshot
        invoice.buyer_snapshot = parent.buyer_snapshot
        if invoice.kind == "credit_note":
            _validate_credit(invoice)
    else:
        try:
            profile = SellerProfile.objects.get(tenant=tenant)
        except SellerProfile.DoesNotExist as error:
            raise ValidationError(
                "Complete invoice settings before issuing."
            ) from error
        profile.full_clean()
        customer = invoice.customer
        if (
            customer.status != "active"
            or customer.country != "IN"
            or not customer.billing_address.strip()
        ):
            raise ValidationError(
                "Complete the active customer's Indian billing address "
                "and country before issuing."
            )
        invoice.seller_snapshot = {
            field: getattr(profile, field)
            for field in (
                "legal_name",
                "address",
                "gstin",
                "state_code",
                "payment_instructions",
                "signatory",
            )
        }
        invoice.buyer_snapshot = {
            "name": str(customer),
            "address": customer.billing_address,
            "gstin": invoice.buyer_gstin,
            "state_code": invoice.buyer_state,
            "email": customer.email,
        }
    seller_state = invoice.seller_snapshot["state_code"]
    expected = (
        "intra_state" if seller_state == invoice.place_of_supply else "inter_state"
    )
    if invoice.supply_type != expected:
        raise ValidationError(
            "Supply type must agree with the explicit place of supply "
            "and seller registration state."
        )
    if expected == "intra_state" and seller_state in UTGST_STATES:
        raise ValidationError(
            "Intra-UT supplies requiring UTGST are not supported in V1."
        )
    if invoice.buyer_state not in STATES or invoice.place_of_supply not in STATES:
        raise ValidationError("Select supported domestic states.")
    if invoice.buyer_gstin:
        validate_gstin(invoice.buyer_gstin)
    financial_year = invoice.issue_date.year - (invoice.issue_date.month < 4)
    if Invoice.objects.filter(
        tenant=tenant,
        state="issued",
        issue_date__gt=invoice.issue_date,
        issue_date__gte=date(financial_year, 4, 1),
        issue_date__lt=date(financial_year + 1, 4, 1),
    ).exists():
        raise ValidationError(
            "The issue date cannot precede a later document in this financial year."
        )
    treatments = set(invoice.lines.values_list("tax_treatment", flat=True))
    if len(treatments) != 1:
        raise ValidationError(
            "Create separate documents for taxable and exempt supplies."
        )
    if invoice.parent_id:
        parent_treatments = set(
            invoice.parent.lines.values_list("tax_treatment", flat=True)
        )
        if treatments != parent_treatments:
            raise ValidationError(
                "Correction tax treatment must match the original document."
            )
    sequence, _ = InvoiceSequence.objects.get_or_create(
        tenant=tenant, financial_year=financial_year
    )
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)
    if sequence.next_number > 999999:
        raise ValidationError(
            "The approved numbering series is exhausted for this financial year."
        )
    year_label = f"{financial_year % 100:02d}-{(financial_year + 1) % 100:02d}"
    invoice.number = f"KP/{year_label}/{sequence.next_number:06d}"
    sequence.next_number += 1
    sequence.save(update_fields=["next_number"])
    invoice.state, invoice.issued_by, invoice.issued_at = (
        "issued",
        actor,
        timezone.now(),
    )
    invoice.full_clean()
    invoice.save()
    record_event(
        tenant=tenant,
        actor=actor,
        action="invoice.issued",
        entity_type="invoice",
        entity_id=invoice.pk,
        correlation_id=correlation_id,
        metadata={"kind": invoice.kind, "number": invoice.number},
    )
    finish_command(
        tenant=tenant,
        operation="invoice.issue",
        key=key,
        fingerprint=fingerprint,
        response_id=invoice.pk,
    )
    return invoice
