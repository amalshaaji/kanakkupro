# Phase 5 financial workflow

## Setup and supported scope

1. Install the pinned Python dependencies and the native Pango libraries needed by WeasyPrint. On macOS with Homebrew: `brew install pango`. On Debian/Ubuntu: `apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`.
2. Configure PostgreSQL and run `python manage.py migrate`, then `npm ci && npm run build`.
3. An Owner or Admin completes **Invoices → Invoice settings** with the regular GST seller's legal name, registered address, GSTIN, registration state, payment instructions, and signatory name.
4. Complete the customer's Indian billing address/country and each catalog item's price, HSN/SAC, unit, tax treatment, and rate.

This implementation covers ordinary domestic supplies by a regular GST-registered seller in an India/INR workspace. The user explicitly confirms applicability and chooses the legally determined place of supply. The seller state and selected place of supply must agree with the selected intra-State/inter-State treatment. GSTIN validation checks syntax, checksum, and registration-state consistency; it does not query the GST registry or determine the seller's registration status.

Reverse charge, composition sellers, SEZ, imports/exports, e-invoicing mandates, advance receipts, and intra-UT supplies needing UTGST are outside V1 and must not be processed through this workflow. Taxable and exempt supplies use separate documents; all-exempt invoices render as bills of supply. Tax applicability, HSN/SAC requirements, special place-of-supply rules, and signing requirements still need business tax review. The PDF prints an authorized-signatory block; it does not digitally sign or file documents.

## Drafts and issuance

Create a draft with an active tenant-owned customer, issue/due dates, buyer GSTIN if registered, billing state, explicit place of supply, delivery address, and up to 100 lines. Each line selects a tenant-owned catalog item. The unit price defaults from the catalog and may be overridden before issue. Customer, seller, and line details are copied into issued snapshots; future customer/catalog/settings changes do not rewrite issued records.

Draft edits replace their lines atomically and increment a revision. A stale form cannot overwrite a newer revision or issue a newer draft without review. Saving drafts, issuing documents, posting payments, and reversing payments all use UUID request keys, persisted request fingerprints, and result references. Reusing a key with different data is rejected.

On issue, one sequence per workspace and Indian financial year (April–March) allocates `KP/YY-YY/000001`. Invoices and correction notes share this series. Numbers are assigned only inside the issuance transaction, with tenant/number uniqueness enforced by PostgreSQL. Dates cannot precede a later issued document in the same financial year. Series exhaustion at 999999 requires a separate numbering decision; the system never silently changes the approved format.

Every financial writer locks the tenant before membership/document/sequence rows. This deliberately serializes financial writes within a workspace, including the first sequence allocation and duplicate-request lookup. Cross-workspace writes remain independent. Finer-grained locking can be considered after measuring production contention.

## Amounts and rounding

- Quantity and unit price support four decimal places. Binary floats and nonfinite values are rejected.
- Prices exclude GST. A fixed line discount in paise is deducted before GST; percentage and tax-inclusive discounts are not supported.
- Multiply quantity by unit price and round half-up to four places; subtract the line discount to obtain the four-place taxable value.
- Calculate GST using the catalog-selected rate and explicit supply type. The existing calculator retains four-place intermediate values, then rounds each CGST/SGST or IGST component independently, half-up to paise.
- Round each line's taxable value to paise and add its paise tax components. Sum these stored line amounts for document totals; never recalculate historical documents from live catalog prices.
- Nearest-rupee statutory payment rounding is not automatically applied to invoice totals. Documents must have a positive total.

## Payments, corrections, and balances

Payments can be posted only against issued invoices, in INR, dated from issue through the current workspace date. Partial payments are supported. Unsupported overpayments and future-dated payments are rejected. Payment method/reference are descriptive records; this feature does not charge a card or initiate a bank transfer.

Posted payments remain unchanged. An authorized reversal appends a linked record with actor, date, and mandatory reason. Each payment can be reversed once. The original entry and audit events remain available.

Issued invoices have no direct edit, destructive void, or delete endpoint. Correct them with a linked credit/debit note, retaining the original billing and supply snapshots. Credit lines reference original invoice or issued debit-note lines, including archived catalog items. Cumulative credited quantities, taxable values, and tax components cannot exceed the source line. Credits also cannot exceed the currently unpaid balance. To cancel an unpaid invoice, issue a full linked credit; the invoice displays **Credited** while both documents remain intact. Refunds of already paid amounts need a separately specified workflow.

The authoritative balance is:

`original invoice + issued debit notes − issued credit notes − unreversed payments`

Payment status (Issued, Partially paid, Paid, Credited) and overdue are derived. Issued document state and stored totals do not change as payments are posted. Dashboard/report summaries use independent aggregate subqueries to avoid multiplying sums when an invoice has several lines, notes, and payments. They show all-time net invoiced value, net receipts, receivables, and overdue balances. Overdue means a positive balance after the due date in the tenant time zone.

## Authorization and storage

Active members can view tenant-scoped invoices/PDFs. Owner/Admin/Manager/Staff can create and issue ordinary invoices and record payments. Only Owner/Admin/Manager can create/issue corrections or reverse payments. Only Owner/Admin can edit seller settings. Views and services both check the applicable action; services revalidate active membership, account, and tenant inside the transaction.

PostgreSQL guards reject issued-document/line mutations, financial-ledger updates/deletes, cross-tenant customer/item/payment associations, ownership reassignment, and payments exceeding the locked invoice balance. Service validation enforces calculation, correction, state, and role rules. This is shared-schema tenant scoping with database integrity defenses, not row-level security.

Invoice PDFs use an autoescaped, controlled WeasyPrint template and deny all URL/file/data resource fetches. PDF downloads are authenticated, tenant-scoped, issued-only, and marked private/no-store. They use stored snapshots and totals, include page numbers and repeated line headers, and do not expose live payment status as part of the immutable invoice document.

## Verification and deployment

The automated suite covers tenant/role denial, CSRF, snapshots, exact arithmetic, fiscal-year numbering, stale revisions, idempotency, rollback, database guards, concurrent issuance/payments, correction limits, PDF text/totals, and multipage output. The browser smoke journey covers login → draft → issue → PDF → partial/final payments → reversal → credit note, with desktop/mobile layout checks.

The new sales/payment migrations are additive. Apply all migrations in order; the financial guards depend on both apps' tables. Test and back up the deployment database before release. Do not remove the guards or reverse these migrations to discard issued documents.

Phase 6 remains: provider-specific monitoring, security/performance review, backup/restore verification, operational readiness, and pilot support. This implementation does not claim production or statutory compliance certification. See [Operations](operations.md) and [ADR-001](decisions/ADR-001-india-launch.md).

References used for implementation: [CBIC invoice particulars](https://cbic-gst.gov.in/gst-invoice-rules.html), [Django transaction locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update), and [WeasyPrint installation](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
