# Database Design & Data Dictionary

**Course:** IT 401W Web Programming and Frameworks
**System:** Campus Equipment Borrowing and Inventory System
**Framework:** Django 6.1.2 ORM / Python 3.13
**Target RDBMS:** Relational (SQLite 3.50+ development / PostgreSQL 15+ production-ready)
**Document Code:** DB-DESIGN-IT401W-2026

---

## 1. Database Architecture Overview

The database for the Campus Equipment Borrowing System is designed using normalized relational principles (Third Normal Form - 3NF) with targeted denormalization (such as immutable historical equipment snapshots on issued loans) to ensure absolute auditability and prevent historical data corruption when master catalog records change.

### Key Database Architectural Principles:
1. **Referential Protection over Cascading Deletes:** Master entities (`User`, `Category`, `Equipment`, `EquipmentUnit`) utilize `on_delete=models.PROTECT`. This guarantees that historical borrowing slips, loan units, return records, and maintenance logs cannot be orphaned or deleted when accounts or equipment items are deactivated.
2. **Database-Level Invariants (Check and Unique Constraints):** Critical business logic—such as positive borrowing quantities, due dates chronologically occurring after submission dates, valid campus roles, and single-unit status exclusivity—is enforced at the database layer via SQL constraints (`models.CheckConstraint` and conditional `models.UniqueConstraint`), preventing bypass from direct SQL or buggy application queries.
3. **Audit Trail Completeness:** All state changes are tied to immutable foreign keys pointing to the initiating actor (`auth.User`), with comprehensive action logging preserved in `dashboard_auditlog`.
4. **Soft Deletion / Archiving Pattern:** In accordance with institutional asset accounting rules, catalog categories and equipment items utilize `is_active` boolean flags rather than physical row deletions.

---

## 2. Comprehensive Data Dictionary

### Table 1: `accounts_user` (`User` Model)
Represents system actors inheriting from Django's `AbstractUser`, with roles restricted to `BASIC_USER` or `ADMIN`.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Unique internal user identifier. |
| `username` | `VARCHAR(150)` | No | — | Unique, Case-insensitive | Institutional account username for authentication. |
| `password` | `VARCHAR(128)` | No | — | PBKDF2 SHA-256 | Cryptographically salted and hashed password string. |
| `first_name` | `VARCHAR(150)` | No | `""` | Standard text | Given name of the user. |
| `last_name` | `VARCHAR(150)` | No | `""` | Standard text | Surname of the user. |
| `email` | `VARCHAR(254)` | No | `""` | Email format | Institutional or contact email address. |
| `role` | `VARCHAR(10)` | No | `'BASIC_USER'` | `CHECK(role IN ('BASIC_USER', 'ADMIN'))` | System role controlling portal access (`/portal/` vs `/manage/`). |
| `contact_number` | `VARCHAR(20)` | No | `""` | Optional string | Mobile contact number for follow-up and overdue notices. |
| `is_active` | `BOOLEAN` | No | `TRUE` | Indexed | Activation flag; deactivating prevents login and all transactions. |
| `is_staff` | `BOOLEAN` | No | `FALSE` | Django internal | Internal flag; unused by custom role authorization. |
| `is_superuser` | `BOOLEAN` | No | `FALSE` | Django internal | Superuser flag; custom role checks take precedence. |
| `date_joined` | `DATETIME` | No | `timezone.now` | Standard timestamp | Timestamp when account was registered. |
| `last_login` | `DATETIME` | Yes | `NULL` | Standard timestamp | Timestamp of the most recent successful login session. |

---

### Table 2: `inventory_category` (`Category` Model)
Classifies equipment into distinct institutional groupings (e.g., Computing, Audiovisual, Field Equipment).

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Unique internal category identifier. |
| `name` | `VARCHAR(100)` | No | — | `UniqueConstraint(Lower(Trim('name')))` | Unique case-insensitive category title. |
| `description` | `TEXT` | No | `""` | Optional text | Detailed description of the category's asset scope. |
| `is_active` | `BOOLEAN` | No | `TRUE` | `db_index=True` | Soft-deletion flag. Archived categories cannot receive new equipment. |

