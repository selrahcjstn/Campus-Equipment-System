from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.borrowing.models import BorrowingRequest
from apps.loans.models import Loan
from .forms import AccountConfirmationForm, LoginForm, ProfileForm, RegisterForm, RoleChangeForm, UserFilterForm
from .models import User
from .services import change_password, set_user_active, set_user_role, update_profile


def account_required(*, admin=False):
    def decorate(view):
        @login_required(login_url="login")
        @wraps(view)
        def protected(request, *args, **kwargs):
            if not request.user.is_active or request.user.role not in User.Role.values or (admin and request.user.role != "ADMIN"):
                raise PermissionDenied("You do not have permission to use this page.")
            return view(request, *args, **kwargs)
        return protected
    return decorate


def _home(user):
    return "admin_dashboard" if user.role == "ADMIN" else "user_dashboard"


def _profile_route(user):
    return "admin_profile" if user.role == "ADMIN" else "my_profile"


def _profile_context(user):
    return {"portal_base": "base_admin.html" if user.role == "ADMIN" else "base_user.html", "profile_route": _profile_route(user), "password_route": "admin_change_password" if user.role == "ADMIN" else "change_password", "active_nav": "profile"}


def _error(form, error):
    if isinstance(error, ValidationError):
        if hasattr(error, "error_dict"):
            for field, errors in error.error_dict.items():
                form.add_error(field if field in form.fields else None, errors)
        else:
            form.add_error(None, error)
    else:
        form.add_error(None, "The account changed or the database is busy. Reload and try again.")


@require_GET
def landing_page(request):
    if request.user.is_authenticated:
        return redirect(_home(request.user))
    return render(request, "landing.html")


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect(_home(request.user))

    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except (IntegrityError, OperationalError):
                form.add_error(None, "This username was just registered or the database is busy. Choose another username or try again.")
            else:
                login(request, user)
                return redirect("user_dashboard")
    else:
        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form}
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_home(request.user))
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)

            return redirect(_home(user))

    else:
        form = LoginForm()

    return render(
        request,
        "accounts/login.html",
        {"form": form}
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@account_required()
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            user = update_profile(actor=request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError, OperationalError) as error:
            _error(form, error)
            status = 409
        else:
            messages.success(request, "Your profile was updated.")
            return redirect(_profile_route(user))
    context = _profile_context(request.user)
    context.update(form=form)
    return render(request, "accounts/profile.html", context, status=status)


@account_required()
@require_http_methods(["GET", "POST"])
def password_change(request):
    form = PasswordChangeForm(user=request.user, data=request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            user = change_password(actor=request.user, data=request.POST)
        except (ValidationError, IntegrityError, OperationalError) as error:
            _error(form, error)
            status = 409
        else:
            update_session_auth_hash(request, user)
            messages.success(request, "Your password was changed. This session stays signed in; other sessions must sign in again.")
            return redirect(_profile_route(user))
    context = _profile_context(request.user)
    context.update(form=form)
    return render(request, "accounts/password_change.html", context, status=status)


@account_required(admin=True)
@require_GET
def user_management(request):
    form = UserFilterForm(request.GET)
    users = User.objects.order_by("username", "pk")
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            users = users.annotate(full_name=Concat("first_name", Value(" "), "last_name")).filter(Q(username__icontains=data["q"]) | Q(full_name__icontains=data["q"]) | Q(email__icontains=data["q"]))
        if data.get("status"):
            users = users.filter(is_active=data["status"] == "active")
        if data.get("role"):
            users = users.filter(role=data["role"])
    else:
        users = users.none()
    return render(request, "accounts/admin/users.html", {"filter_form": form, "page_obj": Paginator(users, 10).get_page(request.GET.get("page")), "active_nav": "users"})


@account_required(admin=True)
@require_GET
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    requests = BorrowingRequest.objects.filter(borrower=user).select_related("loan").prefetch_related("items__equipment", "loan__units")
    loans = Loan.objects.filter(borrower=user).prefetch_related("units")
    return render(request, "accounts/admin/detail.html", {"target_user": user, "request_page": Paginator(requests, 10).get_page(request.GET.get("request_page")), "loan_page": Paginator(loans, 10).get_page(request.GET.get("loan_page")), "active_nav": "users"})


def _account_action(request, pk, action):
    user = get_object_or_404(User, pk=pk)
    role_action = action == "role"
    form = RoleChangeForm(request.POST if request.method == "POST" else None, initial={"role": user.role}) if role_action else AccountConfirmationForm(request.POST if request.method == "POST" else None)
    allowed = user.pk != request.user.pk if role_action else (not user.is_active if action == "activate" else user.is_active and user.pk != request.user.pk)
    titles = {"activate": "Activate account", "deactivate": "Deactivate account", "role": "Change account role"}
    descriptions = {"activate": "Allow this account to sign in with its current campus role.", "deactivate": "Prevent this account from signing in. Requests, loans and returns are preserved.", "role": "Change access to campus workflows. Existing history is preserved; the last active Admin cannot be removed."}
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            if role_action:
                set_user_role(pk, actor=request.user, role=form.cleaned_data["role"])
            else:
                set_user_active(pk, actor=request.user, is_active=action == "activate")
        except (ValidationError, IntegrityError, OperationalError) as error:
            _error(form, error)
            status = 409
        else:
            messages.success(request, "Account role saved." if role_action else "Account activated." if action == "activate" else "Account deactivated. Its borrowing history is preserved.")
            return redirect("user_detail", pk=pk)
    return render(request, "accounts/admin/action.html", {"target_user": user, "form": form, "allowed": allowed, "page_title": titles[action], "description": descriptions[action], "action": action, "active_nav": "users"}, status=status)


@account_required(admin=True)
@require_http_methods(["GET", "POST"])
def activate_user(request, pk):
    return _account_action(request, pk, "activate")


@account_required(admin=True)
@require_http_methods(["GET", "POST"])
def deactivate_user(request, pk):
    return _account_action(request, pk, "deactivate")


@account_required(admin=True)
@require_http_methods(["GET", "POST"])
def change_user_role(request, pk):
    return _account_action(request, pk, "role")


@account_required(admin=True)
@require_http_methods(["GET", "POST"])
def admin_profile(request):
    return profile(request)


@account_required(admin=True)
@require_http_methods(["GET", "POST"])
def admin_password_change(request):
    return password_change(request)
