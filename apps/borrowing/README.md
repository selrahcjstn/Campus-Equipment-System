# Borrowing Requests and Approval — Clark

Implemented on `clark`, using Janelle's completed module as the integration
baseline. With the user's explicit approval, Janelle's work was saved in local
commit `3a38346` and included in Clark by fast-forward. Clark's own implementation
is left uncommitted for testing. Neither branch was pushed or merged into `main`.

## Test locally

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.borrowing apps.loans apps.inventory
.\.venv\Scripts\python.exe manage.py runserver
```

Use existing active accounts with `role="BASIC_USER"` and `role="ADMIN"`.
Staff/superuser flags alone do not grant custom Admin access. Register test users
through `/register/`; local role assignment is described in the
[Loans testing guide](../loans/README.md). This module uses custom pages, not
Django's built-in Admin interface.

If you need test inventory, this optional command adds six available physical
units, two equipment types and a Pending request for an **existing** Basic User:

```powershell
.\.venv\Scripts\python.exe manage.py seed_borrowing_demo --borrower YOUR_BASIC_USER_USERNAME
```

It requires `DEBUG=True`, does not change users or previous transactions, and
refuses to overwrite demo records. No fixtures are added automatically.

## Manual acceptance

1. As Basic User, open My Borrowing Requests and select New request. Browse or
   search the inline inventory catalog, select 1–3 distinct items, specify 1–3
   units per item, a purpose and a due date within seven calendar days.
2. Submit and check the Pending detail page. Pending requests do not reserve
   stock. A second Basic User cannot view or cancel the first user's records.
3. As Admin, open Borrowing Requests. The default view is the Pending queue;
   Show all and the status/search controls include the other request states.
4. Review and approve a request. The server automatically chooses Available
   physical units and reserves every quantity together. Their tags appear on the
   detail page. Equipment is handed over separately through Loan Management.
5. Try another approval after available stock is exhausted. It fails with no
   partial approval or reservation. Reject another Pending request with a reason;
   that reason, Admin and timestamp appear on the borrower's detail page.
6. Cancel a Pending or Approved request as its borrower or Admin. Approved
   reservations are released to Available and their allocation history remains.
   Rejected, Cancelled, Issued and Returned requests cannot be cancelled.
7. Release an Approved request through Janelle's Loan Management. It becomes
   Issued and cannot be cancelled. Partial returns display Partially Returned;
   the last return displays Returned. Overdue remains computed from the loan due
   date and outstanding units. Test history, return conditions and damaged units
   through the existing Loans pages.

## Rules and compatibility

- Default limits are three distinct catalog types, three physical units per type
  and seven calendar days. Admins configure them at `/manage/settings/` through
  the database policy in `apps.dashboard.policies`. Before a policy is saved,
  `BORROWING_MAX_ITEMS`, `BORROWING_MAX_QUANTITY` and `BORROWING_MAX_DAYS` in
  Django settings remain the fallback. New submissions and pending approvals
  use current limits; existing approvals and issued loans retain their terms.
- Due dates entered on the form mean the end of the selected calendar date in
  the application's configured timezone, currently Asia/Manila. Duration is measured
  by local calendar-date difference from submission, not by 24-hour intervals.
- Limits, dates, roles and availability are enforced by the service as well as
  the form. Approval repeats policy and stock checks. Availability shown by the
  browser is informative; posted availability/status/borrower values are ignored.
- Submission locks and checks the current borrower row before creating a request,
  so account deactivation or role promotion after authentication cannot be bypassed
  by an earlier in-memory account state.
- The brief's `BorrowRequest`, `RequestItem`, `UnitAllocation` and `CatalogItem`
  correspond to the existing `BorrowingRequest`, `BorrowingRequestItem`,
  `Allocation` and `Equipment`. They are reused without creating duplicate tables
  or renaming models already consumed by Loans.
- Stored request statuses remain `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`,
  `ISSUED`, `COMPLETED`. The UI displays `COMPLETED` as Returned and derives
  Partially Returned from the related LoanUnit return records while retaining
  `ISSUED`. There is no stored Partially Returned or Overdue request status.
- Approval and cancellation claim eligible request transitions with conditional
  writes before reading mutable stock. `transaction.atomic()`, ordered row locks,
  conditional unit updates and the existing active-allocation uniqueness
  constraint prevent double reservations and partial state changes. SQLite
  serializes writers; a database conflict displays a reload/retry error.
- Cancellation and issuance coordinate on the same request row. The winner
  commits its entire operation. A cancellation cannot make an issued unit
  Available. Rejection is limited to Pending requests and requires a reason.
- `approve_request(request_id, actor=admin)` automatically allocates units. Its
  optional explicit `allocations` mapping is retained for Janelle's existing
  integrations and tests. `submit_request`, `reject_request` and `cancel_request`
  are the other state-changing entry points in `services.py`.
- Borrowing never creates loans or processes returns. Links hand approved
  requests to the unchanged Loans release service and the existing return pages.

## Routes

| URL | Name | Access |
| --- | --- | --- |
| `/portal/requests/` | `my_requests` | Basic User's own records |
| `/portal/requests/new/` | `new_borrowing_request` | Basic User submission |
| `/portal/requests/<id>/` | `request_detail` | Owner only |
| `/portal/requests/<id>/cancel/` | `cancel_borrowing_request` | Owner GET confirmation / POST cancellation |
| `/manage/requests/` | `borrowing_requests` | Admin queue/search/filter |
| `/manage/requests/<id>/` | `admin_request_detail` | Admin review and allocations |
| `/manage/requests/<id>/approve/` | `approve_borrowing_request` | Admin GET confirmation / POST approval |
| `/manage/requests/<id>/reject/` | `reject_borrowing_request` | Admin GET reason form / POST rejection |
| `/manage/requests/<id>/cancel/` | `admin_cancel_borrowing_request` | Admin GET confirmation / POST cancellation |

All changes require POST and CSRF. Approval, rejection and cancellation also
require a server-validated confirmation checkbox. Native confirmation dialogs
and loading feedback enhance the forms; server validation works without JS.

## Files and database changes

- Updated `apps/borrowing/models.py`, `services.py`, `views.py`, `tests.py`.
- Added `forms.py`, `urls.py`, this guide and the optional demo management command
  with package initializers under `apps/borrowing/`.
- Added migration `0002_borrowingrequest_cancelled_at_and_more.py`. It adds only
  rejection reason, rejection date/Admin, and cancellation date/actor fields.
  Existing initial migrations and stored status values remain intact.
- Updated only Borrowing's two preview routes in `config/urls.py`.
- Added user pages under `templates/borrowing/` (`my_requests`, `new_request`,
  `detail`, `action`) and Admin `queue`, `detail`, `action` pages under
  `templates/borrowing/admin/`, plus three module partials.
- Added `static/css/borrowing.css` and `static/js/borrowing.js` using the existing
  design tokens and shared modal, input, button, table and badge patterns.

Inventory catalog management and Maintenance repair screens remain separate
members' modules. Clark's pages consume the current Inventory domain models and
the completed Loans workflow; the optional fixtures allow testing before the
Inventory management UI is built. No remaining dependency blocks this module.

## Verified results — October 14, 2026

- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python manage.py test apps.borrowing`: 57 Borrowing tests passed.
- Combined Borrowing/Loans/Inventory run: **116 tests passed** (57 Borrowing and
  59 Loans; Inventory interactions are covered by these integration tests).
- Migration `borrowing.0002_borrowingrequest_cancelled_at_and_more` applied to
  the local database after creating an ignored SQLite backup. All pre-existing
  data was verified unchanged, all five added fields were verified present,
  and the SQLite foreign-key check reported zero violations.
- No demo data was seeded in the local database during implementation.
