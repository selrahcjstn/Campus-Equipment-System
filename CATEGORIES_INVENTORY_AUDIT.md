# Categories and Equipment Inventory — Audit and Targeted Fixes

Date: 25 October 2026, Asia/Manila. Baseline: `cf985ab`.

Both modules were inspected in place. No module was rebuilt, no category was automatically created, and no stored data was deleted, merged, reassigned or seeded. Changes are limited to inventory validation, save serialization, Admin search, a filter reset URL, tests and documentation. No CSS, sidebar, navigation labels, tables, buttons or modal components were redesigned.

## Functionality already correct

| Area | Verified implementation and evidence |
| --- | --- |
| Category normalization and uniqueness | [Category.clean](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/models.py:14) trims the name and reports duplicate names. `inventory_category_name_ci` is a database unique index on `LOWER(TRIM(name))`. Application and database tests reject case/space variants. Category modal and direct forms remain functional. |
| Category reuse and counts | Protected many-to-one `Equipment.category` allows multiple catalog items per category. [categories view](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/views.py:94) annotates the linked equipment count, including archived items, independently of category-name search. |
| Safe category deletion | [delete_category](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/services.py:76) checks references in an atomic transaction, including archived equipment. The FK uses `PROTECT`. Unused categories require the existing confirmation form; GET and an unconfirmed POST do not delete them. |
| Separate catalog and physical inventory | `Equipment` holds catalog metadata; `EquipmentUnit` holds individual asset identifiers and status. There is no editable stock-total field. Catalog edits preserve unit IDs, statuses and historical loan snapshots. |
| Asset identifier uniqueness | `EquipmentUnit.clean` trims/uppercases identifiers; both ordinary uniqueness and the `LOWER(TRIM(asset_tag))` unique index enforce uniqueness. The existing unit form accepts only the identifier, not a forged parent/status. |
| Physical status and counts | [inventory_queryset](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/services.py:30) counts physical records with distinct unit IDs. Available, Reserved, Issued (`ON_LOAN`), Maintenance and Retired remain separate. The mixed-state test verifies the sum equals total stock. Serviceable totals still include Available/Reserved/Issued only. |
| Borrowing availability | [eligible_units](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/services.py:22) requires Available status and an active catalog, and excludes active allocations, outstanding issues and active maintenance. Submission/approval recheck availability. Zero-stock, Reserved, Issued, Maintenance and Retired units cannot be allocated as available equipment. |
| Lifecycle integration | Existing tests verify approval/reservation, cancellation, issue, good/damaged returns, maintenance, repair and retirement update counts and eligibility correctly. Reserved is integral to approved requests and active allocations; it was retained. |
| Search and filters | Category-name search, physical-unit name/identifier search, category/availability/state filters, pagination and public archived-item exclusion were already present. New tests exercise combined Admin filters and reset behavior. |
| Security and transactions | Admin role and active-account checks, CSRF, protected foreign keys, transactional writes and audit logging were already present. Basic User staff/superuser flags do not grant Admin access. Archive/retirement guards prevent bypassing active borrowing, loans and maintenance. |

## Confirmed problems and fixes

Before changing application code, nine focused regression tests were run. Five failed assertions demonstrated the following gaps; the remaining tests confirmed working behavior.

### 1. Indistinguishable catalog duplicates were accepted

**Cause:** `Equipment.clean` validated only the name; `save_equipment` had no duplicate check. Another record could have the same normalized name, category and description, including duplication of an archived item.

**Fix:** [Equipment.clean](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/models.py:40) now rejects a case/space-normalized name match with the same category and exact description, excluding the current row during edits. The field-level message directs the Admin to add physical units to the existing item or distinguish a genuinely different model in its description. Same names in different categories or with different descriptions remain permitted. Archived records are included in the check, preserving their history and existing restore workflow.

[save_equipment](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/services.py:90) now locks the selected category before duplicate validation or catalog mutation. A first unchanged-value write provides SQLite writer serialization; `select_for_update` also supports row-locking databases. The existing transaction contains validation, save and audit logging. A competing duplicate save cannot pass the supported service path; the concurrency regression records exactly one success.

No global name-only unique constraint was introduced: it would block legitimate catalog variants. This is application validation plus service serialization, not a new database uniqueness guarantee against arbitrary raw SQL writes.

### 2. Model validation accepted an absent category

**Cause:** the category column deliberately remains nullable for older records. Although the Admin form and save service already required an existing category, `Equipment.full_clean()` accepted `category_id=None`.

**Fix:** model validation now also requires a category. Django FK validation rejects nonexistent IDs; forms/services retain their authoritative existing-category checks. Invalid edits preserve the original category relationship, and no category is silently created.

**Remaining schema boundary:** the nullable database column was retained. No automatic backfill, category assignment or NOT NULL migration was performed. Existing legacy rows remain readable, and code using direct `objects.create`, `save` or SQL without validation can still insert NULL. All five records in the inspected database were categorized. Replacing this compatibility policy with an unconditional database NOT NULL guarantee needs a deliberate deployment migration and review of any uncategorized records in other databases; assigning categories automatically would violate the task's data-preservation requirement.

### 3. Admin catalog search did not match physical unit identifiers

**Cause:** the catalog filter matched only `Equipment.name`, even though physical units already had searchable asset identifiers in the separate unit list.

**Fix:** [the shared catalog filter](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/views.py:26) now optionally searches unit identifiers, enabled only by the authorized Admin inventory view. Results are distinct and preserve complete physical-unit aggregates even when only one identifier matches. Search combines with category, availability and active/archived state. The accessible form label describes the supported search.

Basic User search remains name-only; private unit identifiers are not exposed through public catalog searches. No search controls or layout were redesigned.

