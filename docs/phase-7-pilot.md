# Phase 7 pilot preparation

Status: pilot preparation tooling is implemented; pilot admission is blocked by the unchecked Phase 6 gates below. A live Render service does not demonstrate production readiness.

See [Phase 6 verification](phase-6-verification.md) for the isolated HTTP workload,
browser acceptance evidence, safe runtime-alert implementation and remaining
deployment decisions. These checks do not substitute for live provider evidence.

The PRD numbering is authoritative: Phase 6 hardening, Phase 7 pilot, Phase 8 paid SaaS, Phase 9 expansion. Do not start subscription billing or claim the pilot is complete as a substitute for release verification.

## Phase 6 gate register

| Gate | Evidence / current state | Required next action |
| --- | --- | --- |
| Email outage handling | SMTP failures produce a private 503 recovery page. A real application verification email was confirmed in the connected Gmail Spam folder on 2026-11-26; verification remains mandatory | Confirm fresh password-reset and invitation delivery; review inbox placement with the sender provider |
| Financial reporting | Dated issued documents, customer sales, receipts, reversals, bounded pages and role-protected CSV. [CI run 38](https://github.com/amalshaaji/kanakkupro/actions/runs/46025851685) passed the synthetic owner-to-payment/PDF journey, viewer denial and foreign-tenant denial on desktop and mobile | Reconcile each consenting pilot business's actual onboarding workflow after admission |
| Availability monitoring | The push-triggered availability check passed; scheduled checks passed on 2026-11-27 at 03:44 and [09:58 Asia/Kolkata](https://github.com/amalshaaji/kanakkupro/actions/runs/45940107407). Existing CI/deployment-failure alert emails were confirmed in the connected inbox on 2026-11-26 | Verify runtime error-alert routing; scheduled jobs are best effort, not a 99.9% availability guarantee |
| External error alerts | Payload-free runtime email alerts are enabled. The approved probe arrived in Gmail at 15:39:09 UTC on 2026-11-27 and matched the Render log request ID. Gmail placed it in Spam | Resolve dependable inbox placement; retain independent availability monitoring |
| Protected backup coverage | Live Neon Free coverage is 6 hours; the isolated point-in-time drill matched all 19 checked tables. See [drill evidence](recovery-drill-2026-11-26.md); financial tables were empty. GitHub secrets and read-only B2 checks passed. The operator explicitly approved the Neon → GitHub Actions → private B2 transfer and confirmed separate recovery-key custody on 2026-11-27 | Finish GitHub's email access verification to save the enable flag, then prove encrypted upload, scheduled delivery and provider-backed restore. Measure end-to-end RPO/RTO |
| Performance | Query-growth tests, the local four-client workload and the CI single-worker/PDF workload passed with 210 issued documents/1,010 lines and unchanged financial totals. Post-release public readiness returned 200 in 21.54 seconds after a prior 30-second timeout | Measure representative authenticated deployed latency and cold starts; choose hosting behavior acceptable for pilot |
| Security / access | Production configuration, admin MFA, tenant/permission tests implemented | Verify deployed admin enrollment/recovery and least-privilege database/operator access; confirm exposed keys were replaced |
| Accessibility / support / privacy | CI desktop/mobile scans and keyboard journeys passed after contrast, skip-target and scroll-region fixes. Local review confirmed keyboard focus on report/team table regions. Operator runbooks exist | Complete screen-reader/device/zoom review and approve support, incident, retention/deletion, privacy and terms procedures |

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
