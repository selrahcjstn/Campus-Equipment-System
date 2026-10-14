# Charles — Accounts, Authentication and User Management

The final module is implemented on `charles`, with all completed Inventory,
Borrowing, Loans, Maintenance and Dashboard functionality included in its baseline.
It reuses `accounts.User`, `AUTH_USER_MODEL`, Django authentication/password forms,
session middleware, shared portal layouts and the existing audit service.

## Features

- Public registration always creates an active `BASIC_USER`, with Django username
  uniqueness, required email and password validation. Submitted roles, staff,
  superuser flags, groups and permissions cannot promote the account.
- Login uses username/password and rejects inactive accounts and unsupported
  legacy roles. Basic Users land at `/portal/`; Admins land at `/manage/`. Client
  `next` parameters cannot redirect authentication outside the intended role home.
- Logout accepts CSRF-protected POST only and flushes the session.
- Both roles have their own My Profile destination. They can edit first name,
  last name, email and optional contact number, while username and account
  permissions remain read-only. Contact numbers accept 7–15 digits with standard
  separators, within the existing 20-character field. Names remain optional,
  following the existing model; profile email is required.
- Password change uses Django's `PasswordChangeForm`, current-password check and
  configured validators/hashers. The current session is maintained through
  `update_session_auth_hash`; other existing sessions must authenticate again.
- The custom Admin Users interface searches usernames, full names or emails,
  filters role/status and paginates results. Details display registration date,
  account information, borrowing requests, issued loans and return history.
- Each user's request and loan history paginates independently and links to the
  existing Borrowing and Loans detail pages. No return/approval logic is copied.
- Activation, deactivation and explicit role changes use confirmation pages,
  native dialogs, backend checks and transactional audit logging. No account
  deletion or other-user password reset endpoint is introduced.

## URLs

| URL | Name | Purpose |
| --- | --- | --- |
| `/register/` | `register` | Public Basic User registration |
| `/login/` | `login` | Username/password login |
| `/logout/` | `logout` | POST logout |
| `/portal/profile/` | `my_profile` | Own profile |
| `/portal/profile/password/` | `change_password` | Own password change |
| `/manage/profile/` | `admin_profile` | Admin's own profile |
| `/manage/profile/password/` | `admin_change_password` | Admin's own password change |
| `/manage/users/` | `user_management` | Admin user list |
| `/manage/users/<id>/` | `user_detail` | Admin account/history review |
| `/manage/users/<id>/activate/` | `activate_user` | Confirm activation |
| `/manage/users/<id>/deactivate/` | `deactivate_user` | Confirm deactivation |
| `/manage/users/<id>/role/` | `change_user_role` | Confirm campus role change |

Personal routes contain no target-user ID and always act on the authenticated
account. All `/manage/` account routes enforce Admin permission. Admins can also
use the shared self-profile handler through the personal alias; it always shows
only their own account. All mutations require POST and CSRF. GET only renders
information or an action review. Confirmation remains enforced without JavaScript.

## Account-management security

`set_user_active()` and `set_user_role()` first verify an active Admin, claim a
stable existing User row shared by account-management operations, lock the actor
and target, and repeat authorization using current database values. This prevents
stale or forged Admin objects from granting access and serializes the last-Admin
check, including on SQLite. No extra guard table or authentication model is added.

- The currently authenticated Admin cannot deactivate their own account or change
  their own role. No-op requests preserve state without duplicate audit entries.
- Deactivation or demotion cannot remove the last active Admin.
- Promotion waits until Pending/Approved requests are cancelled or finished and
  all outstanding loans are returned. This prevents changing a borrower to Admin
  while their remaining workflows require a Basic User.
- Only the existing `ADMIN`/`BASIC_USER` campus roles are accepted. Role changes
  do not alter Django staff/superuser flags, groups or permissions.
- Deactivation preserves the account and all borrowing, loan and return history.
  Admins can still receive returns for deactivated borrowers.
- Existing sessions load the current account state on their next request: inactive
  users lose authenticated access; demoted users lose Admin access.

Profile and password services independently lock/reload the owning account.
Profile saves use only the four permitted fields, so concurrent role/activation
changes cannot be overwritten by an older form instance. Password changes repeat
validation under the lock and save only the password field through Django's secure
form/hasher path. Neither service accepts another user's ID or exposes credentials.

Audit entries use the existing activation/deactivation actions and the added
`USER_ROLE_CHANGED` action. Descriptions contain the old/new campus role and target
ID, without passwords, tokens or private profile values. Audit failures roll back
the account change. Historical actor identities and records remain intact.

