import uuid

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.sales.test_workflow import FinancialFixtures
from apps.tenants.models import PilotCheck, PilotFeedback, Tenant
from apps.tenants.pilot import confirm_check, pilot_progress, submit_feedback


class PilotGuideTests(FinancialFixtures, TestCase):
    def feedback(self, **overrides):
        return {
            "kind": "issue",
            "severity": "high",
            "description": "Invoice preview is hard to read.",
            "request_id": "",
            **overrides,
        }

    def test_guide_is_read_only_and_does_not_claim_admission(self):
        response = self.client.get(reverse("dashboard:pilot"))
        self.assertContains(response, "Preparation mode")
        self.assertContains(response, "does not approve pilot admission")
        self.assertContains(response, "No feedback yet")
        self.assertEqual(PilotCheck.objects.count(), 0)
        self.assertEqual(PilotFeedback.objects.count(), 0)
        self.assertFalse(response.context["business_checks_complete"])

    def test_checklist_uses_this_business_and_manual_checks_are_audited(self):
        EmailAddress.objects.create(
            user=self.owner, email=self.owner.email, verified=True
        )
        invoice = self.issue()
        self.pay(invoice, "118")
        progress = pilot_progress(self.tenant, self.owner)
        self.assertTrue(all(check["complete"] for check in progress["setup_checks"]))
        self.assertEqual(progress["completed"], 7)
        for code in PilotCheck.Code.values:
            response = self.client.post(
                reverse("dashboard:pilot"),
                {"action": "check", "code": code, "confirmed": "on"},
            )
            self.assertEqual(response.status_code, 302)
        self.assertTrue(
            pilot_progress(self.tenant, self.owner)["business_checks_complete"]
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                tenant=self.tenant, action="pilot.check_reviewed"
            ).count(),
            5,
        )
        self.client.post(reverse("dashboard:pilot"), {"action": "check", "code": "pdf"})
        self.assertFalse(
            PilotCheck.objects.get(tenant=self.tenant, code="pdf").confirmed
        )
        response = self.client.post(
            reverse("dashboard:pilot"),
            {"action": "check", "code": "operator_approved", "confirmed": "on"},
        )
        self.assertEqual(response.status_code, 400)

    def test_feedback_is_escaped_and_audit_does_not_copy_description(self):
        payload = self.feedback(
            description="<script>alert('sensitive-example')</script>"
        )
        response = self.client.post(
            reverse("dashboard:pilot"),
            {"action": "feedback", **payload, "tenant": "forged"},
        )
        self.assertEqual(response.status_code, 302)
        feedback = PilotFeedback.objects.get()
        self.assertEqual(feedback.tenant, self.tenant)
        self.assertEqual(feedback.submitted_by, self.owner)
        response = self.client.get(reverse("dashboard:pilot"))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert")
        audit = AuditEvent.objects.get(action="pilot.feedback_submitted")
        self.assertNotIn("sensitive-example", str(audit.metadata))
        self.assertEqual(response.context["open_high_issues"], 1)
        response = self.client.post(
            reverse("dashboard:feedback_status", args=[feedback.pk]),
            {"status": "resolved"},
        )
        self.assertEqual(response.status_code, 302)
        feedback.refresh_from_db()
        self.assertEqual(feedback.status, "resolved")
        self.assertEqual(pilot_progress(self.tenant, self.owner)["open_high_issues"], 0)

    def test_cross_tenant_feedback_cannot_be_read_or_changed(self):
        other = Tenant.objects.create(name="Other", slug="pilot-other")
        hidden = PilotFeedback.objects.create(
            tenant=other,
            submitted_by=self.owner,
            **self.feedback(description="Other tenant secret"),
        )
        response = self.client.get(
            reverse("dashboard:pilot"), {"tenant_id": str(other.pk)}
        )
        self.assertNotContains(response, "Other tenant secret")
        self.assertEqual(
            self.client.post(
                reverse("dashboard:feedback_status", args=[hidden.pk]),
                {"status": "resolved"},
            ).status_code,
            404,
        )
        hidden.refresh_from_db()
        self.assertEqual(hidden.status, "open")
        self.assertEqual(
            self.client.post(
                reverse("dashboard:feedback_status", args=[uuid.uuid4()]),
                {"status": "resolved"},
            ).status_code,
            404,
        )

    def test_viewer_and_revoked_memberships_are_denied_at_view_and_service(self):
        self.membership.role = "viewer"
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.client.get(reverse("dashboard:pilot")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            submit_feedback(
                tenant=self.tenant, actor=self.owner, values=self.feedback()
            )
        self.membership.role = "owner"
        self.membership.status = "inactive"
        self.membership.save(update_fields=["role", "status"])
        with self.assertRaises(PermissionDenied):
            confirm_check(
                tenant=self.tenant, actor=self.owner, code="pdf", confirmed=True
            )

    def test_invalid_feedback_status_reference_and_csrf_are_rejected(self):
        response = self.client.post(
            reverse("dashboard:pilot"),
            {"action": "feedback", **self.feedback(request_id="not-a-request-id")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PilotFeedback.objects.count(), 0)
        with self.assertRaises(ValidationError):
            submit_feedback(
                tenant=self.tenant,
                actor=self.owner,
                values=self.feedback(description=" "),
            )
        feedback = submit_feedback(
            tenant=self.tenant, actor=self.owner, values=self.feedback()
        )
        self.assertEqual(
            self.client.post(
                reverse("dashboard:feedback_status", args=[feedback.pk]),
                {"status": "unknown"},
            ).status_code,
            400,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(
            csrf_client.post(
                reverse("dashboard:pilot"), {"action": "check", "code": "pdf"}
            ).status_code,
            403,
        )
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse("dashboard:pilot")).status_code, 302)

    def test_feedback_is_paginated_and_status_updates_require_post(self):
        PilotFeedback.objects.bulk_create(
            [
                PilotFeedback(
                    tenant=self.tenant, submitted_by=self.owner, **self.feedback()
                )
                for _ in range(26)
            ]
        )
        response = self.client.get(reverse("dashboard:pilot"))
        self.assertEqual(len(response.context["feedback"]), 25)
        self.assertContains(response, "?page=2")
        item = PilotFeedback.objects.filter(tenant=self.tenant).first()
        self.assertEqual(
            self.client.get(
                reverse("dashboard:feedback_status", args=[item.pk])
            ).status_code,
            405,
        )

    def test_membership_in_another_business_does_not_grant_pilot_access(self):
        other_user = get_user_model().objects.create_user("other-pilot@example.test")
        self.client.force_login(other_user)
        self.assertNotEqual(
            self.client.get(reverse("dashboard:pilot")).status_code, 200
        )
