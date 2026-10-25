from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import BorrowingRequest
from apps.inventory.models import Category
from apps.loans.models import Loan
from apps.loans.services import process_returns
from .services import category_usage, dashboard_statistics, monthly_issued_loans, personal_summary, loan_report
from .tests import DashboardFixtures


class DashboardComplianceTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()
        category = Category.objects.create(name="Audiovisual")
        self.equipment.category = category
        self.equipment.save(update_fields=["category"])

    def test_required_kpis_and_charts_render_and_pending_changes(self):
        record = self.pending()
        self.assertEqual(dashboard_statistics(at=timezone.now())["pending_requests"], 1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        for label in ["Available units", "Pending requests", "Active loans", "Overdue loans", "Monthly issued loans", "Equipment-category usage"]:
            self.assertContains(response, label)
        from apps.borrowing.services import approve_request
        approve_request(record.pk, actor=self.admin, reason="Class presentation approved.")
        self.assertEqual(dashboard_statistics(at=timezone.now())["pending_requests"], 0)

    def test_monthly_chart_counts_loans_once_not_requests_or_physical_units(self):
        self.pending()
        loan = self.issue(quantity=2)
        at = datetime(2026, 9, 30, 16, 0, tzinfo=ZoneInfo("UTC"))  # October in Manila
        Loan.objects.filter(pk=loan.pk).update(issued_at=at, due_at=at+timedelta(days=3))
        with timezone.override("America/New_York"):
            series = monthly_issued_loans(date(2026, 9, 1), date(2026, 11, 30))
            self.assertEqual([(p["date"], p["count"]) for p in series], [(date(2026, 9, 1), 0), (date(2026, 10, 1), 1), (date(2026, 11, 1), 0)])
            self.assertEqual(sum(p["count"] for p in monthly_issued_loans(date(2026, 9, 1), date(2026, 9, 30))), 0)
            self.assertEqual(sum(p["count"] for p in monthly_issued_loans(date(2026, 10, 1), date(2026, 10, 1))), 1)

    def test_category_usage_counts_each_issuance_and_preserves_returned_history(self):
        loan = self.issue(quantity=2)
        start, end = timezone.localdate()-timedelta(days=1), timezone.localdate()
        self.assertEqual(category_usage(start, end), [{"label": "Audiovisual", "count": 2, "percentage": 100.0}])
        self.complete(loan)
        self.issue(quantity=1)
        # A unit borrowed again is another real use. Joining returns must not
        # multiply either the original or repeated issuance.
        self.assertEqual(category_usage(start, end)[0]["count"], 3)
        self.assertEqual(sum(p["count"] for p in monthly_issued_loans(start, end)), 2)
        self.assertEqual(category_usage(start-timedelta(days=30), start-timedelta(days=1)), [])

    def test_legacy_uncategorized_usage_is_not_dropped(self):
        self.equipment.category = None
        self.equipment.save(update_fields=["category"])
        self.issue()
        today = timezone.localdate()
        self.assertEqual(category_usage(today, today)[0]["label"], "Uncategorized (legacy)")

    def test_same_local_due_date_remains_active_across_dashboard_views_reports_and_csv(self):
        loan = self.issue(quantity=2)
        noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        Loan.objects.filter(pk=loan.pk).update(issued_at=noon-timedelta(days=2), due_at=noon)
        at = noon+timedelta(hours=1)
        with patch("django.utils.timezone.now", return_value=at), timezone.override("UTC"):
            loan.refresh_from_db()
            self.assertFalse(loan.is_overdue)
            self.assertFalse(Loan.objects.overdue().exists())
            self.assertEqual(dashboard_statistics(at=at)["overdue_loans"], 0)
            self.assertEqual(len(personal_summary(self.basic, at=at)["upcoming"]), 1)
            self.assertFalse(loan_report({"report": "overdue"}, at=at).exists())
            self.client.force_login(self.basic)
            self.assertEqual(self.client.get(reverse("my_loans"), {"status": "active"}).context["page_obj"].paginator.count, 1)
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(reverse("returns_overdue"), {"status": "overdue"}).context["page_obj"].paginator.count, 0)
            self.assertNotContains(self.client.get(reverse("export_reports"), {"report": "loans"}), "Overdue,Outstanding")
            process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
            loan.refresh_from_db()
            self.assertFalse(loan.is_overdue)
        midnight = noon.replace(hour=0)+timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=midnight):
            self.assertTrue(Loan.objects.overdue().filter(pk=loan.pk).exists())
            self.assertEqual(dashboard_statistics(at=midnight)["overdue_loans"], 1)
            self.complete(loan)
            self.assertFalse(Loan.objects.overdue().exists())
