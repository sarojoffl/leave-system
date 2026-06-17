from datetime import date
from .models import LeaveRequest, AttendanceRequest, HolidayWorkRequest
from .bs_convert import ad_to_bs, bs_fiscal_year   # adjust import path as needed


def sidebar_context(request):
    if not request.user.is_authenticated:
        return {}

    user  = request.user
    today = date.today()

    # ── Nepali fiscal year (Shrawan 1 – Ashad end, i.e. BS month 4 → 3) ──
    # bs_fiscal_year() returns e.g. "2081–82"
    nepali_fy = bs_fiscal_year(today)           # "2082–83" right now
    bs_y, bs_m, bs_d = ad_to_bs(today)          # full BS date if you need it elsewhere

    pending_count = None
    if user.role in ('manager', 'hr'):
        pending_count = (
            LeaveRequest.objects.filter(status='pending').exclude(employee=user).count()
            + AttendanceRequest.objects.filter(status='pending').exclude(employee=user).count()
            + HolidayWorkRequest.objects.filter(status='pending').exclude(employee=user).count()
        )

    return {
        "sidebar_initials":        user.initials,
        "user_role":               user.get_role_display(),
        "current_fiscal_year":     nepali_fy,       # "2082–83"  ← replaces "2025–26"
        "current_year":            today.year,
        "today":                   today,
        "today_bs":                f"{bs_y}-{bs_m:02d}-{bs_d:02d}",   # bonus: BS date
        "pending_approvals_count": pending_count,
    }