from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.dashboard.models import AuditLog
from .forms import EquipmentForm
from .models import Category, Equipment
from .services import archive_equipment, save_category, save_equipment
from .tests import InventoryFixtures


class InventoryIntegrityAuditTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_exact_catalog_duplicate_is_rejected_in_model_service_and_http(self):
        duplicate = Equipment(name="  PROJECTOR  ", category=self.category, description=self.equipment.description)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(ValidationError):
            save_equipment(actor=self.admin, name=duplicate.name, category_id=self.category.pk, description=duplicate.description)
        response = self.client.post(reverse("create_equipment"), {
            "name": duplicate.name, "category": self.category.pk, "description": duplicate.description})
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)
        self.assertEqual(Equipment.objects.count(), 2)

    def test_duplicates_include_archived_items_and_failed_edit_keeps_original_data(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            save_equipment(actor=self.admin, name=self.equipment.name, category_id=self.category.pk,
                           description=self.equipment.description)
        before = (self.other_equipment.name, self.other_equipment.category_id, self.other_equipment.description)
        response = self.client.post(reverse("edit_equipment", args=[self.other_equipment.pk]), {
            "name": self.equipment.name, "category": self.category.pk, "description": self.equipment.description})
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)
        self.other_equipment.refresh_from_db()
        self.assertEqual((self.other_equipment.name, self.other_equipment.category_id, self.other_equipment.description), before)

    def test_same_name_different_category_or_description_remains_legitimate(self):
        for category, description in [(self.other_category, self.equipment.description), (self.category, "Different model and specifications")]:
            with self.subTest(category=category.pk, description=description):
                item = save_equipment(actor=self.admin, name=self.equipment.name, category_id=category.pk, description=description)
                self.assertEqual(item.category_id, category.pk)
        edited = save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name=self.equipment.name,
                                category_id=self.category.pk, description=self.equipment.description)
        self.assertEqual(edited.pk, self.equipment.pk)

    def test_model_form_and_service_require_existing_category_without_creating_categories(self):
        before = Category.objects.count()
        for category_id in [None, 999999]:
            with self.subTest(category_id=category_id):
                item = Equipment(name="Missing category", category_id=category_id)
                with self.assertRaises(ValidationError):
                    item.full_clean()
                with self.assertRaises(ValidationError):
                    save_equipment(actor=self.admin, name=item.name, category_id=category_id)
                form = EquipmentForm({"name": item.name, "category": category_id or "", "description": ""})
                self.assertFalse(form.is_valid())
                self.assertIn("category", form.errors)
        self.assertEqual(Category.objects.count(), before)

    def test_admin_identifier_search_keeps_complete_stock_and_combines_all_filters(self):
        response = self.client.get(reverse("equipment_inventory"), {
            "q": "projector-1", "category": self.category.pk, "availability": "available", "state": "active"})
        self.assertEqual([item.pk for item in response.context["page_obj"]], [self.equipment.pk])
        item = response.context["page_obj"][0]
        # A match on one identifier must not reduce the catalog's two-unit total.
        self.assertEqual((item.total_count, item.available_count), (2, 2))
        wrong_category = self.client.get(reverse("equipment_inventory"), {"q": "projector-1", "category": self.other_category.pk})
        self.assertEqual(len(wrong_category.context["page_obj"]), 0)
        self.client.force_login(self.borrower)
        public = self.client.get(reverse("equipment_catalog"), {"q": "PROJECTOR-1"})
        self.assertEqual(len(public.context["page_obj"]), 0)

    def test_inventory_reset_link_restores_default_active_listing(self):
        archive_equipment(self.other_equipment.pk, actor=self.admin)
        listing = self.client.get(reverse("equipment_inventory"), {"q": "Speaker", "state": "archived"})
        # Follow the actual reset URL rather than only checking a template string.
        from html.parser import HTMLParser

        class ResetLink(HTMLParser):
            href = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and "filter-toolbar__reset" in attrs.get("class", "").split():
                    self.href = attrs["href"]

        parser = ResetLink()
        parser.feed(listing.content.decode())
        self.assertIsNotNone(parser.href)
        reset = self.client.get(parser.href)
        default = self.client.get(reverse("equipment_inventory"))
        self.assertEqual([item.pk for item in reset.context["page_obj"]], [item.pk for item in default.context["page_obj"]])

    def test_category_reuse_counts_and_confirmed_unused_deletion(self):
        extra = save_equipment(actor=self.admin, name="Document camera", category_id=self.category.pk)
        page = self.client.get(reverse("equipment_categories"), {"q": "  pReSeNt  "})
        self.assertEqual([(c.pk, c.equipment_count) for c in page.context["page_obj"]], [(self.category.pk, 2)])
        self.assertEqual(extra.category_id, self.equipment.category_id)
        protected = self.client.post(reverse("delete_category", args=[self.category.pk]), {"confirm": "on"})
        self.assertEqual(protected.status_code, 409)
        with self.assertRaises(ProtectedError):
            self.category.delete()
        unused = save_category(actor=self.admin, name="Unused audit category")
        deletion = reverse("delete_category", args=[unused.pk])
        self.assertEqual(self.client.get(deletion).status_code, 200)
        self.client.post(deletion, {})
        self.assertTrue(Category.objects.filter(pk=unused.pk).exists())
        self.assertEqual(self.client.post(deletion, {"confirm": "on"}).status_code, 302)
        self.assertFalse(Category.objects.filter(pk=unused.pk).exists())

    def test_case_and_trim_duplicates_are_rejected_by_application_and_database(self):
        for name in [" presentation", "PRESENTATION ", "pReSeNtAtIoN"]:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    save_category(actor=self.admin, name=name)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Category.objects.create(name=name)
        self.assertEqual(Category.objects.count(), 2)

    def test_metadata_audit_failure_rolls_back_item_and_category_relationship(self):
        before = (self.equipment.name, self.equipment.category_id, AuditLog.objects.count())
        with patch("apps.inventory.services.record_event", side_effect=IntegrityError("Audit failure")):
            with self.assertRaises(IntegrityError):
                save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name="Changed metadata",
                               category_id=self.other_category.pk, description="Changed description")
        self.equipment.refresh_from_db()
        self.assertEqual((self.equipment.name, self.equipment.category_id, AuditLog.objects.count()), before)
