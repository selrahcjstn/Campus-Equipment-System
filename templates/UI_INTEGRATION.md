# Campus Equipment UI

The templates are in the root `templates/` directory and assets are in the
root `static/` directory. Django discovers them through `TEMPLATES[0]['DIRS']`
and `STATICFILES_DIRS`. No views, forms, models, URL routes, or database files
were changed by the template centralization.

## Page layouts

Extend `base_user.html` for Basic User pages and `base_admin.html` for Admin
pages. Both extend `base_app.html` and `base.html`. Authentication pages extend
`base_auth.html`. Blocks available to module owners:

- `title`: browser title
- `content`: module content
- `modals`: dialogs outside the main content
- `page_styles`, `page_scripts`: page-specific static assets

```django
{% extends "base_user.html" %}
{% block title %}My Loans | Campus Equipment System{% endblock %}
{% block content %}
    {# Render the module's existing content here. #}
{% endblock %}
```

Place page styling in its own static CSS file; reuse the variables in
`static/css/design-system.css`. Use `section-stack` for 20px section spacing and
`content-grid` for a responsive grid with 16px gaps. Mobile section gaps are 16px.
Portal content fills the available workspace with equal 24px desktop padding
and 16px mobile padding. Keep long editors bounded with the form-width classes.
Inter loads from Google
Fonts with a sans-serif fallback if the font service is unavailable.

Load `ui_assets` alongside `static` in templates that link stylesheets, then use
`{% ui_asset 'css/dashboard.css' %}` for the stylesheet URL. The shared tag adds
the source file's modification version so updated templates cannot retain stale
browser-cached CSS. Unchanged files keep stable URLs and remain cacheable.
The configured static storage remains responsible for the asset URL; collected
assets without a local source keep their normal storage URL.

## Monochrome tokens

Use the shared variables rather than page-specific colors. Primary text and
buttons use `#18181B` with `#27272A` hover; page backgrounds use `#FAFAFA`, cards
use white, borders use `#E4E4E7`, secondary text uses `#71717A`, and table headers
and hover surfaces use `#F4F4F5`. Focus rings are black, including invalid fields;
validation borders and messages retain their error color. Colored status badges
and status chart series always have readable labels. General information alerts,
links, charts, navigation, and actions remain neutral.

## Navigation integration

The base layouts automatically select navigation using the authenticated user's
`role`: `BASIC_USER` receives `components/user_nav.html`, and `ADMIN` receives
`components/admin_sidebar.html`. Anonymous users and unknown roles receive no
sidebar. This is presentation only; module owners retain responsibility for their
existing view permissions. The `content` block stays empty until a child page
supplies its own content. Ownership and route mappings are in `NAVIGATION.md`.

Navigation is presentation only. Each item attempts `{% url route as resolved_url %}`.
Missing route names render non-interactive items marked “Soon”; they do not
produce dead links or `NoReverseMatch` errors. The user Dashboard resolves
`user_dashboard` at `/portal/`, and the Admin Dashboard resolves
`admin_dashboard` at `/manage/`. Both now use role-protected Dashboard views:
Basic Users receive their personal borrowing summary; Admins receive live KPIs
and charts. Inventory, Borrowing, Loans, Maintenance, Reports, Audit Logs,
System Settings, Users, My Profile and Password Change are implemented on this
branch. The authentication redirects remain unchanged.

Update the `route` value in the appropriate navigation template to match your
module's actual route name, including any namespace. These names are integration
slots, not requests to create new backend endpoints:

| Template | Item | Route slot |
| --- | --- | --- |
| `components/user_nav.html` | Dashboard | `user_dashboard` |
| | Equipment Catalog | `equipment_catalog` |
| | My Borrowing Requests | `my_requests` |
| | My Loans | `my_loans` |
| | Borrowing History | `borrowing_history` |
| | My Profile | `my_profile` |
| `components/admin_sidebar.html` | Dashboard | `admin_dashboard` |
| | Users | `user_management` |
| | Categories | `equipment_categories` |
| | Equipment Inventory | `equipment_inventory` |
| | Borrowing Requests | `borrowing_requests` |
| | Loan Management | `loan_management` |
| | Returns and Overdue | `returns_overdue` |
| | Maintenance | `maintenance` |
| | Reports | `reports` |
| | Audit Logs | `audit_logs` |
| | System Settings | `system_settings` |

