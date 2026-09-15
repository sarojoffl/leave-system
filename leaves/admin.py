from django.contrib import admin
from django.utils import timezone

from .models import (
    LeaveType, LeaveRequest, LeaveBalance, PublicHoliday,
    AttendanceRequest, HolidayWorkRequest, StaffMovement, StaffMovementAssistant, StaffMovementStop,
    BiometricDevice, AttendanceLog,
)


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "days", "status", "created_at")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__username", "employee__first_name", "employee__last_name", "reason")
    date_hierarchy = "start_date"
    readonly_fields = ("created_at",)
    autocomplete_fields = ("employee",)
    actions = ["mark_approved", "mark_rejected"]

    @admin.display(description="Days")
    def days(self, obj):
        return obj.days

    @admin.action(description="Mark selected requests as approved")
    def mark_approved(self, request, queryset):
        updated = 0
        for leave in queryset.filter(status="pending"):
            leave.status = "approved"
            leave.decided_at = timezone.now()
            leave.save(update_fields=["status", "decided_at"])

            balance, _ = LeaveBalance.objects.get_or_create(
                employee=leave.employee,
                defaults={"total": 12},
            )
            balance.used += leave.days
            balance.save(update_fields=["used"])
            updated += 1

        self.message_user(request, f"{updated} request(s) approved.")

    @admin.action(description="Mark selected requests as rejected")
    def mark_rejected(self, request, queryset):
        updated = queryset.filter(status="pending").update(
            status="rejected", decided_at=timezone.now()
        )
        self.message_user(request, f"{updated} request(s) rejected.")


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "total", "used", "remaining")
    search_fields = ("employee__username", "employee__first_name", "employee__last_name")
    autocomplete_fields = ("employee",)

    @admin.display(description="Remaining")
    def remaining(self, obj):
        return obj.remaining


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "applicable_to")
    list_filter = ("applicable_to", "date")
    date_hierarchy = "date"
    ordering = ("date",)


class BaseDayRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "status", "created_at", "decided_at")
    list_filter = ("status",)
    search_fields = ("employee__username", "employee__first_name", "employee__last_name", "reason")
    date_hierarchy = "date"
    readonly_fields = ("created_at",)
    autocomplete_fields = ("employee",)
    actions = ["mark_approved", "mark_rejected"]

    @admin.action(description="Mark selected requests as approved")
    def mark_approved(self, request, queryset):
        updated = queryset.filter(status="pending").update(
            status="approved", decided_at=timezone.now()
        )
        self.message_user(request, f"{updated} request(s) approved.")

    @admin.action(description="Mark selected requests as rejected")
    def mark_rejected(self, request, queryset):
        updated = queryset.filter(status="pending").update(
            status="rejected", decided_at=timezone.now()
        )
        self.message_user(request, f"{updated} request(s) rejected.")


@admin.register(AttendanceRequest)
class AttendanceRequestAdmin(BaseDayRequestAdmin):
    pass


@admin.register(HolidayWorkRequest)
class HolidayWorkRequestAdmin(BaseDayRequestAdmin):
    pass


class StaffMovementStopInline(admin.TabularInline):
    model = StaffMovementStop
    extra = 0
    fields = ("order", "client", "purpose", "work_done_for", "completion_notes", "resolution_status")
    ordering = ("order", "id")


class StaffMovementAssistantInline(admin.TabularInline):
    """
    Lets a manager see and, if needed, correct each assistant's own
    return time — this is the 'separate flow' referenced in the
    self-service hard lock: once an assistant's in_time is set via the
    normal employee flow, this admin inline is the only way left to fix it.
    """
    model = StaffMovementAssistant
    extra = 0
    autocomplete_fields = ("employee",)
    fields = ("employee", "in_time", "resolution_status", "completion_notes")


@admin.register(StaffMovement)
class StaffMovementAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "client", "purpose_type", "out_time", "in_time", "resolution_status", "created_at")
    list_filter = ("date", "employee", "client", "purpose_type", "resolution_status")
    search_fields = ("employee__username", "employee__first_name", "employee__last_name", "client", "purpose", "problem_description", "completion_notes")
    date_hierarchy = "date"
    readonly_fields = ("created_at",)
    autocomplete_fields = ("employee", "logged_by")
    inlines = [StaffMovementStopInline, StaffMovementAssistantInline]


@admin.register(StaffMovementStop)
class StaffMovementStopAdmin(admin.ModelAdmin):
    list_display = ("movement", "order", "client", "purpose", "work_done_for", "resolution_status")
    list_filter = ("client", "resolution_status", "movement__date")
    search_fields = ("client", "purpose", "work_done_for", "completion_notes", "movement__employee__username")
    ordering = ("-movement__date", "order")


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "name", "is_active", "last_seen", "created_at")
    list_filter = ("is_active",)
    search_fields = ("serial_number", "name")
    readonly_fields = ("created_at", "last_seen")


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ("device_user_id", "employee", "timestamp", "status_display", "verify_display", "device")
    list_filter = ("status", "device", "timestamp")
    search_fields = ("device_user_id", "employee__username", "employee__first_name", "employee__last_name")
    date_hierarchy = "timestamp"
    readonly_fields = ("created_at", "raw_data")
    autocomplete_fields = ("employee",)

    @admin.display(description="Status")
    def status_display(self, obj):
        return obj.get_status_display()

    @admin.display(description="Verify")
    def verify_display(self, obj):
        return obj.get_verify_mode_display() if obj.verify_mode is not None else "—"