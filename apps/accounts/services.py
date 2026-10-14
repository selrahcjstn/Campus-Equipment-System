"""Audited account state hook for the account-management module."""
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Subquery

from apps.dashboard.audit import record_event


def _active_account(actor):
    if not actor.is_authenticated or not actor.is_active or actor.role not in ["ADMIN", "BASIC_USER"]:
        raise PermissionDenied("An active campus account is required.")


def _lock_accounts(user_id, actor):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may manage accounts.")
    User = get_user_model()
    # All account-state and role operations claim the same stable existing row.
    # This serializes the Admin-count check even on SQLite and prevents two
    # simultaneous operations from removing both remaining Admins.
    anchor = User.objects.order_by("pk").values("pk")[:1]
    User.objects.filter(pk=Subquery(anchor)).update(first_name=F("first_name"))
    accounts = {user.pk: user for user in User.objects.select_for_update().filter(pk__in=[actor.pk, user_id]).order_by("pk")}
    current_actor = accounts.get(actor.pk)
    if not current_actor or not current_actor.is_active or current_actor.role != "ADMIN":
        raise PermissionDenied("Your account no longer has active Admin permission.")
    if user_id not in accounts:
        raise ValidationError("This account no longer exists.")
    return accounts[user_id], current_actor


def _protect_last_admin(user):
    User = get_user_model()
    if user.is_active and user.role == "ADMIN" and User.objects.filter(role="ADMIN", is_active=True).count() <= 1:
        raise ValidationError("At least one active Admin account must remain.")


@transaction.atomic
def set_user_active(user_id, *, actor, is_active):
    user, actor = _lock_accounts(user_id, actor)
    if type(is_active) is not bool:
        raise ValidationError("Choose an active or inactive account state.")
    if user.is_active == is_active:
        return user
    if not is_active:
        _protect_last_admin(user)
        if user.pk == actor.pk:
            raise ValidationError("You cannot deactivate your own Admin account.")
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    record_event(actor=actor, action="USER_ACTIVATED" if is_active else "USER_DEACTIVATED", entity_type="user", entity_id=user.pk, description="Activated account." if is_active else "Deactivated account.")
    return user


@transaction.atomic
def set_user_role(user_id, *, actor, role):
    user, actor = _lock_accounts(user_id, actor)
    User = get_user_model()
    if role not in User.Role.values:
        raise ValidationError({"role": "Select a valid campus account role."})
    if user.role == role:
        return user
    if role == "BASIC_USER":
        _protect_last_admin(user)
    if user.pk == actor.pk:
        raise ValidationError("You cannot change your own Admin role.")
    if role == "ADMIN":
        from apps.borrowing.models import BorrowingRequest
        from apps.loans.models import LoanUnit
        if BorrowingRequest.objects.filter(borrower=user, status__in=["PENDING", "APPROVED"]).exists() or LoanUnit.objects.filter(loan__borrower=user, returned_at__isnull=True).exists():
            raise ValidationError("Finish or cancel this user's pending requests, approvals and outstanding loans before promoting them.")
    previous = user.role
    user.role = role
    user.save(update_fields=["role"])
    record_event(actor=actor, action="USER_ROLE_CHANGED", entity_type="user", entity_id=user.pk, description=f"Changed campus role from {previous} to {role}; Django staff and superuser permissions were not changed.")
    return user


def _lock_own_account(actor):
    _active_account(actor)
    User = get_user_model()
    if User.objects.filter(pk=actor.pk).update(first_name=F("first_name")) != 1:
        raise PermissionDenied("This account is no longer available.")
    user = User.objects.select_for_update().get(pk=actor.pk)
    _active_account(user)
    return user


@transaction.atomic
def update_profile(*, actor, first_name, last_name, email, contact_number):
    from .forms import ProfileForm
    user = _lock_own_account(actor)
    form = ProfileForm({"first_name": first_name, "last_name": last_name, "email": email, "contact_number": contact_number}, instance=user)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    user = form.save(commit=False)
    user.save(update_fields=["first_name", "last_name", "email", "contact_number"])
    return user


@transaction.atomic
def change_password(*, actor, data):
    user = _lock_own_account(actor)
    form = PasswordChangeForm(user=user, data=data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    user = form.save(commit=False)
    user.save(update_fields=["password"])
    return user
