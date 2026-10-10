"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path("", include("apps.accounts.urls")),
    path(
        "portal/",
        TemplateView.as_view(template_name="dashboard/user_portal.html"),
        name="user_dashboard",
    ),
    path(
        "manage/",
        TemplateView.as_view(template_name="dashboard/admin_portal.html"),
        name="admin_dashboard",
    ),
    # Navigation previews only; module owners replace these with their real pages.
    path("portal/equipment/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "Equipment Catalog"}), name="equipment_catalog"),
    path("portal/requests/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "My Borrowing Requests"}), name="my_requests"),
    path("portal/loans/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "My Loans"}), name="my_loans"),
    path("portal/history/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "Borrowing History"}), name="borrowing_history"),
    path("portal/profile/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "My Profile"}), name="my_profile"),
    path("manage/users/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Users"}), name="user_management"),
    path("manage/categories/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Categories"}), name="equipment_categories"),
    path("manage/equipment/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Equipment Inventory"}), name="equipment_inventory"),
    path("manage/requests/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Borrowing Requests"}), name="borrowing_requests"),
    path("manage/loans/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Loan Management"}), name="loan_management"),
    path("manage/returns/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Returns and Overdue"}), name="returns_overdue"),
    path("manage/maintenance/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Maintenance"}), name="maintenance"),
    path("manage/reports/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Reports"}), name="reports"),
    path("manage/audit-logs/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Audit Logs"}), name="audit_logs"),
    path("manage/settings/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "System Settings"}), name="system_settings"),
]
