from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers

from .forms import CatalogFilterForm, CategoryFilterForm, CategoryForm, ConfirmationForm, EquipmentFilterForm, EquipmentForm, UnitFilterForm, UnitForm
from .models import Category, Equipment, EquipmentUnit
from .services import add_unit, archive_category, archive_equipment, delete_category, edit_unit, equipment_in_use, inventory_queryset, restore_category, restore_equipment, retire_unit, save_category, save_equipment, unit_queryset


def _role(request, role):
    if not request.user.is_active or request.user.role != role:
        raise PermissionDenied("You do not have permission to use this page.")


def _page(request, records):
    return Paginator(records, 10).get_page(request.GET.get("page"))


def _filter_catalog(records, form, *, include_unit_identifiers=False):
    if not form.is_valid():
        return records.none()
    data = form.cleaned_data
    if data.get("q"):
        query = Q(name__icontains=data["q"])
        if include_unit_identifiers:
            query |= Q(units__asset_tag__icontains=data["q"])
        records = records.filter(query).distinct()
    if data.get("category"):
        records = records.filter(category=data["category"])
    if data.get("availability") == "available":
        records = records.filter(available_count__gt=0)
    elif data.get("availability") == "unavailable":
        records = records.filter(available_count=0)
    if data.get("state"):
        records = records.filter(is_active=data["state"] == "active")
    return records


def _filter_units(records, form):
    if not form.is_valid():
        return records.none()
    data = form.cleaned_data
    if data.get("q"):
        records = records.filter(Q(asset_tag__icontains=data["q"]) | Q(equipment__name__icontains=data["q"]))
    if data.get("category"):
        records = records.filter(equipment__category=data["category"])
    if data.get("equipment"):
        records = records.filter(equipment=data["equipment"])
    if data.get("status"):
        records = records.filter(status=data["status"])
    return records


def _form_error(form, error):
    if isinstance(error, ValidationError):
        form.add_error(None, error)
    else:
        form.add_error(None, "The records changed, an identifier is already in use, or the database is busy. Reload and try again.")


@login_required(login_url="login")
@require_GET
def equipment_catalog(request):
    _role(request, "BASIC_USER")
    form = CatalogFilterForm(request.GET)
    records = _filter_catalog(inventory_queryset().filter(is_active=True), form)
    return render(request, "inventory/catalog.html", {"page_obj": _page(request, records), "filter_form": form, "active_nav": "catalog"})


@login_required(login_url="login")
@require_GET
def equipment_detail(request, pk):
    _role(request, "BASIC_USER")
    equipment = get_object_or_404(inventory_queryset().filter(is_active=True), pk=pk)
    return render(request, "inventory/detail.html", {"equipment": equipment, "active_nav": "catalog"})


@login_required(login_url="login")
@require_GET
def equipment_inventory(request):
    _role(request, "ADMIN")
    form = EquipmentFilterForm(request.GET if request.GET else {"state": "active"})
    records = _filter_catalog(inventory_queryset(), form, include_unit_identifiers=True)
    return render(request, "inventory/admin/equipment_list.html", {"page_obj": _page(request, records), "filter_form": form, "active_nav": "inventory"})


@login_required(login_url="login")
@require_GET
def categories(request):
    _role(request, "ADMIN")
    form = CategoryFilterForm(request.GET)
    records = Category.objects.annotate(equipment_count=Count("equipment")).order_by("name", "pk")
    if form.is_valid() and form.cleaned_data.get("q"):
        records = records.filter(name__icontains=form.cleaned_data["q"])
    elif not form.is_valid():
        records = records.none()
    return render(request, "inventory/admin/categories.html", {"page_obj": _page(request, records), "filter_form": form, "active_nav": "categories"})


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
@vary_on_headers("X-Admin-Modal")
def category_form(request, pk=None):
    _role(request, "ADMIN")
    modal_request = request.headers.get("X-Admin-Modal") == "1"
    category = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(request.POST if request.method == "POST" else None, instance=category)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            save_category(actor=request.user, category_id=pk, **form.cleaned_data)
        except (ValidationError, IntegrityError, OperationalError) as error:
            _form_error(form, error)
            status = 409
        else:
            messages.success(request, "Category saved.")
            if modal_request:
                return JsonResponse({"saved": True})
            return redirect("equipment_categories")
    if modal_request and request.method == "POST" and status == 200:
        status = 422
    context = {
        "form": form, "page_title": "Edit category" if pk else "Create category",
        "description": "Update the category name and description." if pk else "Organize equipment with a category name and optional description.",
        "submit_label": "Save changes" if pk else "Create category",
        "back_url": "equipment_categories", "active_nav": "categories", "modal_request": modal_request,
    }
    template = "components/admin_modal_form.html" if modal_request else "inventory/admin/category_form.html"
    return render(request, template, context, status=status)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def equipment_form(request, pk=None):
    _role(request, "ADMIN")
    equipment = get_object_or_404(Equipment, pk=pk) if pk else None
    form = EquipmentForm(request.POST if request.method == "POST" else None, instance=equipment)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            result = save_equipment(actor=request.user, equipment_id=pk, name=form.cleaned_data["name"], category_id=form.cleaned_data["category"].pk, description=form.cleaned_data["description"])
        except (ValidationError, IntegrityError, OperationalError) as error:
            _form_error(form, error)
            status = 409
        else:
            messages.success(request, "Catalog item saved.")
            return redirect("admin_equipment_detail", pk=result.pk)
    return render(request, "inventory/admin/form.html", {"form": form, "page_title": "Edit catalog item" if pk else "Create catalog item", "back_url": "equipment_inventory", "active_nav": "inventory"}, status=status)


