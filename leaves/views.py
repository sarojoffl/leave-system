from datetime import date, datetime
from calendar import Calendar, month_name

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import LeaveRequest, LeaveType, LeaveBalance, PublicHoliday, AttendanceRequest, HolidayWorkRequest
from .permissions import manager_required

from django.core.mail import send_mail
from django.contrib.auth import get_user_model

import csv
from django.http import HttpResponse


def send_leave_notification_email(leave_request, action_type):
    User = get_user_model()
    subject = ""
    message = ""
    recipient_list = []

    employee_name = leave_request.employee.get_full_name() or leave_request.employee.username

    if action_type == 'requested':
        subject = f"New Leave Request from {employee_name}"
        message = (
            f"Dear Manager/HR,\n\n"
            f"{employee_name} has submitted a new leave request:\n"
            f"- Leave Type: {leave_request.leave_type.name}\n"
            f"- Dates: {leave_request.start_date} to {leave_request.end_date} ({leave_request.days} day(s))\n"
            f"- Reason: {leave_request.reason}\n\n"
            f"Please log in to the portal to review and decide on this request."
        )
        recipient_list = list(User.objects.filter(role__in=['manager', 'hr']).exclude(id=leave_request.employee.id).values_list('email', flat=True))

    elif action_type in ('approved', 'rejected'):
        status_label = "approved" if action_type == 'approved' else "rejected"
        subject = f"Leave Request {status_label.capitalize()}"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your request for {leave_request.leave_type.name} leave from {leave_request.start_date} to {leave_request.end_date} has been {status_label}.\n"
            f"Manager Note: {leave_request.decision_note or 'No additional note'}\n\n"
            f"Thank you."
        )
        recipient_list = [leave_request.employee.email] if leave_request.employee.email else []

    elif action_type == 'cancelled':
        subject = f"Leave Request Cancelled by {employee_name}"
        message = (
            f"Dear Manager/HR,\n\n"
            f"{employee_name} has cancelled their leave request:\n"
            f"- Leave Type: {leave_request.leave_type.name}\n"
            f"- Dates: {leave_request.start_date} to {leave_request.end_date} ({leave_request.days} day(s))\n\n"
            f"The leave status has been updated to Cancelled and any used balance has been refunded."
        )
        recipient_list = list(User.objects.filter(role__in=['manager', 'hr']).exclude(id=leave_request.employee.id).values_list('email', flat=True))

    elif action_type == 'revoked':
        subject = f"Approved Leave Request Revoked"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your approved request for {leave_request.leave_type.name} leave from {leave_request.start_date} to {leave_request.end_date} has been revoked/rejected by a manager.\n"
            f"Manager Note: {leave_request.decision_note or 'No additional note'}\n\n"
            f"Your leave balance has been refunded."
        )
        recipient_list = [leave_request.employee.email] if leave_request.employee.email else []

    recipient_list = [email for email in recipient_list if email]

    if recipient_list:
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=None,
                recipient_list=recipient_list,
                fail_silently=True
            )
        except Exception:
            pass


def send_day_request_notification_email(day_request, action_type, label):
    """
    Notification email for AttendanceRequest / HolidayWorkRequest objects.
    These models don't have leave_type/days like LeaveRequest, so they get
    their own lightweight templates rather than overloading the leave one.
    """
    User = get_user_model()
    subject = ""
    message = ""
    recipient_list = []

    employee_name = day_request.employee.get_full_name() or day_request.employee.username

    if action_type == 'requested':
        subject = f"New {label} Request from {employee_name}"
        message = (
            f"Dear Manager/HR,\n\n"
            f"{employee_name} has submitted a new {label.lower()} request:\n"
            f"- Date: {day_request.date}\n"
            f"- Reason: {day_request.reason}\n\n"
            f"Please log in to the portal to review and decide on this request."
        )
        recipient_list = list(User.objects.filter(role__in=['manager', 'hr']).exclude(id=day_request.employee.id).values_list('email', flat=True))

    elif action_type in ('approved', 'rejected'):
        status_label = "approved" if action_type == 'approved' else "rejected"
        subject = f"{label} Request {status_label.capitalize()}"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your {label.lower()} request for {day_request.date} has been {status_label}.\n"
            f"Manager Note: {day_request.decision_note or 'No additional note'}\n\n"
            f"Thank you."
        )
        recipient_list = [day_request.employee.email] if day_request.employee.email else []

    recipient_list = [email for email in recipient_list if email]

    if recipient_list:
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=None,
                recipient_list=recipient_list,
                fail_silently=True
            )
        except Exception:
            pass


