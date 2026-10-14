from django.urls import path

from . import views

# Keep the established unnamespaced sidebar names for integration.
urlpatterns = [
    path("portal/loans/", views.my_loans, name="my_loans"),
    path("portal/history/", views.borrowing_history, name="borrowing_history"),
    path("portal/loans/<int:pk>/", views.user_loan_detail, name="user_loan_detail"),
    path("manage/loans/", views.loan_management, name="loan_management"),
    path("manage/loans/release/<int:pk>/", views.release_equipment, name="release_equipment"),
    path("manage/loans/<int:pk>/", views.admin_loan_detail, name="admin_loan_detail"),
    path("manage/loans/<int:pk>/slip/", views.borrowing_slip, name="borrowing_slip"),
    path("manage/returns/", views.returns_overdue, name="returns_overdue"),
    path("manage/returns/<int:pk>/", views.return_equipment, name="return_equipment"),
]
