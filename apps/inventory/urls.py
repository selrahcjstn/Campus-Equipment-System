from django.urls import path
from . import views

urlpatterns = [
    path("portal/equipment/", views.equipment_catalog, name="equipment_catalog"),
    path("portal/equipment/<int:pk>/", views.equipment_detail, name="equipment_detail"),
    path("manage/categories/", views.categories, name="equipment_categories"),
    path("manage/categories/new/", views.category_form, name="create_category"),
    path("manage/categories/<int:pk>/edit/", views.category_form, name="edit_category"),
    path("manage/categories/<int:pk>/delete/", views.category_delete, name="delete_category"),
    path("manage/categories/<int:pk>/archive/", views.category_archive, name="archive_category"),
    path("manage/categories/<int:pk>/restore/", views.category_restore, name="restore_category"),
    path("manage/equipment/", views.equipment_inventory, name="equipment_inventory"),
    path("manage/equipment/new/", views.equipment_form, name="create_equipment"),
    path("manage/equipment/units/", views.units, name="equipment_units"),
    path("manage/equipment/units/<int:pk>/edit/", views.unit_form, name="edit_equipment_unit"),
    path("manage/equipment/units/<int:pk>/retire/", views.unit_retire, name="retire_equipment_unit"),
    path("manage/equipment/<int:pk>/", views.admin_equipment_detail, name="admin_equipment_detail"),
    path("manage/equipment/<int:pk>/edit/", views.equipment_form, name="edit_equipment"),
    path("manage/equipment/<int:pk>/archive/", views.archive, name="archive_equipment"),
    path("manage/equipment/<int:pk>/restore/", views.restore, name="restore_equipment"),
    path("manage/equipment/<int:equipment_pk>/units/new/", views.unit_form, name="add_equipment_unit"),
]
