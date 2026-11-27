# Phase 7 pilot preparation

Status: pilot preparation tooling is implemented; pilot admission is blocked by the unchecked Phase 6 gates below. A live Render service does not demonstrate production readiness.

The PRD numbering is authoritative: Phase 6 hardening, Phase 7 pilot, Phase 8 paid SaaS, Phase 9 expansion. Do not start subscription billing or claim the pilot is complete as a substitute for release verification.

## Phase 6 gate register

| Gate | Evidence / current state | Required next action |
| --- | --- | --- |
| Email outage handling | SMTP failures produce a private 503 recovery page. A real application verification email was confirmed in the connected Gmail Spam folder on 2026-11-26; verification remains mandatory | Confirm fresh password-reset and invitation delivery; review inbox placement with the sender provider |
| Financial reporting | Dated issued documents, customer sales, receipts, reversals, bounded pages and role-protected CSV | Run the owner-to-payment browser journey against an isolated staging tenant |
| Availability monitoring | The push-triggered availability check passed; scheduled checks passed on 2026-11-27 at 03:44 and [09:58 Asia/Kolkata](https://github.com/amalshaaji/kanakkupro/actions/runs/45940107407). Existing CI/deployment-failure alert emails were confirmed in the connected inbox on 2026-11-26 | Verify runtime error-alert routing; scheduled jobs are best effort, not a 99.9% availability guarantee |
| External error alerts | Structured errors include request ID, exception type and safe email failure category | Choose an error-tracking provider, configure safe event collection, and prove a test alert reaches the operator |
| Protected backup coverage | Live Neon Free coverage verified as 6 hours; an isolated point-in-time branch was created on 2026-11-26 and all 19 checked table counts/content fingerprints matched production. See [drill evidence](recovery-drill-2026-11-26.md). Financial tables were empty. GitHub backup secrets are configured, but the first manual backup failed | Diagnose the failed stage using the [read-only storage check](encrypted-backups.md), then prove encrypted upload, scheduled delivery and provider-backed restore. Confirm separate recovery-key custody and measure end-to-end RPO/RTO |
| Performance | Query-count regression tests cover invoice/dashboard and report growth; rows paginated | Run concurrent representative workloads and record latency/cold-start measurements; query counts alone are not a latency benchmark |
| Security / access | Production configuration, admin MFA, tenant/permission tests implemented | Verify deployed admin enrollment/recovery and least-privilege database/operator access; confirm exposed keys were replaced |
| Accessibility / support / privacy | Responsive shell and operator runbooks exist | Complete critical keyboard/contrast checks and approve support, incident, retention/deletion, privacy and terms procedures |

## Pilot guide in the app

Owners and Admins can open **Settings → Pilot guide** (`/dashboard/pilot/`) or follow the dashboard banner. Other roles and revoked memberships cannot read or change this business's pilot records.

- Seven setup checks read the current business records: verified account, seller settings, customer, catalog item, issued invoice, unreversed payment, and a fully paid invoice.
- Five manual checks record the reviewing user and time for verification/reset/invitation delivery, PDF review, and financial reconciliation. These are business attestations, not automatic email probes or operator admission approval.
- Feedback records issue/idea, severity, optional support reference, and Open/Investigating/Resolved status. Feedback is visible to this business's Owners/Admins; no external support notification is sent automatically. Checklist and feedback changes write audit events without copying feedback text into audit metadata.
- The timing measure is minutes from business creation to the first issued invoice. It includes setup time and must not be presented as the PRD's separate five-minute-after-setup KPI.
- These two pilot tables are included in the restore manifest. The additive migration creates only these tables and constraints; it does not alter financial records.

This feature does not enroll businesses, contact customers, approve a pilot cohort, bypass verification, or certify that Phase 6 has passed. Recruiting and admitting 3–5 consenting businesses remains an operator task after the release gates pass.

## Operator verification commands

Run these only on a trusted operator host with the deployment environment loaded privately. Do not pass connection strings or passwords as command arguments or paste their values into chat.

```bash
python manage.py check_email_transport
python manage.py pilot_status --tenant TENANT_UUID --reviewer OWNER_OR_ADMIN_USER_UUID
```

`check_email_transport` opens a TLS-protected SMTP connection, authenticates, and closes it without sending any message. Its JSON output distinguishes authentication rejection from connection/TLS failure without provider response text. Successful authentication does not prove sender authorization or delivery to an inbox.

`pilot_status` reads only the explicitly selected business and requires an active Owner/Admin reviewer. It emits progress counts and outstanding operator evidence, without email addresses or feedback text. It never approves admission or changes check marks.

The HTTP acceptance tests in `apps/dashboard/test_pilot_acceptance.py` execute the owner signup/verification → business/customer/catalog setup → invoice issuance → partial/final payments → reports → viewer invitation journey using CSRF-enforced clients and in-memory mail. They test role and cross-tenant denials; Linux CI also downloads and checks the issued PDF. These tests are isolated from the deployed database and do not certify live provider delivery or replace a browser accessibility review.

The availability workflow now runs when its checker/configuration changes on `main`, in addition to its schedule/manual trigger. Verify failure notifications separately; a successful job alone does not prove an alert reaches the incident owner.

## Pilot plan after gates pass

1. Select one initial business segment and an operator/support contact. Recruit 3–5 businesses with their consent; no customer outreach is automated here.
2. Use a separate pilot environment/database with the verified recovery coverage. Keep test data separate from real financial data.
3. For each owner, verify signup/email, create the business, review seller/tax settings, invite one colleague, and explain roles and support.
4. Complete customer → catalog → invoice draft → issue → PDF → partial/final payment → correction/reversal → dashboard/report reconciliation. Verify unauthorized tenant access is denied.
5. Record onboarding completion and time to first invoice, delivery failures, defects, request IDs, and operator response. PRD targets are at least 80% onboarding completion and first invoice within five minutes after setup; measure rather than promise these.
6. Resolve critical/high workflow, isolation and financial defects before expanding. Review pilot results and release gates before Phase 8 billing work.

No pilot tenants, invitations, charges, or real financial records are created by this plan.
