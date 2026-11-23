from apps.tenants.models import TenantMembership
from apps.tenants.permissions import membership_has_permission

ACTIVE_TENANT_SESSION_KEY = "active_tenant_id"


class ActiveTenantMiddleware:
    """Resolve tenant context from session and revalidate membership per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.tenant_membership = None
        request.tenant_memberships = []
        request.can_manage_tenant_team = False

        if request.user.is_authenticated:
            request.tenant_memberships = list(
                TenantMembership.objects.filter(
                    user=request.user,
                    status=TenantMembership.Status.ACTIVE,
                    tenant__status="active",
                )
                .select_related("tenant")
                .order_by("created_at", "tenant__name")
            )

            selected_tenant_id = request.session.get(ACTIVE_TENANT_SESSION_KEY)
            request.tenant_membership = next(
                (
                    membership
                    for membership in request.tenant_memberships
                    if str(membership.tenant_id) == str(selected_tenant_id)
                ),
                None,
            )

            if request.tenant_membership is None and request.tenant_memberships:
                request.tenant_membership = request.tenant_memberships[0]

            if request.tenant_membership:
                request.tenant = request.tenant_membership.tenant
                request.can_manage_tenant_team = membership_has_permission(
                    request.tenant_membership, "team.manage"
                )
                request.session[ACTIVE_TENANT_SESSION_KEY] = str(request.tenant.pk)
            else:
                request.session.pop(ACTIVE_TENANT_SESSION_KEY, None)

        return self.get_response(request)
