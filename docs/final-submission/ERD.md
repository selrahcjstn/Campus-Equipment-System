# Entity Relationship Diagram (ERD)

**Project:** Campus Equipment Borrowing and Inventory System
**Framework:** Django 6.1.2 / Python 3.13
**Database:** Relational Database (SQLite for development / PostgreSQL ready)
**Document Code:** ERD-IT401W-2026

---

## 1. Mermaid Entity Relationship Diagram

The diagram below maps all relational entities, primary keys (PK), foreign keys (FK), cardinalities, and attributes based on the verified Django ORM models and database migrations.

```mermaid
erDiagram
    USER ||--o{ BORROWING_REQUEST : "submits (as borrower)"
    USER ||--o{ BORROWING_REQUEST : "approves (as approved_by)"
    USER ||--o{ BORROWING_REQUEST : "rejects (as rejected_by)"
    USER ||--o{ BORROWING_REQUEST : "cancels (as cancelled_by)"
    USER ||--o{ LOAN : "borrows (as borrower)"
    USER ||--o{ LOAN : "issues (as issued_by)"
    USER ||--o{ LOAN_UNIT : "receives return (as received_by)"
    USER ||--o{ MAINTENANCE_RECORD : "reports (as responsible_admin)"
    USER ||--o{ MAINTENANCE_RECORD : "resolves (as closed_by)"
    USER ||--o{ SYSTEM_SETTING : "configures (as updated_by)"
    USER ||--o{ AUDIT_LOG : "triggers (as actor)"

    CATEGORY ||--o{ EQUIPMENT : "classifies"
    EQUIPMENT ||--o{ EQUIPMENT_UNIT : "tracks physical copies"
    EQUIPMENT ||--o{ BORROWING_REQUEST_ITEM : "specifies equipment type"

    BORROWING_REQUEST ||--|{ BORROWING_REQUEST_ITEM : "contains items"
    BORROWING_REQUEST ||--o| LOAN : "originates"

    BORROWING_REQUEST_ITEM ||--o{ ALLOCATION : "reserves units"

    EQUIPMENT_UNIT ||--o{ ALLOCATION : "assigned to"
    EQUIPMENT_UNIT ||--o{ LOAN_UNIT : "dispatched as"
    EQUIPMENT_UNIT ||--o{ MAINTENANCE_RECORD : "undergoes maintenance"

    ALLOCATION ||--o| LOAN_UNIT : "materialized into"
    LOAN ||--|{ LOAN_UNIT : "comprises units"

    LOAN_UNIT ||--o| MAINTENANCE_RECORD : "triggers repair on damage"

    USER {
        bigint id PK
        string username "Unique"
        string password "PBKDF2 SHA256 hashed"
        string first_name
        string last_name
        string email
        string role "BASIC_USER | ADMIN"
        string contact_number
        boolean is_active
        datetime date_joined
        datetime last_login
    }

    CATEGORY {
        bigint id PK
        string name "Unique (Case-Insensitive)"
        text description
        boolean is_active "Indexed"
    }

    EQUIPMENT {
        bigint id PK
        string name
        text description
        bigint category_id FK "PROTECT"
        boolean is_active "Indexed"
    }

    EQUIPMENT_UNIT {
        bigint id PK
        bigint equipment_id FK "PROTECT"
        string asset_tag "Unique (Case-Insensitive)"
        string status "AVAILABLE | RESERVED | ON_LOAN | MAINTENANCE | RETIRED"
        string condition "GOOD | FAIR | POOR | DAMAGED"
        date acquisition_date "Cannot be future"
    }

    BORROWING_REQUEST {
        bigint id PK
        bigint borrower_id FK "User, PROTECT"
        text purpose
        datetime requested_at
        datetime due_at "due_at > requested_at"
        string status "PENDING | APPROVED | REJECTED | CANCELLED | ISSUED | COMPLETED"
        datetime approved_at "Nullable"
        text approval_reason
        bigint approved_by_id FK "User, PROTECT, Nullable"
        datetime rejected_at "Nullable"
        text rejection_reason
        bigint rejected_by_id FK "User, PROTECT, Nullable"
        datetime cancelled_at "Nullable"
        bigint cancelled_by_id FK "User, PROTECT, Nullable"
    }

    BORROWING_REQUEST_ITEM {
        bigint id PK
        bigint request_id FK "BorrowingRequest, CASCADE"
        bigint equipment_id FK "Equipment, PROTECT"
        integer quantity "quantity > 0, Unique(request, equipment)"
    }

    ALLOCATION {
        bigint id PK
        bigint request_item_id FK "BorrowingRequestItem, PROTECT"
        bigint unit_id FK "EquipmentUnit, PROTECT"
        boolean active "Unique(unit) WHERE active=True"
    }

    LOAN {
        bigint id PK
        bigint request_id FK "BorrowingRequest, OneToOne, PROTECT"
        bigint borrower_id FK "User, PROTECT"
        bigint issued_by_id FK "User, PROTECT"
        datetime issued_at
        datetime due_at "due_at > issued_at"
        datetime completed_at "Nullable, completed_at >= issued_at"
    }

    LOAN_UNIT {
        bigint id PK
        bigint loan_id FK "Loan, PROTECT"
        bigint allocation_id FK "Allocation, OneToOne, PROTECT"
        bigint unit_id FK "EquipmentUnit, PROTECT"
        string equipment_name "Snapshot"
        text equipment_description "Snapshot"
        string asset_tag "Snapshot"
        datetime returned_at "Nullable"
        string return_condition "GOOD | DAMAGED, Nullable"
        text return_notes
        bigint received_by_id FK "User, PROTECT, Nullable"
    }

    MAINTENANCE_RECORD {
        bigint id PK
        bigint unit_id FK "EquipmentUnit, PROTECT"
        text reason "Reported defect description"
        string status "REPORTED | IN_PROGRESS | REPAIRED | RETIRED"
        datetime reported_at
        datetime completed_at "Nullable, completed_at >= reported_at"
        text repair_notes
        bigint responsible_admin_id FK "User, PROTECT, Nullable"
        bigint closed_by_id FK "User, PROTECT, Nullable"
        bigint source_return_id FK "LoanUnit, OneToOne, PROTECT, Nullable"
    }

    SYSTEM_SETTING {
        smallint id PK "Fixed pk=1"
        smallint max_items "Range: 1 to 3"
        smallint max_quantity "Range: 1 to 20"
        smallint max_days "Range: 1 to 30"
        datetime updated_at
        bigint updated_by_id FK "User, PROTECT, Nullable"
    }

    AUDIT_LOG {
        bigint id PK
        bigint actor_id FK "User, PROTECT"
        string actor_username
        string action "Indexed, Whitelist of 24 System Actions"
        string entity_type "Indexed Composite with entity_id"
        bigint entity_id
        datetime occurred_at "Indexed"
        string description
    }
```

