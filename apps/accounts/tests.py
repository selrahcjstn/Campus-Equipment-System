from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import Allocation, BorrowingRequest, BorrowingRequestItem
from apps.borrowing.services import approve_request, submit_request
from apps.dashboard.models import AuditLog
from apps.inventory.models import Equipment, EquipmentUnit
from apps.loans.models import Loan, LoanUnit
from apps.loans.services import process_returns, release_request
from apps.maintenance.models import MaintenanceRecord
from apps.maintenance.services import create_record, update_record, resolve_record
from .models import User
from .services import change_password, set_user_active, set_user_role, update_profile


class AccountFixtures:
    password = "Campus-Start-5927!"
    new_password = "Another-Safe-8264!"

    def make_records(self):
        self.admin = User.objects.create_user("charles-admin", password=self.password, role="ADMIN", email="admin@example.com")
        self.second_admin = User.objects.create_user("second-admin", password=self.password, role="ADMIN", email="second@example.com")
        self.basic = User.objects.create_user("student-charles", password=self.password, role="BASIC_USER", first_name="Robin", last_name="Santos", email="robin@example.com", contact_number="09175550101")
        self.other = User.objects.create_user("other-student", password=self.password, role="BASIC_USER", email="other@example.com")
        self.equipment = Equipment.objects.create(name="Projector")
        self.unit = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="AUTH-UNIT")

    def registration(self, **changes):
        return {"username": "new-student", "first_name": "New", "last_name": "Student", "email": "new@example.com", "contact_number": "09175550101", "password1": self.password, "password2": self.password, **changes}

    def profile_data(self, **changes):
        return {"first_name": "Updated", "last_name": "Student", "email": "updated@example.com", "contact_number": "+63 917 555 0101", **changes}

    def pending(self, *, borrower=None):
        request = BorrowingRequest.objects.create(borrower=borrower or self.basic, purpose="Class project", due_at=timezone.now() + timedelta(days=2))
        BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=1)
        return request

    def issue(self, *, borrower=None):
        request = self.pending(borrower=borrower)
        approve_request(request.pk, actor=self.admin)
        return release_request(request.pk, actor=self.admin)

    def return_loan(self, loan):
        return process_returns(loan.pk, actor=self.admin, returns=[(unit.pk, "GOOD", "") for unit in loan.units.filter(returned_at__isnull=True)])


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AccountsTestCase(AccountFixtures, TestCase):
    # Fast hasher is limited to isolated test fixtures; production settings retain
    # Django's default secure hashers. One registration test explicitly uses PBKDF2.
    def setUp(self):
        self.make_records()


