"""Inventory metadata, eligibility and safe lifecycle operations.

Borrowing, Loans and Maintenance retain ownership of their unit transitions.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.deletion import ProtectedError

from apps.borrowing.models import Allocation
from apps.loans.models import LoanUnit
from apps.maintenance.models import ACTIVE_STATUSES, MaintenanceRecord
from .models import Category, Equipment, EquipmentUnit


def _require_admin(actor):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may manage inventory.")


def eligible_units():
    return EquipmentUnit.objects.filter(status=EquipmentUnit.Status.AVAILABLE, equipment__is_active=True).exclude(
        pk__in=Allocation.objects.filter(active=True).values("unit_id")
    ).exclude(pk__in=LoanUnit.objects.filter(returned_at__isnull=True).values("unit_id")).exclude(
        pk__in=MaintenanceRecord.objects.filter(status__in=ACTIVE_STATUSES).values("unit_id")
    )


def inventory_queryset():
    allocated = Allocation.objects.filter(active=True).values("unit_id")
    issued = LoanUnit.objects.filter(returned_at__isnull=True).values("unit_id")
    maintenance = MaintenanceRecord.objects.filter(status__in=ACTIVE_STATUSES).values("unit_id")
    available = Q(units__status=EquipmentUnit.Status.AVAILABLE) & ~Q(units__pk__in=allocated) & ~Q(units__pk__in=issued) & ~Q(units__pk__in=maintenance)
    return Equipment.objects.select_related("category").annotate(
        total_count=Count("units", distinct=True),
        available_count=Count("units", filter=available, distinct=True),
        reserved_count=Count("units", filter=Q(units__status="RESERVED"), distinct=True),
        issued_count=Count("units", filter=Q(units__status="ON_LOAN"), distinct=True),
        maintenance_count=Count("units", filter=Q(units__status="MAINTENANCE"), distinct=True),
        retired_count=Count("units", filter=Q(units__status="RETIRED"), distinct=True),
    ).order_by("name", "pk")


def unit_queryset():
    return EquipmentUnit.objects.select_related("equipment", "equipment__category").annotate(
        has_active_allocation=Exists(Allocation.objects.filter(unit_id=OuterRef("pk"), active=True)),
        has_outstanding_loan=Exists(LoanUnit.objects.filter(unit_id=OuterRef("pk"), returned_at__isnull=True)),
        has_active_maintenance=Exists(MaintenanceRecord.objects.filter(unit_id=OuterRef("pk"), status__in=ACTIVE_STATUSES)),
    )


@transaction.atomic
def save_category(*, actor, name, description="", category_id=None):
    _require_admin(actor)
    if category_id:
        Category.objects.filter(pk=category_id).update(description=F("description"))
        category = Category.objects.select_for_update().get(pk=category_id)
    else:
        category = Category()
    category.name, category.description = name, description
    category.full_clean()
    category.save()
    return category


@transaction.atomic
def delete_category(category_id, *, actor):
    _require_admin(actor)
    Category.objects.filter(pk=category_id).update(description=F("description"))
    category = Category.objects.select_for_update().get(pk=category_id)
    if category.equipment.exists():
        raise ValidationError("This category is referenced by equipment and cannot be deleted, including archived equipment.")
    try:
        category.delete()
    except ProtectedError as error:
        raise ValidationError("This category has linked records and cannot be deleted.") from error


@transaction.atomic
def save_equipment(*, actor, name, category_id, description="", equipment_id=None):
    _require_admin(actor)
    if equipment_id:
        Equipment.objects.filter(pk=equipment_id).update(is_active=F("is_active"))
        equipment = Equipment.objects.select_for_update().get(pk=equipment_id)
    else:
        equipment = Equipment()
    if not Category.objects.filter(pk=category_id).exists():
        raise ValidationError({"category": "Select an existing category."})
    equipment.name, equipment.category_id, equipment.description = name, category_id, description
    # is_active and stock quantities are deliberately not accepted as inputs.
    equipment.full_clean()
    equipment.save()
    return equipment


@transaction.atomic
def archive_equipment(equipment_id, *, actor):
    _require_admin(actor)
    claimed = Equipment.objects.filter(pk=equipment_id, is_active=True).update(is_active=False)
    if claimed != 1:
        raise ValidationError("This catalog item is already archived or does not exist.")
    equipment = Equipment.objects.select_for_update().get(pk=equipment_id)
    if equipment_in_use(equipment.pk):
        raise ValidationError("This equipment has active reservations or issued units. Cancel or finish those transactions before archiving.")
    return equipment


def equipment_in_use(equipment_id):
    return (
        EquipmentUnit.objects.filter(equipment_id=equipment_id, status__in=["RESERVED", "ON_LOAN"]).exists()
        or Allocation.objects.filter(unit__equipment_id=equipment_id, active=True).exists()
        or LoanUnit.objects.filter(unit__equipment_id=equipment_id, returned_at__isnull=True).exists()
    )


@transaction.atomic
def restore_equipment(equipment_id, *, actor):
    _require_admin(actor)
    if Equipment.objects.filter(pk=equipment_id, is_active=False).update(is_active=True) != 1:
        raise ValidationError("Only archived catalog items can be restored.")
    return Equipment.objects.get(pk=equipment_id)


@transaction.atomic
def add_unit(equipment_id, *, actor, asset_tag):
    _require_admin(actor)
    # Lock the same catalog row used by submission/approval and archiving.
    if Equipment.objects.filter(pk=equipment_id, is_active=True).update(is_active=F("is_active")) != 1:
        raise ValidationError("New physical units can only be added to active catalog items.")
    equipment = Equipment.objects.select_for_update().get(pk=equipment_id)
    unit = EquipmentUnit(equipment=equipment, asset_tag=asset_tag)
    unit.full_clean()
    unit.save()
    return unit


def _idle_unit(unit_id):
    claimed = EquipmentUnit.objects.filter(pk=unit_id, status__in=["AVAILABLE", "RETIRED"]).update(asset_tag=F("asset_tag"))
    if claimed != 1:
        raise ValidationError("Reserved, Issued and Maintenance units cannot be edited through ordinary inventory management.")
    unit = EquipmentUnit.objects.select_for_update().get(pk=unit_id)
    if unit.allocations.filter(active=True).exists() or unit.loan_units.filter(returned_at__isnull=True).exists():
        raise ValidationError("This unit has an active borrowing or loan record and cannot be modified.")
    if unit.maintenance_records.filter(status__in=ACTIVE_STATUSES).exists():
        raise ValidationError("This unit has active maintenance and cannot be modified through inventory.")
    return unit


@transaction.atomic
def edit_unit(unit_id, *, actor, asset_tag):
    _require_admin(actor)
    unit = _idle_unit(unit_id)
    unit.asset_tag = asset_tag
    unit.full_clean()
    unit.save(update_fields=["asset_tag"])
    return unit


@transaction.atomic
def retire_unit(unit_id, *, actor):
    _require_admin(actor)
    unit = _idle_unit(unit_id)
    if unit.status != EquipmentUnit.Status.AVAILABLE:
        raise ValidationError("Only an Available, unallocated unit can be retired.")
    unit.status = EquipmentUnit.Status.RETIRED
    unit.save(update_fields=["status"])
    return unit
