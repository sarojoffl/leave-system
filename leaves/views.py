from datetime import date, datetime
from calendar import Calendar, month_name

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import LeaveRequest, LeaveType, LeaveBalance, PublicHoliday
from .permissions import manager_required

from django.core.mail import send_mail
from django.contrib.auth import get_user_model

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


@login_required
def apply_leave(request):
    if request.method == "POST":
        leave_type_id = request.POST.get("leave_type")
        from_date_str = request.POST.get("from_date")
        to_date_str = request.POST.get("to_date")
        duration = request.POST.get("duration", "full")
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
                from_date = datetime.strptime(
                    from_date_str,
                    "%Y-%m-%d"
                ).date()

                to_date = datetime.strptime(
                    to_date_str,
                    "%Y-%m-%d"
                ).date()

                if to_date < from_date:
                    errors.append("To date cannot be before from date.")

            except ValueError:
                errors.append("Invalid date format.")

        if not reason:
            errors.append("Please provide a reason for leave.")

        # Check overlapping leaves
        if from_date and to_date and not errors:
            overlapping = LeaveRequest.objects.filter(
                employee=request.user,
                start_date__lte=to_date,
                end_date__gte=from_date
            ).exclude(status__in=['cancelled', 'rejected'])
            if overlapping.exists():
                errors.append("You have an overlapping leave request for these dates.")

        # Check balance validation
        if leave_type_id and from_date and to_date and not errors:
            try:
                leave_type = LeaveType.objects.get(id=leave_type_id)
                balance = LeaveBalance.objects.filter(
                    employee=request.user,
                    leave_type=leave_type
                ).first()
                
                temp_request = LeaveRequest(
                    employee=request.user,
                    leave_type=leave_type,
                    start_date=from_date,
                    end_date=to_date,
                    duration=duration
                )
                requested_days = temp_request.days
                
                if requested_days <= 0:
                    errors.append("The requested period does not contain any working days.")
                else:
                    remaining = balance.remaining if balance else leave_type.total_days
                    
                    pending_days = sum(
                        r.days for r in LeaveRequest.objects.filter(
                            employee=request.user,
                            leave_type=leave_type,
                            status='pending'
                        )
                    )
                    
                    available = remaining - pending_days
                    if requested_days > available:
                        errors.append(f"Insufficient balance. You requested {requested_days} day(s), but only have {available} day(s) available (accounting for pending requests).")
            except LeaveType.DoesNotExist:
                errors.append("Invalid leave type selected.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            leave = LeaveRequest.objects.create(
                employee=request.user,
                leave_type_id=leave_type_id,
                start_date=from_date,
                end_date=to_date,
                duration=duration,
                reason=reason,
                handover_to=handover,
            )

            # Trigger email notification
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

    context = {"leaves": leaves}

    if request.session.pop("show_success_modal", False):
        context["show_success_modal"] = True
        context["modal_summary"] = request.session.pop("modal_summary", None)

    return render(request, "leaves/my_leaves.html", context)


@login_required
@require_POST
def cancel_leave(request, id):
    leave = get_object_or_404(LeaveRequest, id=id, employee=request.user)
    if leave.status == "pending":
        leave.status = "cancelled"
        leave.save(update_fields=["status"])
        messages.success(request, "Leave request cancelled.")
        send_leave_notification_email(leave, 'cancelled')
    elif leave.status == "approved":
        leave.status = "cancelled"
        leave.save(update_fields=["status"])
        
        balance, _ = LeaveBalance.objects.get_or_create(
            employee=leave.employee,
            leave_type=leave.leave_type,
            defaults={"total": leave.leave_type.total_days},
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

    return render(request, "leaves/approvals.html", {
        "pending_approvals": pending_approvals,
        "recently_processed": recently_processed,
    })


@manager_required
@require_POST
def approve_leave(request, id):
    leave = get_object_or_404(LeaveRequest, id=id, status="pending")
    
    # Enforce balance validation before approval
    balance, _ = LeaveBalance.objects.get_or_create(
        employee=leave.employee,
        leave_type=leave.leave_type,
        defaults={"total": leave.leave_type.total_days},
    )
    
    if balance.remaining < leave.days:
        messages.error(request, f"Insufficient balance. Employee has only {balance.remaining} days remaining, but requested {leave.days} days.")
        return redirect("approvals")
        
    leave.status       = "approved"
    leave.decided_at   = timezone.now()
    leave.decision_note = request.POST.get("note", "").strip()
    leave.save(update_fields=["status", "decided_at", "decision_note"])

    balance.used += leave.days
    balance.save(update_fields=["used"])

    messages.success(request, f"Leave request for {leave.employee.get_full_name() or leave.employee.username} approved.")
    send_leave_notification_email(leave, 'approved')

    return redirect("approvals")


@manager_required
@require_POST
def reject_leave(request, id):
    leave = get_object_or_404(LeaveRequest, id=id)
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
        
        # Refund balance
        balance, _ = LeaveBalance.objects.get_or_create(
            employee=leave.employee,
            leave_type=leave.leave_type,
            defaults={"total": leave.leave_type.total_days},
        )
        balance.used = max(balance.used - leave.days, 0)
        balance.save(update_fields=["used"])
        
        messages.success(request, f"Approved leave request for {leave.employee.get_full_name() or leave.employee.username} has been revoked.")
        send_leave_notification_email(leave, 'revoked')
    else:
        messages.error(request, "Cannot reject/revoke this request.")
        
    return redirect("approvals")


@login_required
def calendar(request):
    today = date.today()
    cal = Calendar(firstweekday=6)  # Sunday-first

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
            if day_date == today:
                classes.append("today")

            holiday = PublicHoliday.objects.filter(date=day_date).first()
            if holiday:
                classes.append("holiday")
                title = holiday.name

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
        balances = list(LeaveBalance.objects.filter(employee=emp).select_related("leave_type"))
        annual = next((b for b in balances if b.leave_type.name.lower().startswith("annual")), None)
        sick = next((b for b in balances if b.leave_type.name.lower().startswith("sick")), None)
        casual = next((b for b in balances if b.leave_type.name.lower().startswith("casual")), None)

        on_leave_today = LeaveRequest.objects.filter(
            employee=emp, status="approved",
            start_date__lte=today, end_date__gte=today,
        ).exists()

        summary.append({
            "name": emp.get_full_name() or emp.username,
            "department": emp.department or "—",
            "annual_used": annual.used if annual else 0,
            "sick_used": sick.used if sick else 0,
            "casual_used": casual.used if casual else 0,
            "total_taken": sum(b.used for b in balances),
            "status": "On Leave" if on_leave_today else "Active",
        })

    return render(request, "leaves/team.html", {"team_summary": summary})


@manager_required
def reports(request):
    from accounts.models import User

    today = date.today()

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
        total_days = sum(b.used for b in LeaveBalance.objects.filter(employee__in=emps))
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

    return render(request, "leaves/reports.html", {
        "department_usage": department_usage,
        "leave_type_breakdown": leave_type_breakdown,
        "monthly_trend": monthly_trend,
    })