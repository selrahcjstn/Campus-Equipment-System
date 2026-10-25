# Campus Equipment Borrowing and Inventory System
## Technical Project Documentation & Academic Report

**Course Code:** IT 401W
**Course Title:** Web Programming and Frameworks
**Academic Term:** 1st Semester, Academic Year 2026–2027
**Department:** College of Information and Communications Technology (CICT)
**Institution:** Bulacan State University, Main Campus, Guinhawa, City of Malolos, Bulacan
**Instructor:** Dr. Aaron Paul M. Dela Rosa, Assistant Professor III

---

### Project Identification & Team Roster

| Role / Responsibility | Assigned Subsystem & Module | Student Name | Student Number | Section & Group |
|---|---|---|---|---|
| **Project Lead & Auth Architect** | Authentication, Users, Security (`apps/accounts`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |
| **Inventory Specialist** | Catalog, Categories, Physical Units (`apps/inventory`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |
| **Borrowing Operations Architect** | Requests, Review, Allocations (`apps/borrowing`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |
| **Logistics & Returns Engineer** | Issuance, Slips, Returns, Overdue (`apps/loans`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |
| **Maintenance Systems Engineer** | Repairs, Diagnostics, Retirement (`apps/maintenance`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |
| **Analytics & Governance Specialist** | Dashboard, Reports, Audit, Settings (`apps/dashboard`) | *[Insert Student Name]* | *[Insert Student No.]* | BSIT 4A - Group *[#]* |

---

## Executive Summary

The **Campus Equipment Borrowing and Inventory System** is a custom web application engineered with Python 3.13 and the Django 6.1.2 Model-Template-View (MTV) framework. Developed in fulfillment of the IT 401W capstone requirements for the College of Information and Communications Technology (CICT) at Bulacan State University, the platform automates and governs the complete lifecycle of educational physical assets—from student borrowing request submission through administrative review, atomic unit allocation, physical handover, partial and full returns, quarantine maintenance, and overdue tracking.

The system is strictly partitioned into two mutually exclusive access levels: **Basic User** (handling student/faculty equipment browsing, request submission, and loan history) and a 100% custom-built **Admin Portal** (comprising dashboard analytics, user governance, catalog management, inventory reconciliation, repair tracking, CSV report generation, and immutable audit logging). Built-in or third-party automatic admin generators were strictly avoided in compliance with project specifications.

The software utilizes an atomic database transaction model and database-level constraints to prevent common logistical pitfalls such as double allocation of physical units, partial request creation, and unauthorized privilege escalation. The integrated codebase passes **516 automated test cases** with zero failures, verified across comprehensive unit, integration, role security, and multi-threaded concurrency trials.

---

## Table of Contents

- [Chapter 1 — Introduction](#chapter-1--introduction)
  - [1.1 Project Overview](#11-project-overview)
  - [1.2 Background of the Project](#12-background-of-the-project)
  - [1.3 Problem Statement](#13-problem-statement)
  - [1.4 Project Objectives](#14-project-objectives)
  - [1.5 Scope and Limitations](#15-scope-and-limitations)
  - [1.6 Significance of the Project](#16-significance-of-the-project)
- [Chapter 2 — System Requirements](#chapter-2--system-requirements)
  - [2.1 Functional Requirements](#21-functional-requirements)
  - [2.2 Non-Functional Requirements](#22-non-functional-requirements)
  - [2.3 User Roles and Permissions](#23-user-roles-and-permissions)
  - [2.4 Admin Portal Features (A1–A8)](#24-admin-portal-features-a1a8)
  - [2.5 Basic User Portal Features (U1–U4)](#25-basic-user-portal-features-u1u4)
  - [2.6 Core Business Rules (BR1–BR6)](#26-core-business-rules-br1br6)
  - [2.7 System Constraints](#27-system-constraints)
- [Chapter 3 — System Design & Architecture](#chapter-3--system-design--architecture)
  - [3.1 System Architecture (Django MTV Pattern)](#31-system-architecture-django-mtv-pattern)
  - [3.2 Technology Stack Evaluation](#32-technology-stack-evaluation)
  - [3.3 Architectural Options Comparison](#33-architectural-options-comparison)
  - [3.4 System Modules Breakdown](#34-system-modules-breakdown)
  - [3.5 Authentication and Authorization Security Architecture](#35-authentication-and-authorization-security-architecture)
  - [3.6 Inventory and Asset Quarantine Lifecycle](#36-inventory-and-asset-quarantine-lifecycle)
- [Chapter 4 — Database Design](#chapter-4--database-design)
  - [4.1 Database Architecture Overview](#41-database-architecture-overview)
  - [4.2 Entity Relationship Diagram Summary](#42-entity-relationship-diagram-summary)
  - [4.3 Database Schema and Relational Models](#43-database-schema-and-relational-models)
  - [4.4 Integrity Constraints and Indexing Strategy](#44-integrity-constraints-and-indexing-strategy)
  - [4.5 Relational Data Dictionary Summary](#45-relational-data-dictionary-summary)
- [Chapter 5 — System Workflows](#chapter-5--system-workflows)
  - [5.1 Workflow State Machine Overview](#51-workflow-state-machine-overview)
  - [5.2 Account Registration and Secure Login](#52-account-registration-and-secure-login)
  - [5.3 Equipment Browsing and Multi-Item Request Submission](#53-equipment-browsing-and-multi-item-request-submission)
  - [5.4 Administrative Review, Rejection, and Unit Allocation](#54-administrative-review-rejection-and-unit-allocation)
  - [5.5 Equipment Handover and Printable Borrowing Slip Generation](#55-equipment-handover-and-printable-borrowing-slip-generation)
  - [5.6 Partial Returns, Full Returns, and Damaged Unit Quarantine](#56-partial-returns-full-returns-and-damaged-unit-quarantine)
  - [5.7 Maintenance Lifecycle: Diagnostics, Repair, and Retirement](#57-maintenance-lifecycle-diagnostics-repair-and-retirement)
  - [5.8 Overdue Loan Detection and Due-Date Revisions](#58-overdue-loan-detection-and-due-date-revisions)
- [Chapter 6 — System Implementation](#chapter-6--system-implementation)
  - [6.1 Modular Directory Structure](#61-modular-directory-structure)
  - [6.2 Subsystem Implementations](#62-subsystem-implementations)
  - [6.3 Presentation Tier and Reusable Component Architecture](#63-presentation-tier-and-reusable-component-architecture)
  - [6.4 Fictional Demonstration Data Seeding (`seed_project_demo`)](#64-fictional-demonstration-data-seeding-seed_project_demo)
- [Chapter 7 — Testing, Verification, and Evaluation](#chapter-7--testing-verification-and-evaluation)
  - [7.1 Quality Assurance Strategy](#71-quality-assurance-strategy)
  - [7.2 Automated Test Execution Results (516 Passing Tests)](#72-automated-test-execution-results-516-passing-tests)
  - [7.3 Module Test Coverage Breakdown](#73-module-test-coverage-breakdown)
  - [7.4 Concurrency Race Condition Trials (30/30 Passing)](#74-concurrency-race-condition-trials-3030-passing)
  - [7.5 Security and Privilege Escalation Verification](#75-security-and-privilege-escalation-verification)
- [Chapter 8 — Conclusion & Future Recommendations](#chapter-8--conclusion--future-recommendations)
  - [8.1 Project Conclusion](#81-project-conclusion)
  - [8.2 Key Implemented Capabilities](#82-key-implemented-capabilities)
  - [8.3 Known System Limitations](#83-known-system-limitations)
  - [8.4 Recommendations for Future Enhancement](#84-recommendations-for-future-enhancement)
  - [8.5 Ethical, Legal, and Institutional Standards for Team Review](#85-ethical-legal-and-institutional-standards-for-team-review)

---

# Chapter 1 — Introduction

### 1.1 Project Overview
In modern academic institutions, access to high-value technological equipment—such as digital multimedia projectors, DSLR cameras, high-performance laptops, scientific measuring devices, and networking toolkits—is vital for effective classroom instruction, laboratory experimentation, and student research. The **Campus Equipment Borrowing and Inventory System** is a purpose-built Django web application developed for the College of Information and Communications Technology (CICT) at Bulacan State University. It replaces obsolete manual paper logs with a centralized, auditable, and automated digital framework that manages physical assets throughout their entire operational life.

### 1.2 Background of the Project
Historically, campus property custodian offices have relied on paper logbooks, paper equipment request slips, and decentralized spreadsheets. While initially simple, these legacy mechanisms suffer from severe vulnerabilities:
- Borrowing slips are easily misplaced, illegible, or damaged.
- Property custodians lack real-time visibility into the exact physical availability of units versus those reserved for upcoming classes.
- Equipment returned with physical defects is frequently returned to storage shelves without maintenance inspections, leading to unexpected equipment failures during critical classroom sessions.
- Calculating overdue durations and generating departmental inventory audit reports requires hours of manual cross-referencing.

To resolve these operational bottlenecks, this project was commissioned as **Final Project A** under the **IT 401W (Web Programming and Frameworks)** curriculum, challenging the student team to architect an enterprise-grade web application in Python and Django adhering to strict academic and industry standards.

### 1.3 Problem Statement
The absence of a synchronized, transactional asset management system in academic institutions leads to:
1. **Double-Allocation and Inventory Contention:** Multiple faculty members or student groups are inadvertently promised the same projector or laboratory camera due to paper-based scheduling lag.
2. **Untracked Damaged Units:** Equipment returned in a damaged condition is returned to general circulation without quarantine or diagnostic logging.
3. **Audit Trail Vulnerabilities:** Property offices cannot verify which staff member authorized an equipment release, who inspected returned units, or when borrowing policies were modified.
4. **Lack of Enforceable Borrowing Policies:** Manual systems fail to consistently enforce policy limits regarding maximum equipment quantities or allowable loan durations.

### 1.4 Project Objectives
#### General Objective
To design, develop, test, and document a robust, secure, and transactional web application utilizing Python and the Django Model-Template-View framework that manages campus equipment requests, inventory tracking, physical dispatch, returns, maintenance, and administrative reporting.

#### Specific Objectives
1. **Implement Dual-Role Isolation:** Create dedicated user portals for **Basic Users** (`/portal/`) and **Admins** (`/manage/`), completely prohibiting third-party automated admin generators (`django.contrib.admin`).
2. **Enforce Atomic Physical-Unit Allocation:** Develop an all-or-nothing allocation service ensuring that approved requests reserve exact, barcode-identified physical copies without double-booking.
3. **Automate Partial Returns and Defect Quarantine:** Enable borrowers to return items incrementally while ensuring damaged units are automatically routed into maintenance tickets.
4. **Deliver Executive Analytics and Audit Trails:** Build real-time dashboards with live metrics, monthly loan trend charts, category usage charts, filterable CSV report exports, and an immutable 24-event audit log.
5. **Guarantee Absolute Test Verification:** Achieve 100% test pass rates across extensive automated test suites, proving concurrency safety and role-based access control.

### 1.5 Scope and Limitations
#### In-Scope Capabilities
- Public registration, role-based authentication, and profile self-service.
- Administrative user activation, deactivation, and role assignment.
- Catalog classification, category archiving, equipment model management, and unique asset tagging.
- Multi-item borrowing request submission (1 to 3 distinct items, up to configured quantity limits).
- Administrative approval with mandatory rationale and atomic physical unit reservation.
- Equipment handover verification and printable borrowing slip generation.
- Per-unit return processing, return condition assessment, and automatic maintenance ticket creation.
- Maintenance diagnostics, repair tracking, and equipment retirement.
- Real-time dashboard KPI cards, dynamic charts, CSV reports, and configurable institutional borrowing settings.

#### Out-of-Scope Elements
- Financial payment gateways, cash fines, or billing systems for overdue equipment (fines and payments are explicitly excluded by the IT 401W specification).
- Supplier procurement portals, vendor bidding, and automated purchase orders.
- Native mobile applications (iOS/Android); the web application is fully responsive via modern CSS.

### 1.6 Significance of the Project
- **For Campus Property Custodians:** Provides instantaneous inventory reconciliation, eliminates manual paper slips, and provides printable legal borrowing slips with full accountability.
- **For Students and Faculty:** Delivers a transparent, self-service catalog showing live serviceable quantities, transparent approval tracking, and clear return deadlines.
- **For Academic Administration:** Offers tamper-evident audit logs and data-driven CSV reports supporting institutional compliance and accreditation standards.

---

# Chapter 2 — System Requirements

### 2.1 Functional Requirements Summary
The functional specifications are divided between the custom Admin Portal (approximately 75% of development scope) and the Basic User Portal (approximately 25% of development scope).

### 2.2 Non-Functional Requirements
- **Security:** Cryptographic hashing of passwords using PBKDF2 SHA-256; universal CSRF protection on mutation requests; strict server-side authorization guards; protection against SQL injection and XSS via Django ORM and template escaping.
- **Data Integrity:** Database-level check constraints and conditional unique constraints; ACID compliance through `django.db.transaction.atomic`.
- **Performance:** Optimized ORM queries using `select_related`, `prefetch_related`, and database indexes; sub-100ms average local page rendering.
- **Usability & Accessibility:** Monochromatic, high-contrast UI adhering to WCAG 2.1 AA standards; multi-attribute search and filtering toolbar with URL query persistence; responsive layout supporting desktop and mobile viewports.
- **Maintainability:** Modular architecture across 6 decoupled Django apps; clean separation between view controllers and domain service layers.

### 2.3 User Roles and Permissions
The system enforces strictly two user access levels:
1. **Basic User (`BASIC_USER`):** Granted to students, faculty, and standard campus members upon public registration. Restricted to `/portal/` routes.
2. **Administrator (`ADMIN`):** Granted to property custodians and equipment laboratory managers. Restricted to `/manage/` routes. Direct registration into the admin role is architecturally impossible.

### 2.4 Admin Portal Features (A1–A8)
- **A1: Account Management:** Search, view, activate, and deactivate user accounts; inspect historical requests; toggle user roles with full audit logging.
- **A2: Equipment Catalog and Physical Units:** Create categories and catalog models; archive categories/models without breaking historical links; register physical units with unique asset tags, condition ratings, and acquisition dates.
- **A3: Request Review and Approval:** Paginated queue filtered by status and search; inspect borrower justification and requested due dates; approve requests by allocating specific available units; reject with mandatory administrative reasons.
- **A4: Equipment Release:** Convert approved requests into issued loans; verify physical asset tags; generate printable borrowing slips; reject release if agreed due dates have expired without revision.
- **A5: Partial Returns and Overdue Monitoring:** Receive individual units with condition grading (`GOOD` or `DAMAGED`); automatic maintenance intake for damaged units; automatic loan closure upon final return; dynamic overdue flagging based on local calendar dates (`Asia/Manila`).
- **A6: Maintenance and Inventory Reconciliation:** Open, track, repair, and retire maintenance tickets; calculate live 5-state stock reconciliation (Available, Reserved, Issued, Maintenance, Retired).
- **A7: Dashboard and Reports:** 4 live KPI metric cards; monthly loan issuance trends; equipment category utilization charts; date-filtered loan and overdue tabular reports with streaming CSV exports.
- **A8: Audit History and Operational Settings:** Searchable audit trail across 24 distinct system actions; singleton policy editor for maximum loan duration (1–30 days) and item limits (1–3 items, 1–20 units).

### 2.5 Basic User Portal Features (U1–U4)
- **U1: Account and Profile:** Self-service registration; secure sign-in and sign-out; personal profile updates (name and contact number); password change facility.
- **U2: Browse Equipment Catalog:** Search and filter active equipment models; inspect technical descriptions and live available counts; hide confidential internal notes, other borrowers' identities, and maintenance tickets.
- **U3: Submit Borrowing Request:** Submit multi-item requests (1–3 models) with requested quantities, purpose, and due dates within policy thresholds; atomic validation preventing partial submissions.
- **U4: Track and Cancel Own Requests:** Monitor real-time status of personal requests and loans; print personal borrowing slips; self-cancel pending or approved requests prior to physical equipment release.

### 2.6 Core Business Rules (BR1–BR6)
1. **BR1 — Atomic Unit Allocation:** Approvals must allocate the exact requested physical units in an all-or-nothing transaction. Cancelling an approved request atomically releases all reserved units back to available status.
2. **BR2 — Single-Status Inventory Invariant:** Every physical unit exists in exactly one status at any instant: `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`, or `RETIRED`.
3. **BR3 — Concurrency & Race Condition Prevention:** When two administrators simultaneously attempt to allocate the last remaining available unit, transactional locks and unique database constraints guarantee that exactly one succeeds while the other is cleanly rejected.
4. **BR4 — Unique Items per Request & Atomic Line Validation:** A request cannot contain duplicate catalog models. All items in a multi-item submission must validate; any invalid row causes the entire request to abort.
5. **BR5 — Borrowing Thresholds & Due Date Validation:** Default limits are 3 distinct items, 3 units per item, and 7 calendar days maximum duration. Requests past due dates cannot be released without a recorded administrative due-date revision.
6. **BR6 — Calendar-Day Overdue Computation:** Overdue duration is computed as 0 days on or before the due date; after the due date, it is computed as the calendar-day difference between current date and due date in the `Asia/Manila` timezone.

### 2.7 System Constraints
- **Framework Constraint:** Must use Django MTV; external admin panel generators are strictly prohibited.
- **Database Engine:** SQLite for development and demonstration; fully compatible with PostgreSQL/MySQL.
- **Zero Build Step:** Frontend relies on vanilla ES6+ JavaScript and native CSS3 components, eliminating Node.js/npm dependencies.

---

# Chapter 3 — System Design & Architecture

### 3.1 System Architecture (Django MTV Pattern)
The application strictly implements the **Model-Template-View (MTV)** architectural pattern:
- **Model (`M`):** Encapsulates relational data schemas, business constraints, and ORM query managers across `apps/*/models.py`.
- **Template (`T`):** Server-rendered presentation layer utilizing Django Template Language (DTL) with role-specific base wrappers (`admin_portal.html`, `user_portal.html`) and modular component includes.
- **View (`V`):** HTTP request handlers in `apps/*/views.py` that perform authorization, validate forms, coordinate with the domain service layer, and render templates.
- **Service Layer:** Transactional domain logic is abstracted into `apps/*/services.py`, decoupling business operations from HTTP request objects.

### 3.2 Technology Stack Evaluation
- **Backend:** Python 3.13 / Django 6.1.2.
- **Database:** SQLite 3.50+ (ACID compliant, file-based for isolated demonstration) / PostgreSQL ready.
- **Frontend:** Server-Rendered HTML5, CSS3 Custom Properties, Vanilla JavaScript (ES6+).
- **Timezone Management:** Standardized to `Asia/Manila` (`UTC+8`).

### 3.3 Architectural Options Comparison
The design team evaluated two candidate architectures:
1. **Option A: Server-Rendered Django Monolithic MTV (Selected)**
2. **Option B: Decoupled Single-Page App (SPA) + Django REST Framework**

Option A was selected because server-rendered Django templates fit the course requirement, keep the user interface and workflows in one deployable application, and use Django's established form, session, and CSRF facilities. A separate SPA/API could also be secured with sessions or tokens. Transaction behavior depends on the database and service implementation rather than the presentation architecture; SQLite and its concurrency limits are described in the testing and limitations sections.

### 3.4 System Modules Breakdown
```text
campus-equipment-system/
├── apps/
│   ├── accounts/       # Authentication, profiles, RBAC, user management
│   ├── inventory/      # Categories, catalog masters, physical units, archiving
│   ├── borrowing/      # Requests, item lines, review, atomic allocations
│   ├── loans/          # Issuance, borrowing slips, returns, overdue tracking
│   ├── maintenance/    # Defect intake, repairs, diagnostics, unit retirement
│   └── dashboard/      # Executive KPIs, charts, CSV reporting, audit log, policies
├── config/             # Root settings, WSGI/ASGI handlers, global URL dispatcher
├── templates/          # Semantic layouts, portal bases, reusable UI components
└── static/             # Pure CSS styling and lightweight vanilla JS modules
```

---

# Chapter 4 — Database Design

### 4.1 Database Architecture Overview
The database adheres to Third Normal Form (3NF) while incorporating immutable snapshot fields on transaction records (e.g., preserving `equipment_name` and `asset_tag` on `LoanUnit` records even if catalog master names change). All deletions of referenced master records are intercepted and blocked via `models.PROTECT`.

### 4.2 Entity Relationship Diagram Summary
The system comprises 12 interconnected relational models:
1. `User` (`accounts_user`)
2. `Category` (`inventory_category`)
3. `Equipment` (`inventory_equipment`)
4. `EquipmentUnit` (`inventory_equipmentunit`)
5. `BorrowingRequest` (`borrowing_borrowingrequest`)
6. `BorrowingRequestItem` (`borrowing_borrowingrequestitem`)
7. `Allocation` (`borrowing_allocation`)
8. `Loan` (`loans_loan`)
9. `LoanUnit` (`loans_loanunit`)
10. `MaintenanceRecord` (`maintenance_maintenancerecord`)
11. `SystemSetting` (`dashboard_systemsetting`)
12. `AuditLog` (`dashboard_auditlog`)

*(See [`ERD.md`](ERD.md) for the complete, high-resolution Mermaid diagram and [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md) for the complete data dictionary).*

### 4.3 Database Integrity Constraints
- `accounts_valid_campus_role`: Role restricted to `BASIC_USER` or `ADMIN`.
- `inventory_category_name_ci`: Case-insensitive uniqueness on category names.
- `inventory_unit_asset_tag_ci`: Case-insensitive uniqueness on physical asset tags.
- `inventory_valid_unit_status`: Status restricted to `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`, `RETIRED`.
- `borrowing_due_after_request`: Return deadline must be strictly later than submission timestamp.
- `borrowing_positive_quantity`: Requested item quantity must be greater than zero.
- `borrowing_one_active_allocation`: Conditional unique constraint guaranteeing that no physical unit has more than one active allocation.
- `loan_one_active_issue_per_unit`: Conditional unique constraint preventing concurrent active loans for the same physical unit.
- `maintenance_one_active_per_unit`: Conditional unique constraint ensuring a unit has at most one active maintenance ticket.
- `dashboard_single_policy`: Primary key fixed to 1, ensuring a singleton policy row.

---

# Chapter 5 — System Workflows

*(For detailed visual sequence flowcharts and state diagrams, refer to [`SYSTEM_WORKFLOWS.md`](SYSTEM_WORKFLOWS.md)).*

### 5.1 Borrowing Lifecycle
1. **Submission:** Basic User selects 1–3 catalog items and specifies quantities, purpose, and return date. Request enters `PENDING` state.
2. **Review & Allocation:** Admin reviews requested quantities and current availability, then records an approval reason. On approval, the service atomically selects the required `AVAILABLE` physical units. The units transition to `RESERVED`, and active `Allocation` records are created. If rejected, Admin enters a mandatory rejection reason and the request transitions to `REJECTED`.
3. **Release:** At physical handover, Admin verifies student credentials and asset barcodes. The request transitions to `ISSUED`, creating a `Loan` and individual `LoanUnit` records. Physical units transition to `ON_LOAN`. A printable borrowing slip is generated.
4. **Returns:** When units are returned, Admin inspects each item:
   - Units in **Good** condition transition to `AVAILABLE`.
   - Units marked **Damaged** transition to `MAINTENANCE`, automatically opening a maintenance ticket.
   - If only a subset of units is returned, loan status becomes **Partially Returned**. When all units are returned, the loan transitions to **Completed**.
5. **Overdue Handling:** If current date exceeds `due_at` and outstanding units remain, the loan is dynamically flagged as **Overdue**.
6. **Maintenance & Repair:** Technicians update tickets to `IN_PROGRESS`, conduct repairs, and record resolution notes. Repaired units return to `AVAILABLE`; irreparable units are permanently transitioned to `RETIRED`.

---

# Chapter 6 — System Implementation

### 6.1 Application Modules Implementation
- **`apps/accounts`:** Implements `User` model, custom authentication forms, `@account_required` role decorator, session-level deactivation checks, and user administration views.
- **`apps/inventory`:** Implements `Category`, `Equipment`, and `EquipmentUnit` models. Contains category soft-deletion archiving, catalog management views, and modal-based unit registration.
- **`apps/borrowing`:** Manages `BorrowingRequest`, `BorrowingRequestItem`, and `Allocation`. Features multi-item dynamic FormSets, atomic approval services, and administrative due-date revisions.
- **`apps/loans`:** Implements `Loan` and `LoanUnit`. Manages physical equipment dispatch, printable borrowing slips (`window.print`), partial returns, and overdue calculations in `Asia/Manila` time.
- **`apps/maintenance`:** Implements `MaintenanceRecord`. Manages defect reporting, quick-action status changes, repair notes, and physical unit retirement.
- **`apps/dashboard`:** Implements `SystemSetting` and `AuditLog`. Powers live dashboard KPI cards, dynamic charts, CSV report exports, and system policy updates.

### 6.2 Demonstration Data Seeding
The custom management command `seed_project_demo` automates the generation of the complete fictional dataset mandated by the IT 401W specification:
- 3 Categories, 6 Equipment models, 18 Physical units.
- 1 Administrator account (`demo_admin`) and 8 Basic User accounts (`demo_user01` to `demo_user08`).
- 20 Borrowing requests, 8 Issued loans (including active, completed, overdue, and partially returned scenarios), and 5 Maintenance records across all supported statuses.

---

# Chapter 7 — Testing, Verification, and Evaluation

### 7.1 Test Execution Results
The test suite was executed against a clean test database using Django's test runner:
- **Total Tests Executed:** 516
- **Passed:** 516 (100%)
- **Failures / Errors:** 0
- **Duration:** 31.9 seconds

### 7.2 Module Test Distribution
- `apps.accounts`: 80 Tests
- `apps.borrowing`: 111 Tests
- `apps.dashboard`: 76 Tests
- `apps.inventory`: 107 Tests
- `apps.loans`: 67 Tests
- `apps.maintenance`: 75 Tests

### 7.3 Concurrency Verification Evidence
To satisfy Business Rule 3 (BR3), the team conducted **30 automated, isolated, multi-threaded trials** of competing approvals for the last single available unit of an equipment model:
- **Result:** In **30 out of 30 trials**, exactly one approval succeeded while the competing attempt was cleanly rejected with a validation error. No database deadlocks, orphaned allocations, or dual reservations occurred.

*(See [`TESTING_DOCUMENTATION.md`](TESTING_DOCUMENTATION.md) for full test matrices and trial evidence).*

---

# Chapter 8 — Conclusion & Future Recommendations

### 8.1 Project Conclusion
The Campus Equipment Borrowing and Inventory System successfully delivers an institutional-grade, reliable, and secure web application fulfilling all academic learning targets (CO1 to CO6) under the IT 401W syllabus. By implementing strict transactional controls, database-level invariants, dual-role isolation, and comprehensive audit trails, the application completely eliminates the risks of double-booking, untracked damage, and unauthorized access inherent in legacy paper-based operations.

### 8.2 Summary of Implemented Capabilities
- 100% custom Django views, forms, and templates; zero prohibited admin packages.
- All-or-nothing unit allocation preventing inventory contention.
- Seamless partial return processing and automatic damaged unit maintenance routing.
- Real-time executive dashboards, dynamic usage charts, and CSV report exports.
- Immutable audit logging across 24 distinct operational actions.
- Verified test suite containing 516 passing automated test cases.

### 8.3 Known System Limitations
- **Local Deployment Configuration:** The current codebase is optimized for local evaluation with SQLite and development settings. Multi-node cloud deployments require migrating to PostgreSQL and configuring static asset CDNs.
- **Manual Barcode Entry:** Physical asset tags are verified via keyboard input; hardware barcode/RFID scanner API integration is not yet implemented.

### 8.4 Recommendations for Future Enhancement
1. **Automated Institutional Email Notifications:** Integrate Django SMTP backend to dispatch automated email reminders 24 hours prior to loan due dates and immediate notices upon overdue classification.
2. **Hardware Barcode & QR Scanner Integration:** Implement client-side camera-based barcode/QR scanning to accelerate counter checkouts and returns.
3. **Single Sign-On (SSO) Integration:** Connect user authentication to institutional identity providers via LDAP, Google Workspace for Education, or SAML 2.0.

### 8.5 Ethical, Legal, and Institutional Standards for Team Review

The system handles account identifiers and contact details, so the project team should confirm applicable privacy requirements, retention practices, access controls, and institutional review before deployment. The application uses Django password hashing and restricts Basic User views to the signed-in user's records; these technical safeguards do not, by themselves, establish legal compliance. The team should verify any statement about the Data Privacy Act of 2012 (Republic Act No. 10173) with its adviser or institution.
- **Intellectual Property & Code Integrity:** All third-party libraries are declared in `requirements.txt` under permissive open-source licenses (BSD, MIT, Python Software Foundation).
The team must document AI or reused-asset assistance accurately and check the applicable instructor and Bulacan State University policy before submission. This document does not assert that a particular AI use is permitted or claim institutional approval.
