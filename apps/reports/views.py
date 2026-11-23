import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.reports.permissions import tenant_permission_required
from apps.tenants.models import Invitation, TenantMembership
from apps.tenants.permissions import REPORT_EXPORT_ROLES

MAX_EXPORT_ROWS = 10_000


@login_required
@tenant_permission_required("reports.view")
def report_home(request):
    tenant = request.tenant
    customer_counts = Customer.objects.filter(tenant=tenant).aggregate(
        total=Count("id"),
        active_count=Count("id", filter=Q(status=Customer.Status.ACTIVE)),
        archived_count=Count("id", filter=Q(status=Customer.Status.INACTIVE)),
    )
    catalog_counts = CatalogItem.objects.filter(tenant=tenant).aggregate(
        total=Count("id"),
        active_count=Count("id", filter=Q(active=True)),
        archived_count=Count("id", filter=Q(active=False)),
    )
    recent_events = (
        AuditEvent.objects.filter(tenant=tenant)
        .select_related("actor")
        .order_by("-created_at")[:25]
    )
    return render(
        request,
        "reports/home.html",
        {
            "customer_counts": customer_counts,
            "catalog_counts": catalog_counts,
            "member_count": TenantMembership.objects.filter(
                tenant=tenant, status=TenantMembership.Status.ACTIVE
            ).count(),
            "pending_invitation_count": Invitation.objects.filter(
                tenant=tenant,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).count(),
            "recent_events": recent_events,
            "can_export": request.tenant_membership.role in REPORT_EXPORT_ROLES,
            "can_view_actor_names": request.tenant_membership.role
            in REPORT_EXPORT_ROLES,
        },
    )


@login_required
@tenant_permission_required("reports.export")
def export_customers(request):
    customers = Customer.objects.filter(tenant=request.tenant).order_by("name", "id")
    return _export_csv(
        filename="customers.csv",
        queryset=customers,
        headers=(
            "id",
            "name",
            "company_name",
            "email",
            "phone",
            "billing_address",
            "country",
            "status",
            "created_at",
        ),
        row_values=lambda item: (
            item.pk,
            item.name,
            item.company_name,
            item.email,
            item.phone,
            item.billing_address,
            item.country,
            item.status,
            item.created_at.isoformat(),
        ),
    )


@login_required
@tenant_permission_required("reports.export")
def export_catalog(request):
    items = CatalogItem.objects.filter(tenant=request.tenant).order_by("name", "id")
    return _export_csv(
        filename="catalog.csv",
        queryset=items,
        headers=(
            "id",
            "name",
            "kind",
            "sku",
            "description",
            "unit",
            "price",
            "currency",
            "hsn_sac",
            "tax_treatment",
            "tax_rate_percent",
            "active",
            "created_at",
        ),
        row_values=lambda item: (
            item.pk,
            item.name,
            item.kind,
            item.sku or "",
            item.description,
            item.unit,
            item.price if item.price is not None else "",
            request.tenant.currency,
            item.hsn_sac,
            item.tax_treatment or "",
            item.tax_rate if item.tax_rate is not None else "",
            item.active,
            item.created_at.isoformat(),
        ),
    )


def _export_csv(*, filename, queryset, headers, row_values):
    bounded_queryset = queryset[: MAX_EXPORT_ROWS + 1]
    count = bounded_queryset.count()
    if count > MAX_EXPORT_ROWS:
        return HttpResponse(
            "This export exceeds the 10,000 row limit. Narrow the data and retry.",
            status=413,
            content_type="text/plain; charset=utf-8",
        )

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo(), lineterminator="\r\n")

    def rows():
        yield writer.writerow(headers)
        for item in bounded_queryset[:MAX_EXPORT_ROWS].iterator(chunk_size=1000):
            yield writer.writerow([_safe_csv_cell(value) for value in row_values(item)])

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _safe_csv_cell(value):
    if not isinstance(value, str):
        value = str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value
