"""
Utility functions for calculating daily, monthly, and team attendance summaries
from raw ZKTeco biometric punches, integrating with Leaves, Public Holidays,
Attendance Regularizations, and Staff Movements.
"""
from datetime import date, datetime, time, timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import (
    AttendanceLog,
    AttendanceRequest,
    HolidayWorkRequest,
    LeaveRequest,
    PublicHoliday,
    StaffMovement,
    StaffMovementAssistant,
)

User = get_user_model()

# Standard Shift Configuration
SHIFT_START = time(10, 0)       # 10:00 AM
GRACE_CUTOFF = time(10, 15)     # 10:15 AM
HALF_DAY_CUTOFF = time(13, 0)   # 1:00 PM
SHIFT_END = time(17, 30)        # 5:30 PM
MIN_FULL_DAY_HOURS = 7.0        # Minimum hours for full day
MIN_HALF_DAY_HOURS = 4.0        # Minimum hours for half day


def get_daily_attendance_summary(employee, target_date, preloaded_data=None):
    """
    Computes attendance status and punch metrics for a single employee on a given date.
    
    Returns a dict with:
    - date: target_date
    - first_punch: AttendanceLog or None (Check-in)
    - last_punch: AttendanceLog or None (Check-out)
    - punch_count: int
    - duration_seconds: float (0 if 0 or 1 punch)
    - duration_formatted: str (e.g. "7h 28m")
    - status: 'present' | 'late' | 'half_day' | 'on_leave' | 'holiday' | 'weekend' | 'staff_movement' | 'regularized' | 'absent' | 'not_checked_in'
    - status_label: Human-readable display label
    - status_badge_class: CSS badge class
    - leave_info: str or None
    - holiday_name: str or None
    - movement_info: str or None
    - punches: list of AttendanceLog objects
    """
    today = date.today()
    is_future = target_date > today
    is_today = target_date == today
    is_saturday = target_date.weekday() == 5

    # 1. Fetch punches if not preloaded
    if preloaded_data and "punches_by_date" in preloaded_data:
        day_punches = preloaded_data["punches_by_date"].get(target_date, [])
    else:
        # Timezone-aware date boundaries
        tz = timezone.get_current_timezone()
        dt_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
        dt_end = timezone.make_aware(datetime.combine(target_date, time.max), tz)
        day_punches = list(
            AttendanceLog.objects.filter(
                employee=employee,
                timestamp__range=(dt_start, dt_end)
            ).order_by("timestamp")
        )

    first_punch = None
    last_punch = None
    has_missing_in = False
    has_missing_out = False

    if len(day_punches) == 1:
        single_p = day_punches[0]
        single_time = timezone.localtime(single_p.timestamp).time()
        # If punch is in afternoon/evening (>= 2:00 PM) or device status was Check-out (1):
        if single_time >= time(14, 0) or single_p.status == 1:
            first_punch = None
            last_punch = single_p
            has_missing_in = (not is_today)
            has_missing_out = False
        else:
            first_punch = single_p
            last_punch = None
            has_missing_in = False
            has_missing_out = (not is_today)
    elif len(day_punches) > 1:
        first_punch = day_punches[0]
        last_punch = day_punches[-1]

    punch_count = len(day_punches)

    # 2. Check Overlapping Records (Holiday, Leave, Movement, Regularization)
    holiday_name = None
    if preloaded_data and "holidays" in preloaded_data:
        holiday_name = preloaded_data["holidays"].get(target_date)
    else:
        holiday = PublicHoliday.objects.filter(date=target_date).first()
        if holiday and holiday.applies_to(employee):
            holiday_name = holiday.name

    leave_info = None
    if preloaded_data and "leaves" in preloaded_data:
        leave_info = preloaded_data["leaves"].get(target_date)
    else:
        leave = LeaveRequest.objects.filter(
            employee=employee,
            start_date__lte=target_date,
            end_date__gte=target_date,
            status="approved",
        ).select_related("leave_type").first()
        if leave:
            leave_info = leave.leave_type.name

    regularized = False
    if preloaded_data and "regularizations" in preloaded_data:
        regularized = target_date in preloaded_data["regularizations"]
    else:
        regularized = AttendanceRequest.objects.filter(
            employee=employee,
            date=target_date,
            status="approved",
        ).exists()

    holiday_work_approved = False
    if preloaded_data and "holiday_works" in preloaded_data:
        holiday_work_approved = target_date in preloaded_data["holiday_works"]
    else:
        holiday_work_approved = HolidayWorkRequest.objects.filter(
            employee=employee,
            date=target_date,
            status="approved",
        ).exists()

    movement_info = None
    if preloaded_data and "movements" in preloaded_data:
        movement_info = preloaded_data["movements"].get(target_date)
    else:
        movements_list = []
        for mov in StaffMovement.objects.filter(
            employee=employee, date=target_date, is_cancelled=False
        ).prefetch_related("stops").order_by("out_time"):
            stops = mov.get_stops_list()
            stop_clients = [s["client"].strip() for s in stops if s.get("client")]
            client_name = " → ".join(stop_clients) if stop_clients else mov.client
            movements_list.append({
                "client": client_name,
                "out_time": mov.out_time.strftime("%I:%M %p") if mov.out_time else None,
                "in_time": mov.in_time.strftime("%I:%M %p") if mov.in_time else None,
                "purpose": mov.get_purpose_type_display() if mov.purpose_type else (mov.purpose or ""),
                "is_assisting": False,
                "_raw_out": mov.out_time or time.min,
            })
        for asst in StaffMovementAssistant.objects.filter(
            employee=employee, movement__date=target_date, movement__is_cancelled=False
        ).select_related("movement").prefetch_related("movement__stops"):
            m = asst.movement
            stops = m.get_stops_list()
            stop_clients = [s["client"].strip() for s in stops if s.get("client")]
            client_name = " → ".join(stop_clients) if stop_clients else m.client
            movements_list.append({
                "client": client_name,
                "out_time": m.out_time.strftime("%I:%M %p") if m.out_time else None,
                "in_time": asst.in_time.strftime("%I:%M %p") if asst.in_time else (m.in_time.strftime("%I:%M %p") if m.in_time else None),
                "purpose": m.get_purpose_type_display() if m.purpose_type else (m.purpose or ""),
                "is_assisting": True,
                "_raw_out": m.out_time or time.min,
            })
        if movements_list:
            movements_list.sort(key=lambda x: x["_raw_out"])
            for item in movements_list:
                item.pop("_raw_out", None)
            movement_info = movements_list

    # Check if employee started/ended their shift with a movement
    has_morning_movement = False
    has_evening_movement = False
    start_times = []
    end_times = []

    if first_punch:
        start_times.append(timezone.localtime(first_punch.timestamp).time())
    if last_punch:
        end_times.append(timezone.localtime(last_punch.timestamp).time())

    if movement_info:
        for mov_item in movement_info:
            out_str = mov_item.get("out_time")
            if out_str:
                try:
                    out_t = datetime.strptime(out_str, "%I:%M %p").time()
                    start_times.append(out_t)
                    if out_t <= GRACE_CUTOFF:
                        has_morning_movement = True
                except (ValueError, TypeError):
                    pass
            in_str = mov_item.get("in_time")
            if in_str:
                try:
                    in_t = datetime.strptime(in_str, "%I:%M %p").time()
                    end_times.append(in_t)
                    if in_t >= time(17, 0):
                        has_evening_movement = True
                except (ValueError, TypeError):
                    pass

    # Suppress missing punch warnings if covered by movement
    if has_missing_in and has_morning_movement:
        has_missing_in = False
    if has_missing_out and has_evening_movement:
        has_missing_out = False

    duration_seconds = 0
    duration_formatted = "—"
    if first_punch and last_punch and last_punch != first_punch:
        duration_seconds = (last_punch.timestamp - first_punch.timestamp).total_seconds()
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        duration_formatted = f"{hours}h {minutes:02d}m"
    elif first_punch and is_today:
        now = timezone.now()
        duration_seconds = max(0, (now - first_punch.timestamp).total_seconds())
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        duration_formatted = f"{hours}h {minutes:02d}m"

    # Visual Overtime Calculation (Threshold: >= 8.0 hrs worked, i.e. >= 30m over standard 7.5h)
    overtime_seconds = 0
    overtime_formatted = None
    if duration_seconds >= 28800:
        overtime_seconds = int(duration_seconds - 27000)
        ot_hours = overtime_seconds // 3600
        ot_minutes = (overtime_seconds % 3600) // 60
        overtime_formatted = f"+{ot_hours}h {ot_minutes:02d}m"

    # 3. Determine Status
    status = "absent"
    status_label = "Absent"
    status_badge_class = "badge-danger"

    if is_future:
        status = "upcoming"
        status_label = "Upcoming"
        status_badge_class = "badge-muted"
        if holiday_work_approved:
            status = "holiday_work"
            status_label = "Holiday Work"
            status_badge_class = "badge-info"
        elif is_saturday:
            status = "weekend"
            status_label = "Weekend"
            status_badge_class = "badge-weekend"
        elif holiday_name:
            status = "holiday"
            status_label = f"Holiday: {holiday_name}"
            status_badge_class = "badge-holiday"
        elif leave_info:
            status = "on_leave"
            status_label = f"On Leave ({leave_info})"
            status_badge_class = "badge-leave"
    elif first_punch:
        local_in_time = timezone.localtime(first_punch.timestamp).time()
        if holiday_work_approved:
            status = "holiday_work"
            status_label = "Holiday Work"
            status_badge_class = "badge-info"
        elif regularized:
            status = "regularized"
            status_label = "Regularized"
            status_badge_class = "badge-info"
        elif local_in_time <= GRACE_CUTOFF or has_morning_movement:
            status = "present"
            status_label = "Present"
            status_badge_class = "badge-success"
        else:
            status = "late"
            status_label = "Late Arrival"
            status_badge_class = "badge-warning"
    elif last_punch:
        # Only an evening punch was recorded, no morning check-in punch
        if holiday_work_approved:
            status = "holiday_work"
            status_label = "Holiday Work"
            status_badge_class = "badge-info"
        elif regularized:
            status = "regularized"
            status_label = "Regularized"
            status_badge_class = "badge-info"
        else:
            status = "late"
            status_label = "Missing Check-in"
            status_badge_class = "badge-warning"
    elif leave_info:
        status = "on_leave"
        status_label = f"Leave: {leave_info}"
        status_badge_class = "badge-leave"
    elif regularized:
        status = "regularized"
        status_label = "Regularized"
        status_badge_class = "badge-info"
    elif holiday_work_approved:
        status = "holiday_work"
        status_label = "Holiday Work"
        status_badge_class = "badge-info"
    elif holiday_name:
        status = "holiday"
        status_label = f"Holiday: {holiday_name}"
        status_badge_class = "badge-holiday"
    elif is_saturday:
        status = "weekend"
        status_label = "Weekend"
        status_badge_class = "badge-weekend"
    elif is_today:
        status = "not_checked_in"
        status_label = "Not Checked In"
        status_badge_class = "badge-secondary"
    else:
        # Past working day without punch
        status = "absent"
        status_label = "Absent"
        status_badge_class = "badge-danger"

    return {
        "date": target_date,
        "first_punch": first_punch,
        "last_punch": last_punch,
        "punch_count": punch_count,
        "duration_seconds": duration_seconds,
        "duration_formatted": duration_formatted,
        "overtime_seconds": overtime_seconds,
        "overtime_formatted": overtime_formatted,
        "has_missing_in": has_missing_in,
        "has_missing_out": has_missing_out,
        "status": status,
        "status_label": status_label,
        "status_badge_class": status_badge_class,
        "leave_info": leave_info,
        "holiday_name": holiday_name,
        "holiday_work_approved": holiday_work_approved,
        "movement_info": movement_info,
        "punches": day_punches,
    }


