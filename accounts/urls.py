from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("change-password/", views.change_password_view, name="change_password"),
    path("password-reset/", views.CustomPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.CustomPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset-confirm/<uidb64>/<token>/", views.CustomPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset-complete/", views.CustomPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:user_id>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<int:user_id>/toggle/", views.staff_toggle_active, name="staff_toggle_active"),
    path('set-view-mode/', views.set_view_mode, name='set_view_mode'),
]