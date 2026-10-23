# Monochrome UI report — October 24, 2026

The existing Django application now shares a minimal monochrome theme across
public pages, authentication, the Admin portal, and the Basic User portal.
Changes are limited to CSS, existing template presentation, and documentation.
No models, migrations, views, routes, permissions, authentication, services,
JavaScript, dependencies, or business rules changed.

## Design

| Token / component | Presentation |
| --- | --- |
| Primary text and buttons | `#18181B`; button hover `#27272A`; white button text |
| Page / card | `#FAFAFA` / `#FFFFFF` |
| Borders | `#E4E4E7` |
| Secondary text | `#71717A` |
| Table headers and hover | `#F4F4F5`; muted `#52525B` header text |
| Focus | Black outline; invalid fields retain red borders and error text |
| Navigation | Neutral icons, subtle gray active surface, no colored inset stripe |
| Tables | 14px body, 13px medium headers, 12px × 16px cells, content-based column roles |
| Pagination | Compact links; current page has a black background and `aria-current` |
| Inputs and buttons | Shared 36px desktop controls, 6px control radius, 40px touch targets |
| Statuses | Existing labeled semantic badges; general charts and information surfaces are neutral |

Cards and tables use subtle borders. Cards have no shadow. General action
buttons, including destructive confirmations, are black; descriptive action
labels and existing confirmation dialogs remain intact. Error, warning, and
success feedback remains semantic. No zebra stripes, gradients, or framework
replacement were introduced.

Portal content uses the available workspace with equal 24px desktop / 16px
mobile padding. Sidebar width remains 240px. Editors cap at 640px, password
forms at 520px, multi-item forms at 880px, login at 420px, and registration at
520px. Profile, Settings, and review pages deliberately retain the full-width
containers requested earlier. Their grouped fields use responsive grids;
standalone text fields inside these full-width forms still cap at 640px.

Shared fact tiles and six stock-count boxes preserve the earlier layout fixes.
Audit columns retain readable action/entity widths and split date/time lines.
Basic User shortcuts have compact neutral outlines; catalog availability has a
bounded inset surface. Mobile filters use an adaptive grid, removable chips
have 40px targets, and 16px mobile input text avoids automatic input zoom.

The public landing illustration, glass header and scroll behavior, original
links, authentication layout, formsets, status labels, CSRF fields, confirmation
handlers, search debounce, GET fallback, query parameters, sorting, pagination,
and printable loan slips remain in place. Source-versioned stylesheet URLs
continue to prevent stale CSS after updates.

## Modified files

Paths are relative to the repository root.

| Files | Purpose |
| --- | --- |
| `static/css/design-system.css` | Tokens, shell, navigation, cards, fact tiles, tables, pagination, forms, focus, responsive input sizing |
| `static/css/filters.css` | Neutral filter controls, black error focus, responsive grid and chip targets |
| `static/css/dashboard.css` | Neutral charts, dashboard shortcuts, settings field grid, readable audit columns |
| `static/css/inventory.css` | Stock-count boxes, responsive count grid, catalog hierarchy and availability |
| `static/css/maintenance.css` | Readable issue and repair-note boxes |
| `static/css/landing.css`, `static/css/auth.css` | Monochrome public surfaces, process icons, badges, authentication accents |
| `templates/accounts/admin/action.html`, `templates/accounts/profile.html` | Full-width review/profile containers and existing account facts |
| `templates/dashboard/admin/audit_logs.html`, `templates/dashboard/admin/settings.html` | Audit column roles and semantic time markup; grouped settings fields |
| `templates/inventory/_filters.html`, `templates/inventory/admin/action.html`, `templates/inventory/detail.html` | Correct unit-search placeholder, archive/review facts and availability grouping |
| `templates/borrowing/action.html`, `templates/loans/admin/release.html` | Full-width review form containers |
| `templates/maintenance/detail.html`, `templates/maintenance/history.html`, `templates/maintenance/resolve.html` | Grouped issue/record/unit details and full-width reviews |
| `README.md`, `templates/UI_INTEGRATION.md`, `docs/UI_REDESIGN.md`, `docs/UI_MONOCHROME.md` | Current integration guidance, verification, and historical report distinction |

The layout fixes in `7b9554c` carry forward the earlier requests for boxed counts,
full-width settings/profile/reviews, equal outer padding, and readable audit rows.
All later style commits implement the monochrome redesign.

## Verification

- Full regression suite: **365 tests passed** (`manage.py test --noinput`).
- `manage.py check`: no issues.
- `manage.py makemigrations --check --dry-run`: no changes detected.
- All **94 HTML templates compile**.
- All **21 table definitions** use shared `data-table` styling.
- All CSS variable references resolve; module stylesheets introduce no local hex colors.
- Server-render audit: **58 page types returned HTTP 200** — 43 Admin, 12 Basic
  User, and 3 public. All rendered local stylesheet URLs were versioned; all
  rendered table regions had accessible labels and keyboard focus; POST forms
  retained CSRF fields. The preview database was loaded into memory for this
  audit; the project database was unchanged.
- Existing relevant suites cover combined search/status/date filters, reset
  links, invalid and empty results, preserved pagination parameters, independent
  pagination, record isolation, form validation, confirmations, and workflows.
- Text contrast checks: main text 16.97:1, secondary text 4.63:1, table headers
  7.03:1, primary buttons 17.72:1, Approved 4.79:1, Pending 17.08:1,
  Rejected/Overdue 5.91:1, On loan 4.75:1, Inactive 7.03:1. All checked pairs
  exceed WCAG AA's 4.5:1 requirement for normal text.
- Whitespace checks pass using `git -c core.whitespace=cr-at-eol diff --check`.

### Verification limitation

**Live browser verification of the monochrome changes could not be completed.**
Automatic browser approval review failed because the account usage limit was
reached. The blocked browser action was not executed, and its approval check
was not bypassed. The earlier redesign and layout work had browser coverage;
those results must not be interpreted as visual verification of this theme.
Responsive layout, keyboard focus, mobile filter expansion, and no-JavaScript
behavior were reviewed in source and exercised where covered by the existing
suite, but fresh browser screenshots and interaction checks remain outstanding.

## Local commits

No changes were pushed to the remote repository.

| Commit | Improvement |
| --- | --- |
| `7b9554c` | `style: expand portal layouts and group detail summaries` |
| `96fc563` | `style: establish monochrome design tokens` |
| `c645e59` | `style: modernize shared layout and navigation` |
| `a5474ec` | `style: redesign tables and pagination` |
| `6f321fe` | `style: refine forms and interactive components` |
| `8e50af2` | `style: apply monochrome theme to admin portal` |
| `110e003` | `style: apply monochrome theme to user portal` |
| `d0e2386` | `style: refine monochrome landing and authentication pages` |
| `10cd4ca` | `style: polish responsive layouts` |

The documentation commit following these changes records this report and the
updated integration guide.