def get_monthly_attendance_summary(employee, start_date, end_date):
    """
    Computes day-by-day attendance dictionary and aggregate metrics for an employee
    over an AD date range (typically matching a Bikram Sambat month).
    """
    tz = timezone.get_current_timezone()
    dt_start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    dt_end = timezone.make_aware(datetime.combine(end_date, time.max), tz)

    # Bulk fetch punches
    punches_qs = AttendanceLog.objects.filter(
        employee=employee,
        timestamp__range=(dt_start, dt_end)
    ).order_by("timestamp")

    punches_by_date = {}
    for p in punches_qs:
        p_date = timezone.localtime(p.timestamp).date()
        punches_by_date.setdefault(p_date, []).append(p)

    # Bulk fetch holidays applicable to this employee
    holidays = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(date__range=(start_date, end_date))
        if h.applies_to(employee)
    }

    # Bulk fetch approved leaves
    leaves_qs = LeaveRequest.objects.filter(
        employee=employee,
        start_date__lte=end_date,
        end_date__gte=start_date,
        status="approved"
    ).select_related("leave_type")

    leaves_by_date = {}
    for l in leaves_qs:
        curr = max(l.start_date, start_date)
        l_end = min(l.end_date, end_date)
        while curr <= l_end:
            leaves_by_date[curr] = l.leave_type.name
            curr += timedelta(days=1)

    # Bulk fetch regularizations
    regularizations = set(
        AttendanceRequest.objects.filter(
            employee=employee,
            date__range=(start_date, end_date),
            status="approved"
        ).values_list("date", flat=True)
    )

    # Bulk fetch approved holiday work requests
    holiday_works = set(
        HolidayWorkRequest.objects.filter(
            employee=employee,
            date__range=(start_date, end_date),
            status="approved"
        ).values_list("date", flat=True)
    )

    # Bulk fetch staff movements
    movements_by_date = {}
    for m in StaffMovement.objects.filter(
        employee=employee, date__range=(start_date, end_date), is_cancelled=False
    ).prefetch_related("stops").order_by("date", "out_time"):
        stops = m.get_stops_list()
        stop_clients = [s["client"].strip() for s in stops if s.get("client")]
        client_name = " → ".join(stop_clients) if stop_clients else m.client
        movements_by_date.setdefault(m.date, []).append({
            "client": client_name,
            "out_time": m.out_time.strftime("%I:%M %p") if m.out_time else None,
            "in_time": m.in_time.strftime("%I:%M %p") if m.in_time else None,
            "purpose": m.get_purpose_type_display() if m.purpose_type else (m.purpose or ""),
            "is_assisting": False,
            "_raw_out": m.out_time or time.min,
        })

    for asst in StaffMovementAssistant.objects.filter(
        employee=employee,
        movement__date__range=(start_date, end_date),
        movement__is_cancelled=False,
    ).select_related("movement").prefetch_related("movement__stops"):
        m = asst.movement
        stops = m.get_stops_list()
        stop_clients = [s["client"].strip() for s in stops if s.get("client")]
        client_name = " → ".join(stop_clients) if stop_clients else m.client
        movements_by_date.setdefault(m.date, []).append({
            "client": client_name,
            "out_time": m.out_time.strftime("%I:%M %p") if m.out_time else None,
            "in_time": asst.in_time.strftime("%I:%M %p") if asst.in_time else (m.in_time.strftime("%I:%M %p") if m.in_time else None),
            "purpose": m.get_purpose_type_display() if m.purpose_type else (m.purpose or ""),
            "is_assisting": True,
            "_raw_out": m.out_time or time.min,
        })

    for d, m_list in movements_by_date.items():
        m_list.sort(key=lambda x: x["_raw_out"])
        for item in m_list:
            item.pop("_raw_out", None)

    preloaded = {
        "punches_by_date": punches_by_date,
        "holidays": holidays,
        "leaves": leaves_by_date,
        "regularizations": regularizations,
        "holiday_works": holiday_works,
        "movements": movements_by_date,
    }

    days_summary = {}
    total_present = 0
    total_late = 0
    total_half_day = 0
    total_absent = 0
    total_leaves = 0
    total_work_seconds = 0
    total_overtime_seconds = 0
    today = date.today()

    curr = start_date
    while curr <= end_date:
        summary = get_daily_attendance_summary(employee, curr, preloaded_data=preloaded)
        days_summary[curr] = summary

        if curr <= today:
            total_overtime_seconds += summary.get("overtime_seconds", 0)
            st = summary["status"]
            if st in ("present", "short_hours", "regularized", "holiday_work"):
                total_present += 1
                total_work_seconds += summary["duration_seconds"]
            elif st == "late":
                total_late += 1
                total_present += 1
                total_work_seconds += summary["duration_seconds"]
            elif st == "half_day":
                total_half_day += 1
                total_work_seconds += summary["duration_seconds"]
            elif st == "on_leave":
                total_leaves += 1
            elif st == "absent":
                total_absent += 1

        curr += timedelta(days=1)

    total_work_hours = round(total_work_seconds / 3600, 1)
    total_overtime_hours = round(total_overtime_seconds / 3600, 1)
    avg_daily_hours = 0.0
    if total_present > 0:
        avg_daily_hours = round(total_work_hours / total_present, 1)

    return {
        "days": days_summary,
        "total_present": total_present,
        "total_late": total_late,
        "total_half_day": total_half_day,
        "total_absent": total_absent,
        "total_leaves": total_leaves,
        "total_work_hours": total_work_hours,
        "total_overtime_hours": total_overtime_hours,
        "avg_daily_hours": avg_daily_hours,
    }


