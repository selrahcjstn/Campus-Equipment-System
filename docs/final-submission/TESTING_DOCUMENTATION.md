# Testing Documentation & Verification Report

**Course:** IT 401W Web Programming and Frameworks
**System:** Campus Equipment Borrowing and Inventory System
**Test Framework:** Django Test Suite (`django.test.TestCase` / `unittest`)
**Execution Environment:** Python 3.13.7, Django 6.1.2, Windows 11
**Verified Test Total:** **524 Tests Passing (0 Failures, 0 Errors)**
**Document Code:** TEST-IT401W-2026

---

## 1. Quality Assurance Strategy & Test Methodology

The testing architecture for the Campus Equipment Borrowing and Inventory System was developed using a multi-tiered verification methodology:

1. **Unit Testing:** Validating individual model methods, form clean routines, custom template tags, and policy validators in complete isolation.
2. **Service & Transaction Testing:** Verifying multi-table state changes wrapped in `@transaction.atomic`, confirming that partial failures leave zero residual records.
3. **HTTP Client & Integration Testing:** Simulating end-to-end browser requests across both Basic User (`/portal/`) and Admin (`/manage/`) interfaces, including CSRF token validation, session cookies, and pagination controls.
4. **Role-Based Access Control (RBAC) Security Probes:** Explicitly attempting unauthorized actions (e.g., Basic Users invoking admin endpoints, deactivated accounts accessing active sessions, self-promotion attempts via manipulated POST bodies).
5. **Concurrency & Race Condition Trials:** Multi-threaded stress testing of scarce inventory contention (competing approvals for the last remaining unit).
6. **Database Integrity & Migration Consistency:** Applying forward migrations from scratch on empty databases and running foreign key consistency checks (`PRAGMA foreign_key_check`).

---

## 2. Summary of Automated Test Execution

The integrated test suite was executed across all 6 applications and the local tooling tests using Django's test runner on October 25, 2026.

```powershell
.\.venv\Scripts\python.exe manage.py test
```

### Execution Outcome:
- **Total Tests Discovered:** 524
- **Total Tests Passed:** 524
- **Failures:** 0
- **Errors:** 0
- **Skipped:** 0
- **Execution Duration:** 54.474 seconds
- **Database Status:** Isolated SQLite in-memory/temporary test database destroyed cleanly.

---

## 3. Comprehensive Breakdown by Application Module

### 3.1 `apps.accounts` (80 Tests)
Focuses on authentication, password security, session validity, profile management, and admin user administration.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `EnvironmentConfigurationTests` | 2 | Verifies development environment safety, settings invariants, and configuration checks. |
| `RoleConstraintTests` | 1 | Verifies database-level check constraint `accounts_valid_campus_role`. |
| `RoleMigrationSafetyTests` | 1 | Tests backward/forward migration consistency for custom user role definitions. |
| `TableDateTimeTests` | 3 | Verifies timezone-aware formatting (`Asia/Manila`) on user activity timestamps. |
| `StylesheetCacheTests` | 3 | Verifies cache-busting version query parameters on static assets. |
| `AccountManagementTests` | 16 | Admin listing, search, pagination, activation, and deactivation workflows. |
| `AccountServiceSecurityTests` | 14 | Verifies deactivated user eviction, protection against privilege escalation, and owner scoping. |
| `AuthenticationTests` | 14 | Login, logout, registration form validation, password strength, and role redirection. |
| `ConcurrentAccountTests` | 3 | Tests simultaneous account updates and deactivations. |
| `LandingPageTests` | 5 | Public landing page navigation, session redirection, and role routing. |
| `PaginationComponentTests` | 4 | Verifies 10-record pagination, query string preservation, and page boundaries. |
| `ProfileTests` | 14 | Self-service profile updates, password change, and immutability of role/active status. |

---

