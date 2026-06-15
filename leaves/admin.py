from django.contrib import admin

from .models import LeaveType, LeaveRequest, LeaveBalance, PublicHoliday


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "total_days", "color")
    search_fields = ("name",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "days", "status", "created_at")
    list_filter = ("status", "leave_type", "duration")
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
        from django.utils import timezone
        updated = 0
        for leave in queryset.filter(status="pending"):
            leave.status = "approved"
            leave.decided_at = timezone.now()
            leave.save(update_fields=["status", "decided_at"])

            balance, _ = LeaveBalance.objects.get_or_create(
                employee=leave.employee,
                leave_type=leave.leave_type,
                defaults={"total": leave.leave_type.total_days},
            )
            balance.used += leave.days
            balance.save(update_fields=["used"])
            updated += 1

        self.message_user(request, f"{updated} request(s) approved.")

    @admin.action(description="Mark selected requests as rejected")
    def mark_rejected(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status="pending").update(
            status="rejected", decided_at=timezone.now()
        )
        self.message_user(request, f"{updated} request(s) rejected.")


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "total", "used", "remaining")
    list_filter = ("leave_type",)
    search_fields = ("employee__username", "employee__first_name", "employee__last_name")
    autocomplete_fields = ("employee",)

    @admin.display(description="Remaining")
    def remaining(self, obj):
        return obj.remaining


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name")
    list_filter = ("date",)
    date_hierarchy = "date"
    ordering = ("date",)