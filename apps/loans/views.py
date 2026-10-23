from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET

from apps.borrowing.models import BorrowingRequest
from .forms import LoanFilterForm, ReleaseForm, RequestFilterForm, ReturnConfirmationForm, ReturnUnitFormSet
from .models import Loan
from .services import process_returns, release_request, validate_handover


def role_required(role):
    def decorate(view):
        @login_required(login_url="login")
        @wraps(view)
        def protected(request, *args, **kwargs):
            if not request.user.is_active or request.user.role != role:
                raise PermissionDenied("You do not have permission to use this page.")
            return view(request, *args, **kwargs)
        return protected
    return decorate


def _loans():
    return Loan.objects.select_related("borrower", "issued_by", "request").prefetch_related("units__received_by")


def _filtered_loans(queryset, form, *, admin=False):
    if not form.is_valid():
        return queryset.none()
    data = form.cleaned_data
    if data.get("q"):
        query = Q(units__equipment_name__icontains=data["q"]) | Q(units__asset_tag__icontains=data["q"])
        if admin:
            query |= Q(borrower__username__icontains=data["q"]) | Q(borrower__first_name__icontains=data["q"]) | Q(borrower__last_name__icontains=data["q"])
        queryset = queryset.filter(query).distinct()
    now = timezone.now()
    if data.get("status") == "overdue":
        queryset = queryset.overdue(at=now)
    elif data.get("status") == "active":
        queryset = queryset.active().filter(due_at__gte=now)
    elif data.get("status") == "partial":
        queryset = queryset.active().filter(units__returned_at__isnull=False).distinct()
    if data.get("due_from"):
        queryset = queryset.filter(due_at__date__gte=data["due_from"])
    if data.get("due_to"):
        queryset = queryset.filter(due_at__date__lte=data["due_to"])
    return queryset


def _page(request, queryset):
    return Paginator(queryset, 10).get_page(request.GET.get("page"))


def _release_review(borrowing):
    if borrowing.status != BorrowingRequest.Status.APPROVED:
        return "Only approved requests awaiting issuance can be released."
    items = list(borrowing.items.all())
    allocations = [allocation for item in items for allocation in item.allocations.all() if allocation.active]
    units = {allocation.unit_id: allocation.unit for allocation in allocations}
    try:
        validate_handover(borrowing, items, allocations, units)
    except ValidationError as error:
        return " ".join(error.messages)
    return ""


@role_required("BASIC_USER")
@require_GET
def my_loans(request):
    own = _loans().filter(borrower=request.user).active()
    form = LoanFilterForm(request.GET)
    return render(request, "loans/my_loans.html", {"page_obj": _page(request, _filtered_loans(own, form)), "filter_form": form, "active_nav": "loans", "overdue_count": own.overdue().count()})


@role_required("BASIC_USER")
@require_GET
def borrowing_history(request):
    own = _loans().filter(borrower=request.user).completed()
    form = LoanFilterForm(request.GET, history=True)
    return render(request, "loans/history.html", {"page_obj": _page(request, _filtered_loans(own, form)), "filter_form": form, "active_nav": "history"})


@role_required("BASIC_USER")
@require_GET
def user_loan_detail(request, pk):
    loan = get_object_or_404(_loans().filter(borrower=request.user), pk=pk)
    return render(request, "loans/detail.html", {"loan": loan, "active_nav": "history" if loan.completed_at else "loans"})


@role_required("ADMIN")
@require_GET
def loan_management(request):
    approved = BorrowingRequest.objects.filter(status=BorrowingRequest.Status.APPROVED, loan__isnull=True).select_related("borrower").prefetch_related("items__equipment", "items__allocations__unit")
    form = RequestFilterForm(request.GET)
    if form.is_valid() and form.cleaned_data.get("q"):
        query = form.cleaned_data["q"]
        approved = approved.filter(Q(borrower__username__icontains=query) | Q(borrower__first_name__icontains=query) | Q(borrower__last_name__icontains=query) | Q(items__equipment__name__icontains=query)).distinct()
    elif not form.is_valid():
        approved = approved.none()
    page = _page(request, approved)
    for borrowing in page:
        borrowing.release_error = _release_review(borrowing)
    return render(request, "loans/admin/management.html", {"page_obj": page, "filter_form": form, "active_nav": "loans"})


