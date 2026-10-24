from django.urls import path
from . import views


urlpatterns = [
    path("", views.dashboard, name="maintenance"),
    path("new/", views.create, name="maintenance_create"),
    path("units/<int:pk>/history/", views.unit_history, name="maintenance_history"),
    path("<int:pk>/", views.detail, name="maintenance_detail"),
    path("<int:pk>/update/", views.update, name="maintenance_update"),
    path("<int:pk>/start/", views.start, name="maintenance_start"),
    path("<int:pk>/complete/", views.complete, name="maintenance_complete"),
    path("<int:pk>/retire/", views.retire, name="maintenance_retire"),
]