Active items use the current route name/path and `aria-current="page"`.
For detail views, wrap `block.super` inside the page's `body` block with
`{% with active_nav="loans" %}` (use that item's `key`) to select its parent item.
The existing logout view is connected at `/logout/` as `logout`.
`components/logout.html` renders a POST form with CSRF protection.
Never replace it with a GET link.

## Shared components

Include components with explicit arguments; `only` helps avoid inheriting
unrelated values for self-contained components.

```django
{% include "components/button.html" with label="Save" type="submit" variant="primary" only %}
{% include "components/button.html" with label="Cancel" href=cancel_url variant="secondary" only %}
{% include "components/input.html" with field=form.email only %}
{% include "components/form_errors.html" with form=form only %}
{% include "components/badge.html" with label="Approved" variant="approved" only %}
{% include "components/alert.html" with title="Saved" message="Your changes were saved." variant="success" only %}
{% include "components/card.html" with title="Equipment" content_template="inventory/card_content.html" %}
{% include "components/table.html" with caption="Equipment inventory" header_template="inventory/table_header.html" body_template="inventory/table_body.html" %}
```

- Buttons: `primary`, `secondary`, `destructive`; optional `disabled`,
  `full_width`, and `modal_target`. Default type is `button`; explicitly set
  `submit` for form submission.
- Inputs: render the original Django BoundField unchanged, including its name,
  value, widget attributes, help text, hidden fields, and errors.
- Cards: optional `id`, `description`, `actions_template`, `content_template`.
- Tables: partials must output valid `<tr>` rows; headers use `<th scope="col">`.
  The scrolling region is keyboard focusable. Caption is always visible.
- Badges: `success`/`approved`, `warning`/`pending`, `error`/`rejected`,
  `info`/`active`, `inactive`/`retired`. Warning uses the supplied amber as a
  status dot alongside dark text to keep small text legible.
- Alerts: `success`, `warning`, `error`, `info`; optional `content_template`.
- Sidebar/navbar: included automatically by the shared layouts. The mobile
  drawer supports Escape, focus trapping, focus restoration, and inert content.
  Navigation remains visible when JavaScript is disabled.

## Search and filter toolbars

Use `components/filter_toolbar.html` for GET-based search and filters, with the
existing `filter_form` and `request` in context:

```django
{% include "components/filter_toolbar.html" with filter_label="Filter equipment" search_placeholder="Search equipment..." %}
```

The `q` field becomes a labelled search input with an icon. All remaining fields
keep their original Django widgets, labels, choices and errors. Optional arguments
are `reset_query` (for example `state=` or `status=` to preserve an explicit
all-results reset), `filter_help`, and `filter_actions` (a shortcut partial).

`filters.css` and `filters.js` load through `base.html`. Dropdown and date changes
submit the existing GET form; search waits 350 ms and respects IME composition.
Unchanged values do not trigger another automatic submission. The form preserves
unrelated query parameters, including repeated values, and omits pagination keys
so a changed filter starts at the first page. Existing pagination links continue
to use Django's `querystring` tag. No client-side data filtering or extra fetches
are introduced.

On mobile, native `details` groups secondary fields while search stays visible.
Removable chips summarize secondary filters on mobile only; required chart dates
use the range reset instead. Keyboard focus and expanded filters are restored
after an automatic GET submission when browser session storage is available.
Validation errors expand the filter group. Without JavaScript, fields remain
available in the native disclosure and a normal submit button is visible.

## Pagination and table layouts

List views use Django `Paginator` with 10 records per page and `get_page()` for
empty, malformed and out-of-range page requests. Use the shared component below;
it displays the record range even for a single or empty page and elides long
number ranges. Dashboard summaries and transaction-unit tables keep their
complete, deliberately bounded context rather than introducing extra page state.

```django
{% include "components/pagination.html" with page_obj=page_obj pagination_label="Equipment pages" %}
{% include "components/pagination.html" with page_obj=unit_page page_param="units_page" pagination_label="Maintenance unit pages" %}
```

The `ui_pagination` template library lives in Accounts, an existing installed app.
It copies the current query string, retains repeated values and unrelated page
keys, and carries effective bound-form defaults forward. It adds no ORM queries.
Maintenance uses `page`/`units_page`; account history uses
`request_page`/`loan_page` independently. CSV exports still include all matching
records regardless of the visible report page.

Tables use shared `table-cell--text`, `--description`, `--identifier`, `--date`,
`--number`, `--role`, `--status` and `--actions` classes on headers and their cells. Choose
roles by content rather than assigning equal column widths. For compact row
actions, use `table-action-link` on normal anchors; focus rings and touch sizing
remain shared. Use `{% include "components/table_datetime.html" with value=timestamp only %}`
for a semantic date with the time/timezone on a separate, unbroken line.
Overflow regions are
labelled and keyboard focusable; printable loan slips retain their print styles.

## Form widths and empty states

Use `form-panel` on portal POST forms for a 640px maximum width. Add
`form-panel--narrow` for 520px password/simple confirmation forms, or
`form-panel--wide` for 880px borrowing/return forms with multiple unit rows.
`form-page` and `form-page--narrow` apply the matching limit to surrounding account
information and help messages. These limits shrink naturally to the available
mobile width; original Django widgets, errors, CSRF and confirmation handlers stay
in place. Login caps at 420px and registration at 520px.

Use `form-page--full` and `form-panel--full` for the deliberately full-width
Profile, System Settings, and action-review layouts. Their numeric/contact
fields use responsive grids; standalone long text fields remain capped at 640px.
Category and catalog-item create/edit forms also use `form-panel--full`, with
`inventory-editor-form` allowing their inputs, dropdowns, and descriptions to
stretch across the available card width. Keep password forms bounded.

Use `empty-state` for shared empty result messages. Table action buttons use the
compact shared table style and keep 40px minimum targets on coarse-pointer devices.
Form and filter error borders remain visible on hover and focus.

## Metrics, facts, and search inputs

Use `metric-grid` for dashboard statistics and `metric-grid--three` for three
metrics. Include `components/metric.html` with `label`, `value`, and optional
`icon` and `description`; pass `only` so optional content cannot leak from a page.
Use `facts-grid` on definition lists for simple, borderless label/value pairs.
Use `facts-grid--two` for short summaries with two or four fields. These lists
collapse to one column on mobile.

Detailed request, loan, maintenance and user summaries share `record-summary`:
one white container, a `card-heading` with a readable status badge, and
`record-summary__grid` with logical `record-summary__group` sections. The final
`record-summary__status` group spans the tablet row; mobile groups stack with
subtle dividers. Put purpose or longer notes in `record-summary__section` below
the grid. Use `components/table_datetime.html` for compact local timestamps.
Request and maintenance summaries have reusable module partials so review,
confirmation and detail pages keep the same information and presentation.
`detail-box` remains available for other inset content.
Inventory totals use `inventory-counts`: six columns on desktop, three on
tablet, and two on small screens. Keep labels and values in semantic `dt`/`dd`
elements and use existing context data.

The `search-input` wrapper provides the shared inset icon and input padding.
Keep the field's label, original input attributes, and its existing GET or
client-side selection handler. Catalog cards use `inventory-grid` to avoid
stretching a lone card across a desktop row. See `docs/UI_MONOCHROME.md` for
the current design, file list, verification limits, and local commit history.

## Modals

Native `<dialog>` provides keyboard containment and Escape dismissal. Include
it in the `modals` block; use a unique `id` and a primary action partial alongside
the supplied Cancel button:

```django
{% block content %}
    {% include "components/button.html" with label="Open details" modal_target="equipment-details" only %}
{% endblock %}
{% block modals %}
    {% include "components/modal.html" with id="equipment-details" title="Equipment details" description="Review the selected item." content_template="inventory/details.html" actions_template="inventory/details_actions.html" %}
{% endblock %}
```

The action partial owns its actual action/form binding. For a form in the content
partial, give it an ID and use a submit button's native `form="that-id"`
attribute in the action partial. The UI script opens/closes dialogs only; it
does not submit forms, perform requests, or implement module behavior.
