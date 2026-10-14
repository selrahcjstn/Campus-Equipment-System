from django.urls import path
from . import views

urlpatterns = [
    path("portal/requests/", views.my_requests, name="my_requests"),
    path("portal/requests/new/", views.new_request, name="new_borrowing_request"),
    path("portal/requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("portal/requests/<int:pk>/cancel/", views.user_cancel, name="cancel_borrowing_request"),
    path("manage/requests/", views.borrowing_requests, name="borrowing_requests"),
    path("manage/requests/<int:pk>/", views.admin_request_detail, name="admin_request_detail"),
    path("manage/requests/<int:pk>/approve/", views.approve, name="approve_borrowing_request"),
    path("manage/requests/<int:pk>/reject/", views.reject, name="reject_borrowing_request"),
    path("manage/requests/<int:pk>/cancel/", views.admin_cancel, name="admin_cancel_borrowing_request"),
]
