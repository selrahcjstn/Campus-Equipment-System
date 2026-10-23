"""Keep locally served UI styles in sync with their templates."""
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def ui_asset(path):
    url = static(path)
    source = finders.find(path)
    if source:
        try:
            version = Path(source).stat().st_mtime_ns
        except OSError:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}v={version}"
    # Collected assets may only exist in the configured static storage.
    return url
