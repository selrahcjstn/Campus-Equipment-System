from datetime import date, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.models import AuditLog
from .forms import EquipmentForm, UnitForm
from .models import Category, Equipment, EquipmentUnit
from .services import add_unit, archive_category, delete_category, edit_unit, restore_category, save_category, save_equipment
from .tests import InventoryFixtures


class CategoryArchiveTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_archive_restore_keep_relationships_stock_and_existing_borrowing(self):
        original = list(self.equipment.units.values_list("pk", "asset_tag", "status"))
        archive_category(self.category.pk, actor=self.admin)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.category_id, self.category.pk)
        self.assertTrue(self.equipment.is_active)
        self.assertEqual(list(self.equipment.units.values_list("pk", "asset_tag", "status")), original)
        self.assertEqual(self.pending().status, "PENDING")
        with self.assertRaises(ValidationError):
            delete_category(self.category.pk, actor=self.admin)
        restored = restore_category(self.category.pk, actor=self.admin)
        self.assertTrue(restored.is_active)
        self.assertEqual(AuditLog.objects.filter(entity_type="category", entity_id=self.category.pk,
                                               description__startswith="Archived category").count(), 1)

    def test_archived_category_cannot_be_assigned_to_new_or_different_equipment(self):
        archive_category(self.category.pk, actor=self.admin)
        for equipment_id in [None, self.other_equipment.pk]:
            with self.subTest(equipment_id=equipment_id):
                form = EquipmentForm({"name": "New equipment", "category": self.category.pk, "description": ""},
                                     instance=Equipment.objects.get(pk=equipment_id) if equipment_id else None)
                self.assertFalse(form.is_valid())
                self.assertIn("category", form.errors)
                with self.assertRaises(ValidationError):
                    save_equipment(actor=self.admin, equipment_id=equipment_id, name="New equipment",
                                   category_id=self.category.pk)
        self.other_equipment.refresh_from_db()
        self.assertEqual(self.other_equipment.category_id, self.other_category.pk)
        restore_category(self.category.pk, actor=self.admin)
        self.assertEqual(save_equipment(actor=self.admin, name="New equipment", category_id=self.category.pk).category_id, self.category.pk)

    def test_edit_existing_equipment_can_keep_its_archived_category_or_choose_active_one(self):
        archive_category(self.category.pk, actor=self.admin)
        form = EquipmentForm({"name": "Renamed projector", "category": self.category.pk, "description": "Updated"}, instance=self.equipment)
        self.assertTrue(form.is_valid(), form.errors)
        saved = save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name="Renamed projector",
                               category_id=self.category.pk, description="Updated")
        self.assertEqual(saved.category_id, self.category.pk)
        saved = save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name=saved.name,
                               category_id=self.other_category.pk, description=saved.description)
        self.assertEqual(saved.category_id, self.other_category.pk)

    def test_names_remain_unique_and_edit_does_not_restore_archived_category(self):
        archive_category(self.category.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            save_category(actor=self.admin, name=" PRESENTATION ")
        updated = save_category(actor=self.admin, category_id=self.category.pk, name="Presentation renamed")
        self.assertFalse(updated.is_active)

    def test_archive_restore_are_confirmed_admin_actions_and_visible_on_listing(self):
        archive_url = reverse("archive_category", args=[self.category.pk])
        restore_url = reverse("restore_category", args=[self.category.pk])
        self.assertEqual(self.client.get(archive_url).status_code, 200)
        self.client.post(archive_url, {})
        self.assertTrue(Category.objects.get(pk=self.category.pk).is_active)
        self.assertEqual(self.client.post(archive_url, {"confirm": "on"}).status_code, 302)
        page = self.client.get(reverse("equipment_categories"), {"q": "Presentation"})
        self.assertContains(page, "Archived")
        self.assertContains(page, restore_url)
        self.assertEqual(page.context["page_obj"][0].equipment_count, 1)
        self.assertEqual(self.client.post(archive_url, {"confirm": "on"}).status_code, 409)
        self.assertEqual(self.client.post(restore_url, {"confirm": "on"}).status_code, 302)
        self.assertEqual(self.client.post(restore_url, {"confirm": "on"}).status_code, 409)

    def test_archive_restore_permissions_and_csrf(self):
        for name in ["archive_category", "restore_category"]:
            url = reverse(name, args=[self.category.pk])
            self.client.logout()
            self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 302)
            self.client.force_login(self.borrower)
            self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 403)
            self.client.force_login(self.admin)
            csrf = Client(enforce_csrf_checks=True)
            csrf.force_login(self.admin)
            self.assertEqual(csrf.post(url, {"confirm": "on"}).status_code, 403)

    def test_audit_failure_rolls_back_category_state(self):
        with patch("apps.inventory.services.record_event", side_effect=IntegrityError("Audit unavailable")):
            with self.assertRaises(IntegrityError):
                archive_category(self.category.pk, actor=self.admin)
        self.assertTrue(Category.objects.get(pk=self.category.pk).is_active)
        archive_category(self.category.pk, actor=self.admin)
        with patch("apps.inventory.services.record_event", side_effect=IntegrityError("Audit unavailable")):
            with self.assertRaises(IntegrityError):
                restore_category(self.category.pk, actor=self.admin)
        self.assertFalse(Category.objects.get(pk=self.category.pk).is_active)


class PhysicalUnitMetadataTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_known_conditions_and_dates_are_stored_without_changing_status(self):
        acquired = date(2020, 2, 29)
        for condition in EquipmentUnit.Condition.values:
            unit = add_unit(self.equipment.pk, actor=self.admin, asset_tag=f"CONDITION-{condition}",
                            condition=condition, acquisition_date=acquired)
            unit.refresh_from_db()
            self.assertEqual((unit.condition, unit.acquisition_date, unit.status), (condition, acquired, "AVAILABLE"))
        # Metadata alone does not send Damaged units to Maintenance or change borrowing policy.
        self.assertEqual(EquipmentUnit.objects.filter(condition="DAMAGED", status="AVAILABLE").count(), 1)

    def test_unknown_values_remain_unrecorded_and_legacy_edit_api_preserves_known_metadata(self):
        unit = self.units[0]
        self.assertIsNone(unit.condition)
        self.assertIsNone(unit.acquisition_date)
        edit_unit(unit.pk, actor=self.admin, asset_tag=unit.asset_tag, condition="FAIR", acquisition_date=date(2022, 1, 5))
        edited = edit_unit(unit.pk, actor=self.admin, asset_tag="METADATA-KEPT")
        self.assertEqual((edited.condition, edited.acquisition_date), ("FAIR", date(2022, 1, 5)))
        cleared = edit_unit(unit.pk, actor=self.admin, asset_tag=edited.asset_tag, condition=None, acquisition_date=None)
        self.assertIsNone(cleared.condition)
        self.assertIsNone(cleared.acquisition_date)

    def test_invalid_condition_is_rejected_by_form_service_and_database(self):
        with self.assertRaises(ValidationError):
            add_unit(self.equipment.pk, actor=self.admin, asset_tag="INVALID-CONDITION", condition="AVAILABLE")
        form = UnitForm({"asset_tag": "INVALID-CONDITION", "condition": "BROKEN"})
        self.assertFalse(form.is_valid())
        self.assertIn("condition", form.errors)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="DATABASE-CONDITION", condition="BROKEN")
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag__in=["INVALID-CONDITION", "DATABASE-CONDITION"]).exists())

    def test_acquisition_date_validation_rejects_future_and_invalid_dates(self):
        future = timezone.localdate()+timedelta(days=1)
        with self.assertRaises(ValidationError):
            add_unit(self.equipment.pk, actor=self.admin, asset_tag="FUTURE-DATE", acquisition_date=future)
        for invalid in [future.isoformat(), "2025-02-30", "not-a-date"]:
            form = UnitForm({"asset_tag": "INVALID-DATE", "condition": "GOOD", "acquisition_date": invalid})
            self.assertFalse(form.is_valid())
            self.assertIn("acquisition_date", form.errors)
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag="FUTURE-DATE").exists())

    def test_modal_create_and_edit_prefill_validate_and_display_metadata(self):
        create_url = reverse("add_equipment_unit", args=[self.equipment.pk])
        data = {"asset_tag": "METADATA-MODAL", "condition": "GOOD", "acquisition_date": "2021-04-06", "status": "ON_LOAN"}
        self.assertJSONEqual(self.client.post(create_url, data, HTTP_X_ADMIN_MODAL="1").content, {"saved": True})
        unit = EquipmentUnit.objects.get(asset_tag=data["asset_tag"])
        edit_url = reverse("edit_equipment_unit", args=[unit.pk])
        page = self.client.get(edit_url, HTTP_X_ADMIN_MODAL="1")
        self.assertContains(page, 'value="2021-04-06"')
        self.assertContains(page, "Acquisition date")
        data.update(condition="POOR", acquisition_date="2022-05-07")
        self.assertJSONEqual(self.client.post(edit_url, data, HTTP_X_ADMIN_MODAL="1").content, {"saved": True})
        unit.refresh_from_db()
        self.assertEqual((unit.condition, unit.acquisition_date, unit.status), ("POOR", date(2022, 5, 7), "AVAILABLE"))
        for name, args in [("equipment_units", []), ("admin_equipment_detail", [self.equipment.pk])]:
            page = self.client.get(reverse(name, args=args))
            self.assertContains(page, "Poor")
            self.assertContains(page, "May 7, 2022")
            self.assertContains(page, "Not recorded")
        data.update(condition="INVALID")
        response = self.client.post(edit_url, data, HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "METADATA-MODAL", status_code=422)
        self.assertEqual(EquipmentUnit.objects.get(pk=unit.pk).condition, "POOR")

    def test_metadata_cannot_bypass_existing_busy_unit_edit_guards(self):
        for status in ["RESERVED", "ON_LOAN", "MAINTENANCE"]:
            EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                edit_unit(self.units[0].pk, actor=self.admin, asset_tag="BYPASS", condition="GOOD", acquisition_date=date(2020, 1, 1))
        self.units[0].refresh_from_db()
        self.assertIsNone(self.units[0].condition)
        self.assertEqual(self.units[0].asset_tag, "PROJECTOR-1")

    def test_metadata_audit_failure_rolls_back_new_values(self):
        with patch("apps.inventory.services.record_event", side_effect=IntegrityError("Audit unavailable")):
            with self.assertRaises(IntegrityError):
                edit_unit(self.units[0].pk, actor=self.admin, asset_tag="UNSAVED", condition="FAIR", acquisition_date=date(2020, 1, 1))
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].asset_tag, "PROJECTOR-1")
        self.assertIsNone(self.units[0].condition)
        self.assertIsNone(self.units[0].acquisition_date)