### 4. Reset filters did not restore the default inventory listing

**Cause:** the inventory reset URL appended `?state=`, selecting all catalog items. A normal unfiltered visit defaults to active items, so the reset unexpectedly included archived entries.

**Fix:** [inventory/_filters.html](C:/Users/Allen/Desktop/Python/campus-equipment-system/templates/inventory/_filters.html:2) now uses the existing toolbar's plain reset URL. The regression follows the actual rendered reset link and compares its records to a default inventory visit. The control's styling and placement are unchanged.

## Read-only data inspection

The development SQLite file was opened with `mode=ro`. Queries found:

- Five equipment records; zero missing or invalid category references.
- No duplicate normalized category names, identical category/name/description groups, or normalized asset identifiers.
- No blank/untrimmed category names or invalid physical-unit status values.
- Six physical units: Available **0**, Reserved **0**, Issued **2**, Maintenance **2**, Retired **2**. These sum to total physical stock.
- No active allocations attached to incompatible unit statuses, outstanding issues on non-Issued units, or active maintenance on non-Maintenance units.
- The category-name and asset-identifier unique indexes exist in the inspected database.

No writes were performed by this inspection. These are point-in-time observations, not a claim about another deployment or later edits through the running app. [Inventory snapshot](C:/Users/Allen/.codex/visualizations/2026/10/10/01a1241c-8421-7511-8ebd-2cce3c853ce8/inventory-verification/inventory-snapshot.json).

## Files changed

| File | Change |
| --- | --- |
| [apps/inventory/models.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/models.py:40) | Required category in model validation; precise catalog duplicate validation |
| [apps/inventory/services.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/services.py:90) | Serialize catalog saves on category; retain atomic validation/audit behavior |
| [apps/inventory/views.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/views.py:26) | Admin-only asset identifier search |
| [apps/inventory/forms.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/forms.py:44) | Accurate accessible Admin search label |
| [templates/inventory/_filters.html](C:/Users/Allen/Desktop/Python/campus-equipment-system/templates/inventory/_filters.html:2) | Correct reset destination |
| [apps/inventory/test_integrity_audit.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/test_integrity_audit.py) | Nine targeted regression/verification tests |
| [apps/inventory/tests.py](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/tests.py:213) | Explicit stock partition assertion and concurrent duplicate catalog test |
| [apps/inventory/README.md](C:/Users/Allen/Desktop/Python/campus-equipment-system/apps/inventory/README.md) | Document validation, legacy schema boundary and filter behavior |
| [CATEGORIES_INVENTORY_AUDIT.md](C:/Users/Allen/Desktop/Python/campus-equipment-system/CATEGORIES_INVENTORY_AUDIT.md) | This report |

**Database migrations created: none.** No changes were made to borrowing, loan, maintenance, authentication or permission rules. No commit or push was requested for this task, and none was performed.

## Verification results

| Check | Result |
| --- | --- |
| Before-fix targeted tests | 9 tests; 5 reproduced failure assertions |
| Inventory suite after fixes | **83 tests passed** |
| Complete Django suite | **475 tests passed** |
| Django system checks | **No issues (0 silenced)** |
| `makemigrations --check --dry-run` | **No changes detected** |
| Git whitespace check | Passed |
| Development database fingerprint during each test run | Unchanged before/after |

All tests used separately named, freshly migrated, isolated SQLite databases outside the repository. The default database path was overridden before Django initialization, so test setup, fixtures and teardown did not use the development database. No development migration, reset or demo seed command was run.

Existing and new coverage includes category case/trim uniqueness at both validation and database levels, reuse/counts/deletion confirmation, create/edit/category preservation, identifier uniqueness, all five stock statuses, real reservation/issue/return/maintenance transitions, zero inventory, combined search/filter behavior, Admin permissions, CSRF, invalid state transitions, atomic rollback and concurrent saves.

Evidence: [before-fix log](C:/Users/Allen/.codex/visualizations/2026/10/10/01a1241c-8421-7511-8ebd-2cce3c853ce8/inventory-verification/before-tests.log), [inventory test log](C:/Users/Allen/.codex/visualizations/2026/10/10/01a1241c-8421-7511-8ebd-2cce3c853ce8/inventory-verification/targeted-tests.log), [complete test log](C:/Users/Allen/.codex/visualizations/2026/10/10/01a1241c-8421-7511-8ebd-2cce3c853ce8/inventory-verification/full-tests.log), [test isolation result](C:/Users/Allen/.codex/visualizations/2026/10/10/01a1241c-8421-7511-8ebd-2cce3c853ce8/inventory-verification/full-result.json).

## Remaining verification / decisions

1. **Legacy category schema:** an unconditional NOT NULL constraint remains a separate migration decision. No uncategorized records were found here. Review other deployment databases before enforcing it; do not auto-create, auto-assign or merge categories.
2. **Direct database writes:** imports/scripts must use validated services or explicitly call validation. Raw SQL/ORM bypasses of the application duplicate/category checks are not newly constrained by this change. Category-name uniqueness, asset uniqueness, valid status checks and FK protection retain their existing database guarantees.
3. **Inconsistent status data:** defensive availability checks intentionally exclude a unit with conflicting active allocations, loans or maintenance even if its stored status says Available. No such conflict was found here. If imported/manual data creates one later, resolve its history explicitly rather than increasing availability or automatically rewriting statuses to make totals appear consistent.
4. **Browser interaction:** automated Django HTTP tests verify the rendered forms, links, filtering and existing modal endpoints. A manual browser pass against the running deployment, particularly JavaScript filter submission and narrow-screen presentation, was not performed in this task. No CSS or JavaScript was changed.
