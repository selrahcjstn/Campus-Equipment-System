# System Workflows Documentation

**Course:** IT 401W Web Programming and Frameworks
**System:** Campus Equipment Borrowing and Inventory System
**Document Code:** WORKFLOWS-IT401W-2026

---

## 1. System Workflow State Machines

### 1.1 Borrowing Lifecycle State Machine

The borrowing lifecycle governs the progression of requests from initial student submission to complete physical unit return.

```mermaid
stateDiagram-v2
    [*] --> PENDING: Student submits request (1-3 items)
    PENDING --> REJECTED: Admin rejects with mandatory reason
    PENDING --> CANCELLED: Student or Admin cancels before approval
    PENDING --> APPROVED: Admin approves and allocates exact physical units

    APPROVED --> CANCELLED: Student or Admin cancels (frees reserved units)
    APPROVED --> ISSUED: Admin releases units at physical handover counter

    ISSUED --> PARTIALLY_RETURNED: Student returns some units (damaged units to Maintenance)
    PARTIALLY_RETURNED --> PARTIALLY_RETURNED: Additional units returned
    PARTIALLY_RETURNED --> COMPLETED: Final outstanding unit returned
    ISSUED --> COMPLETED: All units returned simultaneously

    REJECTED --> [*]
    CANCELLED --> [*]
    COMPLETED --> [*]

    note right of ISSUED
        Overdue is a dynamically calculated status
        when current date > due_at and outstanding units > 0.
        It is not a stored database status enum.
    end note
```

### 1.2 Physical Unit Inventory State Machine

Each physical `EquipmentUnit` maintains an invariant of exactly one mutually exclusive status at any instant.

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE: Admin registers asset tag in catalog
    AVAILABLE --> RESERVED: Admin approves a borrowing request
    RESERVED --> AVAILABLE: Approved request cancelled or rejected
    RESERVED --> ON_LOAN: Admin issues equipment to borrower
    ON_LOAN --> AVAILABLE: Unit returned in Good condition
    ON_LOAN --> MAINTENANCE: Unit returned Damaged
    AVAILABLE --> MAINTENANCE: Admin manually reports fault/defect
    MAINTENANCE --> AVAILABLE: Repair completed successfully
    MAINTENANCE --> RETIRED: Defect irreparable / unit decommissioned
    AVAILABLE --> RETIRED: Admin decommissions obsolete available unit
    RETIRED --> [*]
```

---

## 2. Core Functional Workflows

### 2.1 User Registration, Authentication & Role Redirection

```mermaid
sequenceDiagram
    autonumber
    actor User as Student / Campus Member
    participant View as accounts/views.py (login_view)
    participant Auth as django.contrib.auth
    participant Guard as accounts/views.py (account_required)
    participant Portal as User Portal (/portal/)
    participant AdminPortal as Admin Portal (/manage/)

    User->>View: POST /login/ (username, password)
    View->>Auth: authenticate(username, password)
    alt Invalid Credentials
        Auth-->>View: None
        View-->>User: 400 Bad Request / "Invalid username or password"
    else Valid Credentials
        Auth-->>View: user instance
        alt Account Deactivated (is_active=False)
            View-->>User: 403 Forbidden / "Account deactivated. Contact administrator."
        else Account Active
            View->>Auth: login(request, user)
            alt Role == 'ADMIN'
                View-->>User: 302 Redirect to /manage/
            else Role == 'BASIC_USER'
                View-->>User: 302 Redirect to /portal/
            end
        end
    end
