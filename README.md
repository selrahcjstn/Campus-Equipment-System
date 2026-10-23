# Campus Equipment System

A Django web application for managing campus equipment from borrowing requests and approval through issuance, returns, maintenance, and reporting. Basic Users can browse equipment and track their requests and loans, while Admins manage physical inventory and campus borrowing operations.

## Features

| Module | Features |
| --- | --- |
| Accounts and authentication | Registration, role-based login, profiles, password changes, and Admin user management |
| Equipment catalog and inventory | Categories, equipment listings, tagged physical units, availability, archiving, and retirement |
| Borrowing requests and approval | Requests with multiple equipment types, policy validation, exact-unit reservations, approval, rejection, and cancellation |
| Loans, returns, and overdue | Equipment release, printable loan slips, partial and complete returns, return conditions, loan history, and overdue tracking |
| Maintenance | Manual repair intake, automatic intake from damaged returns, repair progress, restoration, and retirement |
| Dashboard, reports, and settings | Role-specific dashboards, inventory and borrowing charts, filtered CSV reports, audit logs, and configurable borrowing limits |

## User roles

**Basic User** — Browse the active catalog, submit and cancel eligible requests, view personal loans and return history, and manage their own profile and password.

**Admin** — Manage equipment and users, approve or reject requests, issue reserved equipment, receive returns, manage repairs, inspect reports and audit logs, and update borrowing policies.

Campus permissions use the account's `ADMIN` or `BASIC_USER` role. Django staff and superuser flags alone do not grant access to the campus Admin portal. Public registration always creates a Basic User.

## Equipment workflow

1. An Admin creates catalog entries and adds physical units with unique asset tags.
2. A Basic User submits a borrowing request with equipment quantities, a purpose, and a due date.
3. An Admin approves the request and reserves specific available units, or rejects it with a reason.
4. An Admin releases the reserved units, creating a loan and a printable loan slip.
5. Returns are recorded per unit. Good units become available; damaged units enter maintenance. Partial returns leave the remaining units on loan.
6. Outstanding loans become overdue after their due date. A loan completes when every issued unit has been returned.
7. Maintenance restores repaired units to availability or retires units that cannot be repaired.

Physical unit statuses are **Available**, **Reserved**, **On loan** (shown as Issued in the interface), **Maintenance**, and **Retired**. Approval, release, returns, and repair completion update related records together in database transactions.

The default borrowing policy allows **3 distinct equipment types**, **3 units per type**, and a due date within **7 calendar days**. Admins can adjust these limits through System Settings. New requests and pending approvals use the current policy; existing approvals and issued loans retain their recorded terms. Calendar dates use the `Asia/Manila` time zone.

## Technology

- Python — tested locally with Python 3.13
- Django 6.1.2
- SQLite for local development
- Django templates, shared CSS components, and vanilla JavaScript
- Django authentication, password validation, CSRF protection, and database migrations

Dependencies are pinned in [requirements.txt](requirements.txt). There is no separate frontend build step.

## Local setup

The following commands use Windows PowerShell. Git and Python must already be installed.

### 1. Clone the repository

```powershell
git clone https://github.com/selrahcjstn/Campus-Equipment-System.git
cd Campus-Equipment-System
git switch main
```

### 2. Create a virtual environment and install dependencies

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The commands below call the virtual environment directly, so PowerShell activation is optional.

### 3. Create the local database

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

The database file, local backups, and account data are excluded from Git. A fresh clone starts with an empty database; setup does not automatically create users or equipment.

### 4. Start the application

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the public landing page. Get Started opens registration; Sign In opens login. Browse Equipment requires login through the existing catalog route. Signed-in visitors to the home page go directly to their role's portal. Use `Ctrl+C` to stop the server.

### 5. Set up the first Admin

On a fresh local database, register the account that will become the first Admin. Before submitting borrowing requests with that account, open another terminal in the project directory:

```powershell
.\.venv\Scripts\python.exe manage.py shell
```

Run the following Python code, replacing `YOUR_ADMIN_USERNAME` with the registered username:

```python
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.get(username="YOUR_ADMIN_USERNAME")
user.role = User.Role.ADMIN
user.save(update_fields=["role"])
exit()
```

Sign in with that account at `/login/` to access `/manage/`. Use the Admin Users page for subsequent role and account-status changes so application safeguards and audit logging apply. Register a separate Basic User account to test borrowing.

