import os
import secrets
import tempfile
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from config.environment import environment_bool, load_environment
from .models import User


class EnvironmentConfigurationTests(SimpleTestCase):
    def test_private_file_quotes_comments_and_process_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/".env"
            private_value = secrets.token_urlsafe(48)
            path.write_text('# Private configuration\nDJANGO_SECRET_KEY="'+private_value+'"\nDJANGO_DEBUG=true\n', encoding="utf-8")
            with patch.dict(os.environ, {"DJANGO_DEBUG": "false"}, clear=True):
                load_environment(path)
                self.assertEqual(os.environ["DJANGO_SECRET_KEY"], private_value)
                self.assertFalse(environment_bool("DJANGO_DEBUG", True))

    def test_missing_file_and_invalid_entries(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory)/".env"
            load_environment(path)
            self.assertNotIn("DJANGO_SECRET_KEY", os.environ)
            path.write_text("invalid entry", encoding="utf-8")
            with self.assertRaises(ImproperlyConfigured):
                load_environment(path)
            os.environ["DJANGO_DEBUG"] = "typo"
            with self.assertRaises(ImproperlyConfigured):
                environment_bool("DJANGO_DEBUG", True)


class RoleConstraintTests(TestCase):
    def test_direct_create_and_update_cannot_introduce_third_role(self):
        user = User.objects.create_user("constraint-user")
        for operation in [lambda: User.objects.create(username="bad-role", role="STAFF"), lambda: User.objects.filter(pk=user.pk).update(role="STAFF")]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        user.refresh_from_db()
        self.assertEqual(user.role, "BASIC_USER")


class RoleMigrationSafetyTests(TransactionTestCase):
    def test_invalid_legacy_roles_block_migration_without_reassignment(self):
        latest = ("accounts", "0002_user_role_constraint")
        previous = ("accounts", "0001_initial")
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([previous])
            old_apps = executor.loader.project_state([previous]).apps
            OldUser = old_apps.get_model("accounts", "User")
            bad = OldUser.objects.create(username="legacy-unknown-role", role="STAFF")
            with self.assertRaisesRegex(RuntimeError, "No roles were changed"):
                MigrationExecutor(connection).migrate([latest])
            self.assertEqual(OldUser.objects.get(pk=bad.pk).role, "STAFF")
            # Only this synthetic test record is removed so teardown can restore
            # the schema. The actual migration never rewrites/deletes accounts.
            OldUser.objects.filter(pk=bad.pk).delete()
        finally:
            MigrationExecutor(connection).migrate([latest])