### 3.2 `apps.borrowing` (111 Tests)
Focuses on borrowing request submission, multi-item validation, hard limits, admin approval, unit reservation, and cancellations.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `ApprovalMigrationSafetyTests` | 1 | Schema consistency for approval reason and timestamp columns. |
| `RequestComplianceTests` | 7 | Verifies full compliance with Part 2 (A3) and Part 3 (U3) requirements. |
| `DueDateRevisionConcurrencyTests` | 3 | Tests simultaneous administrative revisions of agreed return dates. |
| `DueDateRevisionTests` | 13 | Verifies recorded administrative due date adjustments before physical issue. |
| `BorrowingHardItemLimitTests` | 5 | Verifies strict enforcement of the 3-item ceiling and positive quantity validation. |
| `BorrowingPageTests` | 21 | Queue filtering (status, search), detail views, and action confirmations. |
| `BorrowingServiceTests` | 30 | Atomic request submission, approval unit assignment, rejection, and cancellation. |
| `ConcurrentBorrowingTests` | 3 | Simultaneous approval requests and reservation locking. |
| `DemoBorrowingTests` | 3 | Repeatable demo seeding and state initialization. |
| `DynamicEquipmentFormTests` | 9 | FormSet dynamic row validation and duplicate catalog item prevention. |
| `EquipmentPreselectionFlowTests` | 7 | Catalog pre-selection into new request form navigation. |
| `RequestSummaryPresentationTests` | 4 | Badge formatting, workflow labels, and empty states. |
| `TwoStepBorrowingPageTests` | 5 | Multi-step request interface validation and CSRF protection. |

---

### 3.3 `apps.dashboard` (76 Tests)
Focuses on live metric derivation, executive charts, CSV reporting, audit logging, and borrowing policy management.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `DashboardComplianceTests` | 5 | PDF compliance checks for live cards, monthly trends, and category usage. |
| `BorrowingItemLimitMigrationTests` | 4 | Database migrations for singleton policy settings (`SystemSetting`). |
| `AuditIntegrationTests` | 11 | End-to-end event logging across all 24 system operations. |
| `AuditViewTests` | 6 | Admin-only searchable audit trail view, filters, and pagination. |
| `DashboardAccessTests` | 7 | RBAC access controls preventing Basic Users from entering `/manage/`. |
| `PersonalDashboardTests` | 4 | Basic User portal statistics (active requests, personal loans). |
| `ReportsTests` | 12 | Date-filtered loan reports, overdue calculations, and CSV export streaming. |
| `SettingsTests` | 17 | Borrowing limits configuration (`max_items`, `max_quantity`, `max_days`). |
| `StatisticsAndChartsTests` | 10 | Dynamic aggregation queries verifying zero static/hardcoded demonstration figures. |

---

### 3.4 `apps.inventory` (108 Tests)
Focuses on categories, catalog masters, physical unit tracking, asset tags, archiving, and inventory reconciliation.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `CategoryArchiveTests` | 7 | Category soft-deletion, archiving behavior, and equipment preservation. |
| `InventoryMigrationSafetyTests` | 1 | Forward/backward migration validation for physical unit metadata. |
| `PhysicalUnitCategoryFilterTests` | 5 | Admin multi-attribute filtering (category, catalog model, status). |
| `PhysicalUnitMetadataTests` | 7 | Asset tag formatting, physical condition ratings, and acquisition dates. |
| `ProjectDemoTests` | 5 | Automated verification of `seed_project_demo` management command. |
| `InventoryIntegrityAuditTests` | 9 | Referential integrity protection (`PROTECT`) and duplicate prevention. |
| `CategoryModalTests` | 5 | Admin modal dialogs for category creation and modification. |
| `ConcurrentInventoryTests` | 4 | Simultaneous asset tag creation and category edits. |
| `InventoryPageTests` | 26 | Public catalog browsing, pagination, search, and admin management pages. |
| `InventoryServiceTests` | 29 | Stock calculations, serviceable vs retired units, and master archiving. |
| `PhysicalUnitModalTests` | 6 | Unit registration modal workflows and validation alerts. |
| `ServiceableInventoryTests` | 4 | Verifies 5-state inventory reconciliation against physical stock. |

---

### 3.5 `apps.loans` (67 Tests)
Focuses on equipment release, printable slips, partial returns, return condition grading, and overdue tracking.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `CalendarOverdueTests` | 5 | Boundary tests for calendar date differences in `Asia/Manila` timezone. |
| `ConcurrentLoanTests` | 2 | Competing releases and duplicate issue prevention. |
| `DemoFixtureTests` | 3 | Demo loan seeding and state verification. |
| `FoundationTests` | 4 | Basic model setup, string representations, and foreign key rules. |
| `LoanPageTests` | 22 | Loan management queue, release verification, and return inspection views. |
| `LoanServiceTests` | 28 | Release execution, unit dispatch, partial returns, and loan completion. |
| `LoanSummaryPresentationTests` | 3 | Printable borrowing slip rendering and equipment summary tables. |

---

### 3.6 `apps.maintenance` (75 Tests)
Focuses on repair intake, damaged return quarantine, diagnostic tracking, unit restoration, and asset retirement.