## Necessary integration fixes

Borrowing submission previously trusted the caller's in-memory role/activation
state. Two regression tests reproduced a deactivated or newly promoted borrower
successfully submitting through that stale object. Submission now conditionally
claims and locks the current active Basic User row before creating a request.
The fix rejects stale authorization and coordinates submission with account role
changes. The focused stale-account and concurrent-promotion tests pass.

Maintenance previously rejected a record's reporting Admin if that person's role
later changed. Existing responsible/closing actor references are now retained as
history, while assigning a new Basic User to an Admin field still fails validation.
Another active Admin can finish the maintenance after the original reporter is
demoted; repair and return history are preserved.

Dashboard audit action choices/constraint include authorized role changes. The
shared sidebar has My Profile for both roles. Users/Profile navigation previews
were replaced by real protected views, and shared integration guides were updated.
No unrelated portal layouts or business workflows were redesigned.

## Files and database changes

Completed/modified Accounts files:

- `apps/accounts/forms.py`, `views.py`, `urls.py`, `services.py`, `tests.py` and
  this guide. `models.py` and `AUTH_USER_MODEL` are unchanged.
- `templates/accounts/profile.html`, `password_change.html` and Admin
  `users.html`, `detail.html`, `action.html`, `_confirm_actions.html`.
- `static/css/accounts.css`.

Integrations:

- `config/urls.py`: remove the final Users/Profile previews.
- `templates/components/sidebar.html`: Admin self-profile destination.
- `apps/dashboard/models.py` and
  `apps/dashboard/migrations/0002_remove_auditlog_dashboard_valid_audit_action_and_more.py`:
  add the role-change audit action and safely update its existing constraint.
- `apps/borrowing/services.py`: current borrower authorization under locks.
- `apps/maintenance/models.py`: preserve historical Admin references after demotion.
- Shared Navigation/UI guides, Borrowing guide and Dashboard guide: current
  integration notes.

The existing login/registration templates retain the Design Foundation and now
render the completed forms' validation/help text. All new forms, tables, messages,
badges and confirmation dialogs reuse the existing components and tokens.

There are no new User fields, replacement authentication tables or Accounts
migration resets. The audit action migration was applied after a SQLite backup:
`.local-backups/db_before_charles_20261014_123509_304759.sqlite3`. All original rows
and fields across 21 tables were verified preserved; the User schema is unchanged
and foreign-key checks pass. Existing passwords, roles and activation states were
not changed during implementation. No accounts or equipment were seeded into the
working database.

## Verification

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.accounts
.\.venv\Scripts\python.exe manage.py test
```

Results: system check passes, no missing migrations, **61 Accounts tests pass**,
and **353 full-project tests pass**. Tests cover registration, password validators
and hashing, login/logout/redirects, inactive/unsupported roles, CSRF, profile
ownership/mass assignment, password changes and session invalidation, user search,
pagination and history, audited activation/deactivation/roles, self/last-Admin
protection, audit rollback and concurrent account changes/submission.

The fast password hasher used by most isolated test fixtures is not configured in
the application. A separate registration test verifies Django's PBKDF2 hashing;
the actual application retains its existing default secure hashers.

Browser checks used the existing separate synthetic preview database. Desktop
profile/password forms, Admin login redirects, Users list, borrowing-history links,
confirmation/cancellation and 390px mobile user details/table scrolling were
verified. No real account credentials or status changes were made. The preview
server is stopped after verification.

For your own testing:

1. Register a Basic User, confirm the `/portal/` redirect and edit My Profile.
   Try invalid email/contact values, then change the password with the current
   password and confirm the current session remains signed in.
2. Sign in as Admin, open Users, search/filter and open a user's details. Follow
   its Borrowing/Loans links and inspect completed and outstanding returns.
3. Deactivate/reactivate a test account and inspect Audit Logs. Verify deactivation
   blocks login/new requests while historical records and returns remain available.
4. Try self-deactivation and last-Admin demotion: both must fail. Promote another
   eligible account through the role confirmation page and check its audit entry.
5. Verify Basic Users cannot access Admin URLs by typing them directly.

No remaining Accounts implementation blockers. All assigned modules are now
available together on `charles` for your full-system testing. Miah's baseline was
saved locally as `c3731f1` with permission. Charles's changes remain uncommitted;
nothing was pushed or merged into `main`.