@login_required
def apply_leave(request):
    if request.method == "POST":
        leave_type_id = request.POST.get("leave_type")
        from_date_str = request.POST.get("from_date")
        to_date_str = request.POST.get("to_date")
        reason = request.POST.get("reason", "").strip()
        handover = request.POST.get("handover", "").strip()

        errors = []

        if not leave_type_id:
            errors.append("Please select a leave type.")

        if not from_date_str or not to_date_str:
            errors.append("Please select the leave dates.")

        from_date = None
        to_date = None

        if from_date_str and to_date_str:
            try:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

                if to_date < from_date:
                    errors.append("To date cannot be before from date.")

            except ValueError:
                errors.append("Invalid date format.")

        if not reason:
            errors.append("Please provide a reason for leave.")

        if from_date and to_date and not errors:
            overlapping = LeaveRequest.objects.filter(
                employee=request.user,
                start_date__lte=to_date,
                end_date__gte=from_date
            ).exclude(status__in=['cancelled', 'rejected'])
            if overlapping.exists():
                errors.append("You have an overlapping leave request for these dates.")

        leave_type = None
        requested_days = None

        if leave_type_id and from_date and to_date and not errors:
            try:
                leave_type = LeaveType.objects.get(id=leave_type_id)

                temp_request = LeaveRequest(
                    employee=request.user,
                    leave_type=leave_type,
                    start_date=from_date,
                    end_date=to_date,
                )
                requested_days = temp_request.days

                if requested_days <= 0:
                    errors.append("The requested period does not contain any working days.")
            except LeaveType.DoesNotExist:
                errors.append("Invalid leave type selected.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            # CRITICAL FIX: lock the balance row and re-check availability
            # inside the same transaction as the create, so two concurrent
            # submissions can't both pass the balance check and overdraw it.
            with transaction.atomic():
                balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
                    employee=request.user,
                    defaults={"total": 12},
                )

                pending_days = sum(
                    r.days for r in LeaveRequest.objects.filter(
                        employee=request.user,
                        status='pending'
                    ).select_for_update()
                )

                available = balance.remaining - pending_days
                if requested_days > available:
                    messages.error(
                        request,
                        f"Insufficient balance. You requested {requested_days} day(s), but only have {available} day(s) available."
                    )
                    return render(
                        request,
                        "leaves/apply_leave.html",
                        {"leave_types": LeaveType.objects.all()},
                    )

                leave = LeaveRequest.objects.create(
                    employee=request.user,
                    leave_type=leave_type,
                    start_date=from_date,
                    end_date=to_date,
                    reason=reason,
                )

            send_leave_notification_email(leave, 'requested')

            request.session["show_success_modal"] = True
            request.session["modal_summary"] = {
                "type": leave.leave_type.name,
                "from_date": from_date.strftime("%b %d, %Y"),
                "to_date": to_date.strftime("%b %d, %Y"),
                "days": leave.days,
            }

            return redirect("my_leaves")

    return render(
        request,
        "leaves/apply_leave.html",
        {
            "leave_types": LeaveType.objects.all(),
        },
    )


@login_required
def my_leaves(request):
    leaves = LeaveRequest.objects.filter(employee=request.user).select_related("leave_type")

    status = request.GET.get("status")
    if status == "pending":
        leaves = leaves.filter(status="pending")
    elif status == "approved":
        leaves = leaves.filter(status="approved")
    elif status == "rejected":
        leaves = leaves.filter(status__in=["rejected", "cancelled"])

    attendance_requests = AttendanceRequest.objects.filter(employee=request.user)
    holiday_work_requests = HolidayWorkRequest.objects.filter(employee=request.user)

    context = {
        "leaves": leaves,
        "attendance_requests": attendance_requests,
        "holiday_work_requests": holiday_work_requests,
    }

    if request.session.pop("show_success_modal", False):
        context["show_success_modal"] = True
        context["modal_summary"] = request.session.pop("modal_summary", None)

    return render(request, "leaves/my_leaves.html", context)


