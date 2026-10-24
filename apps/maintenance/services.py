"""Admin-only, atomic maintenance transitions on existing physical units."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.borrowing.models import Allocation
from apps.dashboard.audit import record_event
from apps.inventory.models import EquipmentUnit
from apps.loans.models import LoanUnit
from .models import ACTIVE_STATUSES, MaintenanceRecord


def _require_admin(actor):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may manage maintenance.")


def _text(value, *, label, maximum, required=True):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValidationError(f"{label} must be text of at most {maximum:,} characters" + (" and cannot be empty." if required else "."))
    return value.strip()


def eligible_units():
    # Archived catalog items can still be repaired; public eligibility separately
    # requires an active catalog item. Existing Maintenance units can be adopted.
    return EquipmentUnit.objects.select_related("equipment").filter(status__in=["AVAILABLE", "MAINTENANCE"]).exclude(
        pk__in=Allocation.objects.filter(active=True).values("unit_id")
    ).exclude(pk__in=LoanUnit.objects.filter(returned_at__isnull=True).values("unit_id")).exclude(
        pk__in=MaintenanceRecord.objects.filter(status__in=ACTIVE_STATUSES).values("unit_id")
    )


def _lock_unit(unit_id):
    # First write also serializes mutations on SQLite, where row locks alone
    # do not serialize two simultaneous requests.
    if EquipmentUnit.objects.filter(pk=unit_id).update(asset_tag=F("asset_tag")) != 1:
        raise ValidationError("This physical unit no longer exists.")
    unit = EquipmentUnit.objects.select_for_update().get(pk=unit_id)
    if unit.allocations.filter(active=True).exists() or unit.loan_units.filter(returned_at__isnull=True).exists():
        raise ValidationError("Finish the reservation or return before managing this unit's maintenance.")
    return unit


@transaction.atomic
def create_record(unit_id, *, actor, reason):
    _require_admin(actor)
    reason = _text(reason, label="Reported issue", maximum=1000)
    unit = _lock_unit(unit_id)
    if unit.status not in ["AVAILABLE", "MAINTENANCE"]:
        raise ValidationError("Only Available or untracked Maintenance units can enter maintenance.")
    if unit.maintenance_records.filter(status__in=ACTIVE_STATUSES).exists():
        raise ValidationError("This physical unit already has active maintenance. Open its existing record.")
    record = MaintenanceRecord(unit=unit, reason=reason, responsible_admin=actor)
    record.full_clean()
    record.save()
    EquipmentUnit.objects.filter(pk=unit.pk).update(status="MAINTENANCE")
    record_event(actor=actor, action="MAINTENANCE_REPORTED", entity_type="maintenance", entity_id=record.pk, description=f"Reported maintenance for physical unit #{unit.pk}.")
    return record


@transaction.atomic
def record_damaged_return(loan_unit_id, *, actor):
    """Called by Loans after recording damage, unit state and allocation release.

    The outer return transaction rolls back if maintenance cannot be recorded.
    Retrying this helper returns the original record without reopening repairs.
    """
    _require_admin(actor)
    source = LoanUnit.objects.get(pk=loan_unit_id)
    unit = _lock_unit(source.unit_id)
    existing = MaintenanceRecord.objects.filter(source_return=source).first()
    if existing:
        return existing
    if source.returned_at is None or source.return_condition != "DAMAGED" or unit.status != "MAINTENANCE":
        raise ValidationError("Maintenance requires a recorded damaged return and a unit in Maintenance.")
    if unit.maintenance_records.filter(status__in=ACTIVE_STATUSES).exists():
        raise ValidationError("This physical unit already has active maintenance. Review its history.")
    record = MaintenanceRecord(unit=unit, source_return=source, reason=source.return_notes, reported_at=source.returned_at, responsible_admin=actor)
    record.full_clean()
    record.save()
    record_event(actor=actor, action="MAINTENANCE_REPORTED", entity_type="maintenance", entity_id=record.pk, description=f"Opened maintenance from damaged return #{source.pk} for unit #{unit.pk}.")
    return record


def _active_record(record_id):
    unit_id = MaintenanceRecord.objects.filter(pk=record_id).values_list("unit_id", flat=True).first()
    if unit_id is None:
        raise ValidationError("This maintenance record no longer exists.")
    unit = _lock_unit(unit_id)
    record = MaintenanceRecord.objects.select_for_update().get(pk=record_id)
    if not record.is_active:
        raise ValidationError("Resolved maintenance records are preserved and cannot be changed.")
    if unit.status != "MAINTENANCE":
        raise ValidationError("This unit is no longer in Maintenance. Review its linked records before continuing.")
    return record, unit


@transaction.atomic
def start_repair(record_id, *, actor):
    _require_admin(actor)
    record, _ = _active_record(record_id)
    if record.status != "REPORTED":
        raise ValidationError("Only Reported maintenance can be started. Reload the record to see its current status.")
    record.status = "IN_PROGRESS"
    record.full_clean()
    record.save(update_fields=["status"])
    # Keep the original reporting Admin/date; the actor and start time belong
    # to this audit event. Starting work must not overwrite existing notes.
    record_event(actor=actor, action="MAINTENANCE_UPDATED", entity_type="maintenance", entity_id=record.pk,
                 description=f"Started repair for physical unit #{record.unit_id}. Status: Reported → In progress.")
    return record


@transaction.atomic
def update_record(record_id, *, actor, status, repair_notes):
    _require_admin(actor)
    repair_notes = _text(repair_notes, label="Repair notes", maximum=2000, required=False)
    record, _ = _active_record(record_id)
    if status not in ACTIVE_STATUSES or (record.status == "IN_PROGRESS" and status != "IN_PROGRESS"):
        raise ValidationError("Progress can move from Reported to In progress. Use repair or retirement to resolve it.")
    previous = (record.status, record.repair_notes)
    record.status, record.repair_notes = status, repair_notes
    record.full_clean()
    record.save(update_fields=["status", "repair_notes"])
    if previous != (record.status, record.repair_notes):
        record_event(actor=actor, action="MAINTENANCE_UPDATED", entity_type="maintenance", entity_id=record.pk, description=f"Updated maintenance progress to {record.get_status_display()} for unit #{record.unit_id}.")
    return record


@transaction.atomic
def resolve_record(record_id, *, actor, outcome, repair_notes):
    _require_admin(actor)
    repair_notes = _text(repair_notes, label="Resolution notes", maximum=2000)
    if outcome not in ["REPAIRED", "RETIRED"]:
        raise ValidationError("Choose repaired or retired to resolve maintenance.")
    record, unit = _active_record(record_id)
    if outcome == "REPAIRED" and record.status != "IN_PROGRESS":
        raise ValidationError("Start maintenance and assess the issue before marking equipment repaired.")
    record.status, record.repair_notes = outcome, repair_notes
    record.completed_at, record.closed_by = timezone.now(), actor
    record.full_clean()
    record.save(update_fields=["status", "repair_notes", "completed_at", "closed_by"])
    EquipmentUnit.objects.filter(pk=unit.pk, status="MAINTENANCE").update(status="AVAILABLE" if outcome == "REPAIRED" else "RETIRED")
    record_event(actor=actor, action="MAINTENANCE_REPAIRED" if outcome == "REPAIRED" else "MAINTENANCE_RETIRED", entity_type="maintenance", entity_id=record.pk, description=f"Resolved maintenance as {record.get_status_display()} for unit #{unit.pk}.")
    return record
