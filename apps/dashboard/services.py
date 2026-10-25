from collections import Counter
from datetime import datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from apps.borrowing.models import BorrowingRequest
from apps.inventory.models import EquipmentUnit
from apps.inventory.services import eligible_units
from apps.loans.models import Loan, LoanUnit, local_day_start
from .audit import record_event
from .models import AuditLog, LIMIT_RANGES, SystemSetting
from .policies import borrowing_limits


def require_admin(actor):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may use this operation.")


@transaction.atomic
def update_settings(*, actor, max_items, max_quantity, max_days):
    require_admin(actor)
    values = {"max_items": max_items, "max_quantity": max_quantity, "max_days": max_days}
    for name, value in values.items():
        minimum, maximum = LIMIT_RANGES[name]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValidationError({name: f"Enter a whole number from {minimum} to {maximum}."})
    SystemSetting.objects.filter(pk=1).update(max_items=F("max_items"))
    policy = SystemSetting.objects.select_for_update().filter(pk=1).first()
    previous = policy.as_limits() if policy else borrowing_limits()
    if policy and previous == values:
        return policy
    policy = policy or SystemSetting(pk=1)
    for name, value in values.items():
        setattr(policy, name, value)
    policy.updated_by = actor
    policy.full_clean()
    policy.save()
    description = "; ".join(f"{name}: {previous[name]} → {values[name]}" for name in values)
    record_event(actor=actor, action="SETTINGS_UPDATED", entity_type="system_setting", entity_id=1, description=description)
    return policy


def filter_dates(records, field, values):
    # Half-open timestamp ranges include the whole selected local end date and
    # continue to use timestamp indexes; no date casts on report queries.
    zone = timezone.get_default_timezone()
    start, end = values.get("start_date"), values.get("end_date")
    if start:
        records = records.filter(**{field + "__gte": timezone.make_aware(datetime.combine(start, time.min), zone)})
    if end:
        records = records.filter(**{field + "__lt": timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone)})
    return records


def loans_queryset():
    return Loan.objects.select_related("borrower").prefetch_related("units").annotate(
        has_outstanding=Exists(LoanUnit.objects.filter(loan_id=OuterRef("pk"), returned_at__isnull=True))
    )


def active_loans(records=None):
    records = records if records is not None else loans_queryset()
    return records.active().filter(has_outstanding=True)


def loan_report(values, *, at=None):
    records = loans_queryset()
    if values["report"] == "overdue":
        records = active_loans(records).overdue(at=at)
        return filter_dates(records, "due_at", values)
    return filter_dates(records, "issued_at", values)


def report_row(loan, *, at):
    units = list(loan.units.all())
    outstanding = sum(unit.returned_at is None for unit in units)
    overdue = loan.is_overdue_at(at)
    if loan.completed_at or (units and outstanding == 0):
        status = "Completed"
    elif overdue:
        status = "Overdue"
    elif outstanding < len(units):
        status = "Partially returned"
    else:
        status = "Active" if units else "Needs review"
    days = loan.overdue_days(at=at)
    equipment_counts = Counter(unit.equipment_name for unit in units if unit.returned_at is None)
    outstanding_equipment = [{"name": name, "quantity": count} for name, count in sorted(equipment_counts.items())]
    return {"loan": loan, "units": units, "outstanding": outstanding, "outstanding_equipment": outstanding_equipment, "returned": len(units) - outstanding, "status": status, "variant": "error" if overdue else "success" if status == "Completed" else "info", "overdue_days": days, "overdue_label": f"{days} calendar day(s) overdue" if overdue else "—"}


def dashboard_statistics(*, at):
    loan_counts = active_loans().aggregate(active=Count("pk"), overdue=Count("pk", filter=Q(due_at__lt=local_day_start(at))))
    return {"total_units": EquipmentUnit.objects.count(), "available_units": eligible_units().count(), "pending_requests": BorrowingRequest.objects.filter(status="PENDING").count(), "active_loans": loan_counts["active"], "overdue_loans": loan_counts["overdue"]}


