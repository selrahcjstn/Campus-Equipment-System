import re

from django import forms
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
)
from .models import User


class ContactNumberField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(required=False, max_length=20, help_text="Optional. Use 7–15 digits, with a leading +, spaces, parentheses or hyphens if needed.", **kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value:
            if not re.fullmatch(r"\+?[0-9][0-9 ()-]*", value) or not 7 <= sum(character.isdigit() for character in value) <= 15:
                raise forms.ValidationError("Enter a valid contact number with 7–15 digits.")
        return value


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    contact_number = ContactNumberField()

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "password1",
            "password2",
        ]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.BASIC_USER
        user.is_active = True
        user.is_staff = user.is_superuser = False
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in User.Role.values:
            raise forms.ValidationError("Unable to sign in with this account.", code="invalid_login")


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    contact_number = ContactNumberField()

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "contact_number"]


class UserFilterForm(forms.Form):
    q = forms.CharField(label="Search username, name or email", required=False, max_length=150)
    status = forms.ChoiceField(required=False, choices=[("", "All account statuses"), ("active", "Active"), ("inactive", "Inactive")])
    role = forms.ChoiceField(required=False, choices=[("", "All roles"), *User.Role.choices])


class AccountConfirmationForm(forms.Form):
    confirm = forms.BooleanField(label="I confirm this account change.", error_messages={"required": "Confirm the account change before continuing."})


class RoleChangeForm(AccountConfirmationForm):
    field_order = ["role", "confirm"]
    role = forms.ChoiceField(choices=User.Role.choices, help_text="Admin grants access to user management, inventory, borrowing approvals, loans, maintenance, reports, audit logs and settings.")