---

### Table 3: `inventory_equipment` (`Equipment` Model)
Defines catalog master records for lendable equipment models (e.g., "Epson Projector EB-X06").

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Unique internal equipment model identifier. |
| `name` | `VARCHAR(150)` | No | — | Cleaned text | Equipment model name. |
| `description` | `TEXT` | No | `""` | Optional text | Technical specifications, contents, and user guidelines. |
| `category_id` | `BIGINT` | Yes | `NULL` | FK to `inventory_category.id` (`on_delete=PROTECT`) | Category reference. Enforced non-null in service/form layers. |
| `is_active` | `BOOLEAN` | No | `TRUE` | `db_index=True` | Active status in the catalog. Archived items are hidden from Basic Users. |

---

### Table 4: `inventory_equipmentunit` (`EquipmentUnit` Model)
Tracks individual, barcode/tag-identified physical units for each catalog equipment item.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Unique internal physical unit identifier. |
| `equipment_id` | `BIGINT` | No | — | FK to `inventory_equipment.id` (`on_delete=PROTECT`) | Master catalog item to which this physical unit belongs. |
| `asset_tag` | `VARCHAR(80)` | No | — | `UniqueConstraint(Lower(Trim('asset_tag')))` | Physical inventory identifier or barcode (e.g., `PDF-DEMO-01-01`). |
| `status` | `VARCHAR(12)` | No | `'AVAILABLE'` | `CHECK(status IN ('AVAILABLE', 'RESERVED', 'ON_LOAN', 'MAINTENANCE', 'RETIRED'))` | Exact lifecycle status. Invariant: exactly one status per unit. |
| `condition` | `VARCHAR(7)` | Yes | `NULL` | `CHECK(condition IS NULL OR condition IN ('GOOD', 'FAIR', 'POOR', 'DAMAGED'))` | Assessed physical health rating. |
| `acquisition_date` | `DATE` | Yes | `NULL` | `acquisition_date <= CURRENT_DATE` | Date when physical unit was acquired by the institution. |

---

