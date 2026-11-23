from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.tenants.forms import InvitationCreateForm, TenantCreateForm
from apps.tenants.middleware import ACTIVE_TENANT_SESSION_KEY
from apps.tenants.models import Invitation, Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission
from apps.tenants.services import (
    InvitationError,
    accept_invitation,
    create_invitation,
    create_tenant_for_owner,
    get_invitation_for_acceptance,
    revoke_invitation,
)


def tenant_permission_required(permission):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not membership_has_permission(
                getattr(request, "tenant_membership", None), permission
            ):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


@login_required
def create_tenant(request):
    if request.method == "POST":
        form = TenantCreateForm(request.POST)
        if form.is_valid():
            try:
                tenant = create_tenant_for_owner(
                    owner=request.user, form_data=form.cleaned_data
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                request.session[ACTIVE_TENANT_SESSION_KEY] = str(tenant.pk)
                messages.success(request, f"{tenant.name} is ready.")
                return redirect("dashboard:index")
    else:
        form = TenantCreateForm(initial={"timezone": "UTC"})

    return render(request, "tenants/create.html", {"form": form})


@login_required
@require_POST
def switch_tenant(request):
    tenant_id = request.POST.get("tenant_id", "")
    membership = (
        TenantMembership.objects.select_related("tenant")
        .filter(
            tenant_id=tenant_id,
            user=request.user,
            status=TenantMembership.Status.ACTIVE,
            tenant__status=Tenant.Status.ACTIVE,
        )
        .first()
    )
    if membership is None:
        raise Http404

    request.session[ACTIVE_TENANT_SESSION_KEY] = str(membership.tenant_id)
    return redirect("dashboard:index")


@login_required
@tenant_permission_required("team.manage")
def team(request):
    invitation_form = InvitationCreateForm()
    if request.method == "POST":
        invitation_form = InvitationCreateForm(request.POST)
        if invitation_form.is_valid():
            try:
                create_invitation(
                    tenant=request.tenant,
                    actor=request.user,
                    email=invitation_form.cleaned_data["email"],
                    role=invitation_form.cleaned_data["role"],
                    request=request,
                )
            except ValidationError as error:
                invitation_form.add_error(None, error)
            else:
                messages.success(request, "The invitation email was sent.")
                return redirect("tenants:team")

    members = (
        TenantMembership.objects.filter(
            tenant=request.tenant, status=TenantMembership.Status.ACTIVE
        )
        .select_related("user")
        .order_by("created_at")
    )
    invitations = Invitation.objects.filter(
        tenant=request.tenant,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("created_at")
    return render(
        request,
        "tenants/team.html",
        {
            "form": invitation_form,
            "members": members,
            "invitations": invitations,
        },
    )


@login_required
@require_POST
def revoke(request, invitation_id):
    if request.tenant is None:
        raise Http404
    try:
        revoke_invitation(
            tenant=request.tenant,
            actor=request.user,
            invitation_id=invitation_id,
        )
    except InvitationError as error:
        raise Http404 from error
    messages.success(request, "The invitation was revoked.")
    return redirect("tenants:team")


@login_required
@require_http_methods(["GET", "POST"])
def accept(request, token):
    if request.method == "GET":
        try:
            invitation = get_invitation_for_acceptance(token=token, user=request.user)
        except InvitationError:
            messages.error(
                request, "This invitation is invalid or no longer available."
            )
            return redirect("dashboard:index")
        except PermissionDenied:
            return render(request, "tenants/invitation_forbidden.html", status=403)
        return render(
            request,
            "tenants/invitation_accept.html",
            {"invitation": invitation},
        )

    try:
        membership = accept_invitation(token=token, user=request.user)
    except InvitationError:
        messages.error(request, "This invitation is invalid or no longer available.")
        return redirect("dashboard:index")
    except PermissionDenied:
        return render(request, "tenants/invitation_forbidden.html", status=403)

    request.session[ACTIVE_TENANT_SESSION_KEY] = str(membership.tenant_id)
    messages.success(request, f"You joined {membership.tenant.name}.")
    return redirect("dashboard:index")
