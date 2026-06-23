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
from leaves.views import get_fiscal_year_start
from leaves.bs_convert import ad_to_bs, bs_month_name, bs_to_ad, build_ad_label, _BS


def _build_bs_calendar(
    bs_year: int,
    bs_month: int,
    today: date,
    holiday_map: dict,
    leave_map: dict | None = None,
    month_leaves: list | None = None,
    is_manager: bool = False,
) -> list:
    total_days = _BS[bs_year][bs_month - 1]
    first_ad = bs_to_ad(bs_year, bs_month, 1)
    last_ad  = bs_to_ad(bs_year, bs_month, total_days)

    first_weekday_py  = first_ad.weekday()
    first_weekday_sun = (first_weekday_py + 1) % 7

    days_flat = [{}] * first_weekday_sun

    for bs_d in range(1, total_days + 1):
        ad_date = first_ad + timedelta(days=bs_d - 1)
        is_saturday = ad_date.weekday() == 5

        classes = []
        title = None
        leave_count = 0

        if is_saturday:
            classes.append("weekend")
        if ad_date == today:
            classes.append("today")

        if not is_saturday:
            if ad_date in holiday_map:
                classes.append("holiday")
                title = holiday_map[ad_date]
            elif not is_manager and leave_map is not None:
                if ad_date in leave_map:
                    leave_today = leave_map[ad_date]
                    if leave_today.status == "approved":
                        classes.append("leave-approved")
                        title = f"{leave_today.leave_type.name} – Approved"
                    else:
                        classes.append("leave-pending")
                        title = f"{leave_today.leave_type.name} – Pending"
            elif is_manager and month_leaves is not None:
                leaves_today = [
                    l for l in month_leaves
                    if l.start_date <= ad_date <= l.end_date
                ]
                if leaves_today:
                    has_approved = any(l.status == "approved" for l in leaves_today)
                    approved_names = sorted({
                        l.employee.get_full_name() or l.employee.username
                        for l in leaves_today if l.status == "approved"
                    })
                    pending_names = sorted({
                        l.employee.get_full_name() or l.employee.username
                        for l in leaves_today if l.status == "pending"
                    })
                    title_parts = []
                    if approved_names:
                        title_parts.append(f"Approved: {', '.join(approved_names)}")
                    if pending_names:
                        title_parts.append(f"Pending: {', '.join(pending_names)}")
                    title = " | ".join(title_parts)
                    leave_count = len(leaves_today)
                    classes.append("leave-approved" if has_approved else "leave-pending")

        days_flat.append({
            "day_number": ad_date.day,
            "bs_day": bs_d,
            "ad_date": ad_date,
            "classes": " ".join(classes),
            "title": title,
            "leave_count": leave_count,
        })

    while len(days_flat) % 7 != 0:
        days_flat.append({})

    return [days_flat[i:i + 7] for i in range(0, len(days_flat), 7)]


def _get_bs_month_from_request(request, today):
    """Parse bs_year/bs_month from GET params, fall back to current BS month."""
    bs_y_today, bs_m_today, _ = ad_to_bs(today)
    try:
        bs_y = int(request.GET.get("bs_year", bs_y_today))
        bs_m = int(request.GET.get("bs_month", bs_m_today))
        if not (1 <= bs_m <= 12) or bs_y not in _BS:
            raise ValueError
    except (ValueError, TypeError):
        bs_y, bs_m = bs_y_today, bs_m_today
    return bs_y, bs_m, bs_y_today, bs_m_today