def get_today_team_attendance_summary():
    """
    Computes live attendance headcount for managers for today across all active employees.
    """
    today = date.today()
    tz = timezone.get_current_timezone()
    dt_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    dt_end = timezone.make_aware(datetime.combine(today, time.max), tz)

    active_employees = list(
        User.objects.filter(is_active=True).exclude(role="ceo").order_by("first_name", "username")
    )

    # Fetch today's punches grouped by employee
    today_punches = AttendanceLog.objects.filter(
        timestamp__range=(dt_start, dt_end)
    ).select_related("employee").order_by("timestamp")

    employee_punches = {}
    for p in today_punches:
        if p.employee_id:
            employee_punches.setdefault(p.employee_id, []).append(p)

    # Fetch today's leaves
    today_leaves = {
        l.employee_id: l.leave_type.name
        for l in LeaveRequest.objects.filter(
            start_date__lte=today, end_date__gte=today, status="approved"
        ).select_related("leave_type")
    }

    # Fetch today's public holiday
    holiday = PublicHoliday.objects.filter(date=today).first()
    holiday_name = holiday.name if holiday else None
    is_saturday = today.weekday() == 5

    present_list = []
    late_list = []
    leave_list = []
    not_in_list = []

    for emp in active_employees:
        punches = employee_punches.get(emp.id, [])
        first_p = punches[0] if punches else None
        last_p = punches[-1] if len(punches) > 1 else None

        is_emp_holiday = holiday and holiday.applies_to(emp)

        if first_p:
            local_in = timezone.localtime(first_p.timestamp).time()
            in_time_str = local_in.strftime("%I:%M %p")
            out_time_str = timezone.localtime(last_p.timestamp).strftime("%I:%M %p") if last_p else "—"

            emp_data = {
                "id": emp.id,
                "name": emp.get_full_name() or emp.username,
                "department": emp.department or "—",
                "in_time": in_time_str,
                "out_time": out_time_str,
                "punch_count": len(punches),
            }

            if local_in <= GRACE_CUTOFF:
                emp_data["status"] = "Present"
                emp_data["badge"] = "badge-success"
                present_list.append(emp_data)
            else:
                emp_data["status"] = "Late"
                emp_data["badge"] = "badge-warning"
                late_list.append(emp_data)
        elif emp.id in today_leaves:
            leave_list.append({
                "id": emp.id,
                "name": emp.get_full_name() or emp.username,
                "department": emp.department or "—",
                "leave_name": today_leaves[emp.id],
            })
        elif is_emp_holiday:
            leave_list.append({
                "id": emp.id,
                "name": emp.get_full_name() or emp.username,
                "department": emp.department or "—",
                "leave_name": f"Holiday: {holiday.name}",
            })
        else:
            not_in_list.append({
                "id": emp.id,
                "name": emp.get_full_name() or emp.username,
                "department": emp.department or "—",
            })

    return {
        "date": today,
        "holiday_name": holiday_name,
        "is_saturday": is_saturday,
        "total_active": len(active_employees),
        "present_count": len(present_list) + len(late_list),
        "on_time_count": len(present_list),
        "late_count": len(late_list),
        "leave_count": len(leave_list),
        "not_in_count": len(not_in_list),
        "present_employees": present_list,
        "late_employees": late_list,
        "leave_employees": leave_list,
        "not_in_employees": not_in_list,
    }
