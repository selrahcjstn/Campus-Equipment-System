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
`static/css/design-system.css`. Use `section-stack` for 32px section spacing and
`content-grid` for a responsive grid with 24px gaps. Inter loads from Google
Fonts with a sans-serif fallback if the font service is unavailable.

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
`admin_dashboard` at `/manage/`. Both entry points render the shared layouts
with large Dashboard headings. Other module destinations currently render
heading-only navigation previews. The authentication redirects remain unchanged.

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
