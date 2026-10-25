# Equipment Catalog and Inventory — Raj

Implemented on `raj`, using the completed Borrowing and Loans modules. With
explicit user approval, Clark's work was saved locally in commit `4457e67`, the
existing remote `raj` branch was checked out, and Clark's baseline was included
by fast-forward. Raj's Inventory changes are left uncommitted for testing.

## Run and test

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.inventory
.\.venv\Scripts\python.exe manage.py test apps.inventory apps.borrowing apps.loans
.\.venv\Scripts\python.exe manage.py runserver
```

Use existing active `ADMIN` and `BASIC_USER` accounts. A staff/superuser flag alone
does not grant custom Admin access. The [Loans guide](../loans/README.md) explains
local test-account role assignment. No demo records are inserted automatically;
you can create categories, equipment and physical units through the new Admin UI.

## Manual acceptance

1. As Admin, open Categories and create a category. Test editing it and submitting
   a duplicate name with different capitalization or surrounding spaces.
2. Open Equipment Inventory, create a catalog item in that category and add two
   or more physical units. New units start Available. Identifier letters are
   normalized to uppercase and surrounding spaces removed; duplicate identifiers
   are rejected across the entire inventory.
3. As Basic User, open Equipment Catalog. Search by name, filter by category or
   availability, and view public details. Internal unit identifiers, maintenance
   counts and Admin controls are not displayed. Request equipment opens Clark's
   form with an eligible item preselected.
4. Submit and approve a request. Inventory immediately counts allocated units as
   Reserved; release through Janelle's Loan Management changes them to Issued.
   Ordinary editing, retirement and catalog archiving cannot bypass those records.
5. Test Approved-request cancellation: reservations end and units become
   Available. Test Good returns: units become Available. Test Damaged returns:
   units become Maintenance and are excluded from borrowing.
6. Retire an unused Available unit. Its record remains, and it stays unavailable.
   Ordinary identifier editing cannot restore a Retired unit's status.
7. Archive an item once its reservations and issued units are resolved. Its units,
   requests, loans and history remain; it disappears from the public catalog and
   cannot be newly requested or approved. Restore it explicitly to make the
   catalog item active again, retaining every physical unit's status.
8. Try deleting a category used by active or archived equipment: deletion is
   blocked. An unreferenced category can be deleted after confirmation.
9. Review global physical-unit search/filtering, counts for all statuses, empty
   states and pagination. Check that Basic Users cannot access any Admin endpoints.

## Domain models and migration

The existing `Equipment` model is the catalog item described as `CatalogItem` in
the task. It is extended, not renamed or duplicated. Borrowing's Equipment FKs,
allocations, and Loans' EquipmentUnit relationships keep their original IDs.

Migration `inventory.0002_category_equipment_is_active_and_more`:

- Adds `Category` with name, description and a database constraint rejecting
  names duplicated by case or surrounding spaces.
- Adds nullable `Equipment.category` with protected deletion and
  `Equipment.is_active`, defaulting to True for existing catalog items.
- Adds a case/trim insensitive identifier constraint in addition to the existing
  unique asset-tag constraint. New/explicitly edited tags are normalized; the
  migration does not rewrite historical identifiers.

Legacy uncategorized rows remain readable and are shown as Uncategorized. Model
validation, service saves and Admin create/edit forms require an existing category;
raw ORM writes still require callers to invoke validation. The nullable legacy
database field is retained without assigning categories or migrating stored data.
Existing initial migrations and all stored unit status values are preserved.

Catalog validation rejects an identical category/name/description combination,
including case/space variations of the name and matches against archived items.
Different categories or descriptions can distinguish legitimate models. Add more
physical units to an existing identical catalog item instead of duplicating it.
Service saves serialize on the category before validating, preventing competing
requests from creating the same catalog metadata. Category name and asset-tag
uniqueness additionally retain their existing database constraints.

Admin inventory search matches equipment names and physical unit identifiers,
while public catalog search stays name-only. Category, availability and state
filters combine with the search, and Reset filters returns to the default active
listing. Physical-unit search and both portals' existing layouts are preserved.

## A2 category lifecycle and unit metadata

- Categories have an Active/Archived state, shown on the existing Admin list.
  Archive and Restore reuse the confirmed action pages and record actor/time in
  category audit events. Name uniqueness and referenced-category deletion
  protection include archived categories.
- New equipment and category reassignment require an active category. Existing
  equipment can retain its own archived category during metadata edits. Category
  archiving never cascades into equipment activity, unit statuses, reservations
  or loans; it controls new assignments only.
- Units record condition (Good, Fair, Poor or Damaged) and acquisition date in the
  existing create/edit forms and shared management table. Unknown values are
  nullable and shown as **Not recorded**; no condition/date is inferred or seeded.
  Acquisition dates cannot be in the future. These are inventory metadata,
  separate from the existing status and historical return-condition snapshots.
  Changing condition alone does not change eligibility or open maintenance.
- Ordinary unit edits retain their Available/Retired and idle-record guards.
  Existing service callers that edit only asset tags preserve recorded metadata;
  explicit blank metadata fields clear a previously recorded value.
- The global physical-unit listing combines category, equipment, status and
  identifier/name search. Archived categories remain filterable for Admin history.
  Reset clears these filters, and pagination preserves them. The per-equipment
  unit table already fixes its category/item and retains its original filters.

Two additive migrations are required: `inventory.0003_category_archiving` sets
existing categories Active; `inventory.0004_unit_condition_and_acquisition_date`
adds nullable metadata and a valid-condition constraint. IDs, category relations,
unit statuses and existing histories remain unchanged. No fabricated acquisition
dates or default physical conditions are assigned. The legacy nullable category
FK is retained. Apply the migrations before starting this updated application:

```powershell
.\.venv\Scripts\python.exe manage.py migrate inventory
```

## Availability and integration

- Unit status values stay `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`,
  `RETIRED`. Inventory displays `ON_LOAN` as Issued to match the task terminology.
- `inventory_queryset()` aggregates actual units into total, available, reserved,
  issued, maintenance and retired counts. There is no editable quantity field.
  Available counts also exclude active allocations and outstanding LoanUnit
  records, protecting against inconsistent stored status values.
- `eligible_units()` additionally excludes archived catalog items. Borrowing's
  existing `available_units()` and `catalog_queryset()` APIs now consume these
  shared inventory queries, retaining their callers and workflow interfaces.
- Borrowing submission and approval coordinate with the catalog row used by
  archiving. An archived item is rejected even if its request was created earlier
  or the browser showed old availability. Approval/cancellation logic, borrowing
  limits, Loans issuance and returns are otherwise preserved.
- Archive checks reject both Reserved/Issued physical statuses and actual active
  allocation/outstanding-loan records. The catalog state update and validation
  are atomic; a failed archive rolls back entirely.
- Unit editing is restricted to unallocated Available or Retired units and only
  changes their identifier. Status and parent catalog item are not accepted as
  posted edit fields. Retirement is Available → Retired only, with the same
  active-record guards. New units can only be added to an active catalog item.
- Catalog metadata edits do not change unit statuses or restore archived items.
  Restoration is a separate confirmed action. Loan snapshots preserve names,
  descriptions and tags from issuance when current inventory metadata changes.
- No catalog-item or physical-unit deletion endpoint is provided; archive and
  retirement preserve historical records. Existing protected FKs also prevent
  deleting equipment or units referenced by borrowing and loan records.
- Mutations require active Admin role, POST and CSRF. Category deletion,
  archiving, restoration and retirement require backend-validated confirmation;
  native dialogs enhance these forms without replacing server checks.
- Critical operations use atomic transactions, ordered row locks and conditional
  writes for SQLite. Database conflicts return a reload/retry error. The
  concurrency tests run against the project's SQLite test database.

## Maintenance boundary

Francis's Maintenance app still contains placeholders. Inventory reports its
physical status and excludes Maintenance units from borrowing, but it does not
invent repair records or a Maintenance → Available transition. Those operations
must be implemented through Francis's validated workflow. Damaged returns already
enter Maintenance through the completed Loans service. This is the remaining
integration requirement; it does not block the Inventory screens or safeguards.

## Routes

| URL | Name | Access |
| --- | --- | --- |
| `/portal/equipment/` | `equipment_catalog` | Basic User active catalog/search/filter |
| `/portal/equipment/<id>/` | `equipment_detail` | Basic User public details |
| `/manage/categories/` | `equipment_categories` | Admin category list |
| `/manage/categories/new/` | `create_category` | Admin create |
| `/manage/categories/<id>/edit/` | `edit_category` | Admin edit |
| `/manage/categories/<id>/delete/` | `delete_category` | Admin confirmation/delete if unreferenced |
| `/manage/equipment/` | `equipment_inventory` | Admin catalog/counts/search/filter |
| `/manage/equipment/new/` | `create_equipment` | Admin catalog create |
| `/manage/equipment/<id>/` | `admin_equipment_detail` | Admin per-item units/counts |
| `/manage/equipment/<id>/edit/` | `edit_equipment` | Admin metadata edit |
| `/manage/equipment/<id>/archive/` | `archive_equipment` | Admin archive confirmation |
| `/manage/equipment/<id>/restore/` | `restore_equipment` | Admin restoration confirmation |
| `/manage/equipment/units/` | `equipment_units` | Admin global unit search/filter |
| `/manage/equipment/<id>/units/new/` | `add_equipment_unit` | Admin new unit |
| `/manage/equipment/units/<id>/edit/` | `edit_equipment_unit` | Admin identifier edit if idle |
| `/manage/equipment/units/<id>/retire/` | `retire_equipment_unit` | Admin retirement confirmation |

## Changed files

- Inventory: `models.py`, `forms.py`, `services.py`, `views.py`, `urls.py`,
  `tests.py`, this guide and `migrations/0002_category_equipment_is_active_and_more.py`.
- Integration only: `apps/borrowing/services.py` (shared eligibility/archive
  coordination), `apps/borrowing/views.py` (validated catalog preselection),
  `templates/borrowing/new_request.html` (preselection messages).
- Navigation: `config/urls.py` replaces only the three Inventory previews.
- Basic templates: `templates/inventory/catalog.html`, `detail.html`.
- Admin templates: `categories.html`, `equipment_list.html`, `equipment_detail.html`,
  `units.html`, `form.html`, `unit_form.html`, `action.html` under
  `templates/inventory/admin/`, plus counts/unit-table/confirmation partials.
- Shared module partials: `templates/inventory/_filters.html`, `_pagination.html`.
- Assets: `static/css/inventory.css`, `static/js/inventory.js`.

Inventory tests cover every requested acceptance area, privacy, forged inputs,
history protection, metadata normalization, and archive/approval, retirement/
approval and duplicate-unit creation races. The full Borrowing and Loans suites
are rerun for integration. Existing database data is backed up and verified before
and after the additive migration.

## Verified results — October 14, 2026

- Django system check passed with no issues.
- Migration dry run reported no missing migrations.
- **52 Inventory tests passed.** The combined Inventory, Borrowing and Loans
  run passed **168 tests** (52 Inventory, 57 Borrowing, 59 Loans), including the
  concurrency and cross-module integration tests.
- The new Inventory migration was applied to the local database after a backup
  and identifier-uniqueness preflight. All original data was verified unchanged;
  the new table, fields and constraint were verified present, with zero SQLite
  foreign-key violations. No fixtures were seeded in the local database.
- Clark's baseline is saved in local commit `4457e67`; Raj's implementation
  remains uncommitted. Neither was pushed, and `main` was not changed.
