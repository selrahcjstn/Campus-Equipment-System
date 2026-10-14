from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


ACTIVE_STATUSES = ("REPORTED", "IN_PROGRESS")


class MaintenanceRecord(models.Model):
    class Status(models.TextChoices):
        REPORTED = "REPORTED", "Reported"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        REPAIRED = "REPAIRED", "Repaired"
        RETIRED = "RETIRED", "Retired"

    unit = models.ForeignKey("inventory.EquipmentUnit", on_delete=models.PROTECT, related_name="maintenance_records")
    reason = models.TextField(max_length=1000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REPORTED)
    reported_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    repair_notes = models.TextField(max_length=2000, blank=True)
    responsible_admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_maintenance", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="closed_maintenance", null=True, blank=True)
    source_return = models.OneToOneField("loans.LoanUnit", on_delete=models.PROTECT, related_name="maintenance_record", null=True, blank=True)

    class Meta:
        ordering = ["-reported_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["REPORTED", "IN_PROGRESS", "REPAIRED", "RETIRED"]), name="maintenance_valid_status"),
            models.UniqueConstraint(fields=["unit"], condition=models.Q(status__in=ACTIVE_STATUSES), name="maintenance_one_active_per_unit"),
            models.CheckConstraint(condition=(models.Q(status__in=ACTIVE_STATUSES, completed_at__isnull=True, closed_by__isnull=True) | (models.Q(status__in=["REPAIRED", "RETIRED"], completed_at__isnull=False, closed_by__isnull=False) & ~models.Q(repair_notes=""))), name="maintenance_coherent_resolution"),
            models.CheckConstraint(condition=models.Q(completed_at__isnull=True) | models.Q(completed_at__gte=models.F("reported_at")), name="maintenance_completion_after_report"),
        ]

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    @property
    def status_variant(self):
        return {"REPORTED": "warning", "IN_PROGRESS": "info", "REPAIRED": "success", "RETIRED": "inactive"}[self.status]

    def clean(self):
        self.reason = self.reason.strip()
        self.repair_notes = self.repair_notes.strip()
        if not self.reason:
            raise ValidationError({"reason": "Describe the reported issue."})
        for field in ["responsible_admin", "closed_by"]:
            admin = getattr(self, field, None)
            if admin and admin.role != "ADMIN":
                # A recorded Admin's later role change must not invalidate
                # maintenance history or block another Admin finishing the work.
                original_id = None if self._state.adding else MaintenanceRecord.objects.filter(pk=self.pk).values_list(field + "_id", flat=True).first()
                if original_id != admin.pk:
                    raise ValidationError({field: "Select an Admin account."})
        if self.source_return_id:
            source = self.source_return
            if source.unit_id != self.unit_id or source.return_condition != "DAMAGED" or source.returned_at is None:
                raise ValidationError("The source must be a recorded damaged return for this physical unit.")
        if not self.is_active and not self.repair_notes:
            raise ValidationError({"repair_notes": "Describe the repair or why the equipment cannot be repaired."})

    def __str__(self):
        return f"Maintenance #{self.pk} · {self.unit}"
