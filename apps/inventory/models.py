from django.db import models


class Equipment(models.Model):
    """An equipment type; each lendable physical copy has an EquipmentUnit."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class EquipmentUnit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        RESERVED = "RESERVED", "Reserved"
        ON_LOAN = "ON_LOAN", "On loan"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        RETIRED = "RETIRED", "Retired"

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="units")
    asset_tag = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        ordering = ["asset_tag"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["AVAILABLE", "RESERVED", "ON_LOAN", "MAINTENANCE", "RETIRED"]), name="inventory_valid_unit_status"),
        ]

    def __str__(self):
        return f"{self.equipment.name} ({self.asset_tag})"