@login_required
@require_POST
def cancel_leave(request, id):
    with transaction.atomic():
        leave = get_object_or_404(
            LeaveRequest.objects.select_for_update(), id=id, employee=request.user
        )

        if leave.status == "pending":
            leave.status = "cancelled"
            leave.save(update_fields=["status"])
            messages.success(request, "Leave request cancelled.")
            send_leave_notification_email(leave, 'cancelled')
        elif leave.status == "approved":
            leave.status = "cancelled"
            leave.save(update_fields=["status"])

            balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
                employee=leave.employee,
                defaults={"total": 12},
            )
            balance.used = max(balance.used - leave.days, 0)
            balance.save(update_fields=["used"])

            messages.success(request, "Approved leave request cancelled. Balance refunded.")
            send_leave_notification_email(leave, 'cancelled')
        else:
            messages.error(request, "Cannot cancel this request.")

    return redirect("my_leaves")


@manager_required
def approvals(request):
    pending = (
        LeaveRequest.objects.filter(status="pending")
        .exclude(employee=request.user)
        .select_related("employee", "leave_type")
    )
    recent = (
        LeaveRequest.objects.filter(status__in=["approved", "rejected"])
        .exclude(employee=request.user)
        .select_related("employee", "leave_type")
        .order_by("-decided_at")[:10]
    )

    pending_approvals = [{
        "id": l.id,
        "employee_name": l.employee.get_full_name() or l.employee.username,
        "employee_initials": l.employee.initials,
        "type": l.leave_type.name,
        "from_date": l.start_date.strftime("%b %d"),
        "to_date": l.end_date.strftime("%b %d"),
        "days": l.days,
        "reason": l.reason,
        "applied_on": l.created_at.strftime("%b %d"),
    } for l in pending]

    recently_processed = [{
        "id": l.id,
        "employee_name": l.employee.get_full_name() or l.employee.username,
        "type": l.leave_type.name,
        "dates": l.date_range,
        "decision": l.get_status_display(),
        "note": l.decision_note,
    } for l in recent]

    def _serialize_day_requests(qs):
        return [{
            "id": r.id,
            "employee_name": r.employee.get_full_name() or r.employee.username,
            "employee_initials": r.employee.initials,
            "date": r.date.strftime("%b %d"),
            "reason": r.reason,
            "applied_on": r.created_at.strftime("%b %d"),
        } for r in qs]

    def _serialize_processed_day_requests(qs):
        return [{
            "id": r.id,
            "employee_name": r.employee.get_full_name() or r.employee.username,
            "date": r.date.strftime("%b %d"),
            "decision": r.get_status_display(),
            "note": r.decision_note,
        } for r in qs]

    pending_attendance = _serialize_day_requests(
        AttendanceRequest.objects.filter(status="pending").exclude(employee=request.user).select_related("employee")
    )
    pending_holiday_work = _serialize_day_requests(
        HolidayWorkRequest.objects.filter(status="pending").exclude(employee=request.user).select_related("employee")
    )

    recently_processed_attendance = _serialize_processed_day_requests(
        AttendanceRequest.objects.filter(status__in=["approved", "rejected"])
        .exclude(employee=request.user)
        .select_related("employee")
        .order_by("-decided_at")[:10]
    )
    recently_processed_holiday_work = _serialize_processed_day_requests(
        HolidayWorkRequest.objects.filter(status__in=["approved", "rejected"])
        .exclude(employee=request.user)
        .select_related("employee")
        .order_by("-decided_at")[:10]
    )

    return render(request, "leaves/approvals.html", {
        "pending_approvals": pending_approvals,
        "recently_processed": recently_processed,
        "pending_attendance": pending_attendance,
        "pending_holiday_work": pending_holiday_work,
        "recently_processed_attendance": recently_processed_attendance,
        "recently_processed_holiday_work": recently_processed_holiday_work,
    })


@manager_required
@require_POST
def approve_leave(request, id):
    tab = request.POST.get("tab", "leave")

    # CRITICAL FIX: lock both the leave request and the balance row for the
    # duration of the check + update, so two concurrent approvals (or an
    # approval racing a user cancellation) can't both succeed.
    with transaction.atomic():
        leave = get_object_or_404(
            LeaveRequest.objects.select_for_update(), id=id, status="pending"
        )

        balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
            employee=leave.employee,
            defaults={"total": 12},
        )

        if balance.remaining < leave.days:
            messages.error(request, f"Insufficient balance. Employee has only {balance.remaining} days remaining, but requested {leave.days} days.")
            return redirect(f"{reverse('approvals')}?tab={tab}")

        leave.status = "approved"
        leave.decided_at = timezone.now()
        leave.decision_note = request.POST.get("note", "").strip()
        leave.save(update_fields=["status", "decided_at", "decision_note"])

        balance.used = F("used") + leave.days
        balance.save(update_fields=["used"])

    messages.success(request, f"Leave request for {leave.employee.get_full_name() or leave.employee.username} approved.")
    send_leave_notification_email(leave, 'approved')

    return redirect(f"{reverse('approvals')}?tab={tab}")


