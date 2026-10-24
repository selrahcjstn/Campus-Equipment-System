import csv
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import set_user_active
from apps.borrowing.forms import BorrowingRequestForm, RequestItemFormSet
from apps.borrowing.models import Allocation, BorrowingRequest, BorrowingRequestItem
from apps.borrowing.services import approve_request, cancel_request, reject_request, submit_request
from apps.inventory.models import Category, Equipment, EquipmentUnit
from apps.inventory.services import add_unit, archive_equipment, delete_category, edit_unit, restore_equipment, retire_unit, save_category, save_equipment
from apps.loans.models import Loan, LoanUnit
from apps.loans.services import process_returns, release_request
from apps.maintenance.models import MaintenanceRecord
from apps.maintenance.services import create_record, record_damaged_return, resolve_record, update_record
from .forms import SystemSettingsForm
from .audit import record_event
from .models import AuditLog, SystemSetting
from .policies import borrowing_limits
from .services import borrowing_activity, dashboard_statistics, loan_report, report_row, status_distribution, update_settings


class DashboardFixtures:
    def make_records(self):
        User = get_user_model()
        self.admin = User.objects.create_user("dashboard-admin", role="ADMIN")
        self.basic = User.objects.create_user("dashboard-basic", role="BASIC_USER")
        self.other = User.objects.create_user("other-basic", role="BASIC_USER")
        self.equipment = Equipment.objects.create(name="Projector", description="Public description")
        self.units = [EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"PROJECTOR-{i}") for i in range(3)]

    def pending(self, *, quantity=1, borrower=None):
        request = BorrowingRequest.objects.create(borrower=borrower or self.basic, purpose="Class presentation", due_at=timezone.now() + timedelta(days=2))
        BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=quantity)
        return request

    def issue(self, *, quantity=1, borrower=None, overdue=False):
        request = self.pending(quantity=quantity, borrower=borrower)
        approve_request(request.pk, actor=self.admin)
        loan = release_request(request.pk, actor=self.admin)
        if overdue:
            now = timezone.now()
            Loan.objects.filter(pk=loan.pk).update(issued_at=now - timedelta(days=4), due_at=now - timedelta(days=1, hours=2))
            BorrowingRequest.objects.filter(pk=request.pk).update(requested_at=now - timedelta(days=5), due_at=now - timedelta(days=1, hours=2))
            loan.refresh_from_db()
        return loan

    def complete(self, loan):
        return process_returns(loan.pk, actor=self.admin, returns=[(unit.pk, "GOOD", "") for unit in loan.units.filter(returned_at__isnull=True)])

    def log(self, *, action="EQUIPMENT_UPDATED", entity_id=1):
        return record_event(actor=self.admin, action=action, entity_type="equipment", entity_id=entity_id, description="Updated catalog metadata.")

    def csv_rows(self, response):
        return list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))


class DashboardAccessTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def admin_urls(self):
        return [reverse(name) for name in ["admin_dashboard", "reports", "export_reports", "audit_logs", "system_settings"]]

    def test_anonymous_users_redirect_on_all_pages(self):
        for url in [reverse("user_dashboard"), *self.admin_urls()]:
            for method in [self.client.get, self.client.post]:
                response = method(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_basic_dashboard_is_basic_only(self):
        self.client.force_login(self.basic)
        self.assertEqual(self.client.get(reverse("user_dashboard")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("user_dashboard")).status_code, 403)

    def test_basic_cannot_access_admin_pages_or_export_even_as_superuser(self):
        self.basic.is_staff = self.basic.is_superuser = True
        self.basic.save()
        self.client.force_login(self.basic)
        for url in self.admin_urls():
            for method in [self.client.get, self.client.post]:
                self.assertEqual(method(url).status_code, 403)

    def test_admin_pages_and_sidebar_destinations_render(self):
        self.client.force_login(self.admin)
        for name in ["admin_dashboard", "reports", "audit_logs", "system_settings"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Admin Portal")
            self.assertContains(response, 'aria-current="page"')
        self.assertEqual(self.client.get(reverse("export_reports")).status_code, 200)

    def test_get_and_read_only_posts_cannot_change_settings_or_audit(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("system_settings"))
        self.assertFalse(SystemSetting.objects.exists())
        self.assertFalse(AuditLog.objects.exists())
        for name in ["admin_dashboard", "reports", "export_reports", "audit_logs"]:
            self.assertEqual(self.client.post(reverse(name)).status_code, 405)
        self.assertEqual(self.client.delete(reverse("system_settings")).status_code, 405)

    def test_settings_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("system_settings"), {"max_items": 1, "max_quantity": 1, "max_days": 1, "confirm": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SystemSetting.objects.exists())

    def test_inactive_accounts_cannot_use_services(self):
        self.admin.is_active = False
        with self.assertRaises(PermissionDenied):
            update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        with self.assertRaises(PermissionDenied):
            set_user_active(self.basic.pk, actor=self.admin, is_active=False)


class StatisticsAndChartsTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_kpis_count_physical_units_and_loans(self):
        loan = self.issue(quantity=2, overdue=True)
        statistics = dashboard_statistics(at=timezone.now())
        self.assertEqual(statistics, {"total_units": 3, "available_units": 1, "active_loans": 1, "overdue_loans": 1})
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
        statistics = dashboard_statistics(at=timezone.now())
        self.assertEqual(statistics["active_loans"], 1)
        self.assertEqual(statistics["overdue_loans"], 1)
        self.assertEqual(statistics["available_units"], 2)
        self.complete(loan)
        statistics = dashboard_statistics(at=timezone.now())
        self.assertEqual(statistics["active_loans"], 0)
        self.assertEqual(statistics["overdue_loans"], 0)

    def test_archived_available_units_excluded_from_borrowable_kpi(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        statistics = dashboard_statistics(at=timezone.now())
        self.assertEqual(statistics["total_units"], 3)
        self.assertEqual(statistics["available_units"], 0)
        self.assertEqual(status_distribution()[0]["count"], 3)

    def test_active_maintenance_excludes_available_kpi_even_if_state_is_stale(self):
        create_record(self.units[0].pk, actor=self.admin, reason="Issue")
        EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status="AVAILABLE")
        self.assertEqual(dashboard_statistics(at=timezone.now())["available_units"], 2)

    def test_status_distribution_includes_all_five_statuses_and_zeroes(self):
        EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status="ON_LOAN")
        EquipmentUnit.objects.filter(pk=self.units[1].pk).update(status="MAINTENANCE")
        groups = status_distribution()
        self.assertEqual([group["label"] for group in groups], ["Available", "Reserved", "Issued", "Maintenance", "Retired"])
        self.assertEqual([group["count"] for group in groups], [1, 0, 1, 1, 0])
        self.assertAlmostEqual(sum(group["percentage"] for group in groups), 100)

    def test_empty_database_dashboard_has_zero_cards_and_both_charts(self):
        EquipmentUnit.objects.all().delete()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.context["statistics"], {"total_units": 0, "available_units": 0, "active_loans": 0, "overdue_loans": 0})
        self.assertEqual(response.context["activity_total"], 0)
        self.assertContains(response, "No borrowing requests were submitted")
        self.assertContains(response, "Equipment status distribution")

    def test_chart_groups_local_dates_and_fills_zero_dates(self):
        # 16:30 UTC is the next calendar date in Manila.
        request = self.pending()
        at = datetime(2026, 10, 13, 16, 30, tzinfo=dt_timezone.utc)
        BorrowingRequest.objects.filter(pk=request.pk).update(requested_at=at, due_at=at + timedelta(days=2))
        start = timezone.localdate(at)
        series = borrowing_activity(start - timedelta(days=1), start + timedelta(days=1))
        self.assertEqual([point["count"] for point in series], [0, 1, 0])
        self.assertEqual(series[1]["date"], start)
        self.assertGreater(series[1]["height"], 0)

    def test_chart_filters_include_end_date_and_exclude_next_local_midnight(self):
        first, second = self.pending(), self.pending()
        boundary = timezone.make_aware(datetime(2026, 10, 15))
        BorrowingRequest.objects.filter(pk=first.pk).update(requested_at=boundary - timedelta(seconds=1), due_at=boundary + timedelta(days=2))
        BorrowingRequest.objects.filter(pk=second.pk).update(requested_at=boundary, due_at=boundary + timedelta(days=2))
        date = (boundary - timedelta(seconds=1)).date()
        self.assertEqual(sum(point["count"] for point in borrowing_activity(date, date)), 1)

    def test_invalid_chart_ranges_render_errors(self):
        self.client.force_login(self.admin)
        for data in [{"start_date": "bad", "end_date": "2026-10-14"}, {"start_date": "2026-10-15", "end_date": "2026-10-14"}, {"start_date": "2024-01-01", "end_date": "2026-10-14"}]:
            response = self.client.get(reverse("admin_dashboard"), data)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(response.context["activity"], [])

    def test_dashboard_query_count_does_not_grow_per_record(self):
        self.pending()
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as first:
            self.client.get(reverse("admin_dashboard"))
        for index in range(20):
            self.pending()
        with CaptureQueriesContext(connection) as expanded:
            self.client.get(reverse("admin_dashboard"))
        self.assertEqual(len(first), len(expanded))
        self.assertLessEqual(len(expanded), 8)

    def test_fully_returned_units_not_overdue_even_if_completion_metadata_is_stale(self):
        loan = self.issue(overdue=True)
        self.complete(loan)
        Loan.objects.filter(pk=loan.pk).update(completed_at=None)
        statistics = dashboard_statistics(at=timezone.now())
        self.assertEqual(statistics["active_loans"], 0)
        self.assertEqual(statistics["overdue_loans"], 0)
        values = {"report": "overdue"}
        self.assertFalse(loan_report(values).exists())


class PersonalDashboardTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.basic)

    def test_empty_personal_dashboard_keeps_all_navigation(self):
        response = self.client.get(reverse("user_dashboard"))
        for name in ["equipment_catalog", "my_requests", "my_loans", "borrowing_history", "my_profile"]:
            self.assertContains(response, reverse(name))
        self.assertContains(response, "No borrowing activity yet")
        self.assertEqual(response.context["borrowed_count"], 0)

    def test_counts_recent_requests_and_upcoming_loans_belong_to_user(self):
        pending = self.pending()
        approved = self.pending()
        approve_request(approved.pk, actor=self.admin)
        loan = self.issue()
        response = self.client.get(reverse("user_dashboard"))
        self.assertEqual(response.context["pending_count"], 1)
        self.assertEqual(response.context["approved_count"], 1)
        self.assertEqual(response.context["borrowed_count"], 1)
        self.assertEqual(response.context["upcoming"][0]["loan"], loan)
        self.assertIn(pending, response.context["recent_requests"])

    def test_data_isolation_excludes_other_borrowers_and_internal_notes(self):
        own = self.pending()
        other = self.issue(borrower=self.other, overdue=True)
        self.other.first_name = "OTHER-PRIVATE-NAME"
        self.other.save()
        BorrowingRequest.objects.filter(pk=other.request_id).update(purpose="PRIVATE-PURPOSE")
        create_record(self.units[2].pk, actor=self.admin, reason="PRIVATE-MAINTENANCE")
        response = self.client.get(reverse("user_dashboard"))
        self.assertEqual(list(response.context["recent_requests"]), [own])
        self.assertEqual(response.context["borrowed_count"], 0)
        self.assertEqual(response.context["overdue_count"], 0)
        for text in ["OTHER-PRIVATE-NAME", "PRIVATE-PURPOSE", "PRIVATE-MAINTENANCE", "/manage/reports/"]:
            self.assertNotContains(response, text)

    def test_partial_overdue_count_excludes_returned_units(self):
        loan = self.issue(quantity=2, overdue=True)
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
        response = self.client.get(reverse("user_dashboard"))
        self.assertEqual(response.context["borrowed_count"], 1)
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["overdue"][0]["outstanding"], 1)
        self.assertEqual(response.context["overdue"][0]["outstanding_equipment"], [{"name": "Projector", "quantity": 1}])
        self.assertContains(response, "Your overdue loans")


class ReportsTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_loan_report_issue_date_filter_matches_export(self):
        loan = self.issue()
        day = timezone.localdate(loan.issued_at)
        query = {"report": "loans", "start_date": day.isoformat(), "end_date": day.isoformat()}
        response = self.client.get(reverse("reports"), query)
        self.assertEqual([row["loan"].pk for row in response.context["rows"]], [loan.pk])
        rows = self.csv_rows(self.client.get(reverse("export_reports"), query))
        self.assertEqual([int(row["Loan ID"]) for row in rows], [loan.pk])
        query["start_date"] = query["end_date"] = (day + timedelta(days=1)).isoformat()
        self.assertFalse(self.csv_rows(self.client.get(reverse("export_reports"), query)))

    def test_overdue_report_filters_due_dates_not_issue_dates(self):
        loan = self.issue(overdue=True)
        due_day = timezone.localdate(loan.due_at)
        query = {"report": "overdue", "start_date": due_day.isoformat(), "end_date": due_day.isoformat()}
        response = self.client.get(reverse("reports"), query)
        self.assertEqual(response.context["rows"][0]["loan"], loan)
        rows = self.csv_rows(self.client.get(reverse("export_reports"), query))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Loan status"], "Overdue")
        self.assertEqual(rows[0]["Overdue days"], "1")
        self.assertEqual(rows[0]["Additional overdue hours"], "2")
        query["start_date"] = query["end_date"] = timezone.localdate(loan.issued_at).isoformat()
        self.assertFalse(self.csv_rows(self.client.get(reverse("export_reports"), query)))

    def test_partial_return_report_contains_each_unit_and_correct_status(self):
        loan = self.issue(quantity=2, overdue=True)
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
        rows = self.csv_rows(self.client.get(reverse("export_reports"), {"report": "overdue"}))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["Unit return status"] for row in rows}, {"Returned", "Outstanding"})
        self.assertEqual({row["Outstanding units on loan"] for row in rows}, {"1"})
        self.complete(loan)
        self.assertFalse(self.csv_rows(self.client.get(reverse("export_reports"), {"report": "overdue"})))

    def test_due_time_boundary_is_not_overdue(self):
        loan = self.issue()
        values = {"report": "overdue"}
        self.assertFalse(loan_report(values, at=loan.due_at).exists())
        self.assertTrue(loan_report(values, at=loan.due_at + timedelta(microseconds=1)).exists())

    def test_invalid_date_range_report_and_export(self):
        for query in [{"start_date": "2026-10-15", "end_date": "2026-10-14"}, {"start_date": "not-a-date"}, {"start_date": "0001-01-01"}, {"end_date": "9999-12-31"}, {"report": "INVALID"}]:
            response = self.client.get(reverse("reports"), query)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(len(response.context["rows"]), 0)
            self.assertEqual(self.client.get(reverse("export_reports"), query).status_code, 400)

    def test_csv_headers_format_and_no_sensitive_notes(self):
        loan = self.issue()
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "DAMAGED", "SECRET-RETURN-NOTE")])
        record = MaintenanceRecord.objects.get()
        update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="SECRET-REPAIR-NOTE")
        response = self.client.get(reverse("export_reports"))
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        rows = self.csv_rows(response)
        self.assertIn("Equipment (issue snapshot)", rows[0])
        self.assertIn("+08:00", rows[0]["Issued at (local ISO 8601)"])
        for secret in ["SECRET-RETURN-NOTE", "SECRET-REPAIR-NOTE", self.admin.password]:
            self.assertNotIn(secret, response.content.decode("utf-8-sig"))

    def test_csv_escapes_formula_like_user_values_and_quotes_commas(self):
        self.basic.first_name = "=HYPERLINK(\"bad\")"
        self.basic.save()
        self.equipment.name = "@SUM(1,2)"
        self.equipment.save()
        loan = self.issue()
        row = self.csv_rows(self.client.get(reverse("export_reports")))[0]
        self.assertTrue(row["Borrower name"].startswith("'="))
        self.assertEqual(row["Equipment (issue snapshot)"], "'@SUM(1,2)")
        self.assertEqual(int(row["Loan ID"]), loan.pk)

    def test_report_uses_issue_snapshots_after_inventory_rename(self):
        loan = self.issue()
        Equipment.objects.filter(pk=self.equipment.pk).update(name="Renamed catalog")
        row = self.csv_rows(self.client.get(reverse("export_reports")))[0]
        self.assertEqual(row["Equipment (issue snapshot)"], "Projector")

    def test_report_pagination_and_export_includes_all_filtered_rows(self):
        for index in range(21):
            loan = self.issue()
            self.complete(loan)
        response = self.client.get(reverse("reports"), {"report": "loans"})
        self.assertEqual(len(response.context["rows"]), 10)
        self.assertContains(response, "report=loans&amp;page=2")
        rows = self.csv_rows(self.client.get(reverse("export_reports"), {"report": "loans", "page": 2}))
        self.assertEqual(len(rows), 21)

    def test_overdue_less_than_an_hour_has_meaningful_label(self):
        loan = self.issue()
        row = report_row(loan, at=loan.due_at + timedelta(minutes=5))
        self.assertEqual(row["overdue_label"], "Less than 1 hour")

    def test_loan_without_unit_rows_is_reported_as_needing_review(self):
        request = self.pending()
        loan = Loan.objects.create(request=request, borrower=self.basic, issued_by=self.admin, due_at=request.due_at)
        row = self.csv_rows(self.client.get(reverse("export_reports")))[0]
        self.assertEqual(row["Loan status"], "Needs review")
        self.assertEqual(row["Unit return status"], "No unit record")

    def test_local_date_boundaries_match_display_and_csv(self):
        loan = self.issue()
        boundary = datetime(2026, 10, 13, 16, 0, tzinfo=dt_timezone.utc)
        Loan.objects.filter(pk=loan.pk).update(issued_at=boundary, due_at=boundary + timedelta(days=2))
        query = {"start_date": "2026-10-14", "end_date": "2026-10-14"}
        self.assertEqual(len(self.client.get(reverse("reports"), query).context["rows"]), 1)
        rows = self.csv_rows(self.client.get(reverse("export_reports"), query))
        self.assertTrue(rows[0]["Issued at (local ISO 8601)"].startswith("2026-10-14T00:00:00+08:00"))


class SettingsTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_default_limits_are_three_three_seven_without_creating_a_row(self):
        self.assertEqual(borrowing_limits(), {"max_items": 3, "max_quantity": 3, "max_days": 7})
        self.assertFalse(SystemSetting.objects.exists())

    @override_settings(BORROWING_MAX_ITEMS=1, BORROWING_MAX_QUANTITY=2, BORROWING_MAX_DAYS=2)
    def test_existing_django_configuration_remains_fallback_only(self):
        self.assertEqual(borrowing_limits(), {"max_items": 1, "max_quantity": 2, "max_days": 2})
        update_settings(actor=self.admin, max_items=2, max_quantity=3, max_days=4)
        self.assertEqual(borrowing_limits(), {"max_items": 2, "max_quantity": 3, "max_days": 4})

    def test_update_persists_actor_and_one_audit_event(self):
        policy = update_settings(actor=self.admin, max_items=1, max_quantity=2, max_days=3)
        self.assertEqual(policy.updated_by, self.admin)
        self.assertEqual(borrowing_limits(), {"max_items": 1, "max_quantity": 2, "max_days": 3})
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, "SETTINGS_UPDATED")
        self.assertIn("max_days: 7 → 3", entry.description)
        self.assertEqual(entry.entity_id, 1)

    def test_identical_updates_do_not_duplicate_audit_events(self):
        update_settings(actor=self.admin, max_items=3, max_quantity=3, max_days=7)
        update_settings(actor=self.admin, max_items=3, max_quantity=3, max_days=7)
        self.assertEqual(SystemSetting.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_numeric_type_and_range_validation(self):
        for name, invalid in [("max_items", 0), ("max_items", 4), ("max_items", 11), ("max_quantity", 21), ("max_days", 31), ("max_days", -1), ("max_days", 1.5), ("max_items", True), ("max_quantity", "2")]:
            values = {"max_items": 3, "max_quantity": 3, "max_days": 7, name: invalid}
            with self.subTest(name=name, invalid=invalid), self.assertRaises(ValidationError):
                update_settings(actor=self.admin, **values)
        self.assertFalse(SystemSetting.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_database_enforces_singleton_and_limit_ranges(self):
        for values in [{"id": 2}, {"max_items": 0}, {"max_items": 4}, {"max_quantity": 21}, {"max_days": 31}]:
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                SystemSetting.objects.create(**values)

    def test_settings_form_and_model_reject_four_distinct_items(self):
        form = SystemSettingsForm({"max_items": 4, "max_quantity": 3, "max_days": 7, "confirm": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("max_items", form.errors)
        self.assertEqual(form.fields["max_items"].widget.attrs["max"], 3)
        with self.assertRaises(ValidationError) as error:
            SystemSetting(max_items=4).full_clean()
        self.assertIn("max_items", error.exception.message_dict)

    def test_admin_cannot_raise_item_limit_or_change_other_values_on_invalid_post(self):
        policy = update_settings(actor=self.admin, max_items=2, max_quantity=5, max_days=12)
        initial = policy.as_limits()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("system_settings"), {
            "max_items": 4, "max_quantity": 6, "max_days": 13, "confirm": "on",
        })
        self.assertContains(response, "Ensure this value is less than or equal to 3.")
        policy.refresh_from_db()
        self.assertEqual(policy.as_limits(), initial)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_quantity_and_duration_remain_configurable_with_three_item_ceiling(self):
        policy = update_settings(actor=self.admin, max_items=3, max_quantity=20, max_days=30)
        self.assertEqual(policy.as_limits(), {"max_items": 3, "max_quantity": 20, "max_days": 30})
        self.assertEqual(borrowing_limits(), policy.as_limits())
        formset = RequestItemFormSet(prefix="items")
        self.assertEqual(len(formset.forms), 1)
        self.assertEqual(formset.forms[0].fields["quantity"].widget.attrs["max"], 20)
        form = BorrowingRequestForm()
        self.assertEqual(form.fields["due_date"].widget.attrs["max"], (timezone.localdate() + timedelta(days=30)).isoformat())

    def test_basic_anonymous_and_inactive_cannot_update_policy(self):
        inactive = get_user_model().objects.create_user("disabled-admin", role="ADMIN", is_active=False)
        for actor in [self.basic, AnonymousUser(), inactive]:
            with self.assertRaises(PermissionDenied):
                update_settings(actor=actor, max_items=1, max_quantity=1, max_days=1)

    def test_audit_failure_rolls_back_policy_update(self):
        with patch("apps.dashboard.services.record_event", side_effect=IntegrityError("audit failure")), self.assertRaises(IntegrityError):
            update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        self.assertFalse(SystemSetting.objects.exists())

    def test_new_submissions_obey_saved_quantities_duration_and_distinct_limits(self):
        update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        other = Equipment.objects.create(name="Camera")
        EquipmentUnit.objects.create(equipment=other, asset_tag="OTHER")
        for items, days in [([(self.equipment.pk, 2)], 1), ([(self.equipment.pk, 1), (other.pk, 1)], 1), ([(self.equipment.pk, 1)], 2)]:
            with self.assertRaises(ValidationError):
                submit_request(borrower=self.basic, purpose="Class", due_at=timezone.now() + timedelta(days=days), items=items)
        request = submit_request(borrower=self.basic, purpose="Class", due_at=timezone.now() + timedelta(hours=1), items=[(self.equipment.pk, 1)])
        self.assertEqual(request.status, "PENDING")

    def test_forms_reflect_policy_without_restarting_server(self):
        update_settings(actor=self.admin, max_items=2, max_quantity=2, max_days=2)
        self.assertEqual(len(RequestItemFormSet(prefix="items").forms), 1)
        self.assertEqual(RequestItemFormSet(prefix="items").max_num, 2)
        form = BorrowingRequestForm()
        self.assertEqual(form.fields["due_date"].widget.attrs["max"], (timezone.localdate() + timedelta(days=2)).isoformat())
        update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        self.assertEqual(len(RequestItemFormSet(prefix="items").forms), 1)

    def test_existing_approved_request_can_release_after_limits_are_lowered(self):
        request = self.pending(quantity=2)
        approve_request(request.pk, actor=self.admin)
        original_due = request.due_at
        update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        loan = release_request(request.pk, actor=self.admin)
        self.assertEqual(loan.quantity, 2)
        self.assertEqual(loan.due_at, original_due)

    def test_settings_changes_do_not_modify_issued_loans_or_returns(self):
        loan = self.issue(quantity=2)
        before = (loan.due_at, loan.issued_at, loan.quantity)
        update_settings(actor=self.admin, max_items=1, max_quantity=1, max_days=1)
        loan.refresh_from_db()
        self.assertEqual(before, (loan.due_at, loan.issued_at, loan.quantity))
        self.complete(loan)
        self.assertIsNotNone(Loan.objects.get(pk=loan.pk).completed_at)

    def test_settings_post_requires_confirmation_and_shows_success(self):
        self.client.force_login(self.admin)
        values = {"max_items": 1, "max_quantity": 2, "max_days": 3}
        response = self.client.post(reverse("system_settings"), values)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(SystemSetting.objects.exists())
        response = self.client.post(reverse("system_settings"), {**values, "confirm": "on"}, follow=True)
        self.assertContains(response, "Borrowing settings saved.")
        self.assertEqual(borrowing_limits(), values)

    def test_settings_post_ignores_forged_actor(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("system_settings"), {"max_items": 1, "max_quantity": 2, "max_days": 3, "confirm": "on", "updated_by": self.basic.pk})
        self.assertEqual(SystemSetting.objects.get().updated_by, self.admin)


class AuditIntegrationTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_inventory_create_update_archive_and_restore_are_audited(self):
        category = save_category(actor=self.admin, name="Media")
        equipment = save_equipment(actor=self.admin, name="Camera", category_id=category.pk)
        save_equipment(actor=self.admin, equipment_id=equipment.pk, name="Camera updated", category_id=category.pk)
        archive_equipment(equipment.pk, actor=self.admin)
        restore_equipment(equipment.pk, actor=self.admin)
        self.assertEqual(set(AuditLog.objects.values_list("action", flat=True)), {"CATEGORY_CREATED", "EQUIPMENT_CREATED", "EQUIPMENT_UPDATED", "EQUIPMENT_ARCHIVED", "EQUIPMENT_RESTORED"})
        self.assertEqual(AuditLog.objects.filter(entity_type="equipment", entity_id=equipment.pk).count(), 4)

    def test_units_and_unused_category_deletion_are_audited(self):
        unit = add_unit(self.equipment.pk, actor=self.admin, asset_tag="NEW")
        edit_unit(unit.pk, actor=self.admin, asset_tag="RENAMED")
        retire_unit(unit.pk, actor=self.admin)
        category = save_category(actor=self.admin, name="Unused")
        pk = category.pk
        delete_category(pk, actor=self.admin)
        self.assertTrue(AuditLog.objects.filter(action="CATEGORY_DELETED", entity_id=pk).exists())
        self.assertEqual(AuditLog.objects.filter(entity_type="equipment_unit").count(), 3)

    def test_noop_inventory_edits_are_not_logged_twice(self):
        category = save_category(actor=self.admin, name="Media")
        save_category(actor=self.admin, category_id=category.pk, name="Media")
        unit = add_unit(self.equipment.pk, actor=self.admin, asset_tag="NEW")
        edit_unit(unit.pk, actor=self.admin, asset_tag="NEW")
        self.assertEqual(AuditLog.objects.filter(action="CATEGORY_UPDATED").count(), 0)
        self.assertEqual(AuditLog.objects.filter(action="UNIT_UPDATED").count(), 0)

    def test_approval_rejection_and_cancellation_are_audited_once(self):
        approved, rejected = self.pending(), self.pending()
        approve_request(approved.pk, actor=self.admin)
        reject_request(rejected.pk, actor=self.admin, reason="PRIVATE-REJECTION")
        cancel_request(approved.pk, actor=self.basic)
        self.assertEqual(set(AuditLog.objects.values_list("action", flat=True)), {"REQUEST_APPROVED", "REQUEST_REJECTED", "REQUEST_CANCELLED"})
        self.assertEqual(AuditLog.objects.get(action="REQUEST_CANCELLED").actor, self.basic)
        with self.assertRaises(ValidationError):
            cancel_request(approved.pk, actor=self.basic)
        self.assertEqual(AuditLog.objects.count(), 3)
        self.assertNotIn("PRIVATE-REJECTION", " ".join(AuditLog.objects.values_list("description", flat=True)))

    def test_release_return_and_automatic_maintenance_have_distinct_audit_events(self):
        loan = self.issue()
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get().pk, "DAMAGED", "PRIVATE-DAMAGE")])
        record = MaintenanceRecord.objects.get()
        record_damaged_return(loan.units.get().pk, actor=self.admin)
        self.assertEqual(AuditLog.objects.filter(action="LOAN_RELEASED").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="UNITS_RETURNED").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_REPORTED").count(), 1)
        update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="PRIVATE-REPAIR")
        resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="PRIVATE-COMPLETION")
        self.assertTrue(AuditLog.objects.filter(action="MAINTENANCE_REPAIRED").exists())
        text = " ".join(AuditLog.objects.values_list("description", flat=True))
        for secret in ["PRIVATE-DAMAGE", "PRIVATE-REPAIR", "PRIVATE-COMPLETION", self.admin.password]:
            self.assertNotIn(secret, text)

    def test_manual_maintenance_retirement_and_noop_progress_are_audited(self):
        record = create_record(self.units[0].pk, actor=self.admin, reason="PRIVATE-ISSUE")
        update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Progress")
        update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Progress")
        resolve_record(record.pk, actor=self.admin, outcome="RETIRED", repair_notes="Beyond repair")
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_UPDATED").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_RETIRED").count(), 1)

    def test_failed_operations_produce_no_audit_or_partial_changes(self):
        loan = self.issue()
        before = AuditLog.objects.count()
        with patch("apps.maintenance.services.record_damaged_return", side_effect=ValidationError("Conflict")), self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get().pk, "DAMAGED", "Issue")])
        self.assertEqual(AuditLog.objects.count(), before)
        self.assertIsNone(loan.units.get().returned_at)

    def test_audit_failure_rolls_back_inventory_creation(self):
        with patch("apps.inventory.services.record_event", side_effect=IntegrityError("Audit failure")), self.assertRaises(IntegrityError):
            add_unit(self.equipment.pk, actor=self.admin, asset_tag="ROLLBACK")
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag="ROLLBACK").exists())

    def test_account_activation_and_deactivation_audited_without_credentials(self):
        original_password = self.basic.password
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        set_user_active(self.basic.pk, actor=self.admin, is_active=True)
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.password, original_password)
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertEqual(set(AuditLog.objects.values_list("action", flat=True)), {"USER_ACTIVATED", "USER_DEACTIVATED"})
        self.assertNotIn(original_password, " ".join(AuditLog.objects.values_list("description", flat=True)))

    def test_account_state_hook_validates_role_state_and_missing_target(self):
        with self.assertRaises(PermissionDenied):
            set_user_active(self.other.pk, actor=self.basic, is_active=False)
        with self.assertRaises(ValidationError):
            set_user_active(self.other.pk, actor=self.admin, is_active="false")
        with self.assertRaises(ValidationError):
            set_user_active(999999, actor=self.admin, is_active=False)
        self.assertFalse(AuditLog.objects.exists())

    def test_actor_snapshot_and_protected_identity_preserve_audit_history(self):
        entry = self.log()
        original_name = self.admin.username
        self.admin.username = "renamed-admin"
        self.admin.save()
        entry.refresh_from_db()
        self.assertEqual(entry.actor_username, original_name)
        with self.assertRaises(ProtectedError):
            self.admin.delete()


