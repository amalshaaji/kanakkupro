import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.permissions import tenant_permission_required
from apps.payments.forms import PaymentForm
from apps.sales.forms import InvoiceForm, IssueForm, LineFormSet, SellerProfileForm
from apps.sales.models import Invoice, SellerProfile
from apps.sales.selectors import with_balances
from apps.sales.services import (
    issue_invoice,
    save_draft,
    save_seller_profile,
    today_for,
)
from apps.tenants.permissions import membership_has_permission


def tenant_documents(request):
    return Invoice.objects.filter(tenant=request.tenant).select_related(
        "customer", "parent", "tenant"
    )


@login_required
@tenant_permission_required("invoices.view")
def invoice_list(request):
    documents = with_balances(tenant_documents(request))
    search = request.GET.get("q", "").strip()[:100]
    state = request.GET.get("state", "all")
    if state in Invoice.State.values:
        documents = documents.filter(state=state)
    if search:
        documents = documents.filter(
            Q(number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(buyer_snapshot__name__icontains=search)
        )
    return render(
        request,
        "sales/invoice_list.html",
        {
            "page_obj": Paginator(documents, 25).get_page(request.GET.get("page")),
            "search": search,
            "state_filter": state,
            "can_manage": membership_has_permission(
                request.tenant_membership, "invoices.manage"
            ),
            "can_settings": membership_has_permission(
                request.tenant_membership, "business.manage"
            ),
        },
    )


@login_required
@tenant_permission_required("invoices.view")
def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(
        with_balances(tenant_documents(request)).prefetch_related("lines"),
        pk=invoice_id,
    )
    return render(
        request,
        "sales/invoice_detail.html",
        {
            "invoice": invoice,
            "financials": invoice.financials,
            "issue_form": IssueForm(initial={"revision": invoice.revision}),
            "payment_form": PaymentForm(initial={"date": today_for(request.tenant)}),
            "payments": invoice.payments.filter(tenant=request.tenant).select_related(
                "reversal", "created_by"
            ),
            "corrections": invoice.corrections.filter(tenant=request.tenant).order_by(
                "created_at"
            ),
            "can_manage": membership_has_permission(
                request.tenant_membership,
                "invoices.manage" if invoice.kind == "invoice" else "invoices.correct",
            ),
            "can_issue": membership_has_permission(
                request.tenant_membership, "invoices.issue"
            )
            and (
                invoice.kind == "invoice"
                or membership_has_permission(
                    request.tenant_membership, "invoices.correct"
                )
            ),
            "can_record": membership_has_permission(
                request.tenant_membership, "payments.record"
            ),
            "can_reverse": membership_has_permission(
                request.tenant_membership, "payments.reverse"
            ),
            "can_correct": membership_has_permission(
                request.tenant_membership, "invoices.correct"
            ),
        },
    )


@login_required
@tenant_permission_required("invoices.manage")
def invoice_edit(request, invoice_id=None):
    invoice = (
        get_object_or_404(tenant_documents(request), pk=invoice_id)
        if invoice_id
        else None
    )
    if invoice and not invoice.is_draft:
        messages.error(
            request, "Issued documents cannot be edited. Use a linked correction note."
        )
        return redirect("sales:detail", invoice_id=invoice.pk)
    kind = invoice.kind if invoice else request.GET.get("kind", "invoice")
    parent = invoice.parent if invoice else None
    if kind != "invoice":
        if kind not in {"credit_note", "debit_note"} or not membership_has_permission(
            request.tenant_membership, "invoices.correct"
        ):
            raise PermissionDenied
    if not invoice and kind != "invoice":
        try:
            parent_id = uuid.UUID(str(request.GET.get("parent")))
        except (ValueError, TypeError) as error:
            raise Http404 from error
        parent = get_object_or_404(
            tenant_documents(request),
            pk=parent_id,
            state="issued",
            kind="invoice",
        )
    initial = {
        "issue_date": today_for(request.tenant),
        "due_date": today_for(request.tenant),
    }
    basis = invoice or parent
    if basis:
        initial.update(
            {
                field: getattr(basis, field)
                for field in (
                    "issue_date",
                    "due_date",
                    "buyer_gstin",
                    "buyer_state",
                    "place_of_supply",
                    "supply_type",
                    "delivery_address",
                    "notes",
                    "reason",
                )
            }
        )
        initial["customer"] = basis.customer_id
        if not invoice:
            initial.update(
                issue_date=today_for(request.tenant),
                due_date=today_for(request.tenant),
                reason="",
            )
    if invoice:
        initial.update(revision=invoice.revision)
    form = InvoiceForm(
        request.POST or None, tenant=request.tenant, parent=parent, initial=initial
    )
    line_initial = (
        [
            {
                "item": line.item_id,
                "source_line": line.source_line_id,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount": line.discount,
            }
            for line in invoice.lines.filter(tenant=request.tenant)
        ]
        if invoice
        else []
    )
    line_forms = LineFormSet(
        request.POST or None,
        initial=line_initial,
        prefix="lines",
        form_kwargs={"tenant": request.tenant, "kind": kind, "parent": parent},
    )
    if request.method == "POST":
        header_valid = form.is_valid()
        lines_valid = line_forms.is_valid()
        if header_valid and lines_valid:
            try:
                saved = save_draft(
                    tenant=request.tenant,
                    actor=request.user,
                    invoice_id=invoice.pk if invoice else None,
                    revision=form.cleaned_data.get("revision"),
                    data=form.payload(kind=kind, parent=parent),
                    lines=[
                        line_form.payload()
                        for line_form in line_forms
                        if line_form.cleaned_data
                        and not line_form.cleaned_data.get("DELETE")
                    ],
                    key=form.cleaned_data["key"],
                    correlation_id=request.request_id,
                )
            except ValidationError as error:
                form.add_error(None, error.messages)
            else:
                messages.success(request, "Draft saved.")
                return redirect("sales:detail", invoice_id=saved.pk)
    return render(
        request,
        "sales/invoice_form.html",
        {
            "form": form,
            "line_forms": line_forms,
            "invoice": invoice,
            "kind": kind,
            "parent": parent,
        },
    )


@login_required
@require_POST
@tenant_permission_required("invoices.issue")
def issue(request, invoice_id):
    invoice = get_object_or_404(tenant_documents(request), pk=invoice_id)
    form = IssueForm(request.POST)
    if form.is_valid():
        try:
            issue_invoice(
                tenant=request.tenant,
                actor=request.user,
                invoice_id=invoice.pk,
                revision=form.cleaned_data["revision"],
                key=form.cleaned_data["key"],
                correlation_id=request.request_id,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Document issued. Its details are now immutable.")
    else:
        messages.error(request, "Invalid issue request. Reload the page and try again.")
    return redirect("sales:detail", invoice_id=invoice.pk)


@login_required
@tenant_permission_required("business.manage")
def invoice_settings(request):
    profile = SellerProfile.objects.filter(tenant=request.tenant).first()
    form = SellerProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        try:
            save_seller_profile(
                tenant=request.tenant,
                actor=request.user,
                values=form.cleaned_data,
                correlation_id=request.request_id,
            )
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, "Invoice settings saved.")
            return redirect("sales:list")
    return render(request, "sales/settings.html", {"form": form})


@login_required
@tenant_permission_required("invoices.view")
def invoice_pdf(request, invoice_id):
    from apps.sales.pdf import render_invoice_pdf

    invoice = get_object_or_404(
        tenant_documents(request).prefetch_related("lines"),
        pk=invoice_id,
        state="issued",
    )
    response = HttpResponse(render_invoice_pdf(invoice), content_type="application/pdf")
    filename = invoice.number.replace("/", "-")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
