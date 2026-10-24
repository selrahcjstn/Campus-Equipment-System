from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BorrowingItemLimitMigrationTests(TransactionTestCase):
    migrate_from = ("dashboard", "0002_remove_auditlog_dashboard_valid_audit_action_and_more")
    migrate_to = ("dashboard", "0003_enforce_three_item_limit")

    def setUp(self):
        super().setUp()
        self.addCleanup(self.restore_schema)
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.old_apps = executor.loader.project_state([self.migrate_from]).apps

    def restore_schema(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def migrate_policy(self, maximum):
        User = self.old_apps.get_model("accounts", "User")
        Policy = self.old_apps.get_model("dashboard", "SystemSetting")
        actor = User.objects.create(username="migration-admin", role="ADMIN")
        before = Policy.objects.create(max_items=maximum, max_quantity=17, max_days=23, updated_by=actor)
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        apps = executor.loader.project_state([self.migrate_to]).apps
        Policy = apps.get_model("dashboard", "SystemSetting")
        after = Policy.objects.get(pk=before.pk)
        self.assertEqual(after.max_items, min(maximum, 3))
        self.assertEqual((after.max_quantity, after.max_days), (17, 23))
        self.assertEqual((after.updated_by_id, after.updated_at), (before.updated_by_id, before.updated_at))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Policy.objects.filter(pk=after.pk).update(max_items=4)

    def test_migrate_four_item_policy(self):
        self.migrate_policy(4)

    def test_migrate_ten_item_policy(self):
        self.migrate_policy(10)

    def test_preserve_lower_item_policy(self):
        self.migrate_policy(2)

    def test_migrate_without_creating_a_policy_when_none_exists(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        apps = executor.loader.project_state([self.migrate_to]).apps
        self.assertFalse(apps.get_model("dashboard", "SystemSetting").objects.exists())
