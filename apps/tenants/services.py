import hashlib
import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.tenants.models import Invitation, Tenant, TenantMembership
from apps.tenants.permissions import membership_has_permission


class InvitationError(Exception):
    """An invitation cannot be used in its current state."""


def create_tenant_for_owner(*, owner, form_data):
    base_slug = slugify(form_data["name"])[:180] or "business"

    for attempt in range(5):
        slug = base_slug if attempt == 0 else f"{base_slug}-{secrets.token_hex(4)}"
        try:
            with transaction.atomic():
                tenant = Tenant.objects.create(slug=slug, **form_data)
                TenantMembership.objects.create(
                    tenant=tenant,
                    user=owner,
                    role=TenantMembership.Role.OWNER,
                )
            return tenant
        except IntegrityError:
            if not Tenant.objects.filter(slug=slug).exists():
                raise

    raise ValidationError("A unique business address could not be generated.")


def create_invitation(*, tenant, actor, email, role, request):
    email = email.strip().lower()
    valid_roles = dict(Invitation._meta.get_field("role").choices)
    if role not in valid_roles:
        raise ValidationError("Choose a valid membership role.")

    now = timezone.now()
    invitation_ttl_days = settings.TENANT_INVITATION_TTL_DAYS
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        with transaction.atomic():
            tenant = Tenant.objects.select_for_update().get(
                pk=tenant.pk, status=Tenant.Status.ACTIVE
            )
            membership = (
                TenantMembership.objects.select_for_update()
                .filter(
                    tenant=tenant,
                    user=actor,
                    status=TenantMembership.Status.ACTIVE,
                    tenant__status=Tenant.Status.ACTIVE,
                )
                .first()
            )
            if not membership_has_permission(membership, "team.manage"):
                raise PermissionDenied

            existing_user = get_user_model().objects.filter(email__iexact=email).first()
            if (
                existing_user
                and TenantMembership.objects.filter(
                    tenant=tenant,
                    user=existing_user,
                    status=TenantMembership.Status.ACTIVE,
                ).exists()
            ):
                raise ValidationError("This person already has access to the business.")

            Invitation.objects.filter(
                tenant=tenant,
                email__iexact=email,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__lte=now,
            ).update(revoked_at=now)

            invitation = Invitation.objects.create(
                tenant=tenant,
                email=email,
                role=role,
                token_hash=token_hash,
                created_by=actor,
                expires_at=now + timedelta(days=invitation_ttl_days),
            )
            invitation_url = request.build_absolute_uri(
                reverse("tenants:accept_invitation", kwargs={"token": token})
            )
            transaction.on_commit(
                lambda: send_mail(
                    subject=f"Invitation to join {tenant.name} on KankkuPro",
                    message=(
                        f"You have been invited to join {tenant.name} on KankkuPro.\n\n"
                        f"Sign in or create an account using {email}, then accept the "
                        f"invitation here: {invitation_url}\n\n"
                        f"This invitation expires in {invitation_ttl_days} days and "
                        "can only be used once."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
            )
    except IntegrityError as error:
        if Invitation.objects.filter(
            tenant=tenant,
            email__iexact=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
        ).exists():
            raise ValidationError("A pending invitation already exists.") from error
        raise

    return invitation


def accept_invitation(*, token, user):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        try:
            invitation = (
                Invitation.objects.select_for_update()
                .select_related("tenant")
                .get(token_hash=token_hash)
            )
        except Invitation.DoesNotExist as error:
            raise InvitationError from error

        _validate_invitation_for_user(invitation, user, now)

        membership = TenantMembership.objects.filter(
            tenant=invitation.tenant, user=user
        ).first()
        if membership and membership.status == TenantMembership.Status.ACTIVE:
            raise InvitationError

        if membership:
            membership.role = invitation.role
            membership.status = TenantMembership.Status.ACTIVE
            membership.save(update_fields=["role", "status"])
        else:
            membership = TenantMembership.objects.create(
                tenant=invitation.tenant,
                user=user,
                role=invitation.role,
                status=TenantMembership.Status.ACTIVE,
            )

        invitation.accepted_at = now
        invitation.accepted_by = user
        invitation.save(update_fields=["accepted_at", "accepted_by"])

    return membership


def get_invitation_for_acceptance(*, token, user):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        invitation = Invitation.objects.select_related("tenant").get(
            token_hash=token_hash
        )
    except Invitation.DoesNotExist as error:
        raise InvitationError from error
    _validate_invitation_for_user(invitation, user, timezone.now())
    return invitation


def _validate_invitation_for_user(invitation, user, now):
    if (
        invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
        or invitation.tenant.status != Tenant.Status.ACTIVE
    ):
        raise InvitationError

    if invitation.email.casefold() != user.email.casefold():
        raise PermissionDenied

    if not EmailAddress.objects.filter(
        user=user, email__iexact=user.email, verified=True
    ).exists():
        raise PermissionDenied

    if TenantMembership.objects.filter(
        tenant=invitation.tenant,
        user=user,
        status=TenantMembership.Status.ACTIVE,
    ).exists():
        raise InvitationError


def revoke_invitation(*, tenant, actor, invitation_id):
    with transaction.atomic():
        membership = (
            TenantMembership.objects.select_for_update()
            .filter(
                tenant=tenant,
                user=actor,
                status=TenantMembership.Status.ACTIVE,
                tenant__status=Tenant.Status.ACTIVE,
            )
            .first()
        )
        if not membership_has_permission(membership, "team.manage"):
            raise PermissionDenied

        try:
            invitation = Invitation.objects.select_for_update().get(
                pk=invitation_id, tenant=tenant
            )
        except Invitation.DoesNotExist as error:
            raise InvitationError from error

        if invitation.accepted_at or invitation.revoked_at:
            raise InvitationError

        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at"])
    return invitation