## Main pages

| Page | URL | Access |
| --- | --- | --- |
| Landing page | `/` | Public; signed-in users redirect to their portal |
| Registration | `/register/` | Public |
| Login | `/login/` | Public |
| Personal dashboard | `/portal/` | Basic User |
| Personal profile | `/portal/profile/` | Authenticated account |
| Admin dashboard | `/manage/` | Admin |
| Admin profile | `/manage/profile/` | Admin |
| User management | `/manage/users/` | Admin |
| Maintenance | `/manage/maintenance/` | Admin |
| Reports | `/manage/reports/` | Admin |
| Audit logs | `/manage/audit-logs/` | Admin |
| System settings | `/manage/settings/` | Admin |

Use the portal sidebar to navigate to the catalog, borrowing requests, loans, and returns. Module guides below provide their detailed routes and workflows.

## Testing

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

The integrated project passed **365 automated tests** on October 24, 2026. Coverage includes stylesheet cache invalidation, landing-page links and role redirects, shared pagination, role permissions, account management, inventory availability, request approval, release, partial and damaged returns, maintenance, reports, audit logs, and borrowing settings. Tests use a separate test database.

Portal lists show 10 records per page with numbered navigation and a record-range summary. Search and filters remain in the URL when changing pages. See the [monochrome UI report](docs/UI_MONOCHROME.md) for the current shared components, modified files, test results, local commits, and browser-verification limitation. The [earlier redesign notes](docs/UI_REDESIGN.md) retain the previous visual review. The [earlier UI review](docs/UI_REVIEW.md) records pagination implementation details.

To test one module:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.accounts
```

Replace `apps.accounts` with the relevant application name.

### Optional local demo records

After creating separate active Admin and Basic User accounts, these commands can add equipment and transactions for manual testing. Replace the username placeholders with your local accounts.

```powershell
.\.venv\Scripts\python.exe manage.py seed_borrowing_demo --borrower YOUR_BASIC_USERNAME
.\.venv\Scripts\python.exe manage.py seed_loans_demo --admin YOUR_ADMIN_USERNAME --borrower YOUR_BASIC_USERNAME
```

The borrowing demo creates six available units and a pending request. The loans demo creates an approved request ready for release and an overdue loan. Both commands require `DEBUG=True`, add records to your local database, and refuse to overwrite an existing matching demo set. They use existing accounts without changing passwords or roles.

## Project structure

```text
campus-equipment-system/
├── apps/
│   ├── accounts/       # Authentication, profiles, and users
│   ├── inventory/      # Catalog, categories, and physical units
│   ├── borrowing/      # Requests, approvals, and reservations
│   ├── loans/          # Issuance, returns, and overdue tracking
│   ├── maintenance/    # Repairs and retirement
│   └── dashboard/      # Dashboards, reports, audit logs, and settings
├── config/             # Django settings and root routes
├── templates/          # Shared layouts and module pages
├── static/             # CSS and JavaScript
├── manage.py
├── requirements.txt
└── README.md
```

## Members and module guides

| Member | Branch | Deliverable | Documentation |
| --- | --- | --- | --- |
| Charles | `charles` | Accounts, authentication, and user management | [Accounts guide](apps/accounts/README.md) |
| Janelle | `janelle` | Loans, returns, and overdue | [Loans guide](apps/loans/README.md) |
| Clark | `clark` | Borrowing requests and approval | [Borrowing guide](apps/borrowing/README.md) |
| Raj | `raj` | Equipment catalog and inventory | [Inventory guide](apps/inventory/README.md) |
| Francis | `francis` | Equipment maintenance | [Maintenance guide](apps/maintenance/README.md) |
| Miah | `miah` | Dashboard, reports, audit logs, and system settings | [Dashboard guide](apps/dashboard/README.md) |

`main` contains all six completed modules. Member branches preserve their module checkpoints and include the earlier modules needed for integration; later branches contain cumulative work. Module guides also record implementation-time verification and branch history.

For new work, create a branch from the latest `main`, test the change locally, and open a pull request for review before merging.

## Deployment configuration

The committed settings are for local development: SQLite, `DEBUG=True`, and a development secret key. Before a public deployment, configure a private secret key, disable debug mode, set allowed hosts, and configure the production database, static-file serving, and HTTPS. The current settings do not automatically load a `.env` file.
