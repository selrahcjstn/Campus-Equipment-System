from django.urls import path
from . import views


urlpatterns = [
    path("portal/", views.user_dashboard, name="user_dashboard"),
    path("manage/", views.admin_dashboard, name="admin_dashboard"),
    path("manage/reports/", views.reports, name="reports"),
    path("manage/reports/export/", views.export_reports, name="export_reports"),
    path("manage/audit-logs/", views.audit_logs, name="audit_logs"),
    path("manage/settings/", views.system_settings, name="system_settings"),
]
