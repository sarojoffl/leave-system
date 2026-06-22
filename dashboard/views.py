from calendar import Calendar, month_name
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from accounts.utils import get_view_mode
from leaves.models import (
    AttendanceRequest,
    HolidayWorkRequest,
    LeaveBalance,
    LeaveRequest,
    PublicHoliday,
)
from leaves.permissions import manager_required
from leaves.views import get_fiscal_year_start  # reuse the shared helper


# ---------------------------------------------------------------------------
# Employee dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    if get_view_mode(request) == 'manager' and request.user.has_management_access:
        return manager_dashboard(request)

    user = request.user
    today = date.today()

    balance = LeaveBalance.objects.filter(employee=user).first()

    recent_leaves = [{
        "type": l.leave_type.name,
        "date_range": l.date_range,
        "days": l.days,
        "status": l.get_status_display(),
    } for l in LeaveRequest.objects.filter(employee=user).select_related("leave_type")[:5]]

    fiscal_start = get_fiscal_year_start(today)
    days_taken = sum(
        l.days for l in LeaveRequest.objects.filter(
            employee=user, status="approved", start_date__gte=fiscal_start,
        )
    )

    own_pending_count = (
        LeaveRequest.objects.filter(employee=user, status="pending").count()
        + AttendanceRequest.objects.filter(employee=user, status="pending").count()
        + HolidayWorkRequest.objects.filter(employee=user, status="pending").count()
    )

    # ---- Calendar grid ----
    # FIX: pre-fetch holidays and leaves for the whole month in two queries
    # instead of one DB hit per calendar day.

    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

    # Build holiday lookup: {date: holiday_name}
    holiday_map = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(date__year=today.year, date__month=today.month)
    }

    # Build leave lookup: {date: leave_obj} for the current user
    # A leave can span multiple days, so expand it into per-day entries.
    user_leave_map = {}
    for leave in LeaveRequest.objects.filter(
        employee=user,
        start_date__lt=next_month_start,
        end_date__gte=month_start,
        status__in=["approved", "pending"],
    ).select_related("leave_type"):
        d = max(leave.start_date, month_start)
        while d < next_month_start and d <= leave.end_date:
            if d not in user_leave_map:  # first match wins (approved > pending by query order)
                user_leave_map[d] = leave
            d = date(d.year, d.month, d.day + 1) if d.day < 28 else d.replace(day=1) if d.month == 12 else d  # noqa
            # simpler:
            d = date.fromordinal(d.toordinal() + 1)

    cal = Calendar(firstweekday=6)
    weeks = []
    for week in cal.monthdayscalendar(today.year, today.month):
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({})
                continue

            day_date = date(today.year, today.month, day_num)
            classes = []
            title = None

            if day_date.weekday() == 5:  # Saturday
                classes.append("weekend")
                week_data.append({
                    "day_number": day_num,
                    "classes": "weekend",
                    "title": None,
                })
                continue

            if day_date == today:
                classes.append("today")

            if day_date in holiday_map:
                classes.append("holiday")
                title = holiday_map[day_date]
            elif day_date in user_leave_map:
                leave_today = user_leave_map[day_date]
                if leave_today.status == "approved":
                    classes.append("leave-approved")
                    title = f"{leave_today.leave_type.name} – Approved"
                else:
                    classes.append("leave-pending")
                    title = f"{leave_today.leave_type.name} – Pending"

            week_data.append({
                "day_number": day_num,
                "classes": " ".join(classes),
                "title": title,
            })
        weeks.append(week_data)

    team_leaves = (
        LeaveRequest.objects.filter(
            status="approved",
            start_date__lt=next_month_start,
            end_date__gte=month_start,
        )
        .exclude(employee=user)
        .select_related("employee", "leave_type")
    )
    team_on_leave_this_month = [{
        "name": l.employee.get_full_name() or l.employee.username,
        "dates": l.date_range,
        "type": l.leave_type.name,
    } for l in team_leaves]

    context = {
        "balance_used": balance.used if balance else 0,
        "balance_total": balance.total if balance else 12,
        "balance_remaining": balance.remaining if balance else 12,
        "balance_percent": balance.percent if balance else 0,
        "days_taken": days_taken,
        "recent_leaves": recent_leaves,
        "own_pending_count": own_pending_count,
        "calendar_month_label": f"{month_name[today.month]} {today.year}",
        "calendar_weeks": weeks,
        "public_holidays": list(holiday_map.items()),  # already fetched
        "team_on_leave_this_month": team_on_leave_this_month,
    }

    return render(request, "dashboard/dashboard.html", context)


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------

