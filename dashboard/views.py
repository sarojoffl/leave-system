from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from leaves.models import LeaveRequest, LeaveBalance, AttendanceRequest, HolidayWorkRequest


@login_required
def dashboard(request):
    user = request.user
    today = date.today()

    balance = LeaveBalance.objects.filter(employee=user).first()

    recent_leaves = [{
        "type": l.leave_type.name,
        "date_range": l.date_range,
        "days": l.days,
        "status": l.get_status_display(),
    } for l in LeaveRequest.objects.filter(employee=user).select_related("leave_type")[:5]]

    fiscal_start = date(today.year if today.month >= 7 else today.year - 1, 7, 17)
    days_taken = sum(
        l.days for l in LeaveRequest.objects.filter(
            employee=user, status="approved", start_date__gte=fiscal_start,
        )
    )

    team_today = []
    if user.role in ("manager", "hr"):
        team_leaves = LeaveRequest.objects.filter(
            status="approved", start_date__lte=today, end_date__gte=today,
        ).exclude(employee=user).select_related("employee", "leave_type")

        team_today = [{
            "name": l.employee.get_full_name() or l.employee.username,
            "department": l.employee.department or "—",
            "leave_type": l.leave_type.name,
            "return_date": (l.end_date + timedelta(days=1)).strftime("%b %d, %Y"),
        } for l in team_leaves]

    own_pending_count = (
        LeaveRequest.objects.filter(employee=user, status="pending").count()
        + AttendanceRequest.objects.filter(employee=user, status="pending").count()
        + HolidayWorkRequest.objects.filter(employee=user, status="pending").count()
    )

    context = {
        "balance_used": balance.used if balance else 0,
        "balance_total": balance.total if balance else 12,
        "balance_remaining": balance.remaining if balance else 12,
        "balance_percent": balance.percent if balance else 0,
        "days_taken": days_taken,
        "recent_leaves": recent_leaves,
        "team_on_leave_today": team_today,
        "own_pending_count": own_pending_count,
    }

    return render(request, "dashboard/dashboard.html", context)