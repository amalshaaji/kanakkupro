# ADR-001: India launch and GST V1 scope

- Status: V1 scope, retention, and recovery targets approved; provider capability verification pending
- Date: 2026-11-23

## Context and confirmed defaults

The product owner selected India as the launch country, serving B2B GST-registered businesses and B2C consumers. INR is the initial currency. Intermediate monetary values use four decimal places; displayed and settled values use two decimal places.

New business workspaces default to `IN`, `INR`, and `Asia/Kolkata`. Existing workspaces are unchanged.

The product owner proposed 18% GST, split into 9% CGST plus 9% SGST for intra-State supplies, or 18% IGST for inter-State supplies. Per-line tax components round half-up to paise. The product owner approved the V1 scope below in the conversation on 2026-11-23.

The product owner approved retention of GST invoices, payments, and related records for at least 72 months from the due date of the annual return, extending retention while a related appeal, proceeding, or investigation remains open. The product owner approved initial recovery objectives of RPO 24 hours and RTO 4 hours. Before pilot, the deployment owner must verify that the selected provider and plan can meet these objectives.

## Approved V1 scope

- Store HSN/SAC and tax treatment/rate per catalog item. Do not assume 18% for every item.
- Support regular GST-registered sellers and ordinary domestic supplies with a supported place-of-supply path. Defer composition sellers, reverse charge, SEZ, imports/exports, and e-invoicing until separately scoped.
- Use invoice numbers of the form `KP/YY-YY/000001`, consecutively unique within each financial year. This pattern is 15 characters and within the referenced 16-character limit.
- Calculate each line GST component using half-up rounding to paise; sum invoice tax in paise. Apply nearest-rupee rounding only to statutory amounts payable/refundable where required, not automatically to invoice tax totals.
- Keep drafts editable and issued invoices immutable. Correct issued documents with linked credit/debit notes and audit events.
- Allow partial payments, reject overpayments, and preserve reversals as append-only records with actor, reason, and idempotency protection.

## Implementation boundary

The tax calculation service accepts a pre-tax line taxable value, the selected tax rate, and a supply type. Callers must supply the legally reviewed HSN/SAC rate and place-of-supply result; the service does not infer either from a customer state or GSTIN. Discounts and tax-inclusive prices are not handled by this calculation service. Invoice aggregation, statutory nearest-rupee adjustments, numbering, and document corrections are separate domain workflows.

Financial retention and recovery decisions are approved, so invoice/payment schema work may proceed in a subsequent implementation slice. The deployment owner must verify provider capability for RPO 24 hours and RTO 4 hours before pilot. The retention baseline is consistent with [CGST Act section 36](https://cbic-gst.gov.in/hindi/CGST-bill-e.html).

## Official references consulted

- [CBIC GST rates](https://cbic-gst.gov.in/hindi/gst-goods-services-rates.html)
- [CBIC tax invoice, credit and debit note rules](https://cbic-gst.gov.in/gst-invoice-rules.html)
- [Integrated Goods and Services Tax Act](https://cbic-gst.gov.in/hindi/IGST-bill-e.html)
- [Central Goods and Services Tax Act, section 170](https://cbic-gst.gov.in/hindi/CGST-bill-e.html)
