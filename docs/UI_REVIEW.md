# Portal UI review — October 23, 2026

The Admin and Basic User interfaces retain the existing palette, typography,
navigation, permissions, and business workflows. Changes refine the shared
presentation and list pagination rather than replace the design system.

## Improvements and affected components

- Shared layout: portal content is capped at 1280px; section and heading spacing
  is more consistent. Headings and action groups wrap naturally on small screens.
- Tables: shared column roles give descriptions and equipment names room to wrap,
  with compact numeric, date, status, identifier and action columns. Table captions,
  headers, row spacing, subtle borders, hover and keyboard-focus states are aligned.
- All 19 concrete table templates have labelled, keyboard-focusable horizontal
  scrolling regions. Scrolling remains inside the table instead of widening the page.
- Table buttons have a consistent compact presentation, with 40px minimum heights
  for coarse-pointer devices. Existing actions, URLs and confirmation controls remain.
- Forms: password/simple confirmation forms cap at 560px, ordinary editors and
  profile/settings forms at 720px, and multi-row borrowing/return forms at 960px.
  Related profile information and help messages share the matching width.
- Inputs: normal, hover, focus, read-only, disabled and validation-error states use
  the existing tokens. Focused filter errors retain their red border and outline.
- Empty messages share one `empty-state` style. Repeated module-specific empty
  and pagination styles have been removed. Badge sizing is consistent.
- Compact, card-free search/filter toolbars and the landing page's existing scroll
  header remain available.

The main shared implementation is in `static/css/design-system.css`,
`templates/components/pagination.html`, and the existing input/filter components.
`templates/UI_INTEGRATION.md` documents how to reuse the presentation classes and
pagination include.

## Pagination coverage

All browsing lists use Django's built-in `Paginator`, with **10 records per page**:

| Area | Lists |
| --- | --- |
| Inventory | Basic User catalog; Admin categories, catalog, physical units and per-equipment unit lists |
| Borrowing | Personal requests and the Admin request queue |
| Loans | Personal active loans, completed history, approved requests awaiting release, and Admin returns/overdue |
| Maintenance | Current maintenance units, maintenance records and a unit's maintenance history |
| Accounts | Admin user list and each user's separate request/loan history tables |
| Dashboard | Admin reports and audit logs |

Every list renders a `Showing X–Y of Z records.` summary. Empty results show
`Showing 0–0 of 0 records.`. Multi-page results add Previous, Next and numbered
links; large page ranges are elided instead of generating hundreds of links.
Current and unavailable navigation states are explicit and keyboard accessible.

The shared `pagination_links` template tag is provided by the existing Accounts
app. It copies the current query string, preserving search, filters, sort/other
parameters, repeated query values, and independent page state. It also includes
effective bound-form defaults so the initial Pending request queue or Active
catalog view does not silently change on page two. Link rendering adds no ORM
queries and reuses the paginator's cached count.

- Maintenance retains independent `page` and `units_page` parameters.
- Account history retains independent `request_page` and `loan_page` parameters.
- Changed filters restart list pagination through the existing GET toolbar.
- `get_page()` handles missing/non-numeric values with the first page and other
  out-of-range values with the last page, without an error response.
- CSV export still includes every matching record, independently of report paging.

Dashboard KPI/recent/upcoming summaries and daily chart data keep their deliberately
bounded summary context. Equipment allocations, printable slips and individual
loan/return unit tables continue showing the entire transaction so review and
confirmation do not conceal units on another page.

## Verification

- Django system checks pass and the migration dry run detects no model changes.
- All **362 automated tests pass**. After the form refinements, the affected
  Accounts/Inventory/Maintenance/Dashboard tests passed (246), followed by the
  Borrowing/Loans tests (116).
- Existing pagination tests now verify 10-row pages, filtered links and the final
  one-row third page for 21-record datasets. Reports still export all matching rows.
- Four new shared-component tests cover repeated query values, independent table
  page keys, effective defaults, elided number ranges, empty/first/last pages and
  invalid page requests. These tests prohibit database queries.
- Browser review covered 15 Admin core pages at 1440, 768 and 390px, and 8 Basic User
  core pages at 1440, 768, 390 and 320px: **77 page/viewport checks**, with no
  page-level horizontal overflow.
- Browser interactions verified combined search/availability filtering, numbered
  page links using Enter, record summaries, empty results, reset, and horizontal
  table scrolling with arrow keys. Desktop profile/settings widths measured 720px;
  password forms measured 560px and all shrank to mobile width.
- Invalid mobile date ranges kept server validation messages, expanded the filter
  disclosure and displayed red focus/error borders. Refreshing the local preview
  asset cache confirmed the final stylesheet.

Browser checks used an isolated SQLite copy. Disposable preview inventory supplied
multiple pages for navigation tests; real accounts, inventory, loans and settings
were not changed. No dependencies, models, migrations or business rules were added
or altered. Interactive checks sampled the main presentation states; the existing
automated suite provides CRUD, permission and workflow regression coverage rather
than manually repeating every possible transaction in the browser.

## Implementation commits

| Commit | Change |
| --- | --- |
| `bc10fe4` | Preserve the completed glass landing header and corrected scroll direction |
| `357c3c7` | Refine shared layout, column widths, table spacing and keyboard scrolling |
| `cef709b` | Add reusable server-side pagination and update regression coverage |
| `0651260` | Bound forms and unify inputs, buttons, badges, empty and error states |

No unresolved functional issues were found during verification. These changes are
committed locally; no remote push was performed for this review.