class AuthenticationTests(AccountsTestCase):
    def test_registration_creates_basic_user_and_authenticated_session(self):
        response = self.client.post(reverse("register"), self.registration())
        self.assertRedirects(response, reverse("user_dashboard"))
        user = User.objects.get(username="new-student")
        self.assertEqual(user.role, "BASIC_USER")
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_registration_uses_django_secure_password_hashing(self):
        self.client.post(reverse("register"), self.registration())
        user = User.objects.get(username="new-student")
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertNotEqual(user.password, self.password)
        self.assertTrue(user.check_password(self.password))

    def test_public_registration_cannot_promote_or_assign_permissions(self):
        self.client.post(reverse("register"), self.registration(role="ADMIN", is_staff="on", is_superuser="on", is_active="", groups="1", user_permissions="1"))
        user = User.objects.get(username="new-student")
        self.assertEqual(user.role, "BASIC_USER")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser or user.groups.exists() or user.user_permissions.exists())

    def test_duplicate_username_is_rejected(self):
        response = self.client.post(reverse("register"), self.registration(username=self.basic.username))
        self.assertTrue(response.context["form"].errors.get("username"))
        self.assertEqual(User.objects.count(), 4)

    def test_required_fields_username_email_and_contact_validation(self):
        for changes in [{"username": ""}, {"username": "spaces not allowed"}, {"email": ""}, {"email": "invalid"}, {"contact_number": "words"}, {"contact_number": "123"}]:
            with self.subTest(changes=changes):
                response = self.client.post(reverse("register"), self.registration(**changes))
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(User.objects.count(), 4)

    def test_password_strength_similarity_and_confirmation_validation(self):
        for first, second in [("short", "short"), ("123456789012", "123456789012"), (self.password, "different"), ("new-student", "new-student")]:
            response = self.client.post(reverse("register"), self.registration(password1=first, password2=second))
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(User.objects.count(), 4)

    def test_basic_and_admin_login_redirects(self):
        for user, name in [(self.basic, "user_dashboard"), (self.admin, "admin_dashboard")]:
            self.client.logout()
            response = self.client.post(reverse("login"), {"username": user.username, "password": self.password, "next": "https://untrusted.example/"})
            self.assertRedirects(response, reverse(name))

    def test_invalid_credentials_do_not_authenticate(self):
        for username, password in [(self.basic.username, "wrong"), ("missing", self.password)]:
            response = self.client.post(reverse("login"), {"username": username, "password": password})
            self.assertTrue(response.context["form"].non_field_errors())
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_users_cannot_login(self):
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        response = self.client.post(reverse("login"), {"username": self.basic.username, "password": self.password})
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unsupported_legacy_roles_cannot_login(self):
        User.objects.filter(pk=self.other.pk).update(role="UNKNOWN")
        response = self.client.post(reverse("login"), {"username": self.other.username, "password": self.password})
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_authenticated_login_and_registration_redirect_to_role_home(self):
        self.client.force_login(self.admin)
        for name in ["login", "register"]:
            self.assertRedirects(self.client.get(reverse(name)), reverse("admin_dashboard"))

    def test_logout_is_post_only_and_flushes_session(self):
        self.client.force_login(self.basic)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registration_login_and_logout_preserve_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for name in ["register", "login", "logout"]:
            self.assertEqual(client.post(reverse(name), self.registration()).status_code, 403)
        self.assertEqual(User.objects.count(), 4)

    def test_authentication_templates_keep_shared_fields_and_password_help(self):
        for name in ["register", "login"]:
            response = self.client.get(reverse(name))
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertContains(response, 'type="password"')
            self.assertContains(response, 'for="id_username"')
        self.assertContains(self.client.get(reverse("register")), "Your password")


class ProfileTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.basic)

    def test_profile_shows_own_information_without_password_hash(self):
        response = self.client.get(reverse("my_profile"))
        self.assertContains(response, self.basic.username)
        self.assertContains(response, self.basic.email)
        self.assertNotContains(response, self.basic.password)
        self.assertNotContains(response, self.other.email)

    def test_profile_updates_only_allowed_fields(self):
        response = self.client.post(reverse("my_profile"), self.profile_data(role="ADMIN", is_active="", is_staff="on", is_superuser="on", username="new-identity", password="plaintext", id=self.other.pk, user_id=self.other.pk), follow=True)
        self.assertContains(response, "Your profile was updated.")
        self.basic.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.basic.first_name, "Updated")
        self.assertEqual(self.basic.role, "BASIC_USER")
        self.assertEqual(self.basic.username, "student-charles")
        self.assertTrue(self.basic.is_active)
        self.assertFalse(self.basic.is_staff or self.basic.is_superuser)
        self.assertTrue(self.basic.check_password(self.password))
        self.assertEqual(self.other.email, "other@example.com")

    def test_profile_validation_errors_do_not_save_partial_values(self):
        for changes in [{"email": "bad"}, {"first_name": "x" * 151}, {"contact_number": "bad"}]:
            response = self.client.post(reverse("my_profile"), self.profile_data(**changes))
            self.assertTrue(response.context["form"].errors)
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.first_name, "Robin")

    def test_profile_has_no_other_user_id_endpoint(self):
        self.assertEqual(self.client.post(f"/portal/profile/{self.other.pk}/", self.profile_data()).status_code, 404)

    def test_unauthenticated_profile_and_password_redirect_to_login(self):
        self.client.logout()
        for name in ["my_profile", "change_password", "admin_profile", "admin_change_password"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_basic_user_cannot_access_admin_profile_aliases(self):
        for name in ["admin_profile", "admin_change_password"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_admin_can_edit_own_profile_without_changing_permissions(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin_profile")), "Admin Portal")
        response = self.client.post(reverse("admin_profile"), self.profile_data())
        self.assertRedirects(response, reverse("admin_profile"))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "ADMIN")

    def test_profile_and_password_posts_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.basic)
        for name in ["my_profile", "change_password"]:
            self.assertEqual(client.post(reverse(name), self.profile_data()).status_code, 403)

    def test_secure_password_change_preserves_current_session_and_invalidates_other(self):
        other_session = Client()
        other_session.login(username=self.basic.username, password=self.password)
        response = self.client.post(reverse("change_password"), {"old_password": self.password, "new_password1": self.new_password, "new_password2": self.new_password}, follow=True)
        self.assertContains(response, "Your password was changed.")
        self.basic.refresh_from_db()
        self.assertTrue(self.basic.check_password(self.new_password))
        self.assertFalse(self.basic.check_password(self.password))
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(other_session.get(reverse("my_profile")).status_code, 302)
        self.assertFalse(AuditLog.objects.exists())

    def test_password_change_rejects_wrong_current_weak_or_mismatched_password(self):
        for data in [{"old_password": "wrong", "new_password1": self.new_password, "new_password2": self.new_password}, {"old_password": self.password, "new_password1": "short", "new_password2": "short"}, {"old_password": self.password, "new_password1": self.new_password, "new_password2": "different"}]:
            response = self.client.post(reverse("change_password"), data)
            self.assertTrue(response.context["form"].errors)
        self.basic.refresh_from_db()
        self.assertTrue(self.basic.check_password(self.password))

    def test_password_change_cannot_target_another_user(self):
        self.client.post(reverse("change_password"), {"old_password": self.password, "new_password1": self.new_password, "new_password2": self.new_password, "user_id": self.other.pk})
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_password(self.password))

    def test_stale_profile_cannot_reactivate_a_deactivated_account(self):
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        with self.assertRaises(PermissionDenied):
            update_profile(actor=self.basic, **self.profile_data())
        self.basic.refresh_from_db()
        self.assertFalse(self.basic.is_active)

    def test_stale_profile_cannot_overwrite_a_role_change(self):
        set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")
        update_profile(actor=self.basic, **self.profile_data())
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.role, "ADMIN")

    def test_password_service_revalidates_current_password_under_lock(self):
        self.basic.set_password(self.new_password)
        self.basic.save(update_fields=["password"])
        with self.assertRaises(ValidationError):
            change_password(actor=self.basic, data={"old_password": self.password, "new_password1": "Yet-Another-5837!", "new_password2": "Yet-Another-5837!"})


