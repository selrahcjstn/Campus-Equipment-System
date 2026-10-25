# Admin guide

## Overview and account management

Sign in with an active Admin account. The dashboard shows pending requests, available units, active loans and overdue loans. Date filters control the monthly issued-loan and category-usage charts. Chart data tables provide text alternatives.

Users provides account search, status changes and an account's borrowing history. Keep at least one active administrator. Do not use personal credentials or actual student data in the fictional course demo.

## Categories, catalog and physical units

Create or edit a category using the quick form dialog. Archive categories that should no longer be assigned to new equipment; restore them when needed. Archiving retains existing relationships. Referenced category deletion remains protected, and archived names are still subject to duplicate-name checks.

Equipment Inventory contains catalog items and individual physical units. A catalog item requires a category. Each physical unit has a unique identifier, condition, acquisition date and separate inventory status. Enter real verified metadata for actual assets. Unknown legacy metadata must not be replaced with guessed dates. Use category, equipment, inventory status and search filters together, then Reset filters to clear them.

Archive catalog items to stop new Basic User borrowing while retaining history. Resolve active reservations and issues before archive/retirement actions that require it. Simple create/edit dialogs have functional direct URLs as fallbacks; dismiss with Cancel or Escape and confirm any unsaved-change warning.

## Review and approve

1. Open Borrowing Requests. Combine search, status and submission-date range filters.
2. Review the purpose, borrower, quantities, desired due date and current availability.
3. Record an approval reason and confirm approval. The service selects exact physical units and reserves the full request atomically. Insufficient stock causes the whole approval to fail.
4. To reject a Pending request, record a rejection reason. To cancel an Approved request before issue, use cancellation; the service releases its reservations.

The one-to-three distinct-item limit cannot be increased beyond three. Settings for quantity per item and duration remain configurable within supported ranges. Approved and issued records retain recorded terms.

## Due-date revision and issuance

For an Approved request awaiting issue, Revise due date accepts a new policy-valid date and mandatory reason, including when the original approved due date has expired. It records old/new dates, Admin, timestamp and reason. The original request-based duration limit still applies; if that window has passed, submit a new request. Revisions are rejected after issue.

At handover, use the release workflow. The service checks allocations, borrower eligibility and that the agreed due timestamp has not expired, then copies the final approved date into the loan. Print the borrowing slip and verify its borrower and physical-unit identifiers.

## Returns, overdue and maintenance

Returns and Overdue supports per-unit returns. Record the return condition and permitted notes. A partial return leaves remaining units outstanding; the last return completes the loan. A damaged unit enters Maintenance with a maintenance record. Completed loans are never overdue; outstanding loans become overdue when the local Manila calendar date is later than the due date.

New maintenance reports start Reported. Use Start repair to confirm the transition to In Progress. Use Complete repair to record the required repair action and the supported outcome: a repaired unit returns to Available, while a retired unit remains unavailable. Use View record for finished work. Existing edit actions permit corrections within the workflow's constraints. Reserved or Issued units cannot receive a new maintenance report through the idle-unit workflow.

## Reports, audit and settings

Reports combines search/date/status filters and exports the matching data to CSV. Audit Logs records administrative decisions and changes, including approval rationale, due-date revisions, returns and maintenance actions. System Settings configures future request policies within validated limits. No payment, fine or procurement workflow is included.

## Fictional local demo

Run the setup and verification in [DEMO_SETUP.md](../../DEMO_SETUP.md). Sign in as `demo_admin` using the private password in `.env.demo`. Use the dedicated demo server and database for rehearsal. Keep `.env.demo`, normal `.env`, databases and credentials out of the public ZIP and repository.
