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
    path("", include("apps.loans.urls")),
    path("", include("apps.borrowing.urls")),
    path("", include("apps.inventory.urls")),
    path("manage/maintenance/", include("apps.maintenance.urls")),
    path("", include("apps.dashboard.urls")),
    # Navigation previews only; module owners replace these with their real pages.
    path("portal/profile/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_user.html", "page_title": "My Profile"}), name="my_profile"),
    path("manage/users/", TemplateView.as_view(template_name="navigation/page.html", extra_context={"portal_base": "base_admin.html", "page_title": "Users"}), name="user_management"),
]
