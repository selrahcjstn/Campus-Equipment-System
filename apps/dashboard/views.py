import csv
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .forms import AuditFilterForm, ChartPeriodForm, ReportFilterForm, SystemSettingsForm
from .models import SystemSetting
from .policies import borrowing_limits
from .services import monthly_issued_loans, category_usage, audit_records, borrowing_activity, dashboard_statistics, loan_report, personal_summary, report_row, status_distribution, update_settings


def role_required(role):
    def decorate(view):
        @login_required(login_url="login")
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not request.user.is_active or request.user.role != role:
                raise PermissionDenied("You do not have permission to use this page.")
            return view(request, *args, **kwargs)
        return guarded
    return decorate


@role_required("BASIC_USER")
@require_GET
def user_dashboard(request):
    context = personal_summary(request.user, at=timezone.now())
    context["active_nav"] = "dashboard"
    return render(request, "dashboard/user_portal.html", context)


@role_required("ADMIN")
@require_GET
def admin_dashboard(request):
    now = timezone.now()
    today = timezone.localdate(now)
    data = request.GET if request.GET else {"start_date": today - timedelta(days=29), "end_date": today}
    form = ChartPeriodForm(data)
    valid = form.is_valid()
    start, end = form.cleaned_data.get("start_date"), form.cleaned_data.get("end_date")
    series = borrowing_activity(start, end) if valid else []
    monthly = monthly_issued_loans(start, end) if valid else []
    categories = category_usage(start, end) if valid else []
    return render(request, "dashboard/admin/dashboard.html", {"active_nav": "dashboard", "statistics": dashboard_statistics(at=now), "filter_form": form, "monthly": monthly, "monthly_total": sum(point["count"] for point in monthly), "category_usage": categories, "activity": series, "activity_total": sum(point["count"] for point in series), "distribution": status_distribution(), "timezone_name": timezone.get_current_timezone_name()})


def _report_form(request):
    data = request.GET.copy()
    if "report" not in data:
        data["report"] = "loans"
    return ReportFilterForm(data)


@role_required("ADMIN")
@require_GET
def reports(request):
    now = timezone.now()
    form = _report_form(request)
    valid = form.is_valid()
    records = loan_report(form.cleaned_data, at=now) if valid else loan_report({"report": "loans"}, at=now).none()
    page = Paginator(records, 10).get_page(request.GET.get("page"))
    return render(request, "dashboard/admin/reports.html", {"active_nav": "reports", "filter_form": form, "page_obj": page, "rows": [report_row(loan, at=now) for loan in page], "valid_filters": valid, "timezone_name": timezone.get_current_timezone_name(), "generated_at": now})


def csv_cell(value):
    # Spreadsheet apps interpret leading formula/control characters even inside
    # quoted CSV cells. Export user-controlled names and identifiers as text.
    text = str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return value


def _date_text(value):
    return timezone.localtime(value).isoformat() if value else ""


@role_required("ADMIN")
@require_GET
def export_reports(request):
    form = _report_form(request)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid report filters. Correct the date range and report selection before exporting.", content_type="text/plain; charset=utf-8")
    now = timezone.now()
    records = loan_report(form.cleaned_data, at=now)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{form.cleaned_data["report"]}-report-{timezone.localdate(now).isoformat()}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Loan ID", "Request ID", "Borrower username", "Borrower name", "Equipment (issue snapshot)", "Physical unit identifier (issue snapshot)", "Issued at (local ISO 8601)", "Due at (local ISO 8601)", "Loan status", "Unit return status", "Returned at (local ISO 8601)", "Return condition", "Outstanding units on loan", "Overdue days", "Report generated at (local ISO 8601)"])
    for loan in records.iterator(chunk_size=200):
        row = report_row(loan, at=now)
        # Keep historical/incomplete loans visible even when no unit rows exist.
        for unit in row["units"] or [None]:
            values = [loan.pk, loan.request_id, loan.borrower.username, loan.borrower.get_full_name(), unit.equipment_name if unit else "", unit.asset_tag if unit else "", _date_text(loan.issued_at), _date_text(loan.due_at), row["status"], "Returned" if unit and unit.returned_at else "Outstanding" if unit else "No unit record", _date_text(unit.returned_at) if unit else "", unit.get_return_condition_display() if unit and unit.returned_at else "", row["outstanding"], row["overdue_days"], _date_text(now)]
            writer.writerow([csv_cell(value) for value in values])
    return response


@role_required("ADMIN")
@require_GET
def audit_logs(request):
    form = AuditFilterForm(request.GET)
    records = audit_records(form.cleaned_data) if form.is_valid() else audit_records({}).none()
    return render(request, "dashboard/admin/audit_logs.html", {"active_nav": "audit_logs", "filter_form": form, "page_obj": Paginator(records, 10).get_page(request.GET.get("page")), "timezone_name": timezone.get_current_timezone_name()})


@role_required("ADMIN")
@require_http_methods(["GET", "POST"])
def system_settings(request):
    form = SystemSettingsForm(request.POST if request.method == "POST" else None, initial=borrowing_limits())
    status = 200
    if request.method == "POST" and form.is_valid():
        values = {key: form.cleaned_data[key] for key in ["max_items", "max_quantity", "max_days"]}
        try:
            update_settings(actor=request.user, **values)
        except (ValidationError, IntegrityError, OperationalError) as error:
            for message in error.messages if isinstance(error, ValidationError) else ["The settings changed or the database is busy. Reload and try again."]:
                form.add_error(None, message)
            status = 409
        else:
            messages.success(request, "Borrowing settings saved. Approved requests and issued loans retain their recorded quantities and due dates.")
            return redirect("system_settings")
    return render(request, "dashboard/admin/settings.html", {"active_nav": "system_settings", "form": form, "policy": SystemSetting.objects.select_related("updated_by").filter(pk=1).first(), "timezone_name": timezone.get_current_timezone_name()}, status=status)
