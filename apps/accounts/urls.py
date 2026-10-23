from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing_page, name="home"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("portal/profile/", views.profile, name="my_profile"),
    path("portal/profile/password/", views.password_change, name="change_password"),
    path("manage/profile/", views.admin_profile, name="admin_profile"),
    path("manage/profile/password/", views.admin_password_change, name="admin_change_password"),
    path("manage/users/", views.user_management, name="user_management"),
    path("manage/users/<int:pk>/", views.user_detail, name="user_detail"),
    path("manage/users/<int:pk>/activate/", views.activate_user, name="activate_user"),
    path("manage/users/<int:pk>/deactivate/", views.deactivate_user, name="deactivate_user"),
    path("manage/users/<int:pk>/role/", views.change_user_role, name="change_user_role"),
]