@login_required(login_url="login")
@require_GET
def admin_equipment_detail(request, pk):
    _role(request, "ADMIN")
    equipment = get_object_or_404(inventory_queryset(), pk=pk)
    form = UnitFilterForm(request.GET)
    form.fields.pop("equipment")
    form.fields.pop("category")  # This page already fixes the equipment and its category.
    records = _filter_units(unit_queryset().filter(equipment=equipment), form)
    return render(request, "inventory/admin/equipment_detail.html", {"equipment": equipment, "page_obj": _page(request, records), "filter_form": form, "active_nav": "inventory"})


@login_required(login_url="login")
@require_GET
def units(request):
    _role(request, "ADMIN")
    form = UnitFilterForm(request.GET)
    return render(request, "inventory/admin/units.html", {"page_obj": _page(request, _filter_units(unit_queryset(), form)), "filter_form": form, "active_nav": "inventory"})


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
@vary_on_headers("X-Admin-Modal")
def unit_form(request, equipment_pk=None, pk=None):
    _role(request, "ADMIN")
    modal_request = request.headers.get("X-Admin-Modal") == "1"
    unit = get_object_or_404(unit_queryset(), pk=pk) if pk else None
    equipment = unit.equipment if unit else get_object_or_404(Equipment, pk=equipment_pk)
    form = UnitForm(request.POST if request.method == "POST" else None, instance=unit)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            if unit:
                edit_unit(unit.pk, actor=request.user, **form.cleaned_data)
            else:
                add_unit(equipment.pk, actor=request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError, OperationalError) as error:
            _form_error(form, error)
            status = 409
        else:
            messages.success(request, "Physical unit saved.")
            if modal_request:
                return JsonResponse({"saved": True})
            return redirect("admin_equipment_detail", pk=equipment.pk)
    allowed = unit.can_edit if unit else equipment.is_active
    if modal_request and request.method == "POST" and status == 200:
        status = 422
    context = {
        "form": form, "unit": unit, "equipment": equipment, "allowed": allowed, "active_nav": "inventory",
        "page_title": "Edit physical unit" if unit else "Add physical unit",
        "description": f"{equipment.name} · {unit.inventory_status_label}" if unit else f"{equipment.name} · New physical units start as Available.",
        "submit_label": "Save changes" if unit else "Add physical unit",
        "modal_request": modal_request, "modal_unavailable": not allowed,
        "unavailable_message": "Archived equipment cannot receive new units. Units with reservations, loans or maintenance must finish the owning workflow before editing.",
    }
    template = "components/admin_modal_form.html" if modal_request else "inventory/admin/unit_form.html"
    return render(request, template, context, status=status)


def _action(request, pk, action):
    form = ConfirmationForm(request.POST if request.method == "POST" else None)
    category = get_object_or_404(Category, pk=pk) if action in {"delete_category", "archive_category", "restore_category"} else None
    unit = get_object_or_404(unit_queryset(), pk=pk) if action == "retire" else None
    equipment = unit.equipment if unit else (None if category else get_object_or_404(inventory_queryset(), pk=pk))
    titles = {"archive": "Archive catalog item", "restore": "Restore catalog item", "delete_category": "Delete category", "retire": "Retire physical unit", "archive_category": "Archive category", "restore_category": "Restore category"}
    descriptions = {"archive": "Archiving keeps all historical records and prevents new borrowing. Active reservations and issued units must be resolved first.", "restore": "This catalog item will become active again. Physical unit statuses are preserved.", "delete_category": "Only an unreferenced category can be deleted. Categories linked to active or archived equipment are protected.", "retire": "Only an Available, unallocated unit can be retired. The unit and its history remain on record; it will be unavailable for borrowing."}
    descriptions.update(archive_category="Stop new equipment assignments to this category. Existing equipment, borrowing and physical units remain unchanged.",
                        restore_category="Allow this category to be selected for new equipment again. Existing records remain unchanged.")
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            operations = {"archive": archive_equipment, "restore": restore_equipment, "delete_category": delete_category, "retire": retire_unit, "archive_category": archive_category, "restore_category": restore_category}
            operations[action](pk, actor=request.user)
        except (ValidationError, IntegrityError, OperationalError) as error:
            _form_error(form, error)
            status = 409
        else:
            messages.success(request, f"{titles[action]} completed.")
            return redirect("equipment_categories") if category else redirect("admin_equipment_detail", pk=equipment.pk)
    if category:
        allowed = category.is_active if action == "archive_category" else not category.is_active if action == "restore_category" else not category.equipment.exists()
    else:
        allowed = unit.can_retire if unit else (equipment.is_active and not equipment_in_use(equipment.pk) if action == "archive" else not equipment.is_active)
    return render(request, "inventory/admin/action.html", {"form": form, "category": category, "equipment": equipment, "unit": unit, "allowed": allowed, "page_title": titles[action], "description": descriptions[action], "active_nav": "categories" if category else "inventory"}, status=status)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def archive(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "archive")


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def restore(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "restore")


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def category_delete(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "delete_category")


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def category_archive(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "archive_category")


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def category_restore(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "restore_category")


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def unit_retire(request, pk):
    _role(request, "ADMIN")
    return _action(request, pk, "retire")
