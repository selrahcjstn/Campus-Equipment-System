"""Shared portal pagination; URL generation performs no database work."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def pagination_links(context, page, parameter="page"):
    query = context["request"].GET.copy()
    # Keep effective defaults (e.g. the initial Pending queue) on later pages.
    form = context.get("filter_form")
    if form is not None and form.is_bound:
        for field in form:
            value = field.value()
            if field.html_name not in query and value not in (None, ""):
                query[field.html_name] = value

    def page_url(number):
        query[parameter] = number
        return "?" + query.urlencode()

    pages = []
    for number in page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1):
        pages.append({"number": number, "url": None if number == page.paginator.ELLIPSIS else page_url(number)})
    return {
        "pages": pages,
        "previous": page_url(page.previous_page_number()) if page.has_previous() else None,
        "next": page_url(page.next_page_number()) if page.has_next() else None,
    }
