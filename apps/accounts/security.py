import time

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.deprecation import MiddlewareMixin

from apps.audit.services import record_event

ADMIN_MFA_SESSION_KEY = "kanakkupro.admin_mfa"


class AdminMFAMiddleware(MiddlewareMixin):
    """Guard every admin view, including sessions created outside allauth."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if (
            not match
            or "admin" not in match.app_names
            or not request.user.is_authenticated
        ):
            return None
        user = request.user
        if not user.is_active or not user.is_staff:
            return None  # Django/admin's secure login wrapper denies access.
        if not EmailAddress.objects.filter(
            user=user, email__iexact=user.email, verified=True
        ).exists():
            return redirect_to_login(
                request.get_full_path(), login_url=reverse("account_email")
            )
        if not Authenticator.objects.filter(
            user=user, type=Authenticator.Type.TOTP
        ).exists():
            return redirect_to_login(
                request.get_full_path(), login_url=reverse("mfa_activate_totp")
            )
        grant = request.session.get(ADMIN_MFA_SESSION_KEY, {})
        valid = isinstance(grant, dict) and grant.get("user") == str(user.pk)
        if valid:
            at = grant.get("at")
            valid = (
                isinstance(at, (int, float))
                and not isinstance(at, bool)
                and 0 <= time.time() - at <= settings.ADMIN_MFA_MAX_AGE
            )
        if valid:
            valid = Authenticator.objects.filter(
                user=user, pk=grant.get("authenticator")
            ).exists()
        if not valid:
            return redirect_to_login(
                request.get_full_path(), login_url=reverse("mfa_reauthenticate")
            )
        request.privileged_admin_access = True
        request.privileged_admin_actor = user
        return None

    def process_response(self, request, response):
        if getattr(request, "privileged_admin_access", False):
            record_event(
                tenant=None,
                actor=request.privileged_admin_actor,
                action="platform_admin.access",
                entity_type="platform_admin",
                correlation_id=getattr(request, "request_id", ""),
                metadata={
                    "method": request.method,
                    "view": request.resolver_match.view_name,
                    "status": response.status_code,
                },
            )
        return response


class PrivateResponseMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        match = getattr(request, "resolver_match", None)
        auth_page = (
            match and match.url_name and match.url_name.startswith(("account_", "mfa_"))
        )
        if request.user.is_authenticated or auth_page:
            patch_cache_control(response, private=True, no_store=True)
        return response
