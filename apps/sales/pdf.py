from django.template.loader import render_to_string

from apps.sales.validation import STATES


def deny_resource_fetch(url, *args, **kwargs):
    # No user-supplied URL, filesystem path, image, font, or CSS import is fetched.
    raise ValueError("External resources are disabled for invoice PDFs.")


def render_invoice_pdf(invoice):
    from weasyprint import HTML

    if invoice.state != "issued":
        raise ValueError("Only issued documents can be exported.")
    lines = list(invoice.lines.all())
    title = invoice.get_kind_display()
    if invoice.kind == "invoice":
        title = (
            "Bill of supply"
            if all(line.tax_treatment == "exempt" for line in lines)
            else "Tax invoice"
        )
    html = render_to_string(
        "sales/invoice_pdf.html",
        {
            "invoice": invoice,
            "lines": lines,
            "document_title": title,
            "supply_state": STATES[invoice.place_of_supply],
            "seller_state": STATES[invoice.seller_snapshot["state_code"]],
            "buyer_state": STATES[invoice.buyer_state],
        },
    )
    return HTML(string=html, url_fetcher=deny_resource_fetch).write_pdf()
