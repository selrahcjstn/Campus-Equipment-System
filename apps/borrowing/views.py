from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import BorrowingRequestForm, RequestFilterForm, RequestItemFormSet, ReviewForm
from .models import BorrowingRequest
from .services import approve_request, borrowing_limits, cancel_request, catalog_queryset, reject_request, submit_request


def _require_role(request, role):
    if not request.user.is_active or request.user.role != role:
        raise PermissionDenied("You do not have permission to use this page.")


def _records():
    return BorrowingRequest.objects.select_related(
        "borrower", "approved_by", "rejected_by", "cancelled_by", "loan",
    ).prefetch_related("items__equipment", "items__allocations__unit", "loan__units")


def _list_context(request, *, admin=False):
    records = _records() if admin else _records().filter(borrower=request.user)
    data = request.GET if request.GET else ({"status": "PENDING"} if admin else {})
    form = RequestFilterForm(data, admin=admin)
    pending_count = records.filter(status="PENDING").count()
    if form.is_valid():
        values = form.cleaned_data
        if values.get("q"):
            query = Q(items__equipment__name__icontains=values["q"]) | Q(purpose__icontains=values["q"])
            if admin:
                query |= Q(borrower__username__icontains=values["q"]) | Q(borrower__first_name__icontains=values["q"]) | Q(borrower__last_name__icontains=values["q"])
            records = records.filter(query).distinct()
        if values.get("status") == "partial":
            records = records.filter(status="ISSUED", loan__completed_at__isnull=True, loan__units__returned_at__isnull=False).distinct()
        elif values.get("status"):
            records = records.filter(status=values["status"])
    else:
        records = records.none()
    return {"page_obj": Paginator(records, 10).get_page(request.GET.get("page")), "filter_form": form, "pending_count": pending_count, "admin_view": admin, "active_nav": "requests"}


@login_required(login_url="login")
@require_GET
def my_requests(request):
    _require_role(request, "BASIC_USER")
    return render(request, "borrowing/my_requests.html", _list_context(request))


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def new_request(request):
    _require_role(request, "BASIC_USER")
    data = request.POST if request.method == "POST" else None
    form = BorrowingRequestForm(data)
    initial = None
    if request.method == "GET" and request.GET.get("equipment"):
        try:
            equipment_id = int(request.GET["equipment"])
        except (TypeError, ValueError):
            equipment_id = None
        equipment = catalog_queryset().filter(pk=equipment_id, available_count__gt=0).first()
        if equipment:
            initial = [{"equipment": equipment.pk, "quantity": 1}]
        else:
            messages.info(request, "That equipment is unavailable. Please choose another catalog item.")
    formset = RequestItemFormSet(data, initial=initial, prefix="items")
    status = 200
    if request.method == "POST":
        form_valid = form.is_valid()
        items_valid = formset.is_valid()
        if form_valid and items_valid:
            try:
                borrowing = submit_request(borrower=request.user, purpose=form.cleaned_data["purpose"], due_at=form.cleaned_data["due_at"], items=formset.requested_items())
            except ValidationError as error:
                form.add_error(None, error)
                status = 409
            except (IntegrityError, OperationalError):
                form.add_error(None, "Availability changed or the database is busy. Please reload and try again.")
                status = 409
            else:
                messages.success(request, f"Request #{borrowing.pk} submitted for Admin review.")
                return redirect("request_detail", pk=borrowing.pk)
    return render(request, "borrowing/new_request.html", {"form": form, "formset": formset, "catalog": catalog_queryset(), "limits": borrowing_limits(), "active_nav": "requests"}, status=status)


def _detail_context(borrowing, *, admin=False):
    return {"borrowing": borrowing, "loan": getattr(borrowing, "loan", None), "admin_view": admin, "active_nav": "requests"}


@login_required(login_url="login")
@require_GET
def request_detail(request, pk):
    _require_role(request, "BASIC_USER")
    borrowing = get_object_or_404(_records().filter(borrower=request.user), pk=pk)
    return render(request, "borrowing/detail.html", _detail_context(borrowing))


@login_required(login_url="login")
@require_GET
def borrowing_requests(request):
    _require_role(request, "ADMIN")
    return render(request, "borrowing/admin/queue.html", _list_context(request, admin=True))


@login_required(login_url="login")
@require_GET
def admin_request_detail(request, pk):
    _require_role(request, "ADMIN")
    borrowing = get_object_or_404(_records(), pk=pk)
    return render(request, "borrowing/admin/detail.html", _detail_context(borrowing, admin=True))


def _action(request, pk, action, *, admin):
    records = _records() if admin else _records().filter(borrower=request.user)
    borrowing = get_object_or_404(records, pk=pk)
    form = ReviewForm(request.POST if request.method == "POST" else None, action=action)
    titles = {"approve": "Approve request", "reject": "Reject request", "cancel": "Cancel request"}
    descriptions = {
        "approve": "Available physical units will be selected and reserved together. Equipment release happens separately in Loan Management.",
        "reject": "The borrower will see your rejection reason. No equipment will be reserved.",
        "cancel": "The request will be cancelled and its reserved units will become Available. Issued equipment cannot be cancelled.",
    }
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            if action == "approve":
                approve_request(borrowing.pk, actor=request.user)
            elif action == "reject":
                reject_request(borrowing.pk, actor=request.user, reason=form.cleaned_data["rejection_reason"])
            else:
                cancel_request(borrowing.pk, actor=request.user)
        except ValidationError as error:
            form.add_error(None, error)
            status = 409
        except (IntegrityError, OperationalError):
            form.add_error(None, "The request or equipment changed, or the database is busy. Reload this page and try again.")
            status = 409
        else:
            labels = {"approve": "approved and equipment reserved", "reject": "rejected", "cancel": "cancelled and any reservations released"}
            messages.success(request, f"Request #{borrowing.pk} {labels[action]}.")
            return redirect("admin_request_detail" if admin else "request_detail", pk=borrowing.pk)
    can_act = borrowing.can_cancel if action == "cancel" else borrowing.status == "PENDING"
    context = _detail_context(borrowing, admin=admin)
    context.update(form=form, action_title=titles[action], action_description=descriptions[action], can_act=can_act, base_template="base_admin.html" if admin else "base_user.html")
    return render(request, "borrowing/admin/action.html" if admin else "borrowing/action.html", context, status=status)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def approve(request, pk):
    _require_role(request, "ADMIN")
    return _action(request, pk, "approve", admin=True)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def reject(request, pk):
    _require_role(request, "ADMIN")
    return _action(request, pk, "reject", admin=True)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def user_cancel(request, pk):
    _require_role(request, "BASIC_USER")
    return _action(request, pk, "cancel", admin=False)


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def admin_cancel(request, pk):
    _require_role(request, "ADMIN")
    return _action(request, pk, "cancel", admin=True)
