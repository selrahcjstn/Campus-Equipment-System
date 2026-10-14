"""Audited account state hook for the account-management module."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from apps.dashboard.audit import record_event


@transaction.atomic
def set_user_active(user_id, *, actor, is_active):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may activate or deactivate accounts.")
    if type(is_active) is not bool:
        raise ValidationError("Choose an active or inactive account state.")
    User = get_user_model()
    if User.objects.filter(pk=user_id).update(is_active=F("is_active")) != 1:
        raise ValidationError("This account no longer exists.")
    user = User.objects.select_for_update().get(pk=user_id)
    if user.is_active == is_active:
        return user
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    record_event(actor=actor, action="USER_ACTIVATED" if is_active else "USER_DEACTIVATED", entity_type="user", entity_id=user.pk, description="Activated account." if is_active else "Deactivated account.")
    return user
