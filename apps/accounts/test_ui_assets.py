import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings


class StylesheetCacheTests(SimpleTestCase):
    def test_changed_stylesheet_gets_a_new_url_while_unchanged_asset_is_cacheable(self):
        with TemporaryDirectory() as directory:
            stylesheet = Path(directory) / "dashboard-cache-check.css"
            stylesheet.write_text(".metric-grid { display: block; }", encoding="utf-8")
            with override_settings(STATICFILES_DIRS=[directory], STATIC_URL="/static/"):
                template = Template("{% load ui_assets %}{% ui_asset 'dashboard-cache-check.css' %}")
                original = template.render(Context())
                self.assertEqual(template.render(Context()), original)
                stylesheet.write_text(".metric-grid { display: grid; }", encoding="utf-8")
                # Avoid relying on the filesystem's clock resolution.
                stamp = stylesheet.stat().st_mtime_ns + 1_000_000_000
                os.utime(stylesheet, ns=(stamp, stamp))
                changed = template.render(Context())
                self.assertNotEqual(original, changed)
                self.assertEqual(urlsplit(original).path, urlsplit(changed).path)

    @override_settings(STATIC_URL="/static/")
    def test_user_dashboard_versions_both_shared_and_page_styles(self):
        html = render_to_string("dashboard/user_portal.html", {
            "request": RequestFactory().get("/portal/"), "user": AnonymousUser(),
            "pending_count": 0, "approved_count": 0, "borrowed_count": 0,
            "overdue_count": 0,
        })
        for asset in ["design-system", "filters", "dashboard"]:
            self.assertRegex(html, rf'href="/static/css/{asset}\.css\?v=\d+"')
        self.assertIn('class="metric-grid"', html)
        self.assertIn('class="dashboard-shortcuts"', html)

    @override_settings(STATIC_URL="/static/")
    def test_missing_source_preserves_the_static_storage_url(self):
        html = Template("{% load ui_assets %}{% ui_asset 'missing-ui-style.css' %}").render(Context())
        self.assertEqual(html, "/static/missing-ui-style.css")
