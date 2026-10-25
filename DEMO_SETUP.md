# Safe local project demonstration

This guide creates a separate fictional demonstration database. It never seeds,
clears, migrates, or changes the normal `db.sqlite3`. The command refuses that
working database and refuses any partially populated database.

## 1. Configure a separate database

Create the private configuration as described in the root [README](README.md).
Use a new filename for the demonstration database. From PowerShell:

```powershell
$env:DJANGO_DATABASE_PATH = (Join-Path (Get-Location) 'demo.sqlite3')
Copy-Item .env.example .env -ErrorAction SilentlyContinue
```

Set a new random `DJANGO_SECRET_KEY` in the ignored `.env` before using this
database. The environment variable takes precedence over `.env`. The demo
database filename ends in `.sqlite3` and is excluded by `.gitignore`.

## 2. Migrate and create fictional records

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

The fixture password is requested as a secure console value. It must be at least
12 characters and pass Django's password validators. It is never printed,
written to a fixture, or supplied as a command-line argument.

```powershell
$secure = Read-Host 'Choose a private fictional demo password' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:CAMPUS_DEMO_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    .\.venv\Scripts\python.exe manage.py seed_project_demo --confirm-isolated
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Item Env:CAMPUS_DEMO_PASSWORD -ErrorAction SilentlyContinue
}
```

The command creates 3 categories, 6 catalog items, 18 physical units, 1 Admin,
8 Basic Users, 20 requests, 8 loans, and 5 maintenance records. The accounts
are `demo_admin` and `demo_user01` through `demo_user08`. Each receives the
private password entered above. These are synthetic identities and asset codes;
they do not refer to real students, campus assets, or contact details.

The requests cover Pending, Approved, Rejected, Cancelled, Issued, and Returned
states. Loans include completed history, a current partial return, an outstanding
overdue loan, and an active loan. A damaged return opens Maintenance; other
maintenance records demonstrate Reported, In Progress, Repaired, and Retired
outcomes. Historical request/approval/issue dates are adjusted only for rows the
seed command created, and remain within the seven-calendar-day policy. Current
submission and issuance validation is unchanged.

Run the seed command a second time to verify idempotent behavior. It confirms
the complete dataset and leaves every row and password unchanged. The command
refuses incomplete or unrelated data; use a new database file for a fresh seed.

## 3. Verify the fixture

The isolated regression test `apps.inventory.test_demo.ProjectDemoTests` checks
all required counts, request/loan states, partial and damaged returns, overdue
classification, each physical inventory status, relationships, active
allocations, password hashing, foreign keys, rollback, and repeat-run safety.
Run it with:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.inventory.test_demo
```

For a manual walkthrough, use both roles to browse by category, submit and track
a request, review availability and the reasoned decision, cancel an unissued
approval, release the ready request, return units partially, process damaged
equipment through Maintenance, inspect overdue reports/CSV, and search Audit
Logs. The dashboard date filter supports up to 366 inclusive calendar dates;
choose a period that includes the historical issued loans to see the monthly
chart.

## 4. Finish the demo session

Stop Django and remove the environment override when finished:

```powershell
Remove-Item Env:DJANGO_DATABASE_PATH -ErrorAction SilentlyContinue
```

The `demo.sqlite3` file is local and ignored by Git. Do not attach the database,
password, `.env`, real user data, or private account details to a public ZIP or
repository. Share credentials only through the instructor-designated channel.
Use a fresh private signing key before sharing the demo database; rotating the
key signs out existing sessions and invalidates signed tokens but preserves DB
records and passwords.