@role_required("ADMIN")
@require_http_methods(["GET", "POST"])
def release_equipment(request, pk):
    borrowing = get_object_or_404(BorrowingRequest.objects.select_related("borrower", "approved_by").prefetch_related("items__equipment", "items__allocations__unit"), pk=pk)
    form = ReleaseForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            loan = release_request(borrowing.pk, actor=request.user)
        except ValidationError as error:
            form.add_error(None, error)
            status = 409
        except (IntegrityError, OperationalError):
            form.add_error(None, "The equipment records changed or the database is busy. Reload this page and try again.")
            status = 409
        else:
            messages.success(request, f"Loan #{loan.pk} created. The reserved equipment has been released.")
            return redirect("admin_loan_detail", pk=loan.pk)
    release_error = _release_review(borrowing)
    return render(request, "loans/admin/release.html", {"borrowing": borrowing, "form": form, "active_nav": "loans", "can_release": not release_error, "release_error": release_error}, status=status)


@role_required("ADMIN")
@require_GET
def returns_overdue(request):
    active = _loans().active()
    form = LoanFilterForm(request.GET, admin=True)
    return render(request, "loans/admin/returns.html", {"page_obj": _page(request, _filtered_loans(active, form, admin=True)), "filter_form": form, "active_nav": "returns", "overdue_count": active.overdue().count()})


@role_required("ADMIN")
@require_GET
def admin_loan_detail(request, pk):
    loan = get_object_or_404(_loans(), pk=pk)
    return render(request, "loans/admin/detail.html", {"loan": loan, "active_nav": "returns" if request.GET.get("from") == "returns" else "loans"})


@role_required("ADMIN")
@require_http_methods(["GET", "POST"])
def return_equipment(request, pk):
    loan = get_object_or_404(_loans(), pk=pk)
    outstanding = [unit for unit in loan.units.all() if unit.returned_at is None]
    formset = ReturnUnitFormSet(request.POST if request.method == "POST" else None, initial=[{"loan_unit_id": unit.pk} for unit in outstanding], expected_ids=[unit.pk for unit in outstanding], prefix="units")
    confirm_form = ReturnConfirmationForm(request.POST if request.method == "POST" else None)
    operation_errors = []
    status = 409 if request.method == "POST" and loan.completed_at else 200
    valid = False
    if request.method == "POST":
        units_valid = formset.is_valid()
        confirmation_valid = confirm_form.is_valid()
        valid = units_valid and confirmation_valid
    if valid:
        try:
            result = process_returns(loan.pk, actor=request.user, returns=formset.selected_returns())
        except ValidationError as error:
            operation_errors = error.messages
            status = 409
        except (IntegrityError, OperationalError):
            operation_errors = ["The equipment records changed or the database is busy. Reload this page and try again."]
            status = 409
        else:
            messages.success(request, "All units returned; the loan is completed." if result.completed_at else "Selected units returned. The remaining units are still on loan.")
            return redirect("admin_loan_detail", pk=result.pk)
    # Associate bound fields with server-owned units by ID, never by a posted
    # label or arbitrary form order. Invalid IDs stay visibly invalid.
    by_id = {unit.pk: unit for unit in outstanding}
    rows = []
    for form in formset:
        try:
            unit = by_id.get(int(form["loan_unit_id"].value()))
        except (TypeError, ValueError):
            unit = None
        rows.append((form, unit))
    return render(request, "loans/admin/return_form.html", {"loan": loan, "formset": formset, "confirm_form": confirm_form, "return_rows": rows, "operation_errors": operation_errors, "active_nav": "returns"}, status=status)


@role_required("ADMIN")
@require_GET
def borrowing_slip(request, pk):
    loan = get_object_or_404(_loans(), pk=pk)
    return render(request, "loans/admin/slip.html", {"loan": loan, "active_nav": "loans"})
