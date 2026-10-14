# Francis — Equipment Maintenance Management

The custom Admin portal now tracks maintenance per existing physical equipment
unit. Sign in with an active account whose role is `ADMIN` and open Maintenance
in the sidebar at `/manage/maintenance/`.

## Features and workflow

- Database-driven totals for units currently in Maintenance, active records and
  completed records. The current-unit table and records table paginate separately.
- Search by unit identifier, equipment name or reported issue; filter by status
  and equipment, including archived equipment.
- Report an issue on an Available unit, or adopt an existing Maintenance unit
  without an active record. Active reservations, outstanding loans, Retired units
  and duplicate active maintenance are rejected.
- Update Reported work to In progress and record internal repair notes. Work
  cannot move backwards; updating progress leaves the unit in Maintenance.
- Confirm a completed repair only after work is In progress. Required notes and
  confirmation close the record and restore the physical unit to Available.
- Retire an irreparable unit from Reported or In progress, with required notes
  and confirmation. The record closes and the unit becomes Retired.
- Completed records are read-only and remain in each unit's history. No deletion
  endpoint exists. Equipment, source returns and referenced Admin accounts use
  protected relationships to preserve history.
- Units without a record remain unavailable and appear in the dashboard's intake
  warning. Open their unit history and report the issue to start tracking.

`MaintenanceRecord` holds the unit, original issue, status, report and completion
dates, repair notes, reporting Admin, closing Admin and optional source damaged
return. Legacy records can lack a reporting Admin when no trustworthy historical
actor exists. Database constraints enforce one active record per unit, valid
statuses, coherent resolution fields and completion after reporting.

All mutations require an active Admin and run atomically. The initial conditional
write and row locks serialize operations, including SQLite. The service repeats
eligibility checks after locking the unit. Validation or database conflicts roll
back both the record and unit transition.

## Inventory, Borrowing and Loans integration

Loans owns return processing. After Loans records a damaged return, sets the unit
to Maintenance and releases its allocation, it calls `record_damaged_return`
inside the same transaction. The new record links to the original `LoanUnit`,
copies the damage description and return date and records the receiving Admin.
If maintenance creation fails, the entire return rolls back. Good returns create
no maintenance record. Partial returns retain the other units' loan state.

Repair and retirement leave the original return, loan snapshots, completed loan
and inactive allocation unchanged. A later damage incident creates a new history
record. The damaged-return helper is idempotent and does not reopen closed work.

Inventory availability and Borrowing allocation exclude active maintenance even
if a unit's status was incorrectly changed directly in the database. Explicit
allocations and loan release also reject active maintenance. Ordinary Inventory
editing and retirement cannot bypass active records. Each Admin inventory unit
row links to its Maintenance history.

Repairing an archived catalog item's unit restores its physical status to
Available but does not reactivate the catalog item; it stays hidden from Basic
Users. Basic Users have no Maintenance destination and cannot access its pages
or actions, including when staff/superuser flags are set. Their catalog exposes
public equipment information and eligible availability, with no unit identifiers,
reported issues, repair notes or administrative actions.

## URLs

| URL | Name | Purpose |
| --- | --- | --- |
| `/manage/maintenance/` | `maintenance` | Dashboard, search and filters |
| `/manage/maintenance/new/` | `maintenance_create` | Report an issue |
| `/manage/maintenance/<id>/` | `maintenance_detail` | Record details |
| `/manage/maintenance/<id>/update/` | `maintenance_update` | Progress and internal notes |
| `/manage/maintenance/<id>/complete/` | `maintenance_complete` | Confirm successful repair |
| `/manage/maintenance/<id>/retire/` | `maintenance_retire` | Confirm retirement |
| `/manage/maintenance/units/<unit_id>/history/` | `maintenance_history` | Unit history and active issue |

Dashboard, details and history accept GET only. Forms/actions accept GET and
CSRF-protected POST. GET never changes state. Resolution also requires a checked
server-validated confirmation; native dialogs enhance the action when JavaScript
is enabled. Form submissions work with JavaScript disabled.

