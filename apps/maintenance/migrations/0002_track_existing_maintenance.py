from django.db import migrations
from django.utils import timezone


def track_existing_units(apps, schema_editor):
    """Adopt existing Maintenance units without changing inventory or returns.

    Only the latest physical return can explain the current issue. Older damage
    from a previous completed borrowing cycle must not be attached by mistake.
    """
    database = schema_editor.connection.alias
    Unit = apps.get_model("inventory", "EquipmentUnit")
    Return = apps.get_model("loans", "LoanUnit")
    Record = apps.get_model("maintenance", "MaintenanceRecord")
    for unit in Unit.objects.using(database).filter(status="MAINTENANCE").iterator():
        if Record.objects.using(database).filter(unit_id=unit.pk, status__in=["REPORTED", "IN_PROGRESS"]).exists():
            continue
        source = Return.objects.using(database).filter(unit_id=unit.pk, returned_at__isnull=False).order_by("-returned_at", "-pk").first()
        damaged = source and source.return_condition == "DAMAGED" and not Record.objects.using(database).filter(source_return_id=source.pk).exists()
        admin_id = source.received_by_id if damaged else None
        User = apps.get_model("accounts", "User")
        if admin_id and not User.objects.using(database).filter(pk=admin_id, role="ADMIN").exists():
            admin_id = None
        Record.objects.using(database).create(
            unit_id=unit.pk, reason=(source.return_notes.strip() or "Damage reported during return; assessment required.") if damaged else "Existing Maintenance unit; assessment required.",
            reported_at=source.returned_at if damaged else timezone.now(),
            responsible_admin_id=admin_id, source_return_id=source.pk if damaged else None,
        )


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0001_initial")]
    operations = [migrations.RunPython(track_existing_units, migrations.RunPython.noop)]
