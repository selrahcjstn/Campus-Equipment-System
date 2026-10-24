from datetime import datetime, timezone as dt_timezone

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import timezone


class TableDateTimeTests(SimpleTestCase):
    def test_local_timestamp_keeps_date_time_together_across_midnight(self):
        value = datetime(2026, 10, 31, 23, 59, tzinfo=dt_timezone.utc)
        with timezone.override("Asia/Manila"):
            html = render_to_string("components/table_datetime.html", {"value": value})
        self.assertIn("Nov 1, 2026 · 7:59 AM", html)
        self.assertIn('datetime="2026-11-01T07:59:00+08:00"', html)
        self.assertNotIn("<br", html)
        self.assertNotIn("<div", html)
        self.assertNotIn("<span", html)
        self.assertEqual(value.hour, 23)

    def test_timestamp_uses_the_active_timezone(self):
        value = datetime(2026, 10, 31, 23, 59, tzinfo=dt_timezone.utc)
        with timezone.override("UTC"):
            html = render_to_string("components/table_datetime.html", {"value": value})
        self.assertIn("Oct 31, 2026 · 11:59 PM", html)
        self.assertIn('datetime="2026-10-31T23:59:00+00:00"', html)

    def test_missing_timestamp_has_a_readable_placeholder(self):
        html = render_to_string("components/table_datetime.html", {"value": None})
        self.assertIn("—", html)
        self.assertNotIn("<time", html)