class AccountManagementTests(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def endpoints(self):
        return [("user_management", []), ("user_detail", [self.basic.pk]), ("activate_user", [self.basic.pk]), ("deactivate_user", [self.basic.pk]), ("change_user_role", [self.basic.pk])]

    def test_all_admin_pages_render_with_navigation_and_no_credentials(self):
        for name, args in self.endpoints():
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Admin Portal")
            self.assertNotContains(response, self.basic.password)
            self.assertNotContains(response, self.password)

    def test_basic_superuser_cannot_access_admin_endpoints(self):
        self.basic.is_staff = self.basic.is_superuser = True
        self.basic.save()
        self.client.force_login(self.basic)
        for name, args in self.endpoints():
            for method in [self.client.get, self.client.post]:
                self.assertEqual(method(reverse(name, args=args)).status_code, 403)

    def test_anonymous_admin_endpoints_redirect(self):
        self.client.logout()
        for name, args in self.endpoints():
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 302)

    def test_search_username_full_name_email_and_combined_filters(self):
        for term in [self.basic.username, "Robin Santos", self.basic.email]:
            response = self.client.get(reverse("user_management"), {"q": term})
            self.assertEqual(list(response.context["page_obj"]), [self.basic])
        set_user_active(self.other.pk, actor=self.admin, is_active=False)
        response = self.client.get(reverse("user_management"), {"status": "inactive", "role": "BASIC_USER"})
        self.assertEqual(list(response.context["page_obj"]), [self.other])

    def test_invalid_filters_show_errors_and_no_results(self):
        for data in [{"status": "INVALID"}, {"role": "SUPERUSER"}, {"q": "x" * 151}]:
            response = self.client.get(reverse("user_management"), data)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(len(response.context["page_obj"]), 0)

    def test_user_list_pagination_preserves_filters(self):
        for index in range(21):
            User.objects.create_user(f"extra-{index}", role="BASIC_USER")
        response = self.client.get(reverse("user_management"), {"role": "BASIC_USER"})
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertContains(response, "role=BASIC_USER&amp;page=2")

    def test_activate_and_deactivate_post_are_audited(self):
        response = self.client.post(reverse("deactivate_user", args=[self.basic.pk]), {"confirm": "on"}, follow=True)
        self.assertContains(response, "Account deactivated.")
        self.basic.refresh_from_db()
        self.assertFalse(self.basic.is_active)
        self.client.post(reverse("activate_user", args=[self.basic.pk]), {"confirm": "on"})
        self.basic.refresh_from_db()
        self.assertTrue(self.basic.is_active)
        self.assertEqual(set(AuditLog.objects.values_list("action", flat=True)), {"USER_DEACTIVATED", "USER_ACTIVATED"})

    def test_confirmation_is_required_and_get_does_not_mutate(self):
        url = reverse("deactivate_user", args=[self.basic.pk])
        response = self.client.get(url)
        self.assertContains(response, 'data-confirm-dialog="account-confirmation"')
        self.assertContains(response, '<dialog class="modal"')
        self.assertEqual(self.client.post(url, {}).status_code, 200)
        self.basic.refresh_from_db()
        self.assertTrue(self.basic.is_active)
        self.assertFalse(AuditLog.objects.exists())

    def test_self_deactivation_and_role_changes_are_blocked(self):
        for name, values in [("deactivate_user", {"confirm": "on"}), ("change_user_role", {"confirm": "on", "role": "BASIC_USER"})]:
            response = self.client.post(reverse(name, args=[self.admin.pk]), values)
            self.assertEqual(response.status_code, 409)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "ADMIN")
        self.assertTrue(self.admin.is_active)

    def test_role_promotion_is_explicit_admin_only_and_audited(self):
        response = self.client.post(reverse("change_user_role", args=[self.basic.pk]), {"role": "ADMIN", "confirm": "on", "is_staff": "on", "is_superuser": "on"})
        self.assertEqual(response.status_code, 302)
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.role, "ADMIN")
        self.assertFalse(self.basic.is_staff or self.basic.is_superuser)
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, "USER_ROLE_CHANGED")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.entity_id, self.basic.pk)
        self.assertNotIn(self.password, entry.description)

    def test_invalid_or_unconfirmed_role_changes_are_rejected(self):
        url = reverse("change_user_role", args=[self.basic.pk])
        for data in [{"role": "ADMIN"}, {"role": "SUPERUSER", "confirm": "on"}]:
            response = self.client.post(url, data)
            self.assertTrue(response.context["form"].errors)
        self.basic.refresh_from_db()
        self.assertEqual(self.basic.role, "BASIC_USER")

    def test_admin_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for name in ["activate_user", "deactivate_user", "change_user_role"]:
            self.assertEqual(client.post(reverse(name, args=[self.basic.pk]), {"confirm": "on", "role": "ADMIN"}).status_code, 403)

    def test_missing_users_and_delete_endpoints(self):
        self.assertEqual(self.client.get(reverse("user_detail", args=[999999])).status_code, 404)
        self.assertEqual(self.client.post(f"/manage/users/{self.basic.pk}/delete/").status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.basic.pk).exists())

    def test_history_scopes_borrowing_loans_and_returns_to_target_user(self):
        loan = self.issue()
        self.return_loan(loan)
        other_request = self.pending(borrower=self.other)
        response = self.client.get(reverse("user_detail", args=[self.basic.pk]))
        self.assertEqual(list(response.context["request_page"]), [loan.request])
        self.assertEqual(list(response.context["loan_page"]), [loan])
        self.assertContains(response, reverse("admin_request_detail", args=[loan.request_id]))
        self.assertContains(response, reverse("admin_loan_detail", args=[loan.pk]))
        self.assertContains(response, "Returned")
        self.assertNotContains(response, reverse("admin_request_detail", args=[other_request.pk]))

    def test_deactivation_preserves_borrowing_and_return_history(self):
        loan = self.issue()
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        self.return_loan(loan)
        self.assertTrue(BorrowingRequest.objects.filter(pk=loan.request_id).exists())
        self.assertIsNotNone(Loan.objects.get(pk=loan.pk).completed_at)
        self.assertEqual(LoanUnit.objects.filter(loan=loan).count(), 1)
        self.basic.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            submit_request(borrower=self.basic, purpose="New", due_at=timezone.now() + timedelta(days=1), items=[(self.equipment.pk, 1)])

    def test_history_tables_paginate_independently(self):
        for index in range(11):
            loan = self.issue()
            self.return_loan(loan)
        response = self.client.get(reverse("user_detail", args=[self.basic.pk]), {"request_page": 2})
        self.assertEqual(len(response.context["request_page"]), 1)
        self.assertEqual(len(response.context["loan_page"]), 10)
        self.assertContains(response, "request_page=2&amp;loan_page=2")