@manager_required
@require_POST
def reject_leave(request, id):
    tab = request.POST.get("tab", "leave")

    with transaction.atomic():
        leave = get_object_or_404(LeaveRequest.objects.select_for_update(), id=id)

        if leave.status == "pending":
            leave.status = "rejected"
            leave.decided_at = timezone.now()
            leave.decision_note = request.POST.get("note", "").strip()
            leave.save(update_fields=["status", "decided_at", "decision_note"])

            messages.success(request, f"Leave request for {leave.employee.get_full_name() or leave.employee.username} rejected.")
            send_leave_notification_email(leave, 'rejected')

        elif leave.status == "approved":
            leave.status = "rejected"
            leave.decided_at = timezone.now()
            leave.decision_note = request.POST.get("note", "").strip()
            leave.save(update_fields=["status", "decided_at", "decision_note"])

            balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
                employee=leave.employee,
                defaults={"total": 12},
            )
            balance.used = max(balance.used - leave.days, 0)
            balance.save(update_fields=["used"])

            messages.success(request, f"Approved leave request for {leave.employee.get_full_name() or leave.employee.username} has been revoked.")
            send_leave_notification_email(leave, 'revoked')
        else:
            messages.error(request, "Cannot reject/revoke this request.")

    return redirect(f"{reverse('approvals')}?tab={tab}")


@login_required
def calendar(request):
    today = date.today()
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
                    employee=request.user,
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

    team_leaves = (
        LeaveRequest.objects.filter(
            status="approved",
            start_date__year=today.year,
            start_date__month=today.month,
        )
        .exclude(employee=request.user)
        .select_related("employee", "leave_type")
    )

    team_on_leave = [{
        "name": l.employee.get_full_name() or l.employee.username,
        "dates": l.date_range,
        "type": l.leave_type.name,
    } for l in team_leaves]

    return render(request, "leaves/calendar.html", {
        "calendar_month_label": f"{month_name[today.month]} {today.year}",
        "calendar_weeks": weeks,
        "public_holidays": public_holidays,
        "team_on_leave_this_month": team_on_leave,
    })


@manager_required
def team(request):
    from accounts.models import User

    employees = User.objects.exclude(id=request.user.id)
    today = date.today()

    summary = []
    for emp in employees:
        balance = LeaveBalance.objects.filter(employee=emp).first()

        on_leave_today = LeaveRequest.objects.filter(
            employee=emp, status="approved",
            start_date__lte=today, end_date__gte=today,
        ).exists()

        summary.append({
            "name": emp.get_full_name() or emp.username,
            "department": emp.department or "—",
            "position": emp.position or "—",
            "leave_used": balance.used if balance else 0,
            "leave_total": balance.total if balance else 12,
            "leave_remaining": balance.remaining if balance else 12,
            "status": "On Leave" if on_leave_today else "Active",
        })

    return render(request, "leaves/team.html", {"team_summary": summary})


def _get_reports_data(today=None):
    from accounts.models import User
    today = today or date.today()

    departments = (
        User.objects.exclude(department__isnull=True)
        .exclude(department="")
        .values_list("department", flat=True)
        .distinct()
    )

    department_usage = []
    for dept in departments:
        emps = User.objects.filter(department=dept)
        emp_count = emps.count()
        total_days = sum(
            b.used for b in LeaveBalance.objects.filter(employee__in=emps)
        )
        department_usage.append({
            "name": dept,
            "employees": emp_count,
            "total_days": total_days,
            "avg_per_person": round(total_days / emp_count, 1) if emp_count else 0,
        })

    leave_type_breakdown = []
    for lt in LeaveType.objects.all():
        qs = LeaveRequest.objects.filter(leave_type=lt)
        days_taken = sum(l.days for l in qs.filter(status="approved"))
        leave_type_breakdown.append({
            "name": lt.name,
            "requests": qs.count(),
            "days_taken": days_taken,
            "pending": qs.filter(status="pending").count(),
        })

    monthly_days = []
    for m in range(1, 13):
        days = sum(
            l.days for l in LeaveRequest.objects.filter(
                status="approved", start_date__year=today.year, start_date__month=m,
            )
        )
        monthly_days.append(days)

    max_days = max(monthly_days) or 1
    monthly_trend = [{
        "label": month_name[m][:3],
        "days": monthly_days[m - 1],
        "bar_height": round((monthly_days[m - 1] / max_days) * 100),
        "is_current": m == today.month,
        "is_future": m > today.month,
    } for m in range(1, 13)]

    return department_usage, leave_type_breakdown, monthly_trend