---

## 2. Cardinalities and Relational Logic

| Parent Entity | Relationship | Child Entity | Cardinality | Relational Rule / Deletion Behavior |
|---|:---:|---|:---:|---|
| `User` | 1 to Many | `BorrowingRequest` | $1 : N$ | `on_delete=models.PROTECT`. User accounts cannot be hard-deleted if borrowing history exists. |
| `User` | 1 to Many | `Loan` | $1 : N$ | `on_delete=models.PROTECT`. Protects historical auditability of issued loans. |
| `User` | 1 to Many | `AuditLog` | $1 : N$ | `on_delete=models.PROTECT`. Preserves immutable chain of custody for all audited operations. |
| `Category` | 1 to Many | `Equipment` | $1 : N$ | `on_delete=models.PROTECT`. Categories cannot be deleted if catalog equipment exists; archiving is enforced. |
| `Equipment` | 1 to Many | `EquipmentUnit` | $1 : N$ | `on_delete=models.PROTECT`. Catalog models cannot be removed if physical copies are registered. |
| `BorrowingRequest` | 1 to Many | `BorrowingRequestItem` | $1 : N$ | `on_delete=models.CASCADE`. Items are tightly coupled to the lifecycle of the request header. |
| `BorrowingRequest` | 1 to 1 | `Loan` | $1 : 1$ | `OneToOneField(on_delete=models.PROTECT)`. Exactly one issued loan can originate from an approved request. |
| `BorrowingRequestItem` | 1 to Many | `Allocation` | $1 : N$ | `on_delete=models.PROTECT`. Allocations tie specific physical units to requested item quantities. |
| `EquipmentUnit` | 1 to Many | `Allocation` | $1 : N$ | Filtered unique constraint: exactly **one active allocation** per physical unit at any instant. |
| `Loan` | 1 to Many | `LoanUnit` | $1 : N$ | `on_delete=models.PROTECT`. Every loan comprises 1 to $N$ individual unit dispatch records. |
| `Allocation` | 1 to 1 | `LoanUnit` | $1 : 1$ | `OneToOneField(on_delete=models.PROTECT)`. Links an approved reservation directly to its loan record. |
| `LoanUnit` | 1 to 1 | `MaintenanceRecord` | $0..1 : 1$ | `OneToOneField(null=True, blank=True)`. Intake link automatically populated when a unit is returned damaged. |
| `EquipmentUnit` | 1 to Many | `MaintenanceRecord` | $1 : N$ | Filtered unique constraint: at most **one active maintenance record** (`REPORTED` or `IN_PROGRESS`) per unit. |

---

## 3. Database Integrity & Concurrency Constraints

1. **Physical Unit Single-State Invariant:**
   Every physical unit belongs strictly to one state at any point in time: `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`, or `RETIRED`.
2. **Atomic All-or-Nothing Unit Reservation:**
   During approval, `apps.borrowing.services.approve_request` validates that all requested quantities can be fulfilled simultaneously from available units. If even one unit cannot be reserved, the transaction aborts with zero side-effects.
3. **No Dual Active Allocations:**
   The database enforces `UniqueConstraint(fields=["unit"], condition=models.Q(active=True), name="borrowing_one_active_allocation")`.
4. **No Dual Active Issue:**
   The database enforces `UniqueConstraint(fields=["unit"], condition=models.Q(returned_at__isnull=True), name="loan_one_active_issue_per_unit")`.
5. **No Dual Active Maintenance:**
   The database enforces `UniqueConstraint(fields=["unit"], condition=models.Q(status__in=["REPORTED", "IN_PROGRESS"]), name="maintenance_one_active_per_unit")`.
6. **Unique Catalog Item Per Request:**
   The database enforces `UniqueConstraint(fields=["request", "equipment"], name="borrowing_one_equipment_per_request")`.