def monthly_issued_loans(start, end):
    records = filter_dates(Loan.objects.all(), "issued_at", {"start_date": start, "end_date": end})
    counts = {month.date(): count for month, count in records.annotate(
        month=TruncMonth("issued_at", tzinfo=timezone.get_default_timezone()),
    ).values("month").annotate(total=Count("pk")).values_list("month", "total")}
    month = start.replace(day=1)
    series = []
    while month <= end:
        series.append({"date": month, "count": counts.get(month, 0)})
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    maximum = max(counts.values(), default=1) or 1
    width = 960 / len(series)
    for index, point in enumerate(series):
        height = point["count"] / maximum * 180
        point.update(x=20 + index * width, y=200-height, width=width * .8, height=height)
    return series


def category_usage(start, end):
    # Each LoanUnit is one physical-unit issuance. Joins are only many-to-one,
    # so multiple items, returns and maintenance events cannot multiply counts.
    units = filter_dates(LoanUnit.objects.all(), "loan__issued_at", {"start_date": start, "end_date": end})
    rows = list(units.values("unit__equipment__category_id", "unit__equipment__category__name").annotate(count=Count("pk")).order_by("-count", "unit__equipment__category__name", "unit__equipment__category_id"))
    total = sum(row["count"] for row in rows)
    return [{"label": row["unit__equipment__category__name"] or "Uncategorized (legacy)", "count": row["count"], "percentage": row["count"] * 100 / total} for row in rows]


def status_distribution():
    counts = dict(EquipmentUnit.objects.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    total = sum(counts.values())
    return [{"status": value, "label": "Issued" if value == "ON_LOAN" else label, "count": counts.get(value, 0), "percentage": counts.get(value, 0) * 100 / total if total else 0} for value, label in EquipmentUnit.Status.choices]


def borrowing_activity(start, end):
    records = filter_dates(BorrowingRequest.objects.all(), "requested_at", {"start_date": start, "end_date": end})
    counts = dict(records.annotate(day=TruncDate("requested_at", tzinfo=timezone.get_current_timezone())).values("day").annotate(total=Count("pk")).values_list("day", "total"))
    days = (end - start).days + 1
    maximum = max(counts.values(), default=1) or 1
    width = 960 / days
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        count = counts.get(day, 0)
        height = count / maximum * 180
        series.append({"date": day, "count": count, "x": 20 + offset * width, "y": 200 - height, "width": max(width * 0.8, 0.5), "height": height})
    return series


def audit_records(values):
    records = filter_dates(AuditLog.objects.select_related("actor"), "occurred_at", values)
    if values.get("action"):
        records = records.filter(action=values["action"])
    if values.get("q"):
        term = values["q"]
        matching_actions = [value for value, label in AuditLog.Action.choices if term.casefold() in label.casefold()]
        query = Q(actor_username__icontains=term) | Q(actor__username__icontains=term) | Q(actor__first_name__icontains=term) | Q(actor__last_name__icontains=term) | Q(action__icontains=term) | Q(action__in=matching_actions) | Q(entity_type__icontains=term) | Q(description__icontains=term)
        if term.isdecimal() and len(term) <= 18:
            query |= Q(entity_id=int(term))
        records = records.filter(query)
    return records


def personal_summary(user, *, at):
    requests = BorrowingRequest.objects.filter(borrower=user)
    loans = loans_queryset().filter(borrower=user)
    active = active_loans(loans)
    request_counts = requests.aggregate(pending=Count("pk", filter=Q(status="PENDING")), approved=Count("pk", filter=Q(status="APPROVED")))
    return {
        "pending_count": request_counts["pending"], "approved_count": request_counts["approved"],
        "borrowed_count": LoanUnit.objects.filter(loan__in=active, returned_at__isnull=True).count(),
        "overdue_count": active.overdue(at=at).count(),
        "upcoming": [report_row(loan, at=at) for loan in active.filter(due_at__gte=local_day_start(at)).order_by("due_at", "pk")[:5]],
        "overdue": [report_row(loan, at=at) for loan in active.overdue(at=at).order_by("due_at", "pk")[:5]],
        "recent_requests": requests.select_related("loan").prefetch_related("items__equipment", "loan__units")[:5],
    }
