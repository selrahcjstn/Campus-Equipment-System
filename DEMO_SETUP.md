# Safe local project demonstration

The demo uses its own `demo.sqlite3`, private `.env.demo` and fictional accounts.
The normal development database is not seeded, migrated or reset by this wrapper.

## Prepare the demo

Install the pinned requirements in the project's virtual environment as described
in [README.md](README.md), then run from the extracted project directory:

```powershell
.\.venv\Scripts\python.exe scripts/demo.py setup
```

On first setup this creates private random signing and credential values in the
ignored `.env.demo`, migrates the separate database and calls the existing
transactional `seed_project_demo` command. It then verifies required counts,
scenarios and inventory relationships. Passwords are not printed.

An existing `.env.demo` is preserved on later runs. A complete existing demo is
left unchanged; an incomplete or unrelated populated database is refused. The
wrapper refuses a configuration pointing at the normal `db.sqlite3`.

## Start and sign in

```powershell
.\.venv\Scripts\python.exe scripts/demo.py runserver 127.0.0.1:8786
```

Open [the local demo](http://127.0.0.1:8786/). Use `demo_admin` for Admin or
`demo_user01` through `demo_user08` for Basic User. Read the value of
`CAMPUS_DEMO_PASSWORD` in `.env.demo` privately; all fictional demo accounts use
that value. Share credentials only through the instructor's designated private
channel. Never include the private file, password or database in Git or the ZIP.

Stop the demo server with Ctrl+C. The wrapper's environment is process-local;
normal `manage.py` commands continue to use their normal configuration.

## Verify and rehearse

```powershell
.\.venv\Scripts\python.exe scripts/demo.py verify
.\.venv\Scripts\python.exe scripts/demo.py check
```

The baseline has 3 categories, 6 catalog items, 18 physical units, 1 Admin,
8 Basic Users, 20 requests, 8 loans and 5 maintenance records. It includes
Pending, Approved, Rejected, Cancelled, Issued and Returned requests; completed,
partial and outstanding overdue loans; damaged returns; and all five physical
inventory statuses. Condition/acquisition metadata is explicitly synthetic.

Read the [Basic User guide](docs/final-submission/BASIC_USER_GUIDE.md),
[Admin guide](docs/final-submission/ADMIN_GUIDE.md) and
[rehearsal worksheet](docs/final-submission/REHEARSAL_AND_EVIDENCE.md). Use a
separate disposable copy for actions that change the prepared scenario mix. The
baseline verification requires the original scenarios to remain represented.

Historical dates are intentional demonstration data. The seed does not refresh
dates or passwords on repeat runs. Re-provision a fresh separate demo when the
presentation date makes its ready-to-issue examples expire; do not change the
ordinary validation rules or overwrite working records to refresh it.

## Build the submission ZIP

Replace section/group arguments with the real class details:

Run the package builder from the Git checkout: it uses Git's source file list.
The extracted ZIP needs no Git installation to run the application/demo.

```powershell
.\.venv\Scripts\python.exe scripts/package_submission.py --section YOUR_SECTION --group YOUR_GROUP
```

The ZIP is written under ignored `dist/`. It contains source, migrations,
requirements, setup guides, current Markdown documentation and a SHA-256 file
manifest. It excludes Git history, local environment files, databases and their
journals, virtual environments, caches, logs and local output. The older PDF
export is excluded because it predates source-document corrections; export the
final manuscript after team/adviser review if a PDF is required for submission.

Actual membership, contributions, peer/leadership records, user acceptance,
policy approvals and presentation evidence must be supplied by the team. A
passing application test suite cannot establish those facts.