class AuditViewTests(DashboardFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_search_by_actor_action_entity_and_record_id(self):
        first = self.log(entity_id=123)
        second = record_event(actor=self.basic, action="REQUEST_CANCELLED", entity_type="borrowing_request", entity_id=456, description="Cancelled request.")
        for query in ["dashboard-admin", "EQUIPMENT_UPDATED", "Equipment updated", "equipment", "123"]:
            response = self.client.get(reverse("audit_logs"), {"q": query})
            self.assertEqual(list(response.context["page_obj"]), [first])
        response = self.client.get(reverse("audit_logs"), {"action": "REQUEST_CANCELLED"})
        self.assertEqual(list(response.context["page_obj"]), [second])

    def test_date_filter_and_newest_first_order(self):
        first, second = self.log(entity_id=1), self.log(entity_id=2)
        boundary = timezone.make_aware(datetime(2026, 10, 15))
        AuditLog.objects.filter(pk=first.pk).update(occurred_at=boundary - timedelta(seconds=1))
        AuditLog.objects.filter(pk=second.pk).update(occurred_at=boundary)
        response = self.client.get(reverse("audit_logs"), {"start_date": "2026-10-14", "end_date": "2026-10-14"})
        self.assertEqual(list(response.context["page_obj"]), [first])
        response = self.client.get(reverse("audit_logs"))
        self.assertEqual(list(response.context["page_obj"]), [second, first])

    def test_audit_pagination_preserves_search(self):
        for index in range(26):
            self.log(entity_id=index + 1)
        response = self.client.get(reverse("audit_logs"), {"q": "equipment"})
        self.assertEqual(len(response.context["page_obj"]), 10)
        self.assertContains(response, "q=equipment&amp;page=2")

    def test_invalid_filters_show_errors(self):
        self.log()
        for data in [{"action": "INVALID"}, {"start_date": "bad"}, {"start_date": "2026-10-15", "end_date": "2026-10-14"}]:
            response = self.client.get(reverse("audit_logs"), data)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(len(response.context["page_obj"]), 0)

    def test_audit_has_no_mutation_endpoints(self):
        entry = self.log()
        for suffix in ["edit", "delete"]:
            self.assertEqual(self.client.post(f"/manage/audit-logs/{entry.pk}/{suffix}/").status_code, 404)
        self.assertEqual(self.client.post(reverse("audit_logs")).status_code, 405)
        self.assertTrue(AuditLog.objects.filter(pk=entry.pk).exists())

    def test_untrusted_audit_text_is_escaped_in_html(self):
        record_event(actor=self.admin, action="EQUIPMENT_UPDATED", entity_type="equipment", entity_id=1, description='<script>alert("x")</script>')
        response = self.client.get(reverse("audit_logs"))
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")
