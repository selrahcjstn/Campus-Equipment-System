# Remaining-task implementation and verification

Date: 25 October 2026, Asia/Manila.

## Completed work

- Added `scripts/demo.py` to prepare, verify and run the existing fictional demo through its own `.env.demo` and `demo.sqlite3`. Saved credentials are preserved, inherited normal-app database settings cannot redirect the wrapper, and the working `db.sqlite3` is refused.
- Provisioned and migrated the separate demo database, ran the existing service-based seed, repeated setup successfully, and passed all 19 read-only verification checks.
- Rotated the private local `.env` signing key and generated a separate private demo key. Keys and passwords were not printed or committed. Already-running development processes must be restarted to load the rotated normal key. Old Git history was not rewritten.
- Added Basic User/Admin operating guides, a rehearsal/evidence worksheet and a future-technology design evaluation. Worksheets explicitly require actual team evidence rather than asserting activities occurred.
- Added a source-only ZIP builder with a SHA-256 manifest, explicit private-data exclusions, local-secret detection and archive integrity verification. The earlier PDF export is excluded until re-exported from final approved sources.
- Added seven tooling safety tests covering demo configuration isolation, saved credential preservation, refusal of existing/unrelated databases, archive exclusions, credential-leak rejection and path-safe metadata. An additional ORM integration test verifies that the read-only demo checker rejects active allocations on Pending requests without repairing or altering them.

## Verified fictional demonstration baseline

| Required data | Verified count/scenario |
| --- | --- |
| Categories / catalog / physical units | 3 / 6 / 18 |
| Admin / Basic Users | 1 / 8 |
| Borrowing requests / issued loans / maintenance records | 20 / 8 / 5 |
| Required transaction examples | Rejected and Cancelled requests; completed, partial and outstanding overdue loans; damaged returns |
| Physical-unit status mix | 10 Available, 1 Reserved, 3 Issued, 3 Maintenance, 1 Retired |
| Metadata | All demo units have explicitly synthetic condition/acquisition values and valid category relationships |
| Integrity | No duplicate active reservations; active allocation statuses match; foreign-key check passes |

These counts come from `demo.sqlite3`, not the old working-database snapshot or a transient test fixture. No historical development metadata was fabricated.

## Verification results

- Separate verification environment: all pinned requirements installed successfully. The ZIP extracted into a separate directory and reproduced setup, migrations, demo verification and system checks. The complete final suite passed **524 tests in 54.474 seconds**.
- Seven script safety tests passed. The first sandbox attempt could not write to the OS temporary directory; rerunning with a writable local temporary directory passed.
- An existing due-revision concurrency test failed in the first fresh run because it assumed a competing cancellation would always succeed. SQLite may reject either writer with a lock conflict. The tests now verify no partial writes when cancellation/issuance receives that conflict, then retry and verify the terminal state. They distinguish expected locks/validation from unexpected database exceptions. **Thirty repeated race tests passed** after this correction; production services and business rules were unchanged.
- Browser checks completed: desktop/mobile Admin dashboard; tablet request table dates/scrolling and loan summary; mobile navigation Enter/Escape and focus restoration; category dialog initial focus and duplicate-name field validation; logout Escape/Cancel restoration; mobile catalog and registration; desktop four-column catalog; preselection, three-item cap and preservation of quantity/purpose across request steps. New request redirects to the catalog. An unsaved-change browser prompt initially blocked automation and was manually dismissed before checks resumed. Full screen-reader and physical print-preview verification remain outstanding.
- The normal development database byte fingerprint remained **unchanged**. The demo verification passed after browser checks; no borrowing records were added by the UI walkthrough. Django checks, migration consistency and dependency checks passed.

## Remaining evidence and finalization

- Supply the real section/group and team identifiers for the final archive name/title page. The initial archive uses explicit `Section` and `Group` placeholders.
- Have the team/adviser verify legal applicability, institutional AI policy, actual member contributions, peer/leadership records, participant acceptance results, presentation/Q&A evidence and rubric artifacts. The application cannot produce historical evidence of activities that were not recorded.
- Deliver the prepared fictional credentials privately through the instructor's designated channel. The ZIP includes the reproducible setup, not passwords or a database.
- Re-export the manuscript PDF after final team review if required. Current Markdown documentation is authoritative.
- New installations use private keys; rotate any other installation still using the old historical key. Restart any already-running normal development server to load the locally rotated key.

No application models, migrations, borrowing rules or allocation workflows were changed in this remaining-task pass.
