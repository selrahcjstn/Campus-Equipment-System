# Miah — Dashboard, Reports, Audit Logs and System Settings

This module uses the existing Accounts, Inventory, Borrowing, Loans and Maintenance
models. It adds `AuditLog` and one optional `SystemSetting` policy row; no equipment,
request or loan models are duplicated. The custom portal uses the existing shared
layouts and design tokens, with no frontend dependencies or built-in Django Admin.

## Pages and permissions

| URL | Name | Access / purpose |
| --- | --- | --- |
| `/portal/` | `user_dashboard` | Active Basic User's personal dashboard |
| `/manage/` | `admin_dashboard` | Active Admin's live KPIs and charts |
| `/manage/reports/` | `reports` | Admin loan and overdue reports |
| `/manage/reports/export/` | `export_reports` | Admin filtered CSV export |
| `/manage/audit-logs/` | `audit_logs` | Admin read-only audit search |
| `/manage/settings/` | `system_settings` | Admin borrowing policy form |

All reads accept GET only. Settings accepts GET and CSRF-protected POST and
requires server-validated confirmation. Role checks run before method handling.
Staff/superuser flags do not override the project's `ADMIN`/`BASIC_USER` roles.
Anonymous callers redirect to Login; wrong-role callers receive 403. Existing
login redirects and sidebar route names are preserved.

The Basic dashboard scopes every query to the authenticated borrower. It shows
Pending requests, Approved requests awaiting release, outstanding borrowed-unit
count, overdue-loan count, upcoming due dates, overdue loans and five recent
requests. Current-loan equipment summaries exclude returned units. Quick links
lead to Catalog, Requests, Loans, History and the existing Profile route. Internal
maintenance notes, other borrowers and Admin destinations are not included.

## Admin KPI and chart definitions

1. **Total inventory:** all physical `EquipmentUnit` rows, including archived
   catalog equipment and Retired units. The card explicitly labels this scope.
2. **Available equipment:** Inventory's existing `eligible_units()` query, requiring
   Available status and an active catalog item, with no active allocation,
   outstanding loan or active maintenance record.
3. **Active loans:** existing `Loan.objects.active()` records with at least one
   outstanding `LoanUnit`, counted once per loan, including partial returns.
4. **Overdue loans:** those active loans with a due time strictly before now.
   Fully returned loans are excluded, including inconsistent legacy completion
   metadata where all units have actually been returned.

The Borrowing Activity chart counts actual `BorrowingRequest.requested_at`
records by local calendar date. It includes all submission statuses, fills missing
dates with zero and supports an inclusive range of up to 366 dates. The default
is the last 30 dates. Its responsive SVG has tooltips; the expandable data table
shows only the latest seven dates of the selected period.

The Equipment Status Distribution chart groups every physical unit's recorded
status into Available, Reserved, Issued (`ON_LOAN`), Maintenance and Retired. It
includes archived inventory, displays zero-count categories and shows counts
beside labeled proportional bars. The different scopes of recorded Available
status and currently borrowable equipment are explicit in the chart and KPI labels.

The dashboard uses grouped/aggregate queries instead of per-record lookups.
Its query count stays constant as the data grows. Empty databases render zero
KPIs, labeled empty charts and usable navigation.

## Reports and CSV

Loan reports filter the **issue date**; currently overdue reports filter the
**due date**. Date ranges are optional, inclusive and use the same shared query
for the table and export. Invalid ranges, dates and report types show form errors;
invalid exports return 400. Supported filter dates are 1900–2100.

The application timezone is now **Asia/Manila**. Timestamp storage remains UTC;
existing timestamps are not rewritten. Calendar boundaries are converted to
timezone-aware half-open timestamp ranges, and CSV dates include their local
ISO 8601 offset. Overdue calculations require both a past due time and outstanding
returns; a loan exactly at its due time is not overdue. Partial returns remain
active until their last unit is returned. Overdue days use Asia/Manila calendar
date differences, not elapsed 24-hour periods. Crossing local midnight counts
as one day. HTML and CSV use the same calendar-day value; the former additional
hours column is omitted to avoid mixing elapsed time with calendar days.

The paginated report shows borrower name/username, equipment and unit issue
snapshots, issue/due dates, return dates/conditions, loan status and outstanding
counts. Historical snapshots remain accurate after inventory names change.

CSV exports contain every matching loan, independent of table pagination, with
one row per physical loan unit. Descriptive headers include loan/request IDs,
borrower, equipment/unit snapshots, issue/due times, loan and unit return status,
return date/condition, outstanding count, overdue duration and generation time.
The standard `csv` library handles quoting; UTF-8 BOM supports spreadsheet imports.
Formula/control-character prefixes in user-controlled cells are escaped as text.
Passwords, contact details, rejection reasons, return notes and repair notes are
not exported. Prefetching and chunked iteration avoid one query per loan/unit.

## Audit integration

`apps.dashboard.audit.record_event()` is called explicitly by successful business
services inside their existing atomic transaction. No request globals, model
signals or duplicate business workflows are introduced. Audit failure rolls back
the business change; validation failures and repeated/no-op operations do not
create misleading duplicate entries.

Recorded operations include:

- Category creation/update/deletion and catalog creation/update/archive/restore.
- Physical unit addition, identifier changes and Inventory retirement.
- Borrowing approval, rejection and cancellation, including borrower cancellation.
- Equipment release and each successful return submission.
- Manual or damaged-return maintenance intake, progress changes, repair and
  maintenance retirement. Automatic intake and a return are distinct events.
