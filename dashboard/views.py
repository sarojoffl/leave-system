from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from leaves.models import LeaveRequest, LeaveBalance


@login_required
def dashboard(request):
    user = request.user
    today = date.today()

    balances = list(LeaveBalance.objects.filter(employee=user).select_related("leave_type"))

    leave_balances = [{
        "name": b.leave_type.name,
        "used": b.used,
        "total": b.total,
        "percent": b.percent,
        "color": b.leave_type.color,
    } for b in balances]

    annual = next((b for b in balances if b.leave_type.name.lower().startswith("annual")), None)
    sick = next((b for b in balances if b.leave_type.name.lower().startswith("sick")), None)

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
        LeaveRequest.objects
        .filter(employee=user, status="pending")
        .count()
    )

    context = {
        "annual_balance": annual.remaining if annual else 0,
        "annual_total": annual.total if annual else 0,
        "sick_balance": sick.remaining if sick else 0,
        "sick_total": sick.total if sick else 0,
        "days_taken": days_taken,
        "leave_balances": leave_balances,
        "recent_leaves": recent_leaves,
        "team_on_leave_today": team_today,
        "own_pending_count": own_pending_count,
    }

    return render(request, "dashboard/dashboard.html", context)