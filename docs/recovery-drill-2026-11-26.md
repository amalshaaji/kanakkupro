# Neon recovery drill — 2026-11-26

Result: an isolated point-in-time recovery branch was created successfully and queried. Production remained the default branch; no production reset, restore, schema change, or application connection change was performed.

## Observed provider configuration

- Neon project: KanakkuPro (`nameless-surf-29988154`).
- Region: AWS US East 2 (Ohio); PostgreSQL 18; Free plan.
- History retention displayed by Neon: **6 hours**. This is a limited recovery window, not evidence of separately protected long-term backups.
- Source: `production` (`br-morning-breeze-be8umjtq`).
- Recovery branch: `recovery-drill-2026-11-26` (`br-solitary-unit-befko6s1`).
- Requested recovery point: **2026-11-26 23:21 Asia/Kolkata**, equivalent to **17:51 UTC**.
- Branch creation time displayed by Neon: **2026-11-26 23:27:38 Asia/Kolkata**.
- Recovery branch expiration: Never. It remains available for review within the same project and permissions. No paid plan was selected.

## Read-only verification

The recovered database exposed 30 public base tables. A single SELECT with UNION ALL computed counts and SHA-256 content fingerprints for 19 critical tables. Each fingerprint used ordered row JSON (ordered by primary-key text) and UTF-8 encoding. The identical SELECT was then run against production; all 19 counts and fingerprints matched. No raw user/customer records, passwords, connection strings, or authentication tokens were extracted into this report.

| Table | Rows | Count and fingerprint comparison |
| --- | ---: | --- |
| account_emailaddress | 1 | Match |
| accounts_user | 1 | Match |
| audit_auditevent | 2 | Match |
| catalog_catalogitem | 1 | Match |
| customers_customer | 0 | Match |
| django_migrations | 44 | Match |
| mfa_authenticator | 0 | Match |
| payments_payment | 0 | Match |
| payments_paymentreversal | 0 | Match |
| sales_financialcommand | 0 | Match |
| sales_invoice | 0 | Match |
| sales_invoiceline | 0 | Match |
| sales_invoicesequence | 0 | Match |
| sales_sellerprofile | 0 | Match |
| tenants_invitation | 0 | Match |
| tenants_pilotcheck | 0 | Match |
| tenants_pilotfeedback | 0 | Match |
| tenants_tenant | 1 | Match |
| tenants_tenantmembership | 1 | Match |

The production comparison was against its current state after branch creation, not a separately pinned historical query. Matching results show the checked contents were equal at those observations; they do not establish recovery of intervening writes or historical changes.

## Remaining release evidence

1. Approve retention and recovery objectives, including coverage beyond the observed six-hour window and protection from project/account loss. Keep MFA encryption keys recoverable separately from the database.
2. Repeat an isolated drill with representative invoices, partial/final payments, corrections/reversals, and audit records. Existing financial tables were empty, so this drill cannot establish nonempty financial reconciliation.
3. Connect an isolated application to the recovered target and verify login/MFA, tenant isolation, invoice PDF and financial reports. This drill verified database queries only.
4. Measure incident-to-restored-service elapsed time and recoverable committed-write loss. Branch timestamps alone are not an end-to-end RTO/RPO measurement.
5. Review the retained drill branch for cleanup after evidence review; it has no automatic expiration. Do not point production at it as part of routine cleanup.

Phase 6 backup readiness and Phase 7 admission remain open until this evidence is complete.