- Borrowing policy updates, with previous/new numeric limits.
- Account activation/deactivation through the small audited Accounts service.

Entries hold the actor FK, username snapshot, fixed action type, affected entity
type/ID, timestamp and concise action description. Actor relationships are
protected so history survives account renaming. Descriptions contain IDs, counts,
statuses and policy numbers, without copying passwords, tokens or private notes.

The Admin page searches actor usernames/names, action codes or display labels,
entity types/IDs and descriptions; filters by action and inclusive date range;
and paginates newest-first with a timestamp/ID tie-breaker. No audit edit/delete
endpoint exists. Logging starts with this integration; past actions are not
fabricated from incomplete historical metadata.

### Charles integration

Users, My Profile and Password Change are now implemented on the Charles branch.
The custom Users interface calls the Accounts activation and role services:

```python
from apps.accounts.services import set_user_active, set_user_role

set_user_active(user_id, actor=request.user, is_active=False)
set_user_role(user_id, actor=request.user, role="ADMIN")
```

The services validate current Admin permission under locks, protect self-management
and the last active Admin, change only the intended account field and write audit
entries atomically. Role changes use `USER_ROLE_CHANGED`. Raw `User.save()` or
`QuerySet.update()` calls intentionally do not infer an actor or create audit history.

## Borrowing settings

Defaults remain **3 distinct items, 3 units per item and 7 calendar days**.
The Admin can save whole-number limits in these ranges:

| Rule | Valid range |
| --- | --- |
| Distinct items per request | 1–3 (hard maximum: 3) |
| Units per item | 1–20 |
| Borrowing duration | 1–30 calendar days |

`SystemSetting` uses PK 1, with database singleton/range constraints, validation,
last-save time and responsible Admin. GET does not create or modify it. Before
an Admin first saves it, the existing `BORROWING_MAX_ITEMS`,
`BORROWING_MAX_QUANTITY` and `BORROWING_MAX_DAYS` Django settings remain the
fallback. Once saved, the database policy is authoritative. No stale global cache
or second conflicting policy store is introduced.

Borrowing services retain their public `borrowing_limits` API, now imported from
`apps.dashboard.policies`; forms and services read the same policy. A submission
or approval uses one policy snapshot for its quantity/item/date checks. New
submissions and pending approvals use current limits. Settings updates never
rewrite previously approved requests or issued loans; those can still release
and return under their recorded quantities and due dates.

## Files and migration

New/completed files:

- `apps/dashboard/models.py`, `audit.py`, `policies.py`, `services.py`, `forms.py`,
  `views.py`, `urls.py`, `tests.py` and this guide.
- `apps/dashboard/migrations/0001_initial.py`: adds `AuditLog`, `SystemSetting`,
  indexes and database constraints. Applied to the working database.
- `apps/accounts/services.py`: audited activation/deactivation hook.
- `templates/dashboard/admin/dashboard.html`, `reports.html`, `audit_logs.html`,
  `settings.html`, `_settings_confirmation.html`.
- `templates/dashboard/user_portal.html`, `admin_portal.html`, `_filters.html`,
  `_pagination.html`, `_personal_loans.html`.
- `static/css/dashboard.css`.

Necessary integrations:

- Inventory, Borrowing, Loans and Maintenance `services.py`: audit hooks.
- Borrowing `services.py` and `forms.py`: shared policy and fewer repeated reads.
- `config/urls.py`: replace Dashboard/Reports/Audit/Settings previews.
- `config/settings.py`: campus timezone Asia/Manila.
- Borrowing guide and shared Navigation/UI guides: current integration notes.

The working SQLite database was backed up before migration to
`.local-backups/db_before_miah_20261014_111739_369269.sqlite3`. All original rows
and columns across 19 existing tables were verified preserved afterward; no
foreign-key violations were found. No audit events were fabricated and no policy,
users or equipment were seeded into the working database.

## Verification and manual review

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.dashboard
.\.venv\Scripts\python.exe manage.py test
```

Results: system check passes, no missing migrations, **64 Dashboard tests pass**,
and **292 tests pass across the full project**. Tests cover permissions and data
isolation, physical-unit KPIs, zero states, date/time boundaries, chart grouping,
report/export parity, partial/full returns, formula escaping, pagination, audit
creation/search/privacy/rollback, account state hooks, database settings validation,
live policy changes and preservation of existing approved/issued terms.

Browser checks used a separate ignored SQLite preview database with synthetic
accounts and equipment. Desktop and 390px mobile Dashboard layouts, both charts,
mobile navigation, local-date overdue filtering, horizontal table scrolling,
Audit Logs, Settings confirmation/cancellation and the personal dashboard were
checked. The preview server is stopped after verification. Synthetic accounts
and their credentials do not exist in the working database.

For your own testing:

1. Sign in as Admin and open Dashboard. Compare available stock with Inventory,
   and overdue counts with Returns and Overdue. Change the chart date range.
2. Open Reports, choose either report type and a date range, then export the CSV.
   Compare loan IDs, physical units and dates with the table.
3. Perform a supported Inventory, Borrowing, Loans or Maintenance operation and
   check its action/actor/entity in Audit Logs. Search and filter its history.
4. Save different borrowing limits, submit a new Basic User request, and confirm
   the new limits apply. Existing approved requests must still release normally.
5. Open `/portal/` as a Basic User and verify only that user's records appear.

No remaining module dependency on the Charles branch. Miah's work was saved locally
as `c3731f1` and carried onto `charles` with permission. Nothing was pushed or merged
into `main`.
