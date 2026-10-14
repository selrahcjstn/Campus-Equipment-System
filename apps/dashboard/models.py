from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


LIMIT_RANGES = {"max_items": (1, 10), "max_quantity": (1, 20), "max_days": (1, 30)}


class SystemSetting(models.Model):
    """One optional policy row; without it existing Django defaults still apply."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    max_items = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(10)])
    max_quantity = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(20)])
    max_days = models.PositiveSmallIntegerField(default=7, validators=[MinValueValidator(1), MaxValueValidator(30)])
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="borrowing_policy_updates", null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="dashboard_single_policy"),
            models.CheckConstraint(condition=models.Q(max_items__gte=1, max_items__lte=10, max_quantity__gte=1, max_quantity__lte=20, max_days__gte=1, max_days__lte=30), name="dashboard_valid_borrowing_limits"),
        ]

    def as_limits(self):
        return {name: getattr(self, name) for name in LIMIT_RANGES}


class AuditLog(models.Model):
    class Action(models.TextChoices):
        USER_ACTIVATED = "USER_ACTIVATED", "User activated"
        USER_DEACTIVATED = "USER_DEACTIVATED", "User deactivated"
        CATEGORY_CREATED = "CATEGORY_CREATED", "Category created"
        CATEGORY_UPDATED = "CATEGORY_UPDATED", "Category updated"
        CATEGORY_DELETED = "CATEGORY_DELETED", "Category deleted"
        EQUIPMENT_CREATED = "EQUIPMENT_CREATED", "Equipment created"
        EQUIPMENT_UPDATED = "EQUIPMENT_UPDATED", "Equipment updated"
        EQUIPMENT_ARCHIVED = "EQUIPMENT_ARCHIVED", "Equipment archived"
        EQUIPMENT_RESTORED = "EQUIPMENT_RESTORED", "Equipment restored"
        UNIT_ADDED = "UNIT_ADDED", "Physical unit added"
        UNIT_UPDATED = "UNIT_UPDATED", "Physical unit updated"
        UNIT_RETIRED = "UNIT_RETIRED", "Physical unit retired"
        REQUEST_APPROVED = "REQUEST_APPROVED", "Borrowing request approved"
        REQUEST_REJECTED = "REQUEST_REJECTED", "Borrowing request rejected"
        REQUEST_CANCELLED = "REQUEST_CANCELLED", "Borrowing request cancelled"
        LOAN_RELEASED = "LOAN_RELEASED", "Equipment released"
        UNITS_RETURNED = "UNITS_RETURNED", "Equipment returned"
        MAINTENANCE_REPORTED = "MAINTENANCE_REPORTED", "Maintenance reported"
        MAINTENANCE_UPDATED = "MAINTENANCE_UPDATED", "Maintenance progress updated"
        MAINTENANCE_REPAIRED = "MAINTENANCE_REPAIRED", "Maintenance completed: repaired"
        MAINTENANCE_RETIRED = "MAINTENANCE_RETIRED", "Maintenance completed: retired"
        SETTINGS_UPDATED = "SETTINGS_UPDATED", "Borrowing settings updated"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_entries")
    actor_username = models.CharField(max_length=150)
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    description = models.CharField(max_length=500)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        indexes = [models.Index(fields=["entity_type", "entity_id"], name="audit_entity_lookup")]
        constraints = [models.CheckConstraint(condition=models.Q(action__in=["USER_ACTIVATED", "USER_DEACTIVATED", "CATEGORY_CREATED", "CATEGORY_UPDATED", "CATEGORY_DELETED", "EQUIPMENT_CREATED", "EQUIPMENT_UPDATED", "EQUIPMENT_ARCHIVED", "EQUIPMENT_RESTORED", "UNIT_ADDED", "UNIT_UPDATED", "UNIT_RETIRED", "REQUEST_APPROVED", "REQUEST_REJECTED", "REQUEST_CANCELLED", "LOAN_RELEASED", "UNITS_RETURNED", "MAINTENANCE_REPORTED", "MAINTENANCE_UPDATED", "MAINTENANCE_REPAIRED", "MAINTENANCE_RETIRED", "SETTINGS_UPDATED"]), name="dashboard_valid_audit_action")]
