from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.inventory.models import EquipmentUnit
from .forms import MaintenanceFilterForm, MaintenanceForm, ProgressForm, ResolutionForm
from .models import ACTIVE_STATUSES, MaintenanceRecord
from .services import create_record, resolve_record, update_record


def _admin(request):
    if not request.user.is_active or request.user.role != "ADMIN":
        raise PermissionDenied("Only Admin accounts can access maintenance records.")


def admin_required(view):
    @login_required(login_url="login")
    @wraps(view)
    def guarded(request, *args, **kwargs):
        _admin(request)
        return view(request, *args, **kwargs)
    return guarded


def _records():
    return MaintenanceRecord.objects.select_related("unit__equipment", "responsible_admin", "closed_by", "source_return")


def _error(form, error):
    # Model validation may refer to protected fields absent from the public form.
    if isinstance(error, ValidationError):
        for message in error.messages:
            form.add_error(None, message)
    else:
        form.add_error(None, "The record changed or the database is busy. Reload and try again.")


@admin_required
@require_GET
def dashboard(request):
    form = MaintenanceFilterForm(request.GET)
    records = _records()
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            records = records.filter(Q(unit__asset_tag__icontains=data["q"]) | Q(unit__equipment__name__icontains=data["q"]) | Q(reason__icontains=data["q"]))
        if data.get("status"):
            records = records.filter(status__in=ACTIVE_STATUSES) if data["status"] == "active" else records.filter(status=data["status"])
        if data.get("equipment"):
            records = records.filter(unit__equipment=data["equipment"])
    else:
        records = records.none()
    counts = MaintenanceRecord.objects.aggregate(active=Count("pk", filter=Q(status__in=ACTIVE_STATUSES)), completed=Count("pk", filter=Q(status__in=["REPAIRED", "RETIRED"])))
    units = EquipmentUnit.objects.filter(status="MAINTENANCE").select_related("equipment").order_by("asset_tag", "pk")
    untracked = units.exclude(pk__in=MaintenanceRecord.objects.filter(status__in=ACTIVE_STATUSES).values("unit_id"))
    return render(request, "maintenance/dashboard.html", {
        "active_nav": "maintenance", "filter_form": form,
        "page_obj": Paginator(records, 10).get_page(request.GET.get("page")),
        "unit_page": Paginator(units, 10).get_page(request.GET.get("units_page")),
        "counts": counts, "maintenance_count": units.count(), "untracked_count": untracked.count(),
    })


@admin_required
@require_GET
def detail(request, pk):
    record = get_object_or_404(_records(), pk=pk)
    return render(request, "maintenance/detail.html", {"record": record, "active_nav": "maintenance"})


@admin_required
@require_GET
def unit_history(request, pk):
    unit = get_object_or_404(EquipmentUnit.objects.select_related("equipment"), pk=pk)
    active = unit.maintenance_records.filter(status__in=ACTIVE_STATUSES).first()
    return render(request, "maintenance/history.html", {"unit": unit, "active_record": active, "active_nav": "maintenance", "page_obj": Paginator(_records().filter(unit=unit), 10).get_page(request.GET.get("page"))})


@admin_required
@require_http_methods(["GET", "POST"])
def create(request):
    initial = {}
    selected = request.GET.get("unit", "")
    if selected.isdecimal():
        initial["unit"] = selected
    form = MaintenanceForm(request.POST if request.method == "POST" else None, initial=initial)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            record = create_record(form.cleaned_data["unit"].pk, actor=request.user, reason=form.cleaned_data["reason"])
        except (ValidationError, IntegrityError, OperationalError) as error:
            _error(form, error)
            status = 409
        else:
            messages.success(request, "Maintenance reported. This physical unit is unavailable for borrowing.")
            return redirect("maintenance_detail", pk=record.pk)
    return render(request, "maintenance/form.html", {"form": form, "page_title": "Report maintenance", "active_nav": "maintenance"}, status=status)


@admin_required
@require_http_methods(["GET", "POST"])
def update(request, pk):
    record = get_object_or_404(_records(), pk=pk)
    form = ProgressForm(request.POST if request.method == "POST" else None, record=record, initial={"status": record.status, "repair_notes": record.repair_notes})
    status = 200
    if request.method == "POST":
        if not record.is_active:
            form.add_error(None, "Resolved maintenance records cannot be changed.")
            status = 409
        elif form.is_valid():
            try:
                update_record(pk, actor=request.user, **form.cleaned_data)
            except (ValidationError, IntegrityError, OperationalError) as error:
                _error(form, error)
                status = 409
            else:
                messages.success(request, "Maintenance progress saved.")
                return redirect("maintenance_detail", pk=pk)
    return render(request, "maintenance/form.html", {"form": form, "record": record, "allowed": record.is_active, "page_title": "Update maintenance", "active_nav": "maintenance"}, status=status)


def _resolve(request, pk, outcome):
    record = get_object_or_404(_records(), pk=pk)
    repairing = outcome == "REPAIRED"
    allowed = record.is_active and (not repairing or record.status == "IN_PROGRESS")
    form = ResolutionForm(request.POST if request.method == "POST" else None, initial={"repair_notes": record.repair_notes})
    status = 200
    if request.method == "POST":
        if not allowed:
            form.add_error(None, "This action is unavailable. Start maintenance before confirming repair; resolved records cannot be changed.")
            status = 409
        elif form.is_valid():
            try:
                resolve_record(pk, actor=request.user, outcome=outcome, repair_notes=form.cleaned_data["repair_notes"])
            except (ValidationError, IntegrityError, OperationalError) as error:
                _error(form, error)
                status = 409
            else:
                messages.success(request, "Equipment repaired. The unit is Available; archived catalog items remain hidden." if repairing else "Equipment retired. The unit cannot be borrowed.")
                return redirect("maintenance_detail", pk=pk)
    return render(request, "maintenance/resolve.html", {"record": record, "form": form, "allowed": allowed, "repairing": repairing, "page_title": "Confirm repair" if repairing else "Retire equipment", "description": "Confirm the repair and checks before restoring this physical unit to Available." if repairing else "Confirm that this physical unit cannot be repaired. It will be Retired and remain unavailable.", "active_nav": "maintenance"}, status=status)


@admin_required
@require_http_methods(["GET", "POST"])
def complete(request, pk):
    return _resolve(request, pk, "REPAIRED")


@admin_required
@require_http_methods(["GET", "POST"])
def retire(request, pk):
    return _resolve(request, pk, "RETIRED")
