> Historical report: this records an earlier audit/implementation pass. For current verified status, see [SYSTEM_COMPLIANCE_AUDIT.md](SYSTEM_COMPLIANCE_AUDIT.md) and [SUBMISSION_READINESS_REPORT.md](docs/final-submission/SUBMISSION_READINESS_REPORT.md).

# PDF compliance implementation report

Date: 25 October 2026 (Asia/Manila). Scope: confirmed application gaps from the
prior `SYSTEM_COMPLIANCE_AUDIT.md`; the live database was not seeded or migrated.
The separately authorized commit and GitHub push are recorded in the final task
summary.

## Changes implemented

- **Private configuration:** removed the literal signing key from tracked
  `config/settings.py`. It loads `DJANGO_SECRET_KEY` from the process environment
  or ignored `.env`; explicit environment settings control debug, hosts, and an
  optional SQLite database path. Added a dependency-free loader and safe
  `.env.example`. The local private file retains the previous development key
  so existing local sessions are not forcibly invalidated. Because that key
  appeared in earlier Git history, replace it before sharing/deployment; key
  rotation signs out sessions and invalidates signed tokens.
- **Request review (A3):** Admin queue date ranges combine with search/status,
  use inclusive Asia/Manila dates, validate errors, reset cleanly, and retain
  query parameters during pagination. Review pages show per-item available
  physical units next to the requested count. The approval service still
  reserves under its atomic revalidation. Admin approval now requires a reason;
  it is saved with the request, shown in the detail, and included in the actor,
  time, and decision audit record.
- **Admin dashboard (A7):** cards now include Available units, Pending requests,
  Active loans, and Overdue loans. New ORM charts group real issue records by
  local month and count each issued physical unit once by its equipment's
  category. Returned units remain historical use. Both charts share the
  validated date range, handle empty results, and have accessible data tables.
  The existing daily request chart and physical-status chart remain available.
- **Overdue classification (A5/BR6):** loan labels, overdue filters, active
  loan views and KPI calculations use the start of the current Asia/Manila
  calendar day. A deadline later the same day is not overdue; it becomes overdue
  at the next local midnight. Day totals still use local date differences and
  require outstanding units. Equipment issue still rejects an expired agreed
  timestamp, as required by BR5.
- **Database integrity:** added a database constraint limiting account roles to
  `BASIC_USER` and `ADMIN`. Its migration checks for unsupported legacy roles
  first and stops without altering them if any exist. Existing category
  relationships and unknown legacy condition/acquisition dates are preserved;
  no values were fabricated and no destructive category migration was made.
- **Demonstration setup:** added a repeatable fictional dataset command that
  requires `DEBUG=True`, an explicit confirmation flag, a separate empty
  database and a private validated password. It builds records using existing
  request, approval, issuance, return and maintenance services. It rolls back
  fully on failure and leaves a complete existing dataset unchanged on rerun.
  Updated the two smaller existing seed commands to create categorized,
  validated units with explicitly synthetic metadata.

## Migrations

- `apps/accounts/migrations/0002_user_role_constraint.py` — preflight legacy
  role values; add a two-role database constraint.
- `apps/borrowing/migrations/0003_borrowingrequest_approval_reason.py` — add a
  nullable-in-practice/blank legacy-safe approval reason field. Old decisions
  remain blank; the migration invents no historical reason.
- Inventory migrations `0003_category_archiving.py` and
  `0004_unit_condition_and_acquisition_date.py` were existing user work and
  were preserved as part of the implementation.

## Verification

- **516 automated Django tests passed** on the isolated test database.
- Added request filter/reason/availability/rollback and migration-safety tests;
  dashboard KPI, monthly usage, category, timezone and return tests; role and
  environment tests; and demo count, relationship, rollback, credential, and
  idempotency tests.
- Django system checks: **0 issues**. `makemigrations --check --dry-run`: no
  model changes outstanding. `pip check`: no broken requirements.
- Demo fixtures were created and audited inside the isolated test database; all
  PDF minimum counts/scenarios, valid role/status relations, hashed passwords
  and foreign keys passed. The seed command does not run against `db.sqlite3`.
- The development database hash before/after test execution was unchanged.
- Last-unit concurrent-approval tests from the prior audit passed 30/30 races;
  the approval service signature was updated in all project callers and tests.

## Remaining limitations

- The existing `Equipment.category` field remains nullable for legacy
  compatibility. Normal catalog create/edit validation requires a category,
  the fixture command always supplies one, and the current development data
  had no uncategorized equipment. A non-null conversion needs a separately
  reviewed legacy-data/import plan.
- The pre-existing working database still has fewer than the PDF's minimum
  demonstration counts and has no rejected, partial, damaged-return, or current
  overdue scenarios. It was deliberately not modified. Follow `DEMO_SETUP.md`
  with a separate database to create and verify a complete demo.
- Existing historical units still have unknown condition/acquisition dates.
  The new seed has explicit synthetic values; old records remain NULL until
  verified acquisition data is supplied.
- The final ZIP, instructor-channel credentials, actual team contributions,
  rotating-leadership/peer records, presentation/Q&A, usability participant
  results, and rubric evidence still need team confirmation. Architecture,
  ERD, workflow diagrams, and legal/ethics discussion exist in
  `docs/final-submission/`; legal applicability and institutional AI-policy
  claims need adviser/team review.
- The previous signing key remains in existing Git history. Do not reuse that
  key outside the preserved local setup. Replacing the local key invalidates
  current sessions; repository history rewriting was not done.

The source implementation was already committed locally before the separate
commit-and-push request; the final documentation commit and push are summarized
in the task response.