| Test Class | Test Count | Scope & Coverage |
|---|:---:|---|
| `MaintenanceBorrowingGuardTests` | 1 | Prevents allocated, reserved, or issued units from entering maintenance. |
| `MaintenanceQuickActionTests` | 11 | One-click maintenance transitions (Start Repair, Complete, Retire). |
| `ConcurrentMaintenanceTests` | 4 | Simultaneous maintenance ticket updates on the same physical unit. |
| `ExistingMaintenanceMigrationTests` | 3 | Data migration safety for historical maintenance records. |
| `MaintenanceIntegrationTests` | 12 | End-to-end integration: Damaged return &rarr; Quarantine &rarr; Repair &rarr; Available. |
| `MaintenanceServiceTests` | 23 | Ticket creation, diagnostic notes, admin attribution, and state changes. |
| `MaintenanceSummaryPresentationTests` | 2 | Maintenance badge styling and ticket history summaries. |
| `MaintenanceViewTests` | 19 | Admin maintenance dashboard, filtering, detail views, and resolve dialogs. |

---

### 3.7 Local tooling (7 Tests)

`DemoConfigurationTests` (3) validates dedicated database configuration, saved
credentials and safe refusal of existing/unrelated databases.
`SubmissionPackageTests` (4) validates source exclusions, archive/manifest
integrity, secret-leak rejection and safe section/group filename values.

## 4. Concurrency Verification: The Last-Unit Allocation Trial

In direct fulfillment of Part 5, Business Rule 3 (BR3) of the IT 401W specifications:
> *"Demonstrate two competing approvals for the last unit: only one succeeds."*

### Empirical Trial Evidence:
- **Experiment Setup:** Two distinct pending borrowing requests competing simultaneously for the final single available unit of an equipment model.
- **Trial Repetitions:** **30 independent, automated, simultaneous trials**.
- **Results:**
  - Exactly **30 out of 30** trials resulted in exactly **one approved request** and **one clean rejection**.
  - Winner received full reservation with active allocation.
  - Loser raised `django.core.exceptions.ValidationError` ("Selected units are no longer available") with zero residual allocations.
  - Zero database lock timeouts, zero deadlocks, and zero orphaned records.

---

## 5. Security & Boundary Verification Matrices

| Test Scenario | Input / Action | Expected Result | Verified Result |
|---|---|---|:---:|
| **Basic User Self-Promotion** | Form POST with injected `role=ADMIN` | Role forced to `BASIC_USER`; DB constraint rejects invalid role | **PASS** |
| **Admin Route Direct Access** | Unauthenticated or Basic User GET to `/manage/` | 302 Redirect to `/login/` or 403 Forbidden | **PASS** |
| **Cross-User Data Leakage** | Basic User GET to `/portal/requests/{other_user_id}/` | 404 Not Found (Owner-scoped QuerySet) | **PASS** |
| **Excess Items in Request** | FormSet submitting 4 distinct catalog items | Form validation error; transaction aborted | **PASS** |
| **Past Due Date Submission** | Due date earlier than current server time | Form validation error (`due_at > requested_at`) | **PASS** |
| **Expired Approved Request** | Admin attempts to release request past due date | Handover validation blocks issue; requires date revision | **PASS** |
| **Damaged Unit Return** | Return recorded with `condition=DAMAGED` | Unit moves to `MAINTENANCE`; ticket auto-created | **PASS** |
| **Duplicate Return Attempt** | Attempting to return already returned unit | View disables returned units; service raises error | **PASS** |

## 6. Latest extracted-package verification

A fresh virtual environment installed the pinned dependencies. The source ZIP
was extracted into a separate directory, and its demo wrapper independently
migrated, seeded and verified all minimum counts and required scenarios.
The final suite passed 524 tests in 54.474 seconds. Standard Django checks,
migration consistency and dependency checks passed. The normal development
database byte fingerprint was unchanged.

The first fresh run exposed an existing concurrency-test assumption: SQLite
may reject cancellation/issuance on writer contention while a revision succeeds.
The tests now distinguish lock conflicts from validation failures, assert no
partial state/audit writes, retry the intended action, and reject later revisions.
Unexpected database exceptions remain failures. No production service or rule was
changed. Thirty additional repeated revision/issue/cancellation race tests passed.

Representative browser checks covered both portals, landing/registration,
mobile navigation and focus, modal validation/logout, catalog preselection,
three-item selection, backward-navigation preservation, and tablet loan/table
layout. This is not an exhaustive assistive-technology or physical print test.
