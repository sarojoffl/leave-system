from calendar import Calendar, month_name
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from leaves.models import (
    LeaveRequest,
    LeaveBalance,
    AttendanceRequest,
    HolidayWorkRequest,
    PublicHoliday,
)
from leaves.permissions import manager_required


@login_required
def dashboard(request):
    if request.user.role in ('manager', 'hr'):
        return redirect('manager_dashboard')

    user = request.user
    today = date.today()

    # ---- Stat cards / balance / recent requests ----

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

    own_pending_count = (
        LeaveRequest.objects.filter(employee=user, status="pending").count()
        + AttendanceRequest.objects.filter(employee=user, status="pending").count()
        + HolidayWorkRequest.objects.filter(employee=user, status="pending").count()
    )

    # ---- Calendar grid ----

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

            if day_date.weekday() == 5:
                classes.append("weekend")
                week_data.append({
                    "day_number": day_num,
                    "classes": " ".join(classes),
                    "title": None,
                })
                continue

            if day_date == today:
                classes.append("today")

            holiday = PublicHoliday.objects.filter(date=day_date).first()
            if holiday:
                classes.append("holiday")
                title = holiday.name
            else:
                leave_today = LeaveRequest.objects.filter(
                    employee=user,
                    start_date__lte=day_date,
                    end_date__gte=day_date,
                    status__in=["approved", "pending"],
                ).first()
                if leave_today:
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

    public_holidays = PublicHoliday.objects.filter(
        date__year=today.year, date__month=today.month
    )

    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

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
        "public_holidays": public_holidays,
        "team_on_leave_this_month": team_on_leave_this_month,
    }

    return render(request, "dashboard/dashboard.html", context)


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

    pending_leave_count = LeaveRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    pending_attendance_count = AttendanceRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    pending_holiday_count = HolidayWorkRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    total_pending = pending_leave_count + pending_attendance_count + pending_holiday_count

    fiscal_start = date(today.year if today.month >= 7 else today.year - 1, 7, 17)
    days_taken_this_fy = sum(
        l.days for l in LeaveRequest.objects.filter(
            status="approved", start_date__gte=fiscal_start,
        ).exclude(employee=request.user)
    )

    needs_attention = []
    for emp in employees:
        count = (
            LeaveRequest.objects.filter(employee=emp, status="pending").count()
            + AttendanceRequest.objects.filter(employee=emp, status="pending").count()
            + HolidayWorkRequest.objects.filter(employee=emp, status="pending").count()
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
                names_on_leave = sorted({
                    l.employee.get_full_name() or l.employee.username
                    for l in month_leaves
                    if l.start_date <= day_date <= l.end_date
                })
                if names_on_leave:
                    classes.append("has-leave")
                    title_bits.append(", ".join(names_on_leave))
                    leave_count = len(names_on_leave)

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