## Shared UI

The existing Admin and User layouts, sidebar, typography, design tokens, buttons,
tables, badges, messages and native dialogs are reused. The established Maintenance
navigation name now resolves to the protected dashboard and marks its sidebar entry
active. The shared checkbox component places a checkbox beside its clickable label,
retaining help/error associations. Shared `ui.js` adds opt-in `data-confirm-dialog`
and `data-submit-loading` behaviors; existing module-specific handlers are preserved.
Maintenance CSS uses existing tokens, flexible card/filter grids and horizontally
scrollable tables without frontend dependencies or a layout redesign.

## Files

New or completed module files:

- `apps/maintenance/models.py`, `services.py`, `forms.py`, `views.py`, `urls.py`,
  `tests.py` and this guide.
- `apps/maintenance/migrations/0001_initial.py` and
  `0002_track_existing_maintenance.py`.
- `templates/maintenance/dashboard.html`, `detail.html`, `history.html`,
  `form.html`, `resolve.html`, `_records.html`, `_confirm_actions.html`.
- `static/css/maintenance.css`.

Necessary integrations:

- `apps/loans/services.py`: atomic damaged-return handoff and conflict checks.
- `apps/inventory/services.py`, `models.py`: active-maintenance eligibility and
  protections for ordinary unit editing/retirement.
- `apps/borrowing/services.py`: explicit allocation eligibility check.
- `config/urls.py`: replace the Maintenance preview with the real module.
- `templates/inventory/admin/_unit_table.html`: unit history links.
- `templates/components/input.html`, `static/css/design-system.css`,
  `static/js/ui.js`: shared checkbox and opt-in confirmation/loading behavior.

## Migrations and data preservation

`0001_initial` adds the maintenance table and constraints, using the existing
Inventory and Loans relationships. `0002_track_existing_maintenance` creates
Reported records for existing Maintenance units without changing any original
Inventory or Loans data. It links only the latest physical return if damaged;
an older damage incident is not reused after a newer good return. Otherwise it
records a legacy assessment reason. Its reverse is intentionally a no-op to
preserve historical records; do not reverse the schema migration after use.

Before applying these migrations, the local SQLite database was backed up to
`.local-backups/db_before_francis_20261014_065720_546956.sqlite3`. All pre-existing
table rows and fields were verified unchanged afterward; foreign-key checks pass.
The local database had no existing units in Maintenance; legacy adoption was
verified through isolated tests. No demo accounts or equipment were inserted in
the working database.

## Verification

Using the project's `.venv` Python:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.maintenance
.\.venv\Scripts\python.exe manage.py test
```

Results: system check passes, no missing migrations, **60 Maintenance tests pass**,
and **228 tests pass across the full project**, including Inventory, Borrowing
and Loans. Coverage includes damaged/good/partial returns, transaction rollback,
repair/re-retirement prevention, history, legacy migration adoption, archived
catalog behavior, stale states, role restrictions, CSRF, forged inputs, search,
pagination and concurrent creation, resolution and approval. Templates, navigation,
shared confirmation forms and private/public output were exercised by Django's
test client. A browser visual review is not included in these results.

For manual review:

1. Open Maintenance as Admin, report an issue on an Available unit and check its
   availability disappears from the Basic User catalog.
2. Open the record, update it to In progress, enter repair notes and confirm repair.
   Check that the unit is Available and the completed record remains in history.
3. Return an issued unit as Damaged through Returns and Overdue. Open Maintenance
   to review the automatically linked issue, then assess and repair or retire it.
4. Check mobile navigation, wrapped actions, filters, table scrolling and confirmation
   dialogs at a narrow viewport; repeat a resolution with JavaScript disabled.

No remaining module dependencies or implementation blockers. Raj's baseline was
saved locally as `aab9e65` and carried onto `francis` with permission. Francis's
implementation remains uncommitted; nothing was pushed and `main` was not changed.
