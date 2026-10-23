# System-wide UI redesign — October 24, 2026

The existing Django application now uses a cohesive, neutral dashboard design.
All work is in templates, CSS, and documentation. Models, migrations, views,
authentication, permissions, services, routes, and JavaScript workflows are unchanged.
This document supersedes the visual sizing guidance in the earlier UI review.

## Design and reusable components

- The shared palette uses white surfaces, a `#F8FAFC` page background, neutral
  zinc text, soft gray borders, and the existing restrained navy/blue brand colors.
- Portal content caps at 1200px, the sidebar is 240px, desktop page padding is
  24px, cards use 20px padding, and section gaps are 20px. Mobile padding and
  section gaps reduce to 16px. Navigation has a subtle active surface, border,
  and inset indicator; the header account link opens the appropriate profile.
- Tables retain `#FAFAFA` headers, white bodies, `#E5E7EB` dividers, muted
  medium-weight headers, and `#F9FAFB` row hover/focus. Content-based column
  roles keep IDs, dates, roles, quantities, statuses, and actions compact.
  Equipment names and descriptions wrap. No equal-width columns or zebra stripes
  are imposed. All table regions, including loan unit history, support keyboard
  scrolling and have accessible labels.
- Card-free filter toolbars use compact search inputs, an inset search icon,
  bounded dropdowns, nearby reset links, mobile disclosures, and existing chips.
  Debounced search, automatic GET submission, and server validation remain intact.
- `components/metric.html` supplies the same metric presentation to both
  dashboards and Maintenance. Shared `facts-grid` styles replace duplicated
  account, request, loan, and maintenance definition-list styling.
- Portal editors and profile/settings content cap at 640px; passwords/simple
  forms and dialogs at 520px; multi-item request/return forms at 880px. Login
  caps at 420px and registration at 520px. All shrink to the available space.
- Buttons, inputs, badges, alerts, dialogs, and empty states use consistent sizing,
  borders, typography, focus states, and restrained transitions. Mobile and
  coarse-pointer controls use 40px minimum heights; reduced motion is respected.
- The landing page has a tighter hero, restrained illustration surface, compact
  process cards, and the existing glass header with its scroll behavior. Auth
  pages use a neutral split layout without decorative circles.
- The Basic User catalog uses compact cards that avoid stretching a single item
  across a large desktop row. The new-request screen places a bounded equipment
  chooser beside the form on wide screens and stacks them on smaller screens.
  Original formsets, selection handlers, field names, and validation are retained.

## Page coverage

Shared styles apply through the existing base templates to every page. The
browser review also visited each of these screen types with live Django data:

| Area | Screens reviewed |
| --- | --- |
| Public | Landing, login, registration |
| Accounts | Profile and password in both portals; Admin user list, user detail, activation, deactivation, and role review |
| Inventory | Basic catalog and equipment detail; Admin categories, create/edit/delete category, inventory, create/edit equipment, equipment detail, archive/restore, physical-unit list, add/edit unit, and retirement review |
| Borrowing | Personal list, new request, detail, cancellation; Admin queue, detail, approval, rejection, and cancellation |
| Loans | Personal active loans, completed history, and loan detail; Admin release queue, release review, loan detail, printable slip, returns/overdue list, and return editor |
| Maintenance | Dashboard, create, unit history, detail, update, repair completion, and retirement review |
| Dashboard | Both dashboards, reports, audit logs, and settings |

The complete review covered **43 Admin screens, 12 Basic User screens, and 3
public pages**, each at **1440, 768, 390, and 320px**: 232 page/viewport checks.
No page-level horizontal overflow was found. A four-action Maintenance header
was tightened to two columns at small widths and rechecked at 320px.

## Pagination and behavior

All applicable browsing lists already use Django `Paginator` with 10 records
per page and the shared pagination component. This redesign preserves that
implementation, including record summaries, numbered/elided links, current-page
labels, effective filter defaults, repeated query values, sorting parameters,
and independent table page keys. Invalid page values remain graceful.

Dashboard summaries and individual transaction allocation/unit tables retain
their complete context. CSV exports continue including all matching records.
No client-side framework, dependency, extra database query, or route was added.

## Verification

- All **362 existing tests pass**. Affected suites were also run before their
  corresponding logical commits: navigation/profile, shared pagination and
  requests/loans, Accounts/Maintenance, Dashboard/Maintenance,
  Inventory/Borrowing/Dashboard, and landing/authentication.
- Django system checks pass; the migration dry run reports no changes.
- All **94 templates** compile. All six existing JavaScript files pass syntax
  checks. Diff whitespace checks pass.
- Browser checks verified combined search/availability/state filters, numbered
  page navigation, preserved query strings and record ranges, mobile disclosure
  and chips, equipment selection, and server-side date validation.
- A normal Django GET request verified the non-JavaScript filter form and submit
  fallback, sorting/query preservation, and malformed/out-of-range pagination.
- Mobile drawer opening, Escape dismissal, profile navigation, confirmation
  opening/cancellation, and keyboard horizontal table scrolling were checked.
  Dialogs were cancelled without changing settings or cancelling requests.
- Text contrast checks pass 4.5:1 for normal text: primary body 17.72:1,
  table headers 7.41:1, muted text on the page background 4.62:1, success badges
  4.79:1, error badges 5.91:1, and info badges 4.75:1.

Browser checks used an isolated SQLite copy with disposable equipment and
transactions created through the existing services. The real project database,
accounts, and transactions were not changed. Preview asset/template caching was
disabled at runtime so the browser reviewed the current files; project settings
were not modified.

The existing automated suite covers permissions and business transitions;
browser verification samples visible data, error, empty, and confirmation
states rather than repeating every possible transaction manually. Print-slip
markup and print styles were retained; physical printer output was not tested.
No unresolved functional issues were found. No remote push was performed.

## Implementation commits

| Commit | Change |
| --- | --- |
| `185e11f` | Refined shared design system and spacing |
| `7dec60d` | Application shell, navigation, and page headers |
| `9d7c760` | Shared tables, column roles, filters, and pagination appearance |
| `91da517` | Forms and interactive components |
| `e208883` | Admin metrics, charts, Maintenance, and shared detail layouts |
| `aa0fb01` | Basic User dashboard, catalog, and borrowing screen |
| `f959756` | Landing and authentication pages |
| `959122b` | Responsive layouts and touch controls |