def _nav_urls(bs_y, bs_m):
    """Return prev/next URL query strings for calendar navigation."""
    if bs_m == 1:
        prev_y, prev_m = bs_y - 1, 12
    else:
        prev_y, prev_m = bs_y, bs_m - 1

    if bs_m == 12:
        next_y, next_m = bs_y + 1, 1
    else:
        next_y, next_m = bs_y, bs_m + 1

    prev_valid = prev_y in _BS
    next_valid = next_y in _BS

    return (
        f"?bs_year={prev_y}&bs_month={prev_m}" if prev_valid else None,
        f"?bs_year={next_y}&bs_month={next_m}" if next_valid else None,
    )


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

    own_leave_pending        = LeaveRequest.objects.filter(employee=user, status="pending").count()
    own_attendance_pending   = AttendanceRequest.objects.filter(employee=user, status="pending").count()
    own_holiday_pending      = HolidayWorkRequest.objects.filter(employee=user, status="pending").count()
    own_attendance_approved  = AttendanceRequest.objects.filter(employee=user, status="approved").count()
    own_holiday_approved     = HolidayWorkRequest.objects.filter(employee=user, status="approved").count()
    own_pending_count        = own_leave_pending + own_attendance_pending + own_holiday_pending

    bs_y, bs_m, bs_y_today, bs_m_today = _get_bs_month_from_request(request, today)
    is_current_month = (bs_y == bs_y_today and bs_m == bs_m_today)
    prev_url, next_url = _nav_urls(bs_y, bs_m)

    total_bs_days     = _BS[bs_y][bs_m - 1]
    bs_month_start_ad = bs_to_ad(bs_y, bs_m, 1)
    bs_month_end_ad   = bs_to_ad(bs_y, bs_m, total_bs_days)
    bs_month_after_ad = bs_month_end_ad + timedelta(days=1)

    holiday_map = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(
            date__gte=bs_month_start_ad,
            date__lte=bs_month_end_ad,
        )
    }

    user_leave_map = {}
    for leave in LeaveRequest.objects.filter(
        employee=user,
        start_date__lt=bs_month_after_ad,
        end_date__gte=bs_month_start_ad,
        status__in=["approved", "pending"],
    ).select_related("leave_type"):
        d = max(leave.start_date, bs_month_start_ad)
        while d < bs_month_after_ad and d <= leave.end_date:
            if d not in user_leave_map:
                user_leave_map[d] = leave
            d = date.fromordinal(d.toordinal() + 1)

    weeks = _build_bs_calendar(
        bs_year=bs_y,
        bs_month=bs_m,
        today=today,
        holiday_map=holiday_map,
        leave_map=user_leave_map,
        is_manager=False,
    )

    team_leaves = (
        LeaveRequest.objects.filter(
            status="approved",
            start_date__lt=bs_month_after_ad,
            end_date__gte=bs_month_start_ad,
        )
        .exclude(employee=user)
        .select_related("employee", "leave_type")
    )
    team_on_leave_this_month = [{
        "name": l.employee.get_full_name() or l.employee.username,
        "dates": l.date_range,
        "type": l.leave_type.name,
    } for l in team_leaves]

    public_holidays = PublicHoliday.objects.filter(
        date__gte=bs_month_start_ad,
        date__lte=bs_month_end_ad,
    )

    overflow_percent = (
        max(round(((balance.used - balance.total) / balance.total) * 100), 0)
        if balance and balance.total > 0 else 0
    )

    context = {
        "balance_used":        balance.used if balance else 0,
        "balance_total":       balance.total if balance else 12,
        "balance_remaining":   balance.remaining if balance else 12,
        "balance_percent":     balance.percent if balance else 0,
        "overflow_percent":    overflow_percent,
        "days_taken":          days_taken,
        "recent_leaves":       recent_leaves,
        "own_pending_count":         own_pending_count,
        "own_leave_pending":         own_leave_pending,
        "own_attendance_pending":    own_attendance_pending,
        "own_holiday_pending":       own_holiday_pending,
        "own_attendance_approved":   own_attendance_approved,
        "own_holiday_approved":      own_holiday_approved,
        "calendar_bs_month_label":   f"{bs_month_name(bs_m)} {bs_y}",
        "calendar_ad_month_label":   build_ad_label(bs_month_start_ad, bs_month_end_ad),
        "calendar_weeks":            weeks,
        "public_holidays":           public_holidays,
        "team_on_leave_this_month":  team_on_leave_this_month,
        "prev_url":          prev_url,
        "next_url":          next_url,
        "is_current_month":  is_current_month,
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

    pending_leave_count      = LeaveRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    pending_attendance_count = AttendanceRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    pending_holiday_count    = HolidayWorkRequest.objects.filter(status="pending").exclude(employee=request.user).count()
    total_pending            = pending_leave_count + pending_attendance_count + pending_holiday_count

    fiscal_start = get_fiscal_year_start(today)
    days_taken_this_fy = sum(
        l.days for l in LeaveRequest.objects.filter(
            status="approved", start_date__gte=fiscal_start,
        ).exclude(employee=request.user)
    )

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

    bs_y, bs_m, bs_y_today, bs_m_today = _get_bs_month_from_request(request, today)
    is_current_month = (bs_y == bs_y_today and bs_m == bs_m_today)
    prev_url, next_url = _nav_urls(bs_y, bs_m)

    total_bs_days     = _BS[bs_y][bs_m - 1]
    bs_month_start_ad = bs_to_ad(bs_y, bs_m, 1)
    bs_month_end_ad   = bs_to_ad(bs_y, bs_m, total_bs_days)
    bs_month_after_ad = bs_month_end_ad + timedelta(days=1)

    month_holidays = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(
            date__gte=bs_month_start_ad,
            date__lte=bs_month_end_ad,
        )
    }

    month_leaves = list(
        LeaveRequest.objects.filter(
            status__in=["approved", "pending"],
            start_date__lt=bs_month_after_ad,
            end_date__gte=bs_month_start_ad,
        )
        .exclude(employee=request.user)
        .select_related("employee")
    )

    weeks = _build_bs_calendar(
        bs_year=bs_y,
        bs_month=bs_m,
        today=today,
        holiday_map=month_holidays,
        month_leaves=month_leaves,
        is_manager=True,
    )

    context = {
        "employee_count":            employee_count,
        "on_leave_today_count":      on_leave_today_count,
        "on_leave_today":            on_leave_today,
        "total_pending":             total_pending,
        "pending_leave_count":       pending_leave_count,
        "pending_attendance_count":  pending_attendance_count,
        "pending_holiday_count":     pending_holiday_count,
        "days_taken_this_fy":        days_taken_this_fy,
        "needs_attention":           needs_attention,
        "upcoming_leaves":           upcoming_leaves,
        "calendar_bs_month_label":   f"{bs_month_name(bs_m)} {bs_y}",
        "calendar_ad_month_label":   build_ad_label(bs_month_start_ad, bs_month_end_ad),
        "calendar_weeks":            weeks,
        "prev_url":          prev_url,
        "next_url":          next_url,
        "is_current_month":  is_current_month,
    }

    return render(request, "dashboard/manager_dashboard.html", context)