### Table 5: `borrowing_borrowingrequest` (`BorrowingRequest` Model)
Header record for a student or faculty member's request to borrow campus equipment.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Unique borrowing request tracking number (`#pk`). |
| `borrower_id` | `BIGINT` | No | — | FK to `accounts_user.id` (`on_delete=PROTECT`) | The Basic User who authored the borrowing request. |
| `purpose` | `TEXT` | No | — | Max length 1000 | Stated educational, project, or campus event justification. |
| `requested_at` | `DATETIME` | No | `timezone.now` | Standard timestamp | Exact submission date and time. |
| `due_at` | `DATETIME` | No | — | `CHECK(due_at > requested_at)` | Agreed return date/time. Validated against policy `max_days`. |
| `status` | `VARCHAR(10)` | No | `'PENDING'` | `CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'ISSUED', 'COMPLETED'))` | High-level request workflow state. |
| `approved_at` | `DATETIME` | Yes | `NULL` | Timestamp | Date and time when Admin reviewed and approved the request. |
| `approval_reason` | `TEXT` | No | `""` | Max length 300 | Administrative rationale or approval notes. |
| `approved_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who approved the request. |
| `rejection_reason` | `TEXT` | No | `""` | Max length 1000 | Mandatory reason provided when a request is rejected. |
| `rejected_at` | `DATETIME` | Yes | `NULL` | Timestamp | Date and time when request was rejected. |
| `rejected_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who rejected the request. |
| `cancelled_at` | `DATETIME` | Yes | `NULL` | Timestamp | Date and time when request was cancelled. |
| `cancelled_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | User or Admin who initiated cancellation. |

---

### Table 6: `borrowing_borrowingrequestitem` (`BorrowingRequestItem` Model)
Line-item detailing equipment models and quantities requested in a borrowing request header.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Line-item identifier. |
| `request_id` | `BIGINT` | No | — | FK to `borrowing_borrowingrequest.id` (`on_delete=CASCADE`) | Parent borrowing request header. |
| `equipment_id` | `BIGINT` | No | — | FK to `inventory_equipment.id` (`on_delete=PROTECT`) | Equipment model being requested. |
| `quantity` | `INTEGER` | No | — | `CHECK(quantity > 0)`, `UniqueConstraint(request, equipment)` | Requested quantity. Must be positive; models cannot duplicate in one request. |

---

### Table 7: `borrowing_allocation` (`Allocation` Model)
Atomic reservation mapping a specific physical `EquipmentUnit` to an approved `BorrowingRequestItem`.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Allocation reservation record identifier. |
| `request_item_id` | `BIGINT` | No | — | FK to `borrowing_borrowingrequestitem.id` (`on_delete=PROTECT`) | Associated requested item line. |
| `unit_id` | `BIGINT` | No | — | FK to `inventory_equipmentunit.id` (`on_delete=PROTECT`) | Specific physical unit reserved. |
| `active` | `BOOLEAN` | No | `TRUE` | `UniqueConstraint(unit) WHERE active=True` | Active reservation flag. Guarantees no unit is reserved by two requests simultaneously. |

---

### Table 8: `loans_loan` (`Loan` Model)
Issued loan document tracking physical handover of reserved units from an approved request to the borrower.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Loan identifier and borrowing slip number (`Loan #pk`). |
| `request_id` | `BIGINT` | No | — | OneToOne to `borrowing_borrowingrequest.id` (`on_delete=PROTECT`) | Approved borrowing request from which this loan originated. |
| `borrower_id` | `BIGINT` | No | — | FK to `accounts_user.id` (`on_delete=PROTECT`) | Borrower account receiving the equipment. |
| `issued_by_id` | `BIGINT` | No | — | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who verified unit tags and executed release. |
| `issued_at` | `DATETIME` | No | `timezone.now` | Standard timestamp | Physical release timestamp. |
| `due_at` | `DATETIME` | No | — | `CHECK(due_at > issued_at)` | Expected return deadline. Derived from approved request or revised by Admin. |
| `completed_at` | `DATETIME` | Yes | `NULL` | `CHECK(completed_at IS NULL OR completed_at >= issued_at)` | Timestamp when the final outstanding unit was returned. |

---

### Table 9: `loans_loanunit` (`LoanUnit` Model)
Represents an individual physical unit on loan, retaining immutable snapshot details and return audit.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Dispatched loan unit identifier. |
| `loan_id` | `BIGINT` | No | — | FK to `loans_loan.id` (`on_delete=PROTECT`) | Parent loan header. |
| `allocation_id` | `BIGINT` | No | — | OneToOne to `borrowing_allocation.id` (`on_delete=PROTECT`) | Original approved allocation reference. |
| `unit_id` | `BIGINT` | No | — | FK to `inventory_equipmentunit.id` (`on_delete=PROTECT`) | Underlying physical inventory unit. |
| `equipment_name` | `VARCHAR(150)` | No | — | Immutable string | Name of equipment at time of release (historical preservation). |
| `equipment_description`| `TEXT` | No | `""` | Immutable text | Description of equipment at time of release. |
| `asset_tag` | `VARCHAR(80)` | No | — | Immutable string | Physical asset tag recorded on the borrowing slip. |
| `returned_at` | `DATETIME` | Yes | `NULL` | Timestamp | Timestamp when this specific unit was physically received back. |
| `return_condition` | `VARCHAR(7)` | No | `""` | Choices: `'GOOD'`, `'DAMAGED'` | Physical condition upon return. Damaged units trigger automatic maintenance intake. |
| `return_notes` | `TEXT` | No | `""` | Max length 1000 | Notes regarding unit wear, battery health, or defect details. |
| `received_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who inspected the unit and processed the return. |

---

### Table 10: `maintenance_maintenancerecord` (`MaintenanceRecord` Model)
Tracks repairs, diagnostics, and decommissioning for damaged or malfunctioning physical units.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Maintenance ticket tracking identifier. |
| `unit_id` | `BIGINT` | No | — | FK to `inventory_equipmentunit.id` (`on_delete=PROTECT`) | Physical unit under maintenance. |
| `reason` | `TEXT` | No | — | Max length 1000 | Description of physical fault, damage, or required diagnostics. |
| `status` | `VARCHAR(12)` | No | `'REPORTED'` | `CHECK(status IN ('REPORTED', 'IN_PROGRESS', 'REPAIRED', 'RETIRED'))` | Current repair stage. Active statuses: `REPORTED`, `IN_PROGRESS`. |
| `reported_at` | `DATETIME` | No | `timezone.now` | Standard timestamp | Date and time maintenance record was initiated. |
| `completed_at` | `DATETIME` | Yes | `NULL` | `CHECK(completed_at IS NULL OR completed_at >= reported_at)` | Timestamp when repair was successfully completed or unit was retired. |
| `repair_notes` | `TEXT` | No | `""` | Max length 2000 | Resolution notes detailing actions taken or reasons for retirement. |
| `responsible_admin_id`| `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who opened the maintenance ticket. |
| `closed_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who certified repair or authorized asset retirement. |
| `source_return_id` | `BIGINT` | Yes | `NULL` | OneToOne to `loans_loanunit.id` (`on_delete=PROTECT`) | Populated when maintenance originates from a damaged return. |

---

### Table 11: `dashboard_systemsetting` (`SystemSetting` Model)
Singleton policy configuration establishing system-wide borrowing thresholds.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `SMALLINT` | No | `1` | Primary Key, `CHECK(pk=1)` | Fixed singleton key ensuring exactly one active institutional policy. |
| `max_items` | `SMALLINT` | No | `3` | `CHECK(max_items BETWEEN 1 AND 3)` | Maximum distinct equipment models allowed per borrowing request. |
| `max_quantity` | `SMALLINT` | No | `3` | `CHECK(max_quantity BETWEEN 1 AND 20)` | Maximum number of units allowed per equipment model in a request. |
| `max_days` | `SMALLINT` | No | `7` | `CHECK(max_days BETWEEN 1 AND 30)` | Maximum loan duration in calendar days from submission to due date. |
| `updated_at` | `DATETIME` | No | `auto_now=True` | Standard timestamp | Timestamp of last policy adjustment. |
| `updated_by_id` | `BIGINT` | Yes | `NULL` | FK to `accounts_user.id` (`on_delete=PROTECT`) | Admin who authorized the policy change. |

---

### Table 12: `dashboard_auditlog` (`AuditLog` Model)
Append-only tamper-evident audit ledger capturing all institutional operations.

| Column Name | SQL Data Type | Nullable | Default Value | Constraints / Foreign Keys | Description |
|---|---|:---:|:---:|---|---|
| `id` | `BIGINT` | No | Auto-increment | Primary Key | Immutable audit record identifier. |
| `actor_id` | `BIGINT` | No | — | FK to `accounts_user.id` (`on_delete=PROTECT`) | User or Admin who initiated the logged event. |
| `actor_username` | `VARCHAR(150)` | No | — | String snapshot | Username snapshot preserved in case of account updates. |
| `action` | `VARCHAR(32)` | No | — | `db_index=True`, `CHECK(action IN (...))` | Specific action code out of 24 enumerated system event types. |
| `entity_type` | `VARCHAR(40)` | No | — | Composite Index with `entity_id` | Target entity model name (e.g., `'loan'`, `'borrowing_request'`). |
| `entity_id` | `BIGINT` | No | — | Composite Index with `entity_type` | Primary key of the affected target record. |
| `occurred_at` | `DATETIME` | No | `timezone.now` | `db_index=True` | Accurate server timestamp when the event transpired. |
| `description` | `VARCHAR(500)` | No | — | Standard string | Human-readable explanation and operational details. |