class InventoryMigrationSafetyTests(TransactionTestCase):
    def test_existing_rows_and_relationships_keep_unknown_metadata_after_upgrade(self):
        latest = ("inventory", "0004_unit_condition_and_acquisition_date")
        previous = ("inventory", "0002_category_equipment_is_active_and_more")
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([previous])
            old_apps = executor.loader.project_state([previous]).apps
            category = old_apps.get_model("inventory", "Category").objects.create(name="Historical category")
            equipment = old_apps.get_model("inventory", "Equipment").objects.create(name="Historical unit type", category_id=category.pk)
            unit = old_apps.get_model("inventory", "EquipmentUnit").objects.create(
                equipment_id=equipment.pk, asset_tag="HISTORICAL-UNIT", status="MAINTENANCE")
            MigrationExecutor(connection).migrate([latest])
            preserved = EquipmentUnit.objects.get(pk=unit.pk)
            self.assertEqual((preserved.asset_tag, preserved.status, preserved.equipment_id), (unit.asset_tag, "MAINTENANCE", equipment.pk))
            self.assertIsNone(preserved.condition)
            self.assertIsNone(preserved.acquisition_date)
            self.assertEqual(Equipment.objects.get(pk=equipment.pk).category_id, category.pk)
            self.assertTrue(Category.objects.get(pk=category.pk).is_active)
        finally:
            MigrationExecutor(connection).migrate([latest])


class PhysicalUnitCategoryFilterTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)
        self.url = reverse("equipment_units")

    def ids(self, query):
        return [unit.pk for unit in self.client.get(self.url, query).context["page_obj"]]

    def test_category_item_status_and_search_work_alone_and_together(self):
        EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status="MAINTENANCE")
        self.assertEqual(set(self.ids({"category": self.category.pk})), {u.pk for u in self.units})
        self.assertEqual(self.ids({"category": self.other_category.pk}), [self.speaker.pk])
        self.assertEqual(set(self.ids({"equipment": self.equipment.pk})), {u.pk for u in self.units})
        self.assertEqual(self.ids({"status": "MAINTENANCE"}), [self.units[0].pk])
        self.assertEqual(self.ids({"q": "projector-1"}), [self.units[0].pk])
        query = {"category": self.category.pk, "equipment": self.equipment.pk, "status": "MAINTENANCE", "q": "projector"}
        self.assertEqual(self.ids(query), [self.units[0].pk])
        self.assertEqual(self.ids({**query, "category": self.other_category.pk}), [])

    def test_archived_categories_remain_filterable_for_admin_history(self):
        archive_category(self.category.pk, actor=self.admin)
        self.assertEqual(set(self.ids({"category": self.category.pk})), {u.pk for u in self.units})
        page = self.client.get(self.url)
        self.assertContains(page, "All categories")
        self.assertContains(page, self.category.name)

    def test_invalid_filters_show_errors_instead_of_ignoring_values(self):
        for query in [{"category": 999999}, {"equipment": 999999}, {"status": "BROKEN"}]:
            with self.subTest(query=query):
                page = self.client.get(self.url, query)
                self.assertTrue(page.context["filter_form"].errors)
                self.assertEqual(len(page.context["page_obj"]), 0)

    def test_pagination_retains_combined_filters_and_reset_clears_them(self):
        from html.parser import HTMLParser

        for index in range(12):
            EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"CATEGORY-PAGE-{index:02d}")
        query = {"category": self.category.pk, "equipment": self.equipment.pk, "status": "AVAILABLE", "q": "CATEGORY-PAGE"}
        page = self.client.get(self.url, query)
        self.assertEqual(len(page.context["page_obj"]), 10)
        self.assertContains(page, f"category={self.category.pk}")
        self.assertContains(page, "status=AVAILABLE")
        second = self.client.get(self.url, {**query, "page": 2})
        self.assertEqual(len(second.context["page_obj"]), 2)
        self.assertTrue(all(unit.equipment.category_id == self.category.pk for unit in second.context["page_obj"]))

        class ResetLink(HTMLParser):
            href = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and "filter-toolbar__reset" in attrs.get("class", "").split():
                    self.href = attrs["href"]

        parser = ResetLink()
        parser.feed(page.content.decode())
        self.assertEqual(parser.href, self.url)
        reset = self.client.get(parser.href)
        self.assertEqual(reset.context["page_obj"].paginator.count, EquipmentUnit.objects.count())

    def test_fixed_equipment_page_keeps_existing_context_filters(self):
        page = self.client.get(reverse("admin_equipment_detail", args=[self.equipment.pk]))
        self.assertNotIn("category", page.context["filter_form"].fields)
        self.assertEqual(set(unit.pk for unit in page.context["page_obj"]), {unit.pk for unit in self.units})
