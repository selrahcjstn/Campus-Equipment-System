from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        BASIC_USER = "BASIC_USER", "Basic User"
        ADMIN = "ADMIN", "Admin"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.BASIC_USER
    )

    contact_number = models.CharField(
        max_length=20,
        blank=True
    )

    class Meta(AbstractUser.Meta):
        constraints = [models.CheckConstraint(
            condition=models.Q(role__in=["BASIC_USER", "ADMIN"]), name="accounts_valid_campus_role",
        )]

    def __str__(self):
        return self.username
