from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def report_page_url(context, parameter, number):
    query = context["request"].GET.copy()
    if parameter not in {"dpage", "ppage", "rpage", "cpage"}:
        raise ValueError("Unknown report page.")
    query[parameter] = str(number)
    return "?" + query.urlencode()
