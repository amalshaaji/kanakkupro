# Phase 7 pilot preparation

Status: preparation only; pilot admission is blocked by the unchecked Phase 6 gates below. A live Render service does not demonstrate production readiness.

The PRD numbering is authoritative: Phase 6 hardening, Phase 7 pilot, Phase 8 paid SaaS, Phase 9 expansion. Do not start subscription billing or claim the pilot is complete as a substitute for release verification.

## Phase 6 gate register

| Gate | Evidence / current state | Required next action |
| --- | --- | --- |
| Email outage handling | SMTP failures produce a private 503 recovery page; account verification remains mandatory; persisted invitations are retained | Confirm successful verification, reset, and invitation delivery through the configured Brevo account |
| Financial reporting | Dated issued documents, customer sales, receipts, reversals, bounded pages and role-protected CSV | Run the owner-to-payment browser journey against an isolated staging tenant |
| Availability monitoring | GitHub Actions readiness check every 30 minutes and manual trigger; no authenticated actions | Verify a scheduled run and configure repository workflow-failure notifications; scheduled jobs are best effort, not a 99.9% availability guarantee |
| External error alerts | Structured errors include request ID, exception type and safe email failure category | Choose an error-tracking provider, configure safe event collection, and prove a test alert reaches the operator |
| Protected backup coverage | Disposable logical restore tooling exists; actual Neon coverage not configured/verified | Select retention/recovery coverage, retain MFA keys separately, restore into an isolated target, reconcile financial records, record observed RPO/RTO |
| Performance | Query-count regression tests cover invoice/dashboard and report growth; rows paginated | Run concurrent representative workloads and record latency/cold-start measurements; query counts alone are not a latency benchmark |
| Security / access | Production configuration, admin MFA, tenant/permission tests implemented | Verify deployed admin enrollment/recovery and least-privilege database/operator access; confirm exposed keys were replaced |
| Accessibility / support / privacy | Responsive shell and operator runbooks exist | Complete critical keyboard/contrast checks and approve support, incident, retention/deletion, privacy and terms procedures |

## Pilot plan after gates pass

1. Select one initial business segment and an operator/support contact. Recruit 3–5 businesses with their consent; no customer outreach is automated here.
2. Use a separate pilot environment/database with the verified recovery coverage. Keep test data separate from real financial data.
3. For each owner, verify signup/email, create the business, review seller/tax settings, invite one colleague, and explain roles and support.
4. Complete customer → catalog → invoice draft → issue → PDF → partial/final payment → correction/reversal → dashboard/report reconciliation. Verify unauthorized tenant access is denied.
5. Record onboarding completion and time to first invoice, delivery failures, defects, request IDs, and operator response. PRD targets are at least 80% onboarding completion and first invoice within five minutes after setup; measure rather than promise these.
6. Resolve critical/high workflow, isolation and financial defects before expanding. Review pilot results and release gates before Phase 8 billing work.

No pilot tenants, invitations, charges, or real financial records are created by this plan.