class AccountServiceSecurityTests(AccountsTestCase):
    def test_last_active_admin_cannot_be_deactivated_or_demoted(self):
        User.objects.filter(pk=self.second_admin.pk).update(is_active=False)
        for operation in [lambda: set_user_active(self.admin.pk, actor=self.admin, is_active=False), lambda: set_user_role(self.admin.pk, actor=self.admin, role="BASIC_USER")]:
            with self.assertRaisesMessage(ValidationError, "At least one active Admin"):
                operation()
        self.assertEqual(User.objects.filter(role="ADMIN", is_active=True).count(), 1)

    def test_another_admin_can_be_demoted_when_one_remains(self):
        set_user_role(self.second_admin.pk, actor=self.admin, role="BASIC_USER")
        self.assertEqual(User.objects.filter(role="ADMIN", is_active=True).count(), 1)
        self.assertEqual(AuditLog.objects.get().action, "USER_ROLE_CHANGED")

    def test_stale_or_forged_admin_identity_cannot_manage_accounts(self):
        User.objects.filter(pk=self.second_admin.pk).update(role="BASIC_USER")
        with self.assertRaises(PermissionDenied):
            set_user_active(self.basic.pk, actor=self.second_admin, is_active=False)
        User.objects.filter(pk=self.second_admin.pk).update(role="ADMIN", is_active=False)
        with self.assertRaises(PermissionDenied):
            set_user_role(self.basic.pk, actor=self.second_admin, role="ADMIN")

    def test_basic_and_anonymous_actors_cannot_use_account_services(self):
        for actor in [self.basic, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                set_user_active(self.other.pk, actor=actor, is_active=False)
            with self.assertRaises(PermissionDenied):
                set_user_role(self.other.pk, actor=actor, role="ADMIN")

    def test_state_and_role_services_validate_inputs(self):
        with self.assertRaises(ValidationError):
            set_user_active(self.basic.pk, actor=self.admin, is_active="false")
        with self.assertRaises(ValidationError):
            set_user_role(self.basic.pk, actor=self.admin, role="SUPERUSER")
        with self.assertRaises(ValidationError):
            set_user_role(999999, actor=self.admin, role="ADMIN")

    def test_noop_changes_do_not_duplicate_audit(self):
        set_user_active(self.basic.pk, actor=self.admin, is_active=True)
        set_user_role(self.basic.pk, actor=self.admin, role="BASIC_USER")
        self.assertFalse(AuditLog.objects.exists())

    def test_audit_failure_rolls_back_state_and_role_changes(self):
        for operation in [lambda: set_user_active(self.basic.pk, actor=self.admin, is_active=False), lambda: set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")]:
            with patch("apps.accounts.services.record_event", side_effect=IntegrityError("Audit failed")), self.assertRaises(IntegrityError):
                operation()
        self.basic.refresh_from_db()
        self.assertTrue(self.basic.is_active)
        self.assertEqual(self.basic.role, "BASIC_USER")

    def test_promotion_cannot_break_pending_or_approved_borrowing(self):
        request = self.pending()
        with self.assertRaises(ValidationError):
            set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")
        approve_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")

    def test_promotion_waits_for_outstanding_loans_then_preserves_history(self):
        loan = self.issue()
        with self.assertRaises(ValidationError):
            set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")
        self.return_loan(loan)
        set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")
        self.assertTrue(Loan.objects.filter(pk=loan.pk, borrower=self.basic).exists())

    def test_demoting_recorded_maintenance_admin_does_not_block_completion(self):
        record = create_record(self.unit.pk, actor=self.second_admin, reason="Issue")
        set_user_role(self.second_admin.pk, actor=self.admin, role="BASIC_USER")
        update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Repair underway")
        resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Repaired and checked")
        record.refresh_from_db()
        self.assertEqual(record.responsible_admin_id, self.second_admin.pk)
        self.assertEqual(record.closed_by, self.admin)
        self.assertEqual(record.status, "REPAIRED")

    def test_deactivated_existing_sessions_lose_authenticated_access(self):
        client = Client()
        client.login(username=self.basic.username, password=self.password)
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        self.assertEqual(client.get(reverse("my_profile")).status_code, 302)
        self.assertEqual(client.get(reverse("user_dashboard")).status_code, 302)

    def test_role_change_is_enforced_in_existing_sessions(self):
        client = Client()
        client.login(username=self.second_admin.username, password=self.password)
        set_user_role(self.second_admin.pk, actor=self.admin, role="BASIC_USER")
        self.assertEqual(client.get(reverse("user_management")).status_code, 403)
        self.assertEqual(client.get(reverse("user_dashboard")).status_code, 200)

    def test_stale_borrower_cannot_submit_after_deactivation(self):
        set_user_active(self.basic.pk, actor=self.admin, is_active=False)
        with self.assertRaises(PermissionDenied):
            submit_request(borrower=self.basic, purpose="New", due_at=timezone.now() + timedelta(days=1), items=[(self.equipment.pk, 1)])
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_stale_borrower_cannot_submit_after_promotion(self):
        set_user_role(self.basic.pk, actor=self.admin, role="ADMIN")
        with self.assertRaises(PermissionDenied):
            submit_request(borrower=self.basic, purpose="New", due_at=timezone.now() + timedelta(days=1), items=[(self.equipment.pk, 1)])
        self.assertFalse(BorrowingRequest.objects.exists())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ConcurrentAccountTests(AccountFixtures, TransactionTestCase):
    def setUp(self):
        self.make_records()

    def race(self, operations):
        barrier = Barrier(2)
        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                operation()
                return "saved"
            except (ValidationError, PermissionDenied, IntegrityError, OperationalError):
                return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(worker, operations))
        self.assertEqual(sorted(results), ["rejected", "saved"])

    def test_two_admins_cannot_concurrently_deactivate_each_other(self):
        self.race([lambda: set_user_active(self.second_admin.pk, actor=self.admin, is_active=False), lambda: set_user_active(self.admin.pk, actor=self.second_admin, is_active=False)])
        self.assertEqual(User.objects.filter(role="ADMIN", is_active=True).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="USER_DEACTIVATED").count(), 1)

    def test_two_admins_cannot_concurrently_demote_each_other(self):
        self.race([lambda: set_user_role(self.second_admin.pk, actor=self.admin, role="BASIC_USER"), lambda: set_user_role(self.admin.pk, actor=self.second_admin, role="BASIC_USER")])
        self.assertEqual(User.objects.filter(role="ADMIN", is_active=True).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="USER_ROLE_CHANGED").count(), 1)

    def test_promotion_and_submission_cannot_leave_an_admin_with_a_pending_request(self):
        self.race([lambda: set_user_role(self.basic.pk, actor=self.admin, role="ADMIN"), lambda: submit_request(borrower=self.basic, purpose="Class", due_at=timezone.now() + timedelta(days=1), items=[(self.equipment.pk, 1)])])
        self.basic.refresh_from_db()
        if BorrowingRequest.objects.filter(borrower=self.basic).exists():
            self.assertEqual(self.basic.role, "BASIC_USER")
        else:
            self.assertEqual(self.basic.role, "ADMIN")
