from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "device_user_id", "gender", "role", "department", "position", "is_staff")
    list_filter = ("role", "gender", "department", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "device_user_id")
    fieldsets = UserAdmin.fieldsets + (
        ("LeaveTrack & Biometric", {"fields": ("role", "gender", "department", "position", "device_user_id", "must_change_password")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("LeaveTrack & Biometric", {"fields": ("role", "gender", "department", "position", "device_user_id")}),
    )