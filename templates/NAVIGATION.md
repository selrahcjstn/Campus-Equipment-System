# Navigation integration

Extend `base_user.html` or `base_admin.html`. The shared `base_app.html` selects
sidebar entries from the authenticated user's role and renders the child's
`content` block without adding page content. Keep each module's existing access
checks in its views; template role selection is presentation, not authorization.

```django
{% extends "base_user.html" %}
{% block title %}My Loans | Campus Equipment System{% endblock %}
{% block content %}
    {# The module owner supplies their existing page here. #}
{% endblock %}
```

The sidebar uses shared CSS tokens and the existing vanilla UI script. Below
1024px it opens from the navbar button, traps keyboard focus, closes with Escape,
the close button or the backdrop, and returns focus to the opener. On desktop
it is 256px wide. Long admin navigation scrolls inside the sidebar while Account
stays accessible. Without JavaScript the smaller-screen navigation is visible
above the content.

## Destinations and owners

Both portal entry points use the shared navigation shell: `/portal/` is named
`user_dashboard` and extends `base_user.html`; `/manage/` is named
`admin_dashboard` and extends `base_admin.html`. Role-protected Dashboard views
provide personal borrowing summaries and live Admin KPIs/charts. Authentication
redirects still target these same paths.

Inventory, Borrowing, Loans, Maintenance, Reports, Audit Logs and System Settings
now resolve to their implemented module views on this branch. Users and My Profile
remain Charles's heading-only `TemplateView` previews in `config/urls.py`.
Named routes take precedence over fallback paths. Missing routes still render
disabled rather than creating broken links. Member names appear only in
documentation and template comments.

| Portal / section | Label | Route slot or existing path | Owner |
| --- | --- | --- | --- |
| Basic User / Main | Dashboard | `user_dashboard` (`/portal/`) | Dashboard team |
| Basic User / Main | Equipment Catalog | `equipment_catalog` | Raj |
| Basic User / Main | My Borrowing Requests | `my_requests` | Clark |
| Basic User / Main | My Loans | `my_loans` | Janelle |
| Basic User / Main | Borrowing History | `borrowing_history` | Janelle |
| Basic User / Account | My Profile | `my_profile` | Charles |
| Both / Account | Logout | `logout` | Charles |
| Admin / Overview | Dashboard | `admin_dashboard` (`/manage/`) | Miah |
| Admin / User Management | Users | `user_management` | Charles |
| Admin / Equipment Management | Categories | `equipment_categories` | Raj |
| Admin / Equipment Management | Equipment Inventory | `equipment_inventory` | Raj |
| Admin / Borrowing Operations | Borrowing Requests | `borrowing_requests` | Clark |
| Admin / Borrowing Operations | Loan Management | `loan_management` | Janelle |
| Admin / Borrowing Operations | Returns and Overdue | `returns_overdue` | Janelle |
| Admin / System Management | Maintenance | `maintenance` | Francis |
| Admin / System Management | Reports | `reports` | Miah |
| Admin / System Management | Audit Logs | `audit_logs` | Miah |
| Admin / System Management | System Settings | `system_settings` | Miah |

My Profile and Logout are in the shared sidebar's Account section. `/logout/`
now connects the existing POST-only view as `logout`. Its component renders a
POST form with the existing CSRF token and redirects to `/login/` after ending
the session. Login, Registration, and their redirects are unchanged.

## Active navigation

`components/nav_item.html` matches the current path, named route, or namespaced
view name. The selected link has a navy background and `aria-current="page"`.
Unavailable entries never become active links. For a detail page under another
route, the child can select its parent item without changing backend behavior:

```django
{% block body %}
    {% with active_nav="loans" %}{{ block.super }}{% endwith %}
{% endblock %}
```

Use the item's `key` from the partial. The old `navigation/user.html` and
`navigation/admin.html` remain compatibility includes pointing to the new
components; they contain no duplicate navigation definitions.
