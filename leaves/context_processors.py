from datetime import date
from .models import LeaveRequest, AttendanceRequest, HolidayWorkRequest
from .bs_convert import ad_to_bs, bs_fiscal_year, bs_month_name


def sidebar_context(request):
    if not request.user.is_authenticated:
        return {}

    user  = request.user
    today = date.today()

    nepali_fy = bs_fiscal_year(today)
    bs_y, bs_m, bs_d = ad_to_bs(today)

    pending_count = None
    if user.has_management_access:
        pending_count = (
            LeaveRequest.objects.filter(status='pending').exclude(employee=user).count()
            + AttendanceRequest.objects.filter(status='pending').exclude(employee=user).count()
            + HolidayWorkRequest.objects.filter(status='pending').exclude(employee=user).count()
        )

    return {
        "sidebar_initials":        user.initials,
        "user_role":               user.get_role_display(),
        "current_fiscal_year":     nepali_fy,
        "current_year":            today.year,
        "today":                   today,
        "today_bs":                f"{bs_month_name(bs_m)} {bs_d}, {bs_y}",
        "pending_approvals_count": pending_count,
    }