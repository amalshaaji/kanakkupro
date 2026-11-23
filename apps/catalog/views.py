from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.forms import CatalogItemForm
from apps.catalog.models import CatalogItem
from apps.catalog.permissions import tenant_permission_required
from apps.catalog.services import (
    create_catalog_item,
    set_catalog_item_active,
    update_catalog_item,
)
from apps.tenants.permissions import membership_has_permission


def _tenant_items(request):
    if request.tenant is None:
        raise PermissionDenied
    return CatalogItem.objects.filter(tenant=request.tenant)


@login_required
@tenant_permission_required("catalog.view")
def item_list(request):
    items = _tenant_items(request)
    search = request.GET.get("q", "").strip()[:100]
    active_filter = request.GET.get("active", "true")
    if active_filter not in {"true", "false", "all"}:
        active_filter = "true"
    if active_filter != "all":
        items = items.filter(active=active_filter == "true")
    kind = request.GET.get("kind", "all")
    if kind not in {"all", *CatalogItem.Kind.values}:
        kind = "all"
    if kind != "all":
        items = items.filter(kind=kind)
    if search:
        items = items.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
            | Q(description__icontains=search)
        )
    page_obj = Paginator(items, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/item_list.html",
        {
            "page_obj": page_obj,
            "search": search,
            "active_filter": active_filter,
            "kind_filter": kind,
            "can_manage_catalog": membership_has_permission(
                request.tenant_membership, "catalog.manage"
            ),
        },
    )


@login_required
@tenant_permission_required("catalog.view")
def item_detail(request, item_id):
    item = get_object_or_404(_tenant_items(request), pk=item_id)
    return render(
        request,
        "catalog/item_detail.html",
        {
            "item": item,
            "can_manage_catalog": membership_has_permission(
                request.tenant_membership, "catalog.manage"
            ),
        },
    )


@login_required
@tenant_permission_required("catalog.manage")
def item_create(request):
    form = CatalogItemForm(
        request.POST if request.method == "POST" else None, tenant=request.tenant
    )
    if request.method == "POST" and form.is_valid():
        try:
            item = create_catalog_item(
                tenant=request.tenant, actor=request.user, values=form.cleaned_data
            )
        except PermissionDenied:
            raise
        except IntegrityError:
            form.add_error(None, "This SKU is already used in this business.")
        else:
            messages.success(request, f"{item.name} was added to the catalog.")
            return redirect("catalog:detail", item_id=item.pk)
    return render(request, "catalog/item_form.html", {"form": form, "is_create": True})


@login_required
@tenant_permission_required("catalog.manage")
def item_update(request, item_id):
    item = get_object_or_404(_tenant_items(request), pk=item_id)
    form = CatalogItemForm(
        request.POST if request.method == "POST" else None,
        instance=item,
        tenant=request.tenant,
    )
    if request.method == "POST" and form.is_valid():
        try:
            item = update_catalog_item(
                tenant=request.tenant,
                actor=request.user,
                item_id=item.pk,
                values=form.cleaned_data,
            )
        except IntegrityError:
            form.add_error("sku", "This SKU is already used in this business.")
        else:
            messages.success(request, f"{item.name} was updated.")
            return redirect("catalog:detail", item_id=item.pk)
    return render(
        request,
        "catalog/item_form.html",
        {"form": form, "item": item, "is_create": False},
    )


@login_required
@require_POST
@tenant_permission_required("catalog.manage")
def item_set_active(request, item_id, active):
    if active not in {"true", "false"}:
        raise PermissionDenied
    item = set_catalog_item_active(
        tenant=request.tenant,
        actor=request.user,
        item_id=item_id,
        active=active == "true",
    )
    state = "restored" if item.active else "archived"
    messages.success(request, f"{item.name} was {state}.")
    return redirect("catalog:detail", item_id=item.pk)