@manager_required
def manager_dashboard(request):
    from accounts.models import User

    today = date.today()
    employees = User.objects.exclude(id=request.user.id)
    employee_count = employees.count()

    on_leave_qs = (
        LeaveRequest.objects.filter(
            status="approved", start_date__lte=today, end_date__gte=today,
        )
        .exclude(employee=request.user)
        .select_related("employee", "leave_type")
    )
    on_leave_today = [{
        "name": l.employee.get_full_name() or l.employee.username,
        "type": l.leave_type.name,
        "returns": l.end_date + timedelta(days=1),
    } for l in on_leave_qs]
    on_leave_today_count = len(on_leave_today)

    pending_leave_count = (
        LeaveRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    )
    pending_attendance_count = (
        AttendanceRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    )
    pending_holiday_count = (
        HolidayWorkRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    )
    total_pending = pending_leave_count + pending_attendance_count + pending_holiday_count

    fiscal_start = get_fiscal_year_start(today)
    days_taken_this_fy = sum(
        l.days for l in LeaveRequest.objects.filter(
            status="approved", start_date__gte=fiscal_start,
        ).exclude(employee=request.user)
    )

    # "Needs attention" — employees with pending requests
    # Fetch counts in 3 bulk queries instead of N*3
    from django.db.models import Count
    emp_ids = list(employees.values_list('id', flat=True))

    leave_pending_map = {
        row['employee_id']: row['cnt']
        for row in LeaveRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }
    att_pending_map = {
        row['employee_id']: row['cnt']
        for row in AttendanceRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }
    hol_pending_map = {
        row['employee_id']: row['cnt']
        for row in HolidayWorkRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }

    needs_attention = []
    for emp in employees.only('id', 'first_name', 'last_name', 'username'):
        count = (
            leave_pending_map.get(emp.id, 0)
            + att_pending_map.get(emp.id, 0)
            + hol_pending_map.get(emp.id, 0)
        )
        if count:
            needs_attention.append({
                "name": emp.get_full_name() or emp.username,
                "initials": emp.initials,
                "count": count,
            })
    needs_attention.sort(key=lambda s: -s["count"])

    upcoming_cutoff = today + timedelta(days=30)
    upcoming_leaves = [{
        "employee_name": l.employee.get_full_name() or l.employee.username,
        "type": l.leave_type.name,
        "dates": l.date_range,
        "days": l.days,
        "status": l.get_status_display(),
        "starts_in": (l.start_date - today).days,
    } for l in (
        LeaveRequest.objects.filter(
            status__in=["approved", "pending"],
            start_date__gte=today,
            start_date__lte=upcoming_cutoff,
        )
        .exclude(employee=request.user)
        .select_related("employee", "leave_type")
        .order_by("start_date")[:15]
    )]

    month_start = date(today.year, today.month, 1)
    next_month_start = (
        date(today.year + 1, 1, 1) if today.month == 12
        else date(today.year, today.month + 1, 1)
    )

    month_leaves = list(
        LeaveRequest.objects.filter(
            status__in=["approved", "pending"],
            start_date__lt=next_month_start,
            end_date__gte=month_start,
        )
        .exclude(employee=request.user)
        .select_related("employee")
    )
    month_holidays = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(date__year=today.year, date__month=today.month)
    }

    cal = Calendar(firstweekday=6)
    weeks = []
    for week in cal.monthdayscalendar(today.year, today.month):
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({})
                continue

            day_date = date(today.year, today.month, day_num)
            classes = []
            title_bits = []

            is_weekend = day_date.weekday() == 5
            is_holiday = day_date in month_holidays

            if is_weekend:
                classes.append("weekend")
            if day_date == today:
                classes.append("today")
            if is_holiday:
                classes.append("holiday")
                title_bits.append(month_holidays[day_date])

            leave_count = 0
            if not is_weekend and not is_holiday:
                leaves_today = [l for l in month_leaves if l.start_date <= day_date <= l.end_date]
                if leaves_today:
                    has_approved = any(l.status == 'approved' for l in leaves_today)

                    approved_names = sorted({
                        l.employee.get_full_name() or l.employee.username
                        for l in leaves_today if l.status == 'approved'
                    })
                    pending_names = sorted({
                        l.employee.get_full_name() or l.employee.username
                        for l in leaves_today if l.status == 'pending'
                    })

                    title_parts = []
                    if approved_names:
                        title_parts.append(f"Approved: {', '.join(approved_names)}")
                    if pending_names:
                        title_parts.append(f"Pending: {', '.join(pending_names)}")

                    title_bits.append(" | ".join(title_parts))
                    leave_count = len(leaves_today)

                    if has_approved:
                        classes.append("leave-approved")
                    else:
                        classes.append("leave-pending")

            week_data.append({
                "day_number": day_num,
                "classes": " ".join(classes),
                "title": " — ".join(title_bits) if title_bits else None,
                "leave_count": leave_count,
            })
        weeks.append(week_data)

    context = {
        "employee_count": employee_count,
        "on_leave_today_count": on_leave_today_count,
        "on_leave_today": on_leave_today,
        "total_pending": total_pending,
        "pending_leave_count": pending_leave_count,
        "pending_attendance_count": pending_attendance_count,
        "pending_holiday_count": pending_holiday_count,
        "days_taken_this_fy": days_taken_this_fy,
        "needs_attention": needs_attention,
        "upcoming_leaves": upcoming_leaves,
        "calendar_month_label": f"{month_name[today.month]} {today.year}",
        "calendar_weeks": weeks,
    }

    return render(request, "dashboard/manager_dashboard.html", context)