# IT 401W Final Project Documentation — Submission Index

**Course:** IT 401W Web Programming and Frameworks
**Term:** 1st Semester, Academic Year 2026–2027
**Institution:** Bulacan State University, College of Information and Communications Technology (CICT)
**Instructor:** Dr. Aaron Paul M. Dela Rosa
**Project:** Campus Equipment Borrowing and Inventory System (Final Project A)
**Architecture:** Django Model-Template-View (MTV) Architecture

---

## 1. Overview & Directory Structure

This directory (`docs/final-submission/`) contains a working technical documentation package for the **Campus Equipment Borrowing and Inventory System**. Implementation sections are checked against the current Django code and test suite. The manual checklist below identifies team, instructor, presentation, and packaging evidence that requires completion and review before submission.

```text
docs/final-submission/
├── documentation/             # Four rendered submission PDFs (25 October 2026 snapshot)
├── screenshots/               # 26 actual fictional-data screenshots used by the PDF guide
├── README.md                   # Documentation index, submission guide, and manual checklist
├── PROJECT_DOCUMENTATION.md    # Comprehensive academic manuscript (Chapters 1 to 8)
├── DATABASE_DESIGN.md          # Database schema, table relationships, and data dictionary
├── ERD.md                      # Complete Mermaid Entity Relationship Diagram (ERD)
├── SYSTEM_ARCHITECTURE.md      # Django MTV architecture diagram, request lifecycle, and tech stack
├── SYSTEM_WORKFLOWS.md         # Detailed workflow diagrams, state machines, and narrative explanations
└── TESTING_DOCUMENTATION.md    # Test methodology, test matrices, and 524 verified test results
```

---

## 2. Document Descriptions

Current operating guides are [BASIC_USER_GUIDE.md](BASIC_USER_GUIDE.md) and
[ADMIN_GUIDE.md](ADMIN_GUIDE.md). [REHEARSAL_AND_EVIDENCE.md](REHEARSAL_AND_EVIDENCE.md)
contains a proposed twelve-minute demonstration plan and blank evidence records
for the team to complete. [TECHNOLOGY_EVALUATION.md](TECHNOLOGY_EVALUATION.md)
documents future-adoption criteria without claiming hardware or institutional
integration trials have happened.

The rendered submission documents are available below. They document the
25 October 2026 snapshot and distinguish executed tests from pending external
evidence. Section/roster details and real disclosure signatures still require
team review. The older `Campus_Equipment_Borrowing_System_Documentation.pdf`
export remains excluded by the source-package script; use these newer PDFs.

| Final PDF | Pages |
| --- | ---: |
| [Project documentation](documentation/Group%201%20-%20Documentation.pdf) | 41 |
| [Test cases and traceability](documentation/Group%201%20-%20Test%20Cases.pdf) | 95 |
| [Illustrated system user guide](documentation/Group%201%20-%20System%20User%20Guide.pdf) | 38 |
| [AI disclosure - unsigned draft](documentation/AI%20Disclosure%20Agreement.pdf) | 3 |

The test register covers 80 normalized specification checks through 116
scenarios: 108 PASS, 0 FAIL, 3 NOT EXECUTED and 5 BLOCKED. The separate permanent
suite passed all 524 automated methods. All 18 required screenshot filenames,
plus eight supplementary views, are in [screenshots/](screenshots/).
Earlier implementation verification is recorded in
[SUBMISSION_READINESS_REPORT.md](SUBMISSION_READINESS_REPORT.md).

| File Name | Scope & Purpose | Target Course Outcomes |
|---|---|---|
| [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md) | **Primary academic document** containing Chapters 1 through 8: Project Introduction, System Requirements (A1–A8, U1–U4, BR1–BR6), System Design & Architectural Options Comparison, Database Design, System Workflows, System Implementation, Testing & Verification, and Conclusion with Ethical & Standards Analysis. | CO1, CO2, CO3, CO4, CO5, CO6 |
| [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md) | In-depth relational database documentation: ERD summary, table specifications, field definitions, primary/foreign keys, uniqueness constraints, database-level check constraints, composite indexes, and complete Data Dictionary for all 12 Django models across 6 modular applications. | CO4, CO5 |
| [`ERD.md`](ERD.md) | Standalone, high-resolution Mermaid Entity Relationship Diagram illustrating entities, attributes, primary keys, foreign keys, cardinality notations (1:N, 1:1), and referential integrity constraints. | CO2, CO5 |
| [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) | Architectural breakdown of the Django Model-Template-View pattern, component interaction diagram, request-response lifecycle, role-based middleware/decorator security layers, transaction isolation, and architectural trade-off analysis. | CO1, CO2, CO4 |
| [`SYSTEM_WORKFLOWS.md`](SYSTEM_WORKFLOWS.md) | Visual state transitions and Mermaid sequence/activity flowcharts covering User Registration & Login, Equipment Browsing, Borrowing Submission, Admin Approval/Rejection, Allocation Locks, Equipment Release, Partial/Full Returns, Damaged Return Maintenance, and Category Archiving. | CO2, CO3 |
| [`TESTING_DOCUMENTATION.md`](TESTING_DOCUMENTATION.md) | Comprehensive testing report covering the test strategy, execution environment, unit tests, integration tests, concurrency race-condition trials (30/30 isolated trials), security/permission tests, and the breakdown of **524 verified automated tests**. | CO3, CO4 |

---

## 3. Team Member Contributions & Roles

In accordance with the IT 401W specification, each member was assigned an end-to-end vertical deliverable including database models, service layers, custom Django views, forms, templates, URL routing, automated tests, and documentation:

| Member | Feature Branch | Assigned Subsystem & Deliverable | Primary Application Module |
|---|---|---|---|
| **Charles** | `charles` | User Authentication, Account Security, Profiles, and Admin User Management (A1, U1, SEC1–5) | `apps/accounts` |
| **Raj** | `raj` | Equipment Catalog, Category Archiving, Asset Tagging, and Inventory Reconciliation (A2, U2, DB2–3) | `apps/inventory` |
| **Clark** | `clark` | Borrowing Request Submission, Multi-Item Validation, Admin Review, and Atomic Unit Allocation (A3, U3, BR1, BR3–4) | `apps/borrowing` |
| **Janelle** | `janelle` | Equipment Issuance, Borrowing Slip Generation, Partial/Full Returns, and Overdue Tracking (A4, A5, U4, BR5–6) | `apps/loans` |
| **Francis** | `francis` | Maintenance Intake, Damaged Unit Quarantine, Repair Progress, and Unit Retirement (A6, DB7) | `apps/maintenance` |
| **Miah** | `miah` | Executive Dashboard, Dynamic Metrics, CSV Reporting, System Settings Policy, and Audit Trail (A7, A8, DB8) | `apps/dashboard` |

---

## 4. Academic Submission Checklist (IT 401W Final Requirements)

Before final submission of the ZIP package (`IT401W_ProjectA_Section_Group.zip`) and the Week 17 defense, the project team must complete the following manual entries:

- [ ] **Title Page & Student Identifiers:** Fill in the group members' Student Numbers, Full Names, Section, and Group Number on the first page of `PROJECT_DOCUMENTATION.md` and the official submission portal.
- [ ] **Safe Demonstration Credentials:** Ensure instructor credentials for 1 Admin and 2 Basic Users are prepared through the designated private submission channel (do not commit passwords to public Git repositories).
- [ ] **Rotational Leadership Evidence:** Document the rotating sprint leadership logs, weekly goal-setting, peer evaluations, and task assignments in accordance with PO-h and PO-j requirements.
- [ ] **Presentation Rehearsal:** Ensure each of the 6 members has an identifiable 2-minute presentation segment for the 12-minute live demonstration, followed by the 3-minute Q&A defense.
- [ ] **Emerging Technology Evaluation:** Review the technology evaluation section in Chapter 3 comparing server-rendered Django against decoupled SPA/API frameworks for institutional deployment.
- [ ] **Clean Archive Packaging:** Package the repository into `IT401W_ProjectA_Section_Group.zip` ensuring `.venv/`, `__pycache__/`, `db.sqlite3` (if containing local/real data), and personal test logs are excluded.
