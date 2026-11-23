from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.customers.forms import CustomerForm
from apps.customers.models import Customer
from apps.customers.permissions import tenant_permission_required
from apps.customers.services import (
    create_customer,
    set_customer_status,
    update_customer,
)
from apps.sales.selectors import with_balances
from apps.tenants.permissions import membership_has_permission


def _active_customers(request):
    if request.tenant is None:
        raise PermissionDenied
    return Customer.objects.filter(tenant=request.tenant)


@login_required
@tenant_permission_required("customers.view")
def customer_list(request):
    customers = _active_customers(request)
    search = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", Customer.Status.ACTIVE)
    if status not in {"all", *Customer.Status.values}:
        status = Customer.Status.ACTIVE
    if status != "all":
        customers = customers.filter(status=status)
    if search:
        customers = customers.filter(
            Q(name__icontains=search)
            | Q(company_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
        )

    page_obj = Paginator(customers, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "customers/customer_list.html",
        {
            "page_obj": page_obj,
            "search": search,
            "status_filter": status,
            "can_manage_customers": membership_has_permission(
                request.tenant_membership, "customers.manage"
            ),
        },
    )


@login_required
@tenant_permission_required("customers.view")
def customer_detail(request, customer_id):
    customer = get_object_or_404(_active_customers(request), pk=customer_id)
    return render(
        request,
        "customers/customer_detail.html",
        {
            "customer": customer,
            "invoice_page": Paginator(
                with_balances(
                    customer.invoices.filter(
                        tenant=request.tenant, kind="invoice"
                    ).select_related("tenant")
                ),
                10,
            ).get_page(request.GET.get("invoice_page")),
            "can_manage_customers": membership_has_permission(
                request.tenant_membership, "customers.manage"
            ),
        },
    )


@login_required
@tenant_permission_required("customers.manage")
def customer_create(request):
    form = CustomerForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        customer = create_customer(
            tenant=request.tenant,
            actor=request.user,
            values=form.cleaned_data,
            correlation_id=request.request_id,
        )
        messages.success(request, f"{customer} was added to your customers.")
        return redirect("customers:detail", customer_id=customer.pk)
    return render(
        request,
        "customers/customer_form.html",
        {"form": form, "is_create": True},
    )


@login_required
@tenant_permission_required("customers.manage")
def customer_update(request, customer_id):
    customer = get_object_or_404(_active_customers(request), pk=customer_id)
    form = CustomerForm(
        request.POST if request.method == "POST" else None, instance=customer
    )
    if request.method == "POST" and form.is_valid():
        customer = update_customer(
            tenant=request.tenant,
            actor=request.user,
            customer_id=customer.pk,
            values=form.cleaned_data,
            correlation_id=request.request_id,
        )
        messages.success(request, f"{customer} was updated.")
        return redirect("customers:detail", customer_id=customer.pk)
    return render(
        request,
        "customers/customer_form.html",
        {"form": form, "customer": customer, "is_create": False},
    )


@login_required
@require_POST
@tenant_permission_required("customers.manage")
def customer_set_status(request, customer_id, status):
    if status not in {Customer.Status.ACTIVE, Customer.Status.INACTIVE}:
        raise PermissionDenied
    customer = set_customer_status(
        tenant=request.tenant,
        actor=request.user,
        customer_id=customer_id,
        status=status,
        correlation_id=request.request_id,
    )
    state_label = "restored" if status == Customer.Status.ACTIVE else "archived"
    messages.success(request, f"{customer} was {state_label}.")
    return redirect("customers:detail", customer_id=customer.pk)