@manager_required
def reports(request):
    department_usage, leave_type_breakdown, monthly_trend = _get_reports_data()

    return render(request, "leaves/reports.html", {
        "department_usage": department_usage,
        "leave_type_breakdown": leave_type_breakdown,
        "monthly_trend": monthly_trend,
    })


@manager_required
def export_reports_csv(request):
    today = date.today()
    department_usage, leave_type_breakdown, monthly_trend = _get_reports_data(today)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="leave_reports_{today.isoformat()}.csv"'

    writer = csv.writer(response)

    writer.writerow([f"Leave Reports & Analytics — {today.year}"])
    writer.writerow([])

    writer.writerow(["Department-wise Leave Usage"])
    writer.writerow(["Department", "Employees", "Total Days", "Avg per Person"])
    for d in department_usage:
        writer.writerow([d["name"], d["employees"], d["total_days"], d["avg_per_person"]])
    writer.writerow([])

    writer.writerow(["Leave Type Breakdown"])
    writer.writerow(["Leave Type", "Requests", "Days Taken", "Pending"])
    for lt in leave_type_breakdown:
        writer.writerow([lt["name"], lt["requests"], lt["days_taken"], lt["pending"]])
    writer.writerow([])

    writer.writerow([f"Monthly Leave Trend — {today.year}"])
    writer.writerow(["Month", "Days Taken"])
    for m in monthly_trend:
        writer.writerow([m["label"], m["days"]])

    return response

def _apply_day_request(request, model, success_msg, tab_key, label):
    if request.method == "POST":
        date_str = request.POST.get("date")
        reason = request.POST.get("reason", "").strip()
        errors = []

        req_date = None
        if not date_str:
            errors.append("Please select a date.")
        else:
            try:
                req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                errors.append("Invalid date format.")

        if not reason:
            errors.append("Please provide a reason.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            obj = model.objects.create(employee=request.user, date=req_date, reason=reason)
            messages.success(request, success_msg)
            send_day_request_notification_email(obj, 'requested', label)

    return redirect(f"{reverse('apply_leave')}?tab={tab_key}")


@login_required
def apply_attendance_request(request):
    return _apply_day_request(request, AttendanceRequest, "Attendance request submitted.", "attendance", "Attendance")


@login_required
def apply_holiday_work(request):
    return _apply_day_request(request, HolidayWorkRequest, "Holiday work request submitted.", "holiday", "Holiday Work")


_DAY_REQUEST_MODELS = {
    'attendance': AttendanceRequest,
    'holiday_work': HolidayWorkRequest,
}

_DAY_REQUEST_LABELS = {
    'attendance': "Attendance",
    'holiday_work': "Holiday Work",
}

# CRITICAL FIX: whitelist of valid decisions. Previously `decision` was
# taken straight from the URL and written to obj.status with no validation,
# allowing arbitrary strings to be stored as the status.
_VALID_DAY_REQUEST_DECISIONS = {'approved', 'rejected'}


_DAY_REQUEST_TAB_KEYS = {
    'attendance': "attendance",
    'holiday_work': "holiday",
}


@manager_required
@require_POST
def decide_day_request(request, request_type, id, decision):
    default_tab = _DAY_REQUEST_TAB_KEYS.get(request_type, "leave")
    tab = request.POST.get("tab", default_tab)

    model = _DAY_REQUEST_MODELS.get(request_type)
    if model is None:
        messages.error(request, "Invalid request type.")
        return redirect(f"{reverse('approvals')}?tab={tab}")

    if decision not in _VALID_DAY_REQUEST_DECISIONS:
        messages.error(request, "Invalid decision.")
        return redirect(f"{reverse('approvals')}?tab={tab}")

    obj = get_object_or_404(model, id=id, status="pending")
    obj.status = decision
    obj.decided_at = timezone.now()
    obj.decision_note = request.POST.get("note", "").strip()
    obj.save(update_fields=["status", "decided_at", "decision_note"])

    label = _DAY_REQUEST_LABELS.get(request_type, request_type.replace('_', ' ').title())
    messages.success(request, f"{label} request {decision}.")
    send_day_request_notification_email(obj, decision, label)

    return redirect(f"{reverse('approvals')}?tab={tab}")