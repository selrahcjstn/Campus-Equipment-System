# Loans, Returns and Overdue — Janelle

This branch implements Django models, atomic services, role-protected custom
pages, printable borrowing slips, migrations and automated tests. It uses the
existing design tokens, sidebar, layouts, messages and native dialog styling.

## Run and test locally

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.loans
.\.venv\Scripts\python.exe manage.py runserver
```

Existing accounts and database records are preserved. No demo records are added
automatically. User accounts must have `role="ADMIN"` or `role="BASIC_USER"`;
`is_staff` and `is_superuser` alone do not grant the custom module's Admin access.

To populate the pages using two **existing test accounts**, optionally run:

```powershell
.\.venv\Scripts\python.exe manage.py seed_loans_demo --admin YOUR_ADMIN_USERNAME --borrower YOUR_BASIC_USER_USERNAME
```

The command is restricted to `DEBUG=True`. It adds four new demo physical units,
one fully approved request ready for release, and one overdue two-unit loan.
It does not change account roles, passwords or existing transactions. Repeating
the command refuses to overwrite existing demo records. The historical dates
are assigned only to the newly-created overdue fixture.

If you need test accounts, register them through `/register/`. A local developer
can assign the Admin role to the intended test account using the Django shell:

```python
from django.contrib.auth import get_user_model
get_user_model().objects.filter(username="YOUR_ADMIN_USERNAME").update(role="ADMIN")
```

The application does not use Django's built-in Admin UI.

## Manual acceptance walkthrough

1. Log in as the test Admin. Open Loan Management, review the approved request,
   confirm the handover, and release it. Check the physical tags, quantities,
   timestamps, and printable slip. Reposting the release cannot create another loan.
2. Log in as its Basic User. My Loans shows their issued equipment and due dates;
   an overdue loan has a warning. Another Basic User cannot see those records,
   including by guessing a detail URL or using search filters.
3. As Admin, open Returns and Overdue and choose Return units. Return just one
   physical unit in Good condition. The other remains outstanding and the request
   remains Issued. The returned unit becomes Available.
4. Return the remaining unit as Damaged with a description. Its inventory status
   becomes Maintenance, its reservation ends, and the loan/request complete.
5. Check the Basic User's Borrowing History and detail page. Return conditions,
   dates, receiving Admins and notes remain visible. Completed loans leave the
   active queue; stale forms cannot record a second return.
6. Filter by borrower (Admin), equipment, asset tag, overdue/partial status or due
   dates. Clear filters to see all records. Test the navigation on a narrow screen.

## Database and integration contract

Inventory and Borrowing had no models in any existing branch. Their minimal
foundations were added with explicit user approval. These are shared domain
models for future member work, not parallel models owned by Loans.

| App | Models | Responsibility |
| --- | --- | --- |
| Inventory | `Equipment`, `EquipmentUnit` | Equipment descriptions and uniquely tagged physical copies |
| Borrowing | `BorrowingRequest`, `BorrowingRequestItem`, `Allocation` | Borrower, purpose, due date, approval and exact unit reservations |
| Loans | `Loan`, `LoanUnit` | One issuance per request, historical equipment snapshots and per-unit returns |

Three initial migrations add seven tables. They depend on the existing Accounts
user migration. No existing tables or data are reset. Historical foreign keys
use protection against deleting referenced equipment, requests or users.

- Physical unit statuses: `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`, `RETIRED`.
- Request transitions for this workflow: `PENDING → APPROVED → ISSUED → COMPLETED`.
  `REJECTED` and `CANCELLED` are reserved for Borrowing's workflow. Loans never
  changes a request to an invented `OVERDUE` status.
- `approve_request(request_id, actor=admin, allocations={item_id: [unit_id, ...]})`
  in `apps.borrowing.services` validates matching equipment, exact quantities,
  availability and Admin permissions, then reserves the units. Clark's approval
  UI should call this service; that UI is outside this branch's scope.
- `release_request(request_id, actor=admin)` in `apps.loans.services` is the only
  issuance entry point. Its due date comes from the approved request. It creates
  one Loan, captures the equipment names/descriptions/tags, and issues each unit.
- `process_returns(loan_id, actor=admin, returns=[(loan_unit_id, condition, notes)])`
  validates ownership of each issued unit, its allocation and current state.
  Conditions are `GOOD` or `DAMAGED`. Damage requires notes. Return timestamps
  come from the server; they cannot be supplied or overwritten through the form.
- Requests and their items/allocations should not be edited after approval except
  through their transactional workflow. Borrower access uses the Loan's recorded
  borrower; changing an unrelated inventory label does not rewrite history.
- Francis's Maintenance module should consume
  `EquipmentUnit.objects.filter(status=EquipmentUnit.Status.MAINTENANCE)` and the
  associated damaged `LoanUnit` return records. This branch supplies that queue
  state and damage notes; maintenance repair scheduling is separate work.
- Overdue means `completed_at is None and due_at < timezone.now()`. Partial loans
  remain overdue after their due date. Completed loans are never overdue.
- Dates use the project's configured timezone (currently UTC), shown on pages
  and slips. No timezone setting is changed by this module.

Approval, release and returns use `transaction.atomic()`, ordered row locking,
conditional writes and database uniqueness/check constraints. A physical unit
can have only one active allocation and one outstanding issuance. On SQLite,
`select_for_update()` does not lock rows; conditional writes acquire its writer
lock before inspecting mutable state. A database conflict returns an error with
no partial change, and the Admin can reload and retry. See the
[Django queryset documentation](https://docs.djangoproject.com/en/6.1/ref/models/querysets/#select-for-update).

## Routes

| URL | Route name | Access |
| --- | --- | --- |
| `/portal/loans/` | `my_loans` | Basic User's own active loans |
| `/portal/history/` | `borrowing_history` | Basic User's own completed loans |
| `/portal/loans/<id>/` | `user_loan_detail` | Basic User's own loan only |
| `/manage/loans/` | `loan_management` | Admin approved requests |
| `/manage/loans/release/<request_id>/` | `release_equipment` | Admin GET review / POST release |
| `/manage/loans/<id>/` | `admin_loan_detail` | Admin loan/return record |
| `/manage/loans/<id>/slip/` | `borrowing_slip` | Admin printable slip |
| `/manage/returns/` | `returns_overdue` | Admin active/overdue/partial loans |
| `/manage/returns/<id>/` | `return_equipment` | Admin GET form / POST per-unit returns |

All state changes require POST, CSRF and server-validated confirmation. GET
reviews and printing do not issue or return equipment. The established sidebar
names are retained; unrelated navigation destinations remain owned by their
respective modules.

## Verification

The automated suite covers release, approval/allocation prerequisites, role
checks, exact quantities, duplicate issuance, partial/full/damaged returns,
duplicate/foreign/stale/tampered submissions, transaction rollback, inventory
reuse, overdue boundaries, data isolation, protected history, CSRF, template
rendering, filters, slips, fixtures and concurrent duplicate operations.

The tests use an isolated test database. No commits, merges, force pushes or
database resets are part of implementation.

Validated on October 14, 2026: `check` passed, the migration dry run found no
changes, and all **59 Loans tests passed**, including the two concurrent-operation
tests. The three migrations were applied to the local database. All rows present
in the pre-migration backup remained present and unchanged; a SQLite foreign-key
check reported zero violations. No demo fixtures were added to that database.

## Changed files

- Loans backend: `models.py`, `forms.py`, `services.py`, `views.py`, `urls.py`,
  `tests.py`, `migrations/0001_initial.py`, and this guide under `apps/loans/`.
- Optional fixtures: `apps/loans/management/commands/seed_loans_demo.py` and the
  management package initializer files.
- Foundations: `apps/inventory/models.py`, `apps/borrowing/models.py`,
  `apps/borrowing/services.py`, and one initial migration for each foundation app.
- URL integration: `config/urls.py` replaces only the four Loans navigation
  previews with the module's real routes.
- User templates: `templates/loans/my_loans.html`, `history.html`, and `detail.html`.
- Admin templates: `templates/loans/admin/management.html`, `release.html`,
  `returns.html`, `detail.html`, `return_form.html`, and `slip.html`.
- Shared module partials: `templates/loans/_filters.html`, `_pagination.html`,
  `_loan_table.html`, `_detail_body.html`, and `_confirmation.html`.
- Module assets: `static/css/loans.css` and `static/js/loans.js`.
