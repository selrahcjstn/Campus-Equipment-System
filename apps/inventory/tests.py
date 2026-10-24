from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import Allocation, BorrowingRequest
from apps.borrowing.services import approve_request, cancel_request, submit_request
from apps.loans.models import Loan
from apps.loans.services import process_returns, release_request
from apps.maintenance.models import MaintenanceRecord
from apps.maintenance.services import create_record, resolve_record, update_record
from .models import Category, Equipment, EquipmentUnit
from .services import add_unit, archive_equipment, delete_category, edit_unit, eligible_units, inventory_queryset, restore_equipment, retire_unit, save_category, save_equipment, unit_queryset


class InventoryFixtures:
    def make_records(self):
        User = get_user_model()
        self.admin = User.objects.create_user("stock-admin", role="ADMIN")
        self.borrower = User.objects.create_user("stock-borrower", role="BASIC_USER")
        self.category = save_category(actor=self.admin, name="Presentation", description="Teaching equipment")
        self.other_category = save_category(actor=self.admin, name="Audio")
        self.equipment = save_equipment(actor=self.admin, name="Projector", category_id=self.category.pk, description="Public classroom projector description")
        self.other_equipment = save_equipment(actor=self.admin, name="Speaker", category_id=self.other_category.pk)
        self.units = [add_unit(self.equipment.pk, actor=self.admin, asset_tag=f"PROJECTOR-{i}") for i in [1, 2]]
        self.speaker = add_unit(self.other_equipment.pk, actor=self.admin, asset_tag="SPEAKER-PRIVATE-TAG")

    def pending(self):
        return submit_request(borrower=self.borrower, purpose="Class presentation",
                              due_at=timezone.now() + timedelta(days=3),
                              items=[(self.equipment.pk, 2)])

    def issue(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        return release_request(request.pk, actor=self.admin)

    def return_all(self, loan):
        process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "GOOD", "") for item in loan.units.all()])

    def counts(self):
        return inventory_queryset().get(pk=self.equipment.pk)


class InventoryServiceTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_category_create_edit_and_trim(self):
        category = save_category(actor=self.admin, name="  Cameras  ", description="Camera equipment")
        self.assertEqual(category.name, "Cameras")
        edited = save_category(actor=self.admin, category_id=category.pk, name="Photography", description="Updated")
        self.assertEqual(edited.pk, category.pk)
        self.assertEqual(edited.name, "Photography")
        self.assertEqual(edited.description, "Updated")

    def test_category_duplicate_case_and_whitespace_validation(self):
        for name in ["presentation", " PRESENTATION ", "Presentation"]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                save_category(actor=self.admin, name=name)
        self.assertEqual(Category.objects.count(), 2)

    def test_database_prevents_case_duplicate_category(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name=" PRESENTATION ")

    def test_blank_and_overlong_category_and_equipment_names(self):
        for name in [" ", "x" * 101]:
            with self.assertRaises(ValidationError):
                save_category(actor=self.admin, name=name)
        for name in [" ", "x" * 151]:
            with self.assertRaises(ValidationError):
                save_equipment(actor=self.admin, name=name, category_id=self.category.pk)

    def test_unreferenced_category_deletion(self):
        category = save_category(actor=self.admin, name="Unused")
        delete_category(category.pk, actor=self.admin)
        self.assertFalse(Category.objects.filter(pk=category.pk).exists())

    def test_referenced_category_cannot_be_deleted_even_when_equipment_archived(self):
        for archived in [False, True]:
            if archived:
                archive_equipment(self.equipment.pk, actor=self.admin)
            with self.assertRaises(ValidationError):
                delete_category(self.category.pk, actor=self.admin)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_catalog_create_edit_requires_existing_category(self):
        equipment = save_equipment(actor=self.admin, name="  Camera ", category_id=self.category.pk, description="Public details")
        self.assertEqual(equipment.name, "Camera")
        self.assertTrue(equipment.is_active)
        edited = save_equipment(actor=self.admin, equipment_id=equipment.pk, name="Camera kit", category_id=self.other_category.pk, description="Updated details")
        self.assertEqual(edited.category_id, self.other_category.pk)
        self.assertEqual(edited.name, "Camera kit")
        for category_id in [None, 999999]:
            with self.assertRaises(ValidationError):
                save_equipment(actor=self.admin, name="Invalid", category_id=category_id)

    def test_legacy_catalog_items_without_category_remain_supported(self):
        legacy = Equipment.objects.create(name="Legacy equipment")
        self.assertIsNone(legacy.category)
        self.assertTrue(legacy.is_active)
        unit = add_unit(legacy.pk, actor=self.admin, asset_tag="LEGACY-001")
        self.assertEqual(unit.status, "AVAILABLE")
        self.assertEqual(inventory_queryset().get(pk=legacy.pk).available_count, 1)

    def test_archive_and_restore_preserve_units_and_statuses(self):
        original = list(self.equipment.units.values_list("pk", "asset_tag", "status"))
        archived = archive_equipment(self.equipment.pk, actor=self.admin)
        self.assertFalse(archived.is_active)
        self.assertEqual(list(self.equipment.units.values_list("pk", "asset_tag", "status")), original)
        self.assertFalse(eligible_units().filter(equipment=self.equipment).exists())
        restored = restore_equipment(self.equipment.pk, actor=self.admin)
        self.assertTrue(restored.is_active)
        self.assertEqual(list(self.equipment.units.values_list("pk", "asset_tag", "status")), original)

    def test_archive_already_archived_and_restore_active_are_rejected(self):
        with self.assertRaises(ValidationError):
            restore_equipment(self.equipment.pk, actor=self.admin)
        archive_equipment(self.equipment.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            archive_equipment(self.equipment.pk, actor=self.admin)

    def test_archived_items_reject_new_requests_units_and_pending_approvals(self):
        pending = self.pending()
        archive_equipment(self.equipment.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            self.pending()
        with self.assertRaises(ValidationError):
            add_unit(self.equipment.pk, actor=self.admin, asset_tag="ARCHIVED-NEW")
        with self.assertRaises(ValidationError):
            approve_request(pending.pk, actor=self.admin)
        pending.refresh_from_db()
        self.assertEqual(pending.status, "PENDING")
        self.assertFalse(Allocation.objects.exists())

    def test_catalog_edit_does_not_restore_archived_item(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        result = save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name="Renamed", category_id=self.category.pk)
        self.assertFalse(result.is_active)

    def test_reserved_and_issued_catalogs_cannot_be_archived(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            archive_equipment(self.equipment.pk, actor=self.admin)
        loan = release_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            archive_equipment(self.equipment.pk, actor=self.admin)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)
        self.assertEqual(loan.outstanding_count, 2)

    def test_archive_with_only_maintenance_units_preserves_maintenance_state(self):
        EquipmentUnit.objects.filter(equipment=self.equipment).update(status="MAINTENANCE")
        archive_equipment(self.equipment.pk, actor=self.admin)
        self.assertEqual(self.equipment.units.filter(status="MAINTENANCE").count(), 2)

    def test_unit_create_normalization_and_unique_identifier(self):
        unit = add_unit(self.equipment.pk, actor=self.admin, asset_tag="  camera-001 ")
        self.assertEqual(unit.asset_tag, "CAMERA-001")
        self.assertEqual(unit.status, "AVAILABLE")
        for tag in ["CAMERA-001", " camera-001 "]:
            with self.assertRaises(ValidationError):
                add_unit(self.other_equipment.pk, actor=self.admin, asset_tag=tag)

    def test_database_enforces_unique_identifier_case_and_trim(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentUnit.objects.create(equipment=self.other_equipment, asset_tag=" projector-1 ")

    def test_invalid_unit_identifier(self):
        for tag in ["", " ", "x" * 81]:
            with self.assertRaises(ValidationError):
                add_unit(self.equipment.pk, actor=self.admin, asset_tag=tag)

    def test_available_and_retired_identifiers_can_be_edited_without_status_change(self):
        unit = edit_unit(self.units[0].pk, actor=self.admin, asset_tag=" NEW-TAG ")
        self.assertEqual(unit.asset_tag, "NEW-TAG")
        self.assertEqual(unit.status, "AVAILABLE")
        retire_unit(unit.pk, actor=self.admin)
        unit = edit_unit(unit.pk, actor=self.admin, asset_tag="RETIRED-NEW")
        self.assertEqual(unit.status, "RETIRED")
        self.assertFalse(eligible_units().filter(pk=unit.pk).exists())

    def test_reserved_issued_and_maintenance_units_cannot_be_edited_or_retired(self):
        for status in ["RESERVED", "ON_LOAN", "MAINTENANCE"]:
            EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                edit_unit(self.units[0].pk, actor=self.admin, asset_tag="UNSAFE-CHANGE")
            with self.assertRaises(ValidationError):
                retire_unit(self.units[0].pk, actor=self.admin)
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].asset_tag, "PROJECTOR-1")

    def test_retirement_keeps_physical_record_and_prevents_duplicate_retirement(self):
        retired = retire_unit(self.units[0].pk, actor=self.admin)
        self.assertEqual(retired.status, "RETIRED")
        self.assertTrue(EquipmentUnit.objects.filter(pk=retired.pk).exists())
        self.assertEqual(self.counts().available_count, 1)
        with self.assertRaises(ValidationError):
            retire_unit(retired.pk, actor=self.admin)

    def test_all_status_counts_are_calculated_from_physical_units(self):
        EquipmentUnit.objects.filter(equipment=self.equipment).update(status="AVAILABLE")
        for status in ["RESERVED", "ON_LOAN", "MAINTENANCE", "RETIRED"]:
            EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"COUNT-{status}", status=status)
        counts = self.counts()
        self.assertEqual(counts.total_count, 6)
        self.assertEqual(counts.serviceable_count, 4)
        self.assertEqual(counts.available_count, 2)
        self.assertEqual((counts.reserved_count, counts.issued_count, counts.maintenance_count, counts.retired_count), (1, 1, 1, 1))
        self.assertEqual(eligible_units().filter(equipment=self.equipment).count(), 2)

    def test_aggregate_catalog_order_is_explicit_and_stable(self):
        equipment = save_equipment(actor=self.admin, name="AAA first", category_id=self.category.pk)
        records = inventory_queryset()
        self.assertTrue(records.ordered)
        self.assertEqual(records.first().pk, equipment.pk)

    def test_allocation_excludes_available_status_inconsistency_and_blocks_edits_archive(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        EquipmentUnit.objects.filter(equipment=self.equipment).update(status="AVAILABLE")
        self.assertEqual(self.counts().available_count, 0)
        self.assertFalse(unit_queryset().get(pk=self.units[0].pk).can_edit)
        with self.assertRaises(ValidationError):
            edit_unit(self.units[0].pk, actor=self.admin, asset_tag="BYPASS")
        with self.assertRaises(ValidationError):
            archive_equipment(self.equipment.pk, actor=self.admin)

    def test_outstanding_loan_blocks_availability_even_with_inactive_allocation_and_available_status(self):
        loan = self.issue()
        Allocation.objects.filter(request_item__request=loan.request).update(active=False)
        EquipmentUnit.objects.filter(equipment=self.equipment).update(status="AVAILABLE")
        self.assertEqual(self.counts().available_count, 0)
        self.assertFalse(eligible_units().filter(equipment=self.equipment).exists())
        with self.assertRaises(ValidationError):
            edit_unit(self.units[0].pk, actor=self.admin, asset_tag="BYPASS")
        with self.assertRaises(ValidationError):
            archive_equipment(self.equipment.pk, actor=self.admin)

    def test_borrowing_cancellation_updates_availability_immediately(self):
        request = self.pending()
        self.assertEqual(self.counts().available_count, 2)
        approve_request(request.pk, actor=self.admin)
        self.assertEqual(self.counts().available_count, 0)
        self.assertEqual(self.counts().reserved_count, 2)
        cancel_request(request.pk, actor=self.borrower)
        self.assertEqual(self.counts().available_count, 2)
        self.assertEqual(self.counts().reserved_count, 0)

    def test_loan_release_good_and_damaged_returns_update_counts(self):
        loan = self.issue()
        self.assertEqual(self.counts().issued_count, 2)
        items = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(items[0].pk, "GOOD", "")])
        self.assertEqual((self.counts().available_count, self.counts().issued_count), (1, 1))
        process_returns(loan.pk, actor=self.admin, returns=[(items[1].pk, "DAMAGED", "Internal damage report")])
        counts = self.counts()
        self.assertEqual((counts.available_count, counts.issued_count, counts.maintenance_count), (1, 0, 1))
        self.assertFalse(unit_queryset().get(pk=items[1].unit_id).can_edit)

    def test_archive_after_completed_loan_preserves_history_and_prevents_deletion(self):
        loan = self.issue()
        self.return_all(loan)
        archive_equipment(self.equipment.pk, actor=self.admin)
        self.assertEqual(loan.units.count(), 2)
        with self.assertRaises(ProtectedError):
            self.equipment.delete()
        with self.assertRaises(ProtectedError):
            self.units[0].delete()

    def test_historical_snapshots_survive_metadata_changes(self):
        loan = self.issue()
        self.return_all(loan)
        save_equipment(actor=self.admin, equipment_id=self.equipment.pk, name="Renamed projector", category_id=self.other_category.pk, description="Updated")
        edit_unit(self.units[0].pk, actor=self.admin, asset_tag="NEW-HISTORICAL-TAG")
        self.assertEqual(loan.units.get(unit_id=self.units[0].pk).asset_tag, "PROJECTOR-1")
        self.assertEqual(loan.units.first().equipment_name, "Projector")

    def test_only_active_admin_can_modify_inventory(self):
        for actor in [self.borrower, self.admin]:
            if actor == self.admin:
                actor.is_active = False
            operations = [
                lambda: save_category(actor=actor, name="Unauthorized"),
                lambda: save_equipment(actor=actor, name="Unauthorized", category_id=self.category.pk),
                lambda: add_unit(self.equipment.pk, actor=actor, asset_tag="UNAUTHORIZED"),
                lambda: edit_unit(self.units[0].pk, actor=actor, asset_tag="UNAUTHORIZED"),
                lambda: archive_equipment(self.equipment.pk, actor=actor),
                lambda: retire_unit(self.units[0].pk, actor=actor),
                lambda: delete_category(self.category.pk, actor=actor),
                lambda: restore_equipment(self.equipment.pk, actor=actor),
            ]
            for operation in operations:
                with self.assertRaises(PermissionDenied):
                    operation()


class ServiceableInventoryTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.borrower)

    def assert_public_stock(self, available, serviceable, equipment=None):
        equipment = equipment or self.equipment
        urls = [
            reverse("equipment_catalog") + f"?q={equipment.name}",
            reverse("equipment_detail", args=[equipment.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                if "page_obj" in response.context:
                    records = list(response.context["page_obj"])
                    self.assertEqual([item.pk for item in records], [equipment.pk])
                    item = records[0]
                else:
                    item = response.context["equipment"]
                self.assertEqual((item.available_count, item.serviceable_count), (available, serviceable))
                label = "Available" if "page_obj" in response.context else "Available Units"
                self.assertContains(response, f"<dt>{label}</dt><dd>{available}</dd>", html=True)
                self.assertContains(response, f"<dt>Total Serviceable</dt><dd>{serviceable}</dd>", html=True)
                if available:
                    self.assertContains(response, f"?equipment={equipment.pk}")
                else:
                    self.assertNotContains(response, f"?equipment={equipment.pk}")

    def test_each_status_and_zero_inventory_are_aggregated_in_one_query(self):
        expected = {}
        for status, counts in [
            (EquipmentUnit.Status.AVAILABLE, (1, 1)),
            (EquipmentUnit.Status.RESERVED, (0, 1)),
            (EquipmentUnit.Status.ON_LOAN, (0, 1)),
            (EquipmentUnit.Status.MAINTENANCE, (0, 0)),
            (EquipmentUnit.Status.RETIRED, (0, 0)),
        ]:
            equipment = Equipment.objects.create(name=f"Status {status}", category=self.category)
            EquipmentUnit.objects.create(equipment=equipment, asset_tag=f"STATUS-{status}", status=status)
            expected[equipment.pk] = counts
        empty = Equipment.objects.create(name="Empty inventory", category=self.category)
        expected[empty.pk] = (0, 0)
        with self.assertNumQueries(1):
            actual = {item.pk: (item.available_count, item.serviceable_count)
                      for item in inventory_queryset().filter(pk__in=expected)}
        self.assertEqual(actual, expected)

    def test_public_pages_display_mixed_serviceable_totals(self):
        for status in ["RESERVED", "ON_LOAN", "MAINTENANCE", "RETIRED"]:
            EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"MIXED-{status}", status=status)
        self.assert_public_stock(2, 4)

    def test_public_pages_display_zero_inventory(self):
        empty = save_equipment(actor=self.admin, name="Camera", category_id=self.category.pk)
        self.assert_public_stock(0, 0, equipment=empty)

    def test_public_totals_follow_reservation_issue_return_and_maintenance_transitions(self):
        self.assert_public_stock(2, 2)
        request = self.pending()
        with self.subTest(phase="pending"):
            self.assert_public_stock(2, 2)
        approve_request(request.pk, actor=self.admin)
        with self.subTest(phase="reserved"):
            self.assert_public_stock(0, 2)
        cancel_request(request.pk, actor=self.borrower)
        with self.subTest(phase="reservation cancelled"):
            self.assert_public_stock(2, 2)
        loan = self.issue()
        with self.subTest(phase="issued"):
            self.assert_public_stock(0, 2)
        items = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(items[0].pk, "GOOD", "")])
        with self.subTest(phase="good partial return"):
            self.assert_public_stock(1, 2)
        process_returns(loan.pk, actor=self.admin, returns=[(items[1].pk, "DAMAGED", "Broken lens")])
        with self.subTest(phase="damaged return"):
            self.assert_public_stock(1, 1)
        repair = MaintenanceRecord.objects.get(source_return=items[1])
        update_record(repair.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Replacing lens")
        with self.subTest(phase="repair in progress"):
            self.assert_public_stock(1, 1)
        resolve_record(repair.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Lens replaced and tested")
        with self.subTest(phase="repaired"):
            self.assert_public_stock(2, 2)
        maintenance = create_record(items[0].unit_id, actor=self.admin, reason="Failed inspection")
        with self.subTest(phase="maintenance intake"):
            self.assert_public_stock(1, 1)
        resolve_record(maintenance.pk, actor=self.admin, outcome="RETIRED", repair_notes="Beyond repair")
        with self.subTest(phase="retired from maintenance"):
            self.assert_public_stock(1, 1)
        retire_unit(items[1].unit_id, actor=self.admin)
        with self.subTest(phase="all units retired"):
            self.assert_public_stock(0, 0)


class InventoryPageTests(InventoryFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_catalog_search_category_and_availability_filters(self):
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("equipment_catalog"), {"q": "projector", "category": self.category.pk})
        self.assertContains(response, "Projector")
        self.assertNotContains(response, "<h2>Speaker</h2>")
        self.assertEqual(len(response.context["page_obj"]), 1)
        retire_unit(self.units[0].pk, actor=self.admin)
        retire_unit(self.units[1].pk, actor=self.admin)
        unavailable = self.client.get(reverse("equipment_catalog"), {"availability": "unavailable"})
        self.assertContains(unavailable, "Unavailable")
        self.assertEqual([item.pk for item in unavailable.context["page_obj"]], [self.equipment.pk])

    def test_catalog_cards_show_flat_stock_counts_and_only_available_request_actions(self):
        self.client.force_login(self.borrower)
        EquipmentUnit.objects.filter(pk=self.speaker.pk).update(status="RESERVED")
        response = self.client.get(reverse("equipment_catalog"))
        self.assertContains(response, "inventory-catalog-card__heading")
        self.assertContains(response, "inventory-catalog-card__counts")
        self.assertNotContains(response, 'class="inventory-stock"')
        self.assertContains(response, f'href="{reverse("new_borrowing_request")}?equipment={self.equipment.pk}"')
        self.assertNotContains(response, f'href="{reverse("new_borrowing_request")}?equipment={self.other_equipment.pk}"')
        self.assertContains(response, f'href="{reverse("equipment_detail", args=[self.other_equipment.pk])}">View details</a>')
        self.assertContains(response, "<dt>Available</dt><dd>0</dd>", html=True)
        self.assertContains(response, "<dt>Total Serviceable</dt><dd>1</dd>", html=True)

        EquipmentUnit.objects.filter(pk=self.speaker.pk).update(status="RETIRED")
        zero_stock = self.client.get(reverse("equipment_catalog"))
        self.assertContains(zero_stock, "<dt>Available</dt><dd>0</dd>", html=True)
        self.assertContains(zero_stock, "<dt>Total Serviceable</dt><dd>0</dd>", html=True)
        self.assertNotContains(zero_stock, f'href="{reverse("new_borrowing_request")}?equipment={self.other_equipment.pk}"')

    def test_catalog_cards_handle_long_names_and_descriptions(self):
        self.client.force_login(self.borrower)
        long_name = "Presentation " + "equipment " * 12
        long_description = "A detailed public description for catalog users. " * 8
        item = Equipment.objects.create(name=long_name[:150], category=self.category, description=long_description)
        EquipmentUnit.objects.create(equipment=item, asset_tag="LONG-CATALOG-1")

        response = self.client.get(reverse("equipment_catalog"), {"q": item.name[:24]})
        self.assertContains(response, item.name[:150])
        self.assertContains(response, "A detailed public description for catalog users.")
        self.assertContains(response, "inventory-catalog-card__description")
        self.assertContains(response, f'href="{reverse("new_borrowing_request")}?equipment={item.pk}"')

    def test_catalog_and_details_never_expose_identifiers_internal_counts_or_admin_controls(self):
        EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status="MAINTENANCE")
        self.client.force_login(self.borrower)
        for url in [reverse("equipment_catalog"), reverse("equipment_detail", args=[self.equipment.pk])]:
            response = self.client.get(url)
            for private in ["PROJECTOR-1", "PROJECTOR-2", "SPEAKER-PRIVATE-TAG", "Maintenance", "Retired", "Add physical unit", "Review archive", "/manage/equipment/"]:
                self.assertNotContains(response, private)
            label = "Available" if url == reverse("equipment_catalog") else "Available Units"
            self.assertContains(response, f"<dt>{label}</dt><dd>1</dd>", html=True)
            self.assertContains(response, "<dt>Total Serviceable</dt><dd>1</dd>", html=True)

    def test_archived_items_hidden_and_detail_returns_404(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("equipment_catalog"), {"state": "archived"})
        self.assertNotContains(response, "<h2>Projector</h2>")
        self.assertEqual(self.client.get(reverse("equipment_detail", args=[self.equipment.pk])).status_code, 404)

    def test_combined_catalog_filters_and_pagination_preserve_query_parameters(self):
        self.client.force_login(self.borrower)
        matching = []
        for index in range(12):
            item = Equipment.objects.create(name=f"Camera kit {index:02d}", category=self.category)
            EquipmentUnit.objects.create(equipment=item, asset_tag=f"FILTER-{index}")
            matching.append(item.pk)
        Equipment.objects.create(name="Camera unavailable", category=self.category)
        wrong_category = Equipment.objects.create(name="Camera audio kit", category=self.other_category)
        EquipmentUnit.objects.create(equipment=wrong_category, asset_tag="FILTER-OTHER")
        archived = Equipment.objects.create(name="Camera archived", category=self.category, is_active=False)
        EquipmentUnit.objects.create(equipment=archived, asset_tag="FILTER-ARCHIVED")
        query = {"q": "cAmErA", "category": str(self.category.pk), "availability": "available"}
        response = self.client.get(reverse("equipment_catalog"), query)
        self.assertEqual([item.pk for item in response.context["page_obj"]], matching[:10])
        self.assertEqual(response.context["page_obj"].paginator.count, 12)
        links = response.context["links"]
        self.assertEqual(parse_qs(urlsplit(links["next"]).query), {**{key: [value] for key, value in query.items()}, "page": ["2"]})
        self.assertContains(response, 'method="get"')
        self.assertContains(response, 'aria-label="Filter equipment catalog"')
        second = self.client.get(reverse("equipment_catalog") + links["next"])
        self.assertEqual([item.pk for item in second.context["page_obj"]], matching[10:])
        self.assertEqual(parse_qs(urlsplit(second.context["links"]["previous"]).query), {**{key: [value] for key, value in query.items()}, "page": ["1"]})
        no_match = self.client.get(reverse("equipment_catalog"), {**query, "category": self.other_category.pk, "q": "Projector"})
        self.assertEqual(no_match.context["page_obj"].paginator.count, 0)
        self.assertContains(no_match, "No equipment in this view")
        self.assertContains(no_match, f'<a class="inventory-empty-reset" href="{reverse("equipment_catalog")}">Clear filters</a>', html=True)

    def test_catalog_empty_state_when_only_archived_items_exist(self):
        Equipment.objects.update(is_active=False)
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("equipment_catalog"))
        self.assertContains(response, "No equipment listed yet")
        self.assertNotContains(response, "Clear filters")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_public_descriptions_and_text_availability_labels(self):
        self.equipment.description = "Classroom projector <script>alert(1)</script>\nIncludes carrying case."
        self.equipment.save(update_fields=["description"])
        self.client.force_login(self.borrower)
        catalog = self.client.get(reverse("equipment_catalog"))
        self.assertContains(catalog, "Classroom projector &lt;script&gt;")
        self.assertNotContains(catalog, "<script>alert(1)</script>")
        detail = self.client.get(reverse("equipment_detail", args=[self.equipment.pk]))
        self.assertContains(detail, "&lt;/script&gt;<br>Includes carrying case.")
        self.assertContains(detail, 'aria-describedby="serviceable-help"')
        EquipmentUnit.objects.filter(equipment=self.equipment).update(status="RESERVED")
        for url in [reverse("equipment_catalog"), reverse("equipment_detail", args=[self.equipment.pk])]:
            response = self.client.get(url)
            self.assertContains(response, "Unavailable")
            label = "Available" if url == reverse("equipment_catalog") else "Available Units"
            self.assertContains(response, f"<dt>{label}</dt><dd>0</dd>", html=True)
            self.assertContains(response, "<dt>Total Serviceable</dt><dd>2</dd>", html=True)
            self.assertNotContains(response, f"?equipment={self.equipment.pk}")

    def test_equipment_detail_keeps_long_names_and_complete_escaped_descriptions(self):
        from django.utils.html import escape
        self.client.force_login(self.borrower)
        maximum = Equipment._meta.get_field("name").max_length
        self.equipment.name = "Equipment" + "X" * (maximum - len("Equipment"))
        self.equipment.description = "Classroom use and presentation equipment. " * 40 + "\nFinal note: <script>private</script>"
        self.equipment.save(update_fields=["name", "description"])
        response = self.client.get(reverse("equipment_detail", args=[self.equipment.pk]))
        self.assertContains(response, f'<h1 id="equipment-title">{self.equipment.name}</h1>', html=True)
        self.assertContains(response, str(escape(self.equipment.description)).replace("\n", "<br>"))
        self.assertNotContains(response, "<script>private</script>")
        self.assertNotContains(response, "Equipment details")
        self.assertContains(response, f"?equipment={self.equipment.pk}")

    def test_request_link_prefills_eligible_equipment_and_handles_invalid_selection(self):
        self.client.force_login(self.borrower)
        self.assertContains(self.client.get(reverse("equipment_detail", args=[self.equipment.pk])), f"?equipment={self.equipment.pk}")
        selected = self.client.get(reverse("new_borrowing_request"), {"equipment": self.equipment.pk})
        self.assertEqual(selected.context["formset"][0]["equipment"].value(), self.equipment.pk)
        self.assertEqual(len(selected.context["formset"]), 1)
        invalid = self.client.get(reverse("new_borrowing_request"), {"equipment": "invalid"})
        self.assertContains(invalid, "equipment is unavailable")

    def test_archived_equipment_cannot_be_prefilled_or_submitted(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        self.client.force_login(self.borrower)
        self.assertContains(self.client.get(reverse("new_borrowing_request"), {"equipment": self.equipment.pk}), "equipment is unavailable")
        data = {"purpose": "Bypass archive", "due_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
                "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-0-equipment": self.equipment.pk, "items-0-quantity": "1"}
        self.assertEqual(self.client.post(reverse("new_borrowing_request"), data).status_code, 200)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_admin_category_create_edit_duplicate_and_delete_routes(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("create_category"), {"name": "Photography", "description": "Cameras"}).status_code, 302)
        category = Category.objects.get(name="Photography")
        self.assertEqual(self.client.post(reverse("edit_category", args=[category.pk]), {"name": "Camera equipment", "description": "Updated"}).status_code, 302)
        response = self.client.post(reverse("create_category"), {"name": " presentation ", "description": ""})
        self.assertContains(response, "category with this name already exists")
        self.assertEqual(self.client.post(reverse("delete_category", args=[category.pk]), {"confirm": "on"}).status_code, 302)
        self.assertFalse(Category.objects.filter(pk=category.pk).exists())

    def test_referenced_category_deletion_denied_in_backend(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("delete_category", args=[self.category.pk]), {"confirm": "on"})
        self.assertContains(response, "cannot be deleted", status_code=409)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_catalog_create_edit_and_forged_stock_state_ignored(self):
        self.client.force_login(self.admin)
        data = {"name": "Camera", "description": "Public details", "category": self.category.pk, "is_active": "", "available_count": "99999"}
        self.assertEqual(self.client.post(reverse("create_equipment"), data).status_code, 302)
        equipment = Equipment.objects.get(name="Camera")
        self.assertTrue(equipment.is_active)
        self.assertEqual(inventory_queryset().get(pk=equipment.pk).available_count, 0)
        archive_equipment(equipment.pk, actor=self.admin)
        data.update(name="Camera renamed", is_active="on")
        self.assertEqual(self.client.post(reverse("edit_equipment", args=[equipment.pk]), data).status_code, 302)
        equipment.refresh_from_db()
        self.assertFalse(equipment.is_active)
        self.assertEqual(equipment.name, "Camera renamed")

    def test_catalog_creation_requires_category_and_name(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("create_equipment"), {"name": "", "description": "Incomplete"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_archive_restore_confirmation_and_admin_state_filters(self):
        self.client.force_login(self.admin)
        url = reverse("archive_equipment", args=[self.equipment.pk])
        self.assertContains(self.client.post(url, {}), "Confirm this action")
        self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 302)
        self.assertEqual(len(self.client.get(reverse("equipment_inventory"), {"state": "archived"}).context["page_obj"]), 1)
        self.assertEqual(self.client.post(reverse("restore_equipment", args=[self.equipment.pk]), {"confirm": "on"}).status_code, 302)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

    def test_archive_reserved_equipment_rejected_and_no_form_on_review(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        self.client.force_login(self.admin)
        url = reverse("archive_equipment", args=[self.equipment.pk])
        self.assertNotContains(self.client.get(url), 'id="inventory-action"')
        self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 409)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

    def test_unit_create_edit_unique_identifier_and_forged_status_parent_ignored(self):
        self.client.force_login(self.admin)
        data = {"asset_tag": " camera-new ", "status": "ON_LOAN", "equipment": self.other_equipment.pk}
        self.assertEqual(self.client.post(reverse("add_equipment_unit", args=[self.equipment.pk]), data).status_code, 302)
        unit = EquipmentUnit.objects.get(asset_tag="CAMERA-NEW")
        self.assertEqual(unit.status, "AVAILABLE")
        self.assertEqual(unit.equipment, self.equipment)
        data["asset_tag"] = "EDITED"
        self.assertEqual(self.client.post(reverse("edit_equipment_unit", args=[unit.pk]), data).status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.equipment, self.equipment)
        self.assertEqual(unit.status, "AVAILABLE")
        response = self.client.post(reverse("add_equipment_unit", args=[self.equipment.pk]), {"asset_tag": "PROJECTOR-1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_busy_unit_edit_and_maintenance_restore_attempts_rejected(self):
        self.client.force_login(self.admin)
        for status in ["RESERVED", "ON_LOAN", "MAINTENANCE"]:
            EquipmentUnit.objects.filter(pk=self.units[0].pk).update(status=status)
            response = self.client.post(reverse("edit_equipment_unit", args=[self.units[0].pk]), {"asset_tag": "BYPASS", "status": "AVAILABLE"})
            self.assertEqual(response.status_code, 409)
            self.units[0].refresh_from_db()
            self.assertEqual(self.units[0].status, status)
            self.assertEqual(self.units[0].asset_tag, "PROJECTOR-1")

    def test_archived_item_cannot_receive_new_units(self):
        archive_equipment(self.equipment.pk, actor=self.admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("add_equipment_unit", args=[self.equipment.pk]), {"asset_tag": "ARCHIVE-BYPASS"}).status_code, 409)

    def test_retirement_and_retired_edit_do_not_reactivate_unit(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("retire_equipment_unit", args=[self.units[0].pk]), {"confirm": "on"}).status_code, 302)
        self.assertEqual(self.client.post(reverse("edit_equipment_unit", args=[self.units[0].pk]), {"asset_tag": "RETIRED-TAG", "status": "AVAILABLE"}).status_code, 302)
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].status, "RETIRED")

    def test_admin_search_unit_status_equipment_and_category_filters(self):
        self.client.force_login(self.admin)
        retire_unit(self.units[0].pk, actor=self.admin)
        response = self.client.get(reverse("equipment_units"), {"status": "RETIRED", "q": "PROJECTOR", "equipment": self.equipment.pk})
        self.assertEqual([unit.pk for unit in response.context["page_obj"]], [self.units[0].pk])
        self.assertContains(response, "PROJECTOR-1")
        self.assertEqual(len(self.client.get(reverse("equipment_inventory"), {"category": self.other_category.pk}).context["page_obj"]), 1)
        self.assertEqual(len(self.client.get(reverse("equipment_categories"), {"q": "Audio"}).context["page_obj"]), 1)

    def test_get_admin_pages_render_without_modifying_data(self):
        self.client.force_login(self.admin)
        pages = [
            ("equipment_inventory", []), ("equipment_categories", []), ("create_category", []),
            ("edit_category", [self.category.pk]), ("create_equipment", []), ("edit_equipment", [self.equipment.pk]),
            ("admin_equipment_detail", [self.equipment.pk]), ("equipment_units", []),
            ("add_equipment_unit", [self.equipment.pk]), ("edit_equipment_unit", [self.units[0].pk]),
            ("archive_equipment", [self.equipment.pk]), ("retire_equipment_unit", [self.units[0].pk]),
        ]
        original = list(EquipmentUnit.objects.values_list("pk", "asset_tag", "status"))
        for name, args in pages:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(list(EquipmentUnit.objects.values_list("pk", "asset_tag", "status")), original)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

    def test_permissions_for_anonymous_basic_admin_and_staff_roles(self):
        self.assertEqual(self.client.get(reverse("equipment_catalog")).status_code, 302)
        self.assertEqual(self.client.get(reverse("equipment_inventory")).status_code, 302)
        self.borrower.is_staff = True
        self.borrower.is_superuser = True
        self.borrower.save()
        self.client.force_login(self.borrower)
        for name, args in [
            ("create_category", []), ("edit_category", [self.category.pk]), ("delete_category", [self.category.pk]),
            ("create_equipment", []), ("edit_equipment", [self.equipment.pk]), ("archive_equipment", [self.equipment.pk]),
            ("restore_equipment", [self.equipment.pk]), ("add_equipment_unit", [self.equipment.pk]),
            ("edit_equipment_unit", [self.units[0].pk]), ("retire_equipment_unit", [self.units[0].pk]),
        ]:
            url = reverse(name, args=args)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("equipment_units")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("equipment_catalog")).status_code, 403)

    def test_csrf_on_all_state_changing_endpoints(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for name, args in [
            ("create_category", []), ("edit_category", [self.category.pk]), ("delete_category", [self.category.pk]),
            ("create_equipment", []), ("edit_equipment", [self.equipment.pk]), ("archive_equipment", [self.equipment.pk]),
            ("restore_equipment", [self.equipment.pk]), ("add_equipment_unit", [self.equipment.pk]),
            ("edit_equipment_unit", [self.units[0].pk]), ("retire_equipment_unit", [self.units[0].pk]),
        ]:
            self.assertEqual(client.post(reverse(name, args=args), {"confirm": "on"}).status_code, 403)

    def test_empty_catalog_invalid_filters_and_pagination(self):
        self.client.force_login(self.borrower)
        invalid = self.client.get(reverse("equipment_catalog"), {"category": "999999"})
        self.assertTrue(invalid.context["filter_form"].errors)
        self.assertContains(invalid, "No equipment in this view")
        for index in range(20):
            save_equipment(actor=self.admin, name=f"Projector extra {index}", category_id=self.category.pk)
        first = self.client.get(reverse("equipment_catalog"), {"category": self.category.pk})
        self.assertEqual(len(first.context["page_obj"]), 10)
        self.assertContains(first, f"category={self.category.pk}&amp;page=2")
        second = self.client.get(reverse("equipment_catalog"), {"category": self.category.pk, "page": "2"})
        self.assertEqual(len(second.context["page_obj"]), 10)
        third = self.client.get(second.wsgi_request.path, {**second.wsgi_request.GET.dict(), "page": "3"})
        self.assertEqual(len(third.context["page_obj"]), 1)
        self.assertContains(third, "Showing 21–21 of 21 records.")
        self.assertEqual(self.client.get(reverse("equipment_catalog"), {"page": "invalid"}).status_code, 200)


class CategoryModalTests(InventoryFixtures, TestCase):
    headers = {"HTTP_X_ADMIN_MODAL": "1"}

    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_modal_loads_prefilled_form_without_changing_category(self):
        response = self.client.get(reverse("edit_category", args=[self.category.pk]), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-admin-modal-form')
        self.assertContains(response, 'value="Presentation"')
        self.assertContains(response, "Teaching equipment")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, "<html")
        self.assertIn("X-Admin-Modal", response.headers["Vary"])
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "Presentation")

    def test_modal_create_and_edit_use_existing_validation_and_success_feedback(self):
        response = self.client.post(reverse("create_category"), {"name": "Cameras", "description": "Photo equipment"}, **self.headers)
        self.assertEqual(response.json(), {"saved": True})
        category = Category.objects.get(name="Cameras")
        response = self.client.post(reverse("edit_category", args=[category.pk]), {"name": "Photography", "description": "Updated"}, **self.headers)
        self.assertEqual(response.json(), {"saved": True})
        category.refresh_from_db()
        self.assertEqual((category.name, category.description), ("Photography", "Updated"))
        listing = self.client.get(reverse("equipment_categories"), {"q": "Photo", "page": 1})
        self.assertContains(listing, "Category saved.")
        self.assertContains(listing, "Photography")
        self.assertContains(listing, 'data-admin-form="Create category"')
        self.assertContains(listing, 'data-admin-form="Edit category"')

    def test_invalid_modal_values_are_preserved_and_do_not_write_partial_records(self):
        original_count = Category.objects.count()
        response = self.client.post(reverse("create_category"), {"name": "", "description": "Keep this draft"}, **self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "This field is required", status_code=422)
        self.assertContains(response, "Keep this draft", status_code=422)
        self.assertEqual(Category.objects.count(), original_count)
        response = self.client.post(reverse("edit_category", args=[self.category.pk]), {"name": "audio", "description": "Keep this too"}, **self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Keep this too", status_code=422)
        self.category.refresh_from_db()
        self.assertEqual((self.category.name, self.category.description), ("Presentation", "Teaching equipment"))

        from unittest.mock import patch
        with patch("apps.inventory.views.save_category", side_effect=ValidationError("Category changed concurrently.")):
            response = self.client.post(reverse("edit_category", args=[self.category.pk]), {"name": "Valid draft", "description": "Uncommitted description"}, **self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Category changed concurrently.", status_code=409)
        self.assertContains(response, "Uncommitted description", status_code=409)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "Presentation")

    def test_direct_urls_remain_functional_without_modal_header(self):
        self.assertContains(self.client.get(reverse("create_category")), "<h1>Create category</h1>", html=True)
        response = self.client.post(reverse("create_category"), {"name": "", "description": "Draft"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Draft")
        self.assertRedirects(self.client.post(reverse("create_category"), {"name": "Direct form", "description": ""}), reverse("equipment_categories"))
        self.assertRedirects(self.client.post(reverse("edit_category", args=[self.category.pk]), {"name": "Updated directly", "description": ""}), reverse("equipment_categories"))

    def test_modal_header_does_not_bypass_permissions_or_csrf(self):
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.admin)
        for route, args in [("create_category", []), ("edit_category", [self.category.pk])]:
            url = reverse(route, args=args)
            self.assertEqual(protected.post(url, {"name": "Forged"}, **self.headers).status_code, 403)
            self.client.force_login(self.borrower)
            self.assertEqual(self.client.get(url, **self.headers).status_code, 403)
            self.assertEqual(self.client.post(url, {"name": "Forbidden"}, **self.headers).status_code, 403)
            self.client.logout()
            self.assertEqual(self.client.get(url, **self.headers).status_code, 302)
        self.assertFalse(Category.objects.filter(name__in=["Forged", "Forbidden"]).exists())


class ConcurrentInventoryTests(InventoryFixtures, TransactionTestCase):
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
            except (ValidationError, IntegrityError, OperationalError):
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(worker, operations))
        self.assertEqual(sorted(results), ["rejected", "saved"])

    def test_archiving_and_approval_serialize_without_bypassing_reservations(self):
        request = self.pending()
        self.race([lambda: archive_equipment(self.equipment.pk, actor=self.admin), lambda: approve_request(request.pk, actor=self.admin)])
        self.equipment.refresh_from_db()
        request.refresh_from_db()
        if self.equipment.is_active:
            self.assertEqual(request.status, "APPROVED")
            self.assertEqual(Allocation.objects.filter(active=True).count(), 2)
        else:
            self.assertEqual(request.status, "PENDING")
            self.assertFalse(Allocation.objects.exists())

    def test_two_creations_cannot_duplicate_the_same_physical_identifier(self):
        self.race([lambda: add_unit(self.equipment.pk, actor=self.admin, asset_tag="RACING-TAG")] * 2)
        self.assertEqual(EquipmentUnit.objects.filter(asset_tag="RACING-TAG").count(), 1)

    def test_retirement_and_approval_cannot_allocate_retired_equipment(self):
        request = self.pending()
        self.race([lambda: retire_unit(self.units[0].pk, actor=self.admin), lambda: approve_request(request.pk, actor=self.admin)])
        self.units[0].refresh_from_db()
        request.refresh_from_db()
        if request.status == "APPROVED":
            self.assertEqual(self.units[0].status, "RESERVED")
        else:
            self.assertEqual(self.units[0].status, "RETIRED")
            self.assertFalse(Allocation.objects.exists())
