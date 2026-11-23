from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.catalog.models import CatalogItem
from apps.customers.models import Customer
from apps.sales.selectors import financial_summary
from apps.tenants.permissions import membership_has_permission


def home(request):
    return render(request, "pages/home.html")


@login_required
def dashboard(request):
    if request.tenant is None:
        return redirect("tenants:create")
    return render(
        request,
        "pages/dashboard.html",
        {
            "financial_summary": financial_summary(request.tenant),
            "can_manage_team": membership_has_permission(
                request.tenant_membership, "team.manage"
            ),
            "customer_count": Customer.objects.filter(
                tenant=request.tenant, status=Customer.Status.ACTIVE
            ).count(),
            "catalog_count": CatalogItem.objects.filter(
                tenant=request.tenant, active=True
            ).count(),
        },
    )
