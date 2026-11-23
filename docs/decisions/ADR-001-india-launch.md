# ADR-001: India launch defaults and GST scope

- Status: Partially decided; tax behavior not approved for implementation
- Date: 2026-11-23

## Context

The product owner selected India as the launch country, serving B2B GST-registered businesses and B2C consumers. INR is the initial currency. The proposed monetary representation keeps four decimal places for intermediate calculations and displays or settles amounts at two decimal places.

## Confirmed product defaults

- New business workspaces default to `IN` country, `INR` currency, and `Asia/Kolkata` time zone.
- A proposed standard taxable rate is 18% GST, split as 9% CGST plus 9% SGST for qualifying intra-State supplies, or 18% IGST for qualifying inter-State supplies.
- The proposed per-line calculation uses round-half-up to two decimal places.
- The product owner requests nearest-rupee rounding for invoice tax totals when required by local compliance; the exact scope of that rounding still needs confirmation.

## Constraints and unresolved tax scope

The 18% rate must not be applied to every item by default. CBIC's published rate schedule contains multiple rates. The applicable rate depends on the goods/services classification and other rules. Inter-State versus intra-State treatment depends on the legally determined place of supply relative to the supplier location, with special cases; it cannot always be derived from the customer's state alone.

Before tax calculation is implemented, decide whether the initial release:

1. Supports only specifically selected standard-rated 18% supplies and rejects all other supplies; or
2. Stores per-item HSN/SAC and tax treatment/rate, including the supported zero-rated, exempt, and other rate cases.

Also unresolved:

- Seller GST status and registration details to collect (GSTIN, registration state, registered address, regular/composition/unregistered modes).
- Buyer GSTIN, billing/shipping addresses, and the place-of-supply inputs needed for goods and services.
- Whether the line rounding rule applies independently to each GST component, and exactly where nearest-rupee rounding applies. CGST Act section 170 describes rounding amounts payable/refundable under the Act to the nearest rupee; tax counsel/accountant should confirm how the product should represent paise-level invoice tax versus statutory payment totals.
- Invoice series format. GST invoice rules require a consecutive serial number unique for a financial year and impose a 16-character limit; the chosen series format/reset operation remains open.
- Void, credit/debit note, and correction workflow.
- Payment overpayment, reversal/refund, and idempotency policy.
- Financial retention and the production recovery objectives.

## Proposed V1 scope for review (not approved)

- Configure HSN/SAC and tax treatment per catalog item; do not assume 18% for every item.
- Initially support regular GST-registered sellers and ordinary domestic supplies with a supported place-of-supply path. Defer composition sellers, reverse charge, SEZ, imports/exports, and e-invoicing until separately scoped.
- Use invoice numbers in the form `KP/YY-YY/000001`, consecutively unique within each financial year. This pattern is 15 characters and remains within the referenced 16-character limit.
- Round each line tax component half-up to paise and retain invoice tax totals in paise. Apply nearest-rupee rounding only to statutory payable/refundable amounts where required, subject to accountant confirmation.
- Keep drafts editable and issued invoices immutable. Correct issued documents with linked credit/debit notes and audit events.
- Allow partial payments, reject overpayments, and preserve reversals as append-only records with actor, reason, and idempotency protection.

## Decision

Apply only the market defaults above to new tenant workspaces. Do not create invoice/payment schema or calculate tax until the unresolved scope and financial document policies are signed off. Existing workspaces are not changed by these defaults. The V1 scope above remains a proposal until approved.

## Official references consulted

- [CBIC GST rates](https://cbic-gst.gov.in/hindi/gst-goods-services-rates.html)
- [CBIC tax invoice, credit and debit note rules](https://cbic-gst.gov.in/gst-invoice-rules.html)
- [Integrated Goods and Services Tax Act](https://cbic-gst.gov.in/hindi/IGST-bill-e.html)
- [Central Goods and Services Tax Act, section 170](https://cbic-gst.gov.in/hindi/CGST-bill-e.html)
