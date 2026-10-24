from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers

from .forms import BorrowingRequestForm, DueDateRevisionForm, RequestFilterForm, RequestItemFormSet, ReviewForm
from .models import BorrowingRequest
from .services import approve_request, borrowing_limits, cancel_request, catalog_queryset, reject_request, revise_due_date, submit_request


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
    preselected_equipment = None
    if request.method == "GET" and request.GET.get("equipment"):
        try:
            equipment_id = int(request.GET["equipment"])
        except (TypeError, ValueError):
            equipment_id = None
        equipment = catalog_queryset().filter(pk=equipment_id, available_count__gt=0).first()
        if equipment:
            initial = [{"equipment": equipment.pk, "quantity": 1}]
            preselected_equipment = equipment
        else:
            messages.info(request, "That equipment is unavailable. Please choose another catalog item.")
    formset = RequestItemFormSet(data, initial=initial, prefix="items")
    status = 200
    row_action = request.POST.get("row_action", "")
    if request.method == "POST" and row_action:
        # Presentation-only fallback: adding/removing rows never submits a request.
        count = formset.management_form.cleaned_data.get("TOTAL_FORMS", 0)
        if formset.management_form.is_valid() and 1 <= count <= formset.max_num:
            rows = [{name: request.POST.get(f"items-{index}-{name}", "")
                     for name in ("equipment", "quantity")} for index in range(count)]
            if row_action == "add" and count < formset.max_num:
                rows.append({"equipment": "", "quantity": 1})
            elif row_action in {f"remove:items-{index}" for index in range(1, count)}:
                rows.pop(int(row_action[13:]))
            else:
                rows = None
            if rows is not None:
                form = BorrowingRequestForm(initial={name: request.POST.get(name, "") for name in form.fields})
                formset = RequestItemFormSet(initial=rows, prefix="items")
            else:
                form.add_error(None, "Unable to change equipment rows. Keep between 1 and the allowed maximum.")
        else:
            form.add_error(None, "Unable to change equipment rows. Reload the form and try again.")
    elif request.method == "POST":
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
    return render(request, "borrowing/new_request.html", {"form": form, "formset": formset, "catalog": catalog_queryset(), "preselected_equipment": preselected_equipment, "limits": borrowing_limits(), "active_nav": "requests"}, status=status)


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


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
@vary_on_headers("X-Admin-Modal")
def revise_request_due_date(request, pk):
    _require_role(request, "ADMIN")
    borrowing = get_object_or_404(_records(), pk=pk)
    modal_request = request.headers.get("X-Admin-Modal") == "1"
    form = DueDateRevisionForm(request.POST if request.method == "POST" else None, borrowing=borrowing)
    allowed = borrowing.status == "APPROVED" and not hasattr(borrowing, "loan")
    status = 200
    if request.method == "POST":
        if not allowed:
            form.add_error(None, "Only Approved requests awaiting issuance can have their due date revised.")
            status = 409
        elif form.is_valid():
            try:
                revise_due_date(borrowing.pk, actor=request.user, due_at=form.cleaned_data["due_date"],
                                reason=form.cleaned_data["reason"], expected_due_at=form.cleaned_data["expected_due_at"])
            except ValidationError as error:
                if hasattr(error, "message_dict"):
                    for field, errors in error.message_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, error)
                status = 409
            except (IntegrityError, OperationalError):
                form.add_error(None, "The request changed or the database is busy. Reload and try again.")
                status = 409
            else:
                messages.success(request, "Approved due date revised. The previous date and reason are recorded in Audit Logs.")
                if modal_request:
                    return JsonResponse({"saved": True})
                return redirect("admin_request_detail", pk=pk)
        elif modal_request:
            status = 422
    context = {
        "form": form, "borrowing": borrowing, "page_title": f"Revise due date · Request #{pk}",
        "description": "Change the agreed return date before equipment is issued. Existing reservations remain in place.",
        "submit_label": "Save due date", "modal_request": modal_request,
        "modal_unavailable": not allowed, "unavailable_message": "Only Approved requests awaiting issuance can be revised.",
        "active_nav": "requests",
    }
    return render(request, "components/admin_modal_form.html" if modal_request else "borrowing/admin/revise_due_date.html", context, status=status)


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