```

**Implementation Details:**
- Defined in `apps/accounts/views.py` and `apps/accounts/services.py`.
- Enforces session-level checks so that an account deactivated by an administrator is immediately locked out upon their next authenticated action.
- Self-promotion is structurally impossible during registration (`apps/accounts/forms.py` sets `role=User.Role.BASIC_USER`).

---

### 2.2 Borrowing Request Submission Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Borrower as Basic User
    participant Browser as Browser Client
    participant View as borrowing/views.py (new_request)
    participant Policy as dashboard/policies.py (borrowing_limits)
    participant Service as borrowing/services.py (submit_request)
    participant DB as Relational Database

    Borrower->>Browser: Select 1–3 catalog items, quantities, purpose, return date
    Browser->>View: POST /portal/requests/new/ (FormSet data + CSRF)
    View->>Policy: borrowing_limits() -> (max_items, max_qty, max_days)
    View->>View: Validate form: positive quantities, <= max_items, <= max_qty
    View->>Service: submit_request(borrower, purpose, due_at, items)
    Service->>Service: Validate due_at > requested_at AND due_at <= max_days
    alt Validation Failure
        Service-->>View: ValidationError
        View-->>Borrower: Render form with specific error alerts
    else Validation Successful
        Service->>DB: BEGIN TRANSACTION
        Service->>DB: INSERT INTO borrowing_borrowingrequest (status='PENDING')
        loop For each distinct item
            Service->>DB: INSERT INTO borrowing_borrowingrequestitem
        end
        Service->>DB: COMMIT TRANSACTION
        Service-->>View: request instance
        View-->>Borrower: 302 Redirect to /portal/requests/{id}/
    end
```

**Implementation Details:**
- Hard-capped limits enforced via server-side settings (`SystemSetting` singleton). Default: max 3 distinct equipment types, max 3 units per type, max 7 calendar days loan duration.
- Atomic line-item validation: if row 3 of a 3-item request fails, zero records are saved.

---

### 2.3 Admin Review, Exact Unit Allocation & Approval Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as System Administrator
    participant View as borrowing/views.py (approve)
    participant Service as borrowing/services.py (approve_request)
    participant DB as Relational Database

    Admin->>View: POST /manage/requests/{id}/approve/ (approval reason)
    View->>Service: approve_request(request_id, actor, reason, allocations)
    Service->>DB: BEGIN TRANSACTION (isolation)
    Service->>DB: SELECT * FROM borrowing_borrowingrequest WHERE id={id}
    alt Status != PENDING
        Service-->>View: ValidationError("Request is not pending review.")
    else Status == PENDING
        Service->>DB: Verify selected units are status='AVAILABLE'
        alt Any unit already reserved or issued
            Service->>DB: ROLLBACK TRANSACTION
            Service-->>View: ValidationError("Selected units are no longer available.")
        else All units available
            Service->>DB: UPDATE inventory_equipmentunit SET status='RESERVED'
            loop For each reserved unit
                Service->>DB: INSERT INTO borrowing_allocation (active=True)
            end
            Service->>DB: UPDATE borrowing_borrowingrequest SET status='APPROVED', approved_at=NOW, approval_reason=reason
            Service->>DB: INSERT INTO dashboard_auditlog (action='REQUEST_APPROVED')
            Service->>DB: COMMIT TRANSACTION
            Service-->>View: Success
            View-->>Admin: 302 Redirect to /manage/requests/{id}/
        end
    end
```

**Implementation Details:**
- Solves the concurrency race condition where two administrators attempt to allocate the final available unit. Database-level unique constraint `borrowing_one_active_allocation` combined with transactional locking ensures exactly one succeeds and the other receives a clean validation rejection.

---

### 2.4 Equipment Release & Handover Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as System Administrator
    actor Borrower as Student at Handover Counter
    participant View as loans/views.py (release_equipment)
    participant Service as loans/services.py (release_request)
    participant DB as Relational Database

    Admin->>View: GET /manage/loans/release/{request_id}/
    View-->>Admin: Render release verification page (lists reserved units)
    Admin->>Borrower: Physically inspect student ID and physical unit barcodes
    Admin->>View: POST /manage/loans/release/{request_id}/ (Confirm Release)
    View->>Service: release_request(request_id, actor)
    Service->>DB: BEGIN TRANSACTION
    Service->>DB: Verify request status == 'APPROVED' AND due_at > NOW
    Service->>DB: INSERT INTO loans_loan (borrower, issued_by, issued_at, due_at)
    loop For each allocated unit
        Service->>DB: INSERT INTO loans_loanunit (snapshots equipment_name, asset_tag)
        Service->>DB: UPDATE inventory_equipmentunit SET status='ON_LOAN'
    end
    Service->>DB: UPDATE borrowing_borrowingrequest SET status='ISSUED'
    Service->>DB: INSERT INTO dashboard_auditlog (action='LOAN_RELEASED')
    Service->>DB: COMMIT TRANSACTION
    Service-->>View: loan instance
    View-->>Admin: 302 Redirect to /manage/loans/{loan_id}/slip/ (Print Borrowing Slip)
```

**Implementation Details:**
- Generates an official printable borrowing slip displaying borrower name, student identifier, asset tag numbers, issuance timestamp, return deadline, and signature acknowledgment lines.
- Automatically triggers browser `window.print()` upon user print initiation.

---

### 2.5 Partial & Full Equipment Return Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as System Administrator
    actor Borrower as Returning Borrower
    participant View as loans/views.py (return_equipment)
    participant Service as loans/services.py (process_returns)
    participant Maint as maintenance/services.py (create_record)
    participant DB as Relational Database

    Borrower->>Admin: Hands over equipment units at counter
    Admin->>View: POST /manage/returns/{loan_id}/ (units, condition='GOOD'|'DAMAGED', notes)
    View->>Service: process_returns(loan_id, actor, returns)
    Service->>DB: BEGIN TRANSACTION
    loop For each returned unit
        Service->>DB: UPDATE loans_loanunit SET returned_at=NOW, return_condition=condition
        Service->>DB: UPDATE borrowing_allocation SET active=False
        alt Condition == 'GOOD'
            Service->>DB: UPDATE inventory_equipmentunit SET status='AVAILABLE'
        else Condition == 'DAMAGED'
            Service->>DB: UPDATE inventory_equipmentunit SET status='MAINTENANCE'
            Service->>Maint: create_record(unit, reason, source_return=loan_unit)
            Maint->>DB: INSERT INTO maintenance_maintenancerecord (status='REPORTED')
        end
    end
    alt All units in loan returned
        Service->>DB: UPDATE loans_loan SET completed_at=NOW
        Service->>DB: UPDATE borrowing_borrowingrequest SET status='COMPLETED'
    end
    Service->>DB: INSERT INTO dashboard_auditlog (action='UNITS_RETURNED')
    Service->>DB: COMMIT TRANSACTION
    Service-->>View: Success
    View-->>Admin: 302 Redirect to /manage/returns/
```

**Implementation Details:**
- **Partial Return Support:** If a student borrows 3 units and returns 1, the loan remains active with 2 outstanding units. The borrowing slip and admin view reflect real-time outstanding tallies.
- **Immediate Defect Quarantine:** Any unit marked `DAMAGED` upon return is barred from returning to `AVAILABLE` status and is directly quarantined into a `REPORTED` maintenance ticket.

---

### 2.6 Maintenance Diagnostics, Repair & Retirement Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Custodian / Technician Admin
    participant View as maintenance/views.py
    participant Service as maintenance/services.py
    participant DB as Relational Database

    Admin->>View: POST /manage/maintenance/{id}/start/ (Begin Diagnosis)
    View->>Service: start_repair(record_id, actor)
    Service->>DB: UPDATE maintenance_maintenancerecord SET status='IN_PROGRESS'
    Service->>DB: INSERT INTO dashboard_auditlog (action='MAINTENANCE_UPDATED')

    alt Unit Repaired Successfully
        Admin->>View: POST /manage/maintenance/{id}/complete/ (repair_notes, outcome='REPAIRED')
        View->>Service: resolve_record(record_id, actor, outcome='REPAIRED', notes)
        Service->>DB: UPDATE maintenance_maintenancerecord SET status='REPAIRED', completed_at=NOW
        Service->>DB: UPDATE inventory_equipmentunit SET status='AVAILABLE'
        Service->>DB: INSERT INTO dashboard_auditlog (action='MAINTENANCE_REPAIRED')
    else Unit Deemed Beyond Repair
        Admin->>View: POST /manage/maintenance/{id}/retire/ (repair_notes, outcome='RETIRED')
        View->>Service: resolve_record(record_id, actor, outcome='RETIRED', notes)
        Service->>DB: UPDATE maintenance_maintenancerecord SET status='RETIRED', completed_at=NOW
        Service->>DB: UPDATE inventory_equipmentunit SET status='RETIRED'
        Service->>DB: INSERT INTO dashboard_auditlog (action='MAINTENANCE_RETIRED')
    end
```

**Implementation Details:**
- Maintenance tickets require detailed problem documentation upon intake and resolution notes upon closing.
- Units undergoing maintenance cannot be allocated, approved, or issued.
- Retiring a unit permanently excludes it from the lendable inventory pool while preserving its complete historical records.
