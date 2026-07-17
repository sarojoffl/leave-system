import logging
from calendar import month_name
from datetime import date, datetime
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable

from .models import AttendanceRequest, HolidayWorkRequest, LeaveBalance, LeaveRequest, LeaveType, StaffMovement, StaffMovementAssistant
from .permissions import manager_required

logger = logging.getLogger(__name__)
from leaves.bs_convert import ad_to_bs_display


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_fiscal_year_start(today=None):
    """Return the start date of the current Nepali fiscal year (Shrawan 1 = July 17).

    The new fiscal year begins on July 17. Dates from July 1-16 still belong
    to the *previous* fiscal year, so we check both month and day.
    """
    today = today or date.today()
    # New FY starts on July 17; before that date we are still in the previous FY
    in_new_fy = today.month > 7 or (today.month == 7 and today.day >= 17)
    year = today.year if in_new_fy else today.year - 1
    return date(year, 7, 17)


def _ceo_recipients(exclude_user_id=None):
    """Email addresses for CEO-role users, optionally excluding one user."""
    User = get_user_model()
    qs = User.objects.filter(role='ceo')
    if exclude_user_id is not None:
        qs = qs.exclude(id=exclude_user_id)
    return list(qs.values_list('email', flat=True))


# ---------------------------------------------------------------------------
# PDF export helper (landscape, multi-record tables — reports, history)
# ---------------------------------------------------------------------------

def _build_pdf_response(filename, title, subtitle, sections):
    """Build a landscape PDF made of one or more titled tables and return it
    as a downloadable HttpResponse.

    sections: list of (section_title, headers, rows) tuples. `rows` is a
    list of row-lists; values are coerced to strings automatically.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ExportSubtitle", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey, spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "ExportSection", parent=styles["Heading2"], fontSize=12,
        spaceBefore=14, spaceAfter=6,
    )

    elements = [Paragraph(title, title_style)]
    if subtitle:
        elements.append(Paragraph(subtitle, subtitle_style))

    for section_title, headers, rows in sections:
        if section_title:
            elements.append(Paragraph(section_title, section_style))

        if not rows:
            elements.append(Paragraph("No records.", styles["Normal"]))
            continue

        table_data = [headers] + [
            ["" if cell is None else str(cell) for cell in row] for row in rows
        ]
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Single-request PDF (paper-form style, digitized) — shared helpers
#
# Used by both _build_single_leave_pdf and _build_single_day_request_pdf so
# the two builders don't duplicate style/layout code. Signature lines are
# always left blank — these are meant to be printed and signed by hand.
# ---------------------------------------------------------------------------

def _paper_form_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "FormTitle", parent=styles["Heading1"], fontSize=18,
            alignment=TA_CENTER, spaceAfter=18,
        ),
        "section": ParagraphStyle(
            "FormSection", parent=styles["Normal"], fontSize=11,
            textColor=colors.HexColor("#111827"), fontName="Helvetica-Bold",
            spaceBefore=14, spaceAfter=6,
        ),
        "label": ParagraphStyle(
            "FormLabel", parent=styles["Normal"], fontSize=10,
            textColor=colors.HexColor("#111827"), leading=14,
        ),
        "disclaimer": ParagraphStyle(
            "FormDisclaimer", parent=styles["Normal"], fontSize=9,
            textColor=colors.HexColor("#374151"), spaceBefore=16, spaceAfter=6,
        ),
    }


def _form_section_box(lines, label_style, width=6.5 * inch):
    """A single bordered box containing plain 'Label: value' lines — one
    outer box per section, matching the paper form. No inner grid lines,
    so there are no empty boxes around individual fields."""
    data = [[Paragraph(line, label_style)] for line in lines]
    t = Table(data, colWidths=[width])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#9ca3af")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _signature_line(label, width=6.5 * inch, with_date=False):
    """A single full-width 'Label ____________  [Date: ____]' line — left
    blank for physical signing after printing. Each signature gets its
    own line rather than several crammed into one row."""
    label_style = ParagraphStyle(
        "SigLineLabel", fontName="Helvetica", fontSize=10,
        textColor=colors.HexColor("#111827"),
    )
    if with_date:
        data = [[
            Paragraph(label, label_style), "",
            Paragraph("Date:", label_style), "",
        ]]
        t = Table(data, colWidths=[1.6 * inch, 2.4 * inch, 0.6 * inch, width - 4.6 * inch])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (1, 0), (1, 0), 0.75, colors.HexColor("#9ca3af")),
            ("LINEBELOW", (3, 0), (3, 0), 0.75, colors.HexColor("#9ca3af")),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 0), (-1, 0), 20),
        ]
    else:
        data = [[Paragraph(label, label_style), ""]]
        t = Table(data, colWidths=[1.8 * inch, width - 1.8 * inch])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (1, 0), (1, 0), 0.75, colors.HexColor("#9ca3af")),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 0), (-1, 0), 20),
        ]
    t.setStyle(TableStyle(style))
    return t


def _signature_line(label, width=6.5 * inch, with_date=False):
    """A single full-width 'Label ____________  [Date: ____]' line — left
    blank for physical signing after printing. Each signature gets its
    own line rather than several crammed side-by-side into one row."""
    label_style = ParagraphStyle(
        "SigLineLabel", fontName="Helvetica", fontSize=10,
        textColor=colors.HexColor("#111827"),
    )
    if with_date:
        data = [[
            Paragraph(label, label_style), "",
            Paragraph("Date:", label_style), "",
        ]]
        t = Table(data, colWidths=[1.6 * inch, 2.4 * inch, 0.6 * inch, width - 4.6 * inch])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (1, 0), (1, 0), 0.75, colors.HexColor("#9ca3af")),
            ("LINEBELOW", (3, 0), (3, 0), 0.75, colors.HexColor("#9ca3af")),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 0), (-1, 0), 20),
        ]
    else:
        data = [[Paragraph(label, label_style), ""]]
        t = Table(data, colWidths=[1.8 * inch, width - 1.8 * inch])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (1, 0), (1, 0), 0.75, colors.HexColor("#9ca3af")),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 0), (-1, 0), 20),
        ]
    t.setStyle(TableStyle(style))
    return t


def _paper_form_disclaimer_and_signatures(elements, styles):
    """Disclaimer + signatures. Employee Signature appears once, at the
    bottom, and each signature gets its own full-width line."""
    elements.append(Paragraph(
        "I understand that this request is subject to approval by my employer.",
        styles["disclaimer"],
    ))
    elements.append(_signature_line("Employee Signature", with_date=True))
    elements.append(_signature_line("Approved By"))
    elements.append(_signature_line("Director Approval"))


# ---------------------------------------------------------------------------
# Single leave-request PDF (paper-form style, digitized)
# ---------------------------------------------------------------------------

def _build_single_leave_pdf(leave):
    """Single-page PDF for one approved leave request, matching the
    original paper Leave Request Form. Signature lines are left blank
    for physical signing after printing.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    s = _paper_form_styles()
    employee = leave.employee

    date_of_absent = (
        ad_to_bs_display(leave.start_date) if leave.start_date == leave.end_date
        else f"{ad_to_bs_display(leave.start_date)} to {ad_to_bs_display(leave.end_date)}"
    )

    elements = [Paragraph("Leave Request Form", s["title"])]

    elements.append(Paragraph("Employee information:", s["section"]))
    elements.append(_form_section_box([
        f"<b>Name:</b> {employee.get_full_name() or employee.username}",
        f"<b>Department:</b> {employee.department or '—'}"
        f"&nbsp;&nbsp;&nbsp;&nbsp;<b>Position:</b> {employee.position or '—'}",
        f"<b>Request Type:</b> Leave Request",
        f"<b>Date of Absent:</b> {date_of_absent}"
        f"&nbsp;&nbsp;&nbsp;&nbsp;<b>Days:</b> {leave.days}",
    ], s["label"]))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("Type of leave:", s["section"]))
    elements.append(_form_section_box([f"<b>Leave Type:</b> {leave.leave_type.name}"], s["label"]))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("Remarks:", s["section"]))
    elements.append(_form_section_box([leave.reason or "—"], s["label"]))
    elements.append(Spacer(1, 10))

    _paper_form_disclaimer_and_signatures(elements, s)

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Email notifications
# ---------------------------------------------------------------------------

def send_leave_notification_email(leave_request, action_type):
    subject = ""
    message = ""
    recipient_list = []

    employee_name = leave_request.employee.get_full_name() or leave_request.employee.username

    if action_type == 'requested':
        subject = f"New Leave Request from {employee_name}"
        message = (
            f"Dear CEO,\n\n"
            f"{employee_name} has submitted a new leave request:\n"
            f"- Leave Type: {leave_request.leave_type.name}\n"
            f"- Dates: {leave_request.start_date} to {leave_request.end_date} ({leave_request.days} day(s))\n"
            f"- Reason: {leave_request.reason}\n\n"
            f"Please log in to the portal to review and decide on this request."
        )
        recipient_list = _ceo_recipients(exclude_user_id=leave_request.employee.id)

    elif action_type in ('approved', 'rejected'):
        status_label = "approved" if action_type == 'approved' else "rejected"
        subject = f"Leave Request {status_label.capitalize()}"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your request for {leave_request.leave_type.name} leave "
            f"from {leave_request.start_date} to {leave_request.end_date} has been {status_label}.\n"
            f"CEO Note: {leave_request.decision_note or 'No additional note'}\n\n"
            f"Thank you."
        )
        recipient_list = [leave_request.employee.email] if leave_request.employee.email else []

    elif action_type == 'cancelled':
        subject = f"Leave Request Cancelled by {employee_name}"
        message = (
            f"Dear CEO,\n\n"
            f"{employee_name} has cancelled their leave request:\n"
            f"- Leave Type: {leave_request.leave_type.name}\n"
            f"- Dates: {leave_request.start_date} to {leave_request.end_date} ({leave_request.days} day(s))\n\n"
            f"The leave status has been updated to Cancelled and any used balance has been refunded."
        )
        recipient_list = _ceo_recipients(exclude_user_id=leave_request.employee.id)

    elif action_type == 'revoked':
        subject = "Approved Leave Request Revoked"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your approved request for {leave_request.leave_type.name} leave "
            f"from {leave_request.start_date} to {leave_request.end_date} "
            f"has been revoked/rejected by a CEO.\n"
            f"CEO Note: {leave_request.decision_note or 'No additional note'}\n\n"
            f"Your leave balance has been refunded."
        )
        recipient_list = [leave_request.employee.email] if leave_request.employee.email else []

    recipient_list = [e for e in recipient_list if e]
    if not recipient_list:
        return

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=recipient_list,
            fail_silently=False,
        )
    except Exception as exc:
        logger.error("Failed to send leave notification email (action=%s, leave_id=%s): %s",
                     action_type, leave_request.id, exc)


def send_day_request_notification_email(day_request, action_type, label):
    """Notification email for AttendanceRequest / HolidayWorkRequest."""
    subject = ""
    message = ""
    recipient_list = []

    employee_name = day_request.employee.get_full_name() or day_request.employee.username

    if action_type == 'requested':
        subject = f"New {label} Request from {employee_name}"
        message = (
            f"Dear CEO,\n\n"
            f"{employee_name} has submitted a new {label.lower()} request:\n"
            f"- Date: {day_request.date}\n"
            f"- Reason: {day_request.reason}\n\n"
            f"Please log in to the portal to review and decide on this request."
        )
        recipient_list = _ceo_recipients(exclude_user_id=day_request.employee.id)

    elif action_type in ('approved', 'rejected'):
        status_label = "approved" if action_type == 'approved' else "rejected"
        subject = f"{label} Request {status_label.capitalize()}"
        message = (
            f"Dear {employee_name},\n\n"
            f"Your {label.lower()} request for {day_request.date} has been {status_label}.\n"
            f"CEO Note: {day_request.decision_note or 'No additional note'}\n\n"
            f"Thank you."
        )
        recipient_list = [day_request.employee.email] if day_request.employee.email else []

    recipient_list = [e for e in recipient_list if e]
    if not recipient_list:
        return

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=recipient_list,
            fail_silently=False,
        )
    except Exception as exc:
        logger.error("Failed to send day-request notification email (action=%s, id=%s): %s",
                     action_type, day_request.id, exc)


# ---------------------------------------------------------------------------
# Employee leave views
# ---------------------------------------------------------------------------

@login_required
def ad_to_bs_api(request):
    from leaves.bs_convert import ad_to_bs_display
    d = request.GET.get("date")
    try:
        from datetime import datetime
        parsed = datetime.strptime(d, "%Y-%m-%d").date()
        return JsonResponse({"bs": ad_to_bs_display(parsed)})
    except Exception:
        return JsonResponse({"bs": ""})

@login_required
def apply_leave(request):
    today = date.today()

    if request.method == "POST":
        leave_type_id = request.POST.get("leave_type")
        from_date_str = request.POST.get("from_date")
        to_date_str = request.POST.get("to_date")
        reason = request.POST.get("reason", "").strip()

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

                if from_date < today:
                    errors.append("You cannot request leave for a date in the past.")
                elif to_date < from_date:
                    errors.append("To date cannot be before from date.")
            except ValueError:
                errors.append("Invalid date format.")

        if not reason:
            errors.append("Please provide a reason for leave.")

        if from_date and to_date and not errors:
            overlapping = LeaveRequest.objects.filter(
                employee=request.user,
                start_date__lte=to_date,
                end_date__gte=from_date,
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
            with transaction.atomic():
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
                "from_date": ad_to_bs_display(from_date),
                "to_date": ad_to_bs_display(to_date),
                "days": leave.days,
            }
            return redirect("my_leaves")

    return render(
        request,
        "leaves/apply_leave.html",
        {"leave_types": LeaveType.objects.all()},
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
        "today": date.today(),
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
            if leave.start_date <= date.today():
                messages.error(
                    request,
                    "This leave has already started or finished and can no longer be "
                    "cancelled. Please contact your CEO if changes are needed."
                )
                return redirect("my_leaves")

            leave.status = "cancelled"
            leave.save(update_fields=["status"])

            # FIX: use F() + clamp instead of read-modify-write
            LeaveBalance.objects.filter(employee=leave.employee).update(
                used=F('used') - leave.days
            )
            LeaveBalance.objects.filter(employee=leave.employee, used__lt=0).update(used=0)

            messages.success(request, "Approved leave request cancelled. Balance refunded.")
            send_leave_notification_email(leave, 'cancelled')

        else:
            messages.error(request, "Cannot cancel this request.")

    return redirect("my_leaves")


# ---------------------------------------------------------------------------
# Manager approval views
# ---------------------------------------------------------------------------

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
        "from_date": l.start_date,
        "to_date": l.end_date,
        "days": l.days,
        "reason": l.reason,
        "applied_on": l.created_at,
    } for l in pending]

    recently_processed = [{
        "id": l.id,
        "employee_name": l.employee.get_full_name() or l.employee.username,
        "type": l.leave_type.name,
        "dates": l.date_range,
        "decision": l.get_status_display(),
        "note": l.decision_note,
        "end_date": l.end_date,
    } for l in recent]

    def _serialize_day_requests(qs):
        return [{
            "id": r.id,
            "employee_name": r.employee.get_full_name() or r.employee.username,
            "employee_initials": r.employee.initials,
            "date": r.date,
            "reason": r.reason,
            "applied_on": r.created_at,
        } for r in qs]

    def _serialize_processed_day_requests(qs):
        return [{
            "id": r.id,
            "employee_name": r.employee.get_full_name() or r.employee.username,
            "date": r.date,
            "decision": r.get_status_display(),
            "note": r.decision_note,
        } for r in qs]

    pending_attendance = _serialize_day_requests(
        AttendanceRequest.objects.filter(status="pending")
        .exclude(employee=request.user)
        .select_related("employee")
    )
    pending_holiday_work = _serialize_day_requests(
        HolidayWorkRequest.objects.filter(status="pending")
        .exclude(employee=request.user)
        .select_related("employee")
    )

    total_pending_count = len(pending_approvals) + len(pending_attendance) + len(pending_holiday_work)

    breakdown_parts = []
    if pending_approvals:
        breakdown_parts.append(f"{len(pending_approvals)} leave")
    if pending_attendance:
        breakdown_parts.append(f"{len(pending_attendance)} attendance")
    if pending_holiday_work:
        breakdown_parts.append(f"{len(pending_holiday_work)} holiday work")
    pending_breakdown_text = ", ".join(breakdown_parts)

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
        "total_pending_count": total_pending_count,
        "pending_breakdown_text": pending_breakdown_text,
        "today": date.today(),
    })


@manager_required
@require_POST
def approve_leave(request, id):
    tab = request.POST.get("tab", "leave")

    with transaction.atomic():
        leave = get_object_or_404(
            LeaveRequest.objects.select_for_update(), id=id, status="pending"
        )
        balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
            employee=leave.employee,
            defaults={"total": 12},
        )

        leave.status = "approved"
        leave.decided_at = timezone.now()
        leave.decision_note = request.POST.get("note", "").strip()
        leave.save(update_fields=["status", "decided_at", "decision_note"])

        balance.used = F("used") + leave.days
        balance.save(update_fields=["used"])

    messages.success(
        request,
        f"Leave request for {leave.employee.get_full_name() or leave.employee.username} approved."
    )
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

            messages.success(
                request,
                f"Leave request for {leave.employee.get_full_name() or leave.employee.username} rejected."
            )
            send_leave_notification_email(leave, 'rejected')

        elif leave.status == "approved":
            if leave.end_date < date.today():
                messages.error(request, "This leave has already finished and can no longer be revoked.")
                return redirect(f"{reverse('approvals')}?tab={tab}")

            leave.status = "rejected"
            leave.decided_at = timezone.now()
            leave.decision_note = request.POST.get("note", "").strip()
            leave.save(update_fields=["status", "decided_at", "decision_note"])

            # FIX: use F() + clamp instead of read-modify-write
            LeaveBalance.objects.filter(employee=leave.employee).update(
                used=F('used') - leave.days
            )
            LeaveBalance.objects.filter(employee=leave.employee, used__lt=0).update(used=0)

            messages.success(
                request,
                f"Approved leave request for "
                f"{leave.employee.get_full_name() or leave.employee.username} has been revoked."
            )
            send_leave_notification_email(leave, 'revoked')

        else:
            messages.error(request, "Cannot reject/revoke this request.")

    return redirect(f"{reverse('approvals')}?tab={tab}")


# ---------------------------------------------------------------------------
# Team view
# ---------------------------------------------------------------------------

@manager_required
def team(request):
    from accounts.models import User

    today = date.today()
    employees = list(
        User.objects.filter(is_active=True)
        .exclude(role__in=['ceo'])
        .order_by('first_name', 'last_name')
    )
    emp_ids = [e.id for e in employees]

    # Prefetch all balances in one query
    balance_map = {
        b.employee_id: b
        for b in LeaveBalance.objects.filter(employee_id__in=emp_ids)
    }

    # Prefetch current leaves (on leave today) in one query
    current_leave_map = {}
    for l in (
        LeaveRequest.objects.filter(
            employee_id__in=emp_ids,
            status="approved",
            start_date__lte=today,
            end_date__gte=today,
        ).select_related("leave_type")
    ):
        current_leave_map.setdefault(l.employee_id, l)

    # Prefetch pending counts in three queries (one per model) then merge
    leave_pending = dict(
        LeaveRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id')
        .annotate(cnt=Sum('id'))  # just counting rows
        .values_list('employee_id', 'cnt')
    )
    # Use a proper Count instead
    from django.db.models import Count
    leave_pending = {
        row['employee_id']: row['cnt']
        for row in LeaveRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }
    attendance_pending = {
        row['employee_id']: row['cnt']
        for row in AttendanceRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }
    holiday_pending = {
        row['employee_id']: row['cnt']
        for row in HolidayWorkRequest.objects.filter(employee_id__in=emp_ids, status="pending")
        .values('employee_id').annotate(cnt=Count('id'))
    }

    # Prefetch last approved leave per employee in one query
    # We can't do "first per group" in one ORM call easily, so we fetch all
    # approved and then pick the latest in Python.
    approved_leaves = list(
        LeaveRequest.objects.filter(employee_id__in=emp_ids, status="approved")
        .select_related("leave_type")
        .order_by('employee_id', '-end_date')
    )
    last_leave_map = {}
    for l in approved_leaves:
        if l.employee_id not in last_leave_map:
            last_leave_map[l.employee_id] = l

    summary = []
    for emp in employees:
        balance = balance_map.get(emp.id)
        current_leave = current_leave_map.get(emp.id)
        last_leave = last_leave_map.get(emp.id)

        pending_count = (
            leave_pending.get(emp.id, 0)
            + attendance_pending.get(emp.id, 0)
            + holiday_pending.get(emp.id, 0)
        )

        summary.append({
            "id": emp.id,
            "name": emp.get_full_name() or emp.username,
            "initials": emp.initials,
            "department": emp.department or "—",
            "position": emp.position or "—",
            "leave_used": balance.used if balance else 0,
            "leave_total": balance.total if balance else 12,
            "leave_remaining": balance.remaining if balance else 12,
            "pending_count": pending_count,
            "status": "On Leave" if current_leave else "Active",
            "current_leave_type": current_leave.leave_type.name if current_leave else None,
            "last_leave": (
                f"{last_leave.leave_type.name} · {last_leave.date_range}"
                if last_leave else "—"
            ),
        })

    summary.sort(key=lambda s: (-s["pending_count"], s["name"]))
    return render(request, "leaves/team.html", {"team_summary": summary})


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _get_reports_data(today=None):
    from accounts.models import User
    from django.db.models import Count, Sum

    today = today or date.today()

    departments = (
        User.objects.exclude(department__isnull=True)
        .exclude(department="")
        .values_list("department", flat=True)
        .distinct()
    )

    # Pull per-department balance totals in one query
    dept_balance_qs = (
        LeaveBalance.objects.exclude(employee__department__isnull=True)
        .exclude(employee__department="")
        .values("employee__department")
        .annotate(total_days=Sum("used"), emp_count=Count("employee"))
    )
    dept_balance_map = {
        row["employee__department"]: row
        for row in dept_balance_qs
    }

    department_usage = []
    for dept in departments:
        row = dept_balance_map.get(dept, {})
        emp_count = row.get("emp_count", 0)
        total_days = row.get("total_days", 0) or 0
        department_usage.append({
            "name": dept,
            "employees": emp_count,
            "total_days": total_days,
            "avg_per_person": round(total_days / emp_count, 1) if emp_count else 0,
        })

    # Leave type breakdown — use DB aggregation
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

    # Monthly trend — one query, aggregate in Python
    monthly_qs = LeaveRequest.objects.filter(
        status="approved",
        start_date__year=today.year,
    ).only("start_date", "end_date")
    monthly_days_map = {m: 0 for m in range(1, 13)}
    for l in monthly_qs:
        monthly_days_map[l.start_date.month] = monthly_days_map.get(l.start_date.month, 0) + l.days
    monthly_days = [monthly_days_map[m] for m in range(1, 13)]

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
def export_reports_pdf(request):
    today = date.today()
    department_usage, leave_type_breakdown, monthly_trend = _get_reports_data(today)

    sections = [
        (
            "Department-wise Leave Usage",
            ["Department", "Employees", "Total Days", "Avg per Person"],
            [[d["name"], d["employees"], d["total_days"], d["avg_per_person"]] for d in department_usage],
        ),
        (
            "Leave Type Breakdown",
            ["Leave Type", "Requests", "Days Taken", "Pending"],
            [[lt["name"], lt["requests"], lt["days_taken"], lt["pending"]] for lt in leave_type_breakdown],
        ),
        (
            f"Monthly Leave Trend — {today.year}",
            ["Month", "Days Taken"],
            [[m["label"], m["days"]] for m in monthly_trend],
        ),
    ]

    return _build_pdf_response(
        filename=f"leave_reports_{today.isoformat()}.pdf",
        title=f"Leave Reports & Analytics — {today.year}",
        subtitle=f"Generated on {today}",
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Day requests (attendance / holiday work)
# ---------------------------------------------------------------------------

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

    # FIX: wrap in transaction + select_for_update to prevent double-decision
    with transaction.atomic():
        obj = get_object_or_404(model.objects.select_for_update(), id=id, status="pending")
        obj.status = decision
        obj.decided_at = timezone.now()
        obj.decision_note = request.POST.get("note", "").strip()
        obj.save(update_fields=["status", "decided_at", "decision_note"])

    label = _DAY_REQUEST_LABELS.get(request_type, request_type.replace('_', ' ').title())
    messages.success(request, f"{label} request {decision}.")
    send_day_request_notification_email(obj, decision, label)

    return redirect(f"{reverse('approvals')}?tab={tab}")


# ---------------------------------------------------------------------------
# Employee detail & PDF exports
# ---------------------------------------------------------------------------

@manager_required
def employee_detail(request, employee_id):
    from accounts.models import User

    employee = get_object_or_404(User, id=employee_id)
    today = date.today()

    balance = LeaveBalance.objects.filter(employee=employee).first()

    leave_history = (
        LeaveRequest.objects.filter(employee=employee)
        .select_related("leave_type")
        .order_by("-start_date")
    )
    attendance_history = AttendanceRequest.objects.filter(employee=employee).order_by("-date")
    holiday_work_history = HolidayWorkRequest.objects.filter(employee=employee).order_by("-date")

    current_leave = leave_history.filter(
        status="approved", start_date__lte=today, end_date__gte=today,
    ).first()

    fiscal_start = get_fiscal_year_start(today)
    fy_leaves = leave_history.filter(status="approved", start_date__gte=fiscal_start)
    type_breakdown = {}
    for l in fy_leaves:
        type_breakdown[l.leave_type.name] = type_breakdown.get(l.leave_type.name, 0) + l.days

    context = {
        "employee": employee,
        "balance": balance,
        "current_leave": current_leave,
        "leave_history": leave_history,
        "attendance_history": attendance_history,
        "holiday_work_history": holiday_work_history,
        "type_breakdown": type_breakdown,
        "rejected_count": leave_history.filter(status="rejected").count(),
        "cancelled_count": leave_history.filter(status="cancelled").count(),
    }
    return render(request, "leaves/employee_detail.html", context)


@manager_required
def export_employee_pdf(request, employee_id):
    from accounts.models import User

    today = date.today()
    employee = get_object_or_404(User, id=employee_id)

    leave_history = (
        LeaveRequest.objects.filter(employee=employee)
        .select_related("leave_type")
        .order_by("-start_date")
    )
    attendance_history = AttendanceRequest.objects.filter(employee=employee).order_by("-date")
    holiday_work_history = HolidayWorkRequest.objects.filter(employee=employee).order_by("-date")

    sections = [
        (
            "Leave Requests",
            ["Type", "From", "To", "Days", "Status", "Reason", "Decision Note", "Applied On"],
            [
                [
                    l.leave_type.name, l.start_date, l.end_date, l.days,
                    l.get_status_display(), l.reason,
                    l.decision_note or "", l.created_at.strftime("%Y-%m-%d"),
                ]
                for l in leave_history
            ],
        ),
        (
            "Attendance Requests",
            ["Date", "Status", "Reason", "Decision Note"],
            [
                [a.date, a.get_status_display(), a.reason, a.decision_note or ""]
                for a in attendance_history
            ],
        ),
        (
            "Holiday Work Requests",
            ["Date", "Status", "Reason", "Decision Note"],
            [
                [h.date, h.get_status_display(), h.reason, h.decision_note or ""]
                for h in holiday_work_history
            ],
        ),
    ]

    filename = f"leave_history_{employee.username}_{today.isoformat()}.pdf"
    return _build_pdf_response(
        filename=filename,
        title=f"Leave History — {employee.get_full_name() or employee.username}",
        subtitle=f"Exported on {today}",
        sections=sections,
    )


@login_required
def export_leave_pdf(request, id):
    leave = get_object_or_404(
        LeaveRequest.objects.select_related("leave_type", "employee"),
        id=id, employee=request.user, status="approved",
    )

    buffer = _build_single_leave_pdf(leave)
    filename = f"leave_request_{leave.employee.username}_{leave.id:03d}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _build_single_day_request_pdf(day_request, request_type_label):
    """Single-page PDF for one approved AttendanceRequest or
    HolidayWorkRequest, matching the paper Leave Request Form layout.
    Signature lines are left blank for physical signing after printing.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    s = _paper_form_styles()
    employee = day_request.employee

    elements = [Paragraph(f"{request_type_label} Request Form", s["title"])]

    request_type_text = "Attendance Request" if request_type_label == "Attendance" else "Holiday Work"

    elements.append(Paragraph("Employee information:", s["section"]))
    elements.append(_form_section_box([
        f"<b>Name:</b> {employee.get_full_name() or employee.username}",
        f"<b>Department:</b> {employee.department or '—'}"
        f"&nbsp;&nbsp;&nbsp;&nbsp;<b>Position:</b> {employee.position or '—'}",
        f"<b>Request Type:</b> {request_type_text}",
        f"<b>Date:</b> {ad_to_bs_display(day_request.date)}",
    ], s["label"]))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("Remarks:", s["section"]))
    elements.append(_form_section_box([day_request.reason or "—"], s["label"]))
    elements.append(Spacer(1, 10))

    _paper_form_disclaimer_and_signatures(elements, s)

    doc.build(elements)
    buffer.seek(0)
    return buffer


@login_required
def export_attendance_request_pdf(request, id):
    day_request = get_object_or_404(
        AttendanceRequest, id=id, employee=request.user, status="approved",
    )
    buffer = _build_single_day_request_pdf(day_request, "Attendance")
    filename = f"attendance_request_{day_request.employee.username}_{day_request.id:03d}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_holiday_work_request_pdf(request, id):
    day_request = get_object_or_404(
        HolidayWorkRequest, id=id, employee=request.user, status="approved",
    )
    buffer = _build_single_day_request_pdf(day_request, "Holiday Work")
    filename = f"holiday_work_request_{day_request.employee.username}_{day_request.id:03d}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def staff_movement(request):
    from accounts.utils import get_view_mode, exclude_staff_movement_ineligible
    from accounts.models import User
    from django.conf import settings
    from django.db.models import Q

    today = date.today()
    is_manager = get_view_mode(request) == 'manager' and request.user.has_management_access

    if is_manager:
        filter_date = request.GET.get("date")
        filter_employee_id = request.GET.get("employee")
        filter_client = request.GET.get("client", "").strip()
        show_all = request.GET.get("all") == "1"

        movements = StaffMovement.objects.all().select_related(
            "employee", "logged_by"
        ).prefetch_related("assistant_links__employee")

        if not filter_date and not show_all and not filter_employee_id and not filter_client:
            filter_date = today.strftime("%Y-%m-%d")

        filter_date_obj = None
        if filter_date:
            try:
                filter_date_obj = datetime.strptime(filter_date, "%Y-%m-%d").date()
                movements = movements.filter(date=filter_date_obj)
            except ValueError:
                pass

        if filter_employee_id:
            try:
                filter_employee_id = int(filter_employee_id)
                movements = movements.filter(employee_id=filter_employee_id)
            except ValueError:
                filter_employee_id = None

        if filter_client:
            movements = movements.filter(client__icontains=filter_client)

        employees = exclude_staff_movement_ineligible(
            User.objects.exclude(role="ceo")
        ).order_by("first_name", "username")

        return render(request, "leaves/staff_movement.html", {
            "movements": movements,
            "employees": employees,
            "filter_date": filter_date,
            "filter_date_obj": filter_date_obj,
            "filter_employee_id": filter_employee_id,
            "filter_client": filter_client,
            "show_all": show_all,
            "is_manager": True,
        })
    else:
        other_employees = exclude_staff_movement_ineligible(
            User.objects.exclude(id=request.user.id).exclude(role="ceo")
        ).order_by("first_name", "username")

        # Same username list now grants two things: logging visits on behalf of
        # others, AND full read/edit authority over every staff movement record
        # (used to cover people who can't fill their own times in).
        is_staff_movement_admin = request.user.username in getattr(settings, "STAFF_MOVEMENT_PROXY_LOGGER_USERNAMES", [])
        can_log_on_behalf = is_staff_movement_admin
        proxy_employees = (
            exclude_staff_movement_ineligible(
                User.objects.exclude(role="ceo").exclude(pk=request.user.pk)
            ).order_by("first_name", "username")
            if can_log_on_behalf
            else None
        )

        if request.method == "POST":
            date_str = request.POST.get("date")
            client_str = request.POST.get("client", "").strip()
            in_time_str = request.POST.get("in_time")
            purpose_type = request.POST.get("purpose_type", "").strip()
            purpose = request.POST.get("purpose", "").strip()
            problem_description = request.POST.get("problem_description", "").strip()
            assistant_ids = request.POST.getlist("assistants")
            on_behalf_of_id = request.POST.get("on_behalf_of", "").strip()

            out_time = datetime.now().time()

            errors = []
            if not date_str:
                errors.append("Please select a date.")
            if not client_str:
                errors.append("Please specify the client / location.")
            if in_time_str:
                errors.append("Return time must be filled in after the movement is logged.")
            if purpose_type not in dict(StaffMovement.PURPOSE_CHOICES):
                errors.append("Please select a purpose.")
            if purpose_type == "problem_solving" and not problem_description:
                errors.append("Please describe the problem being addressed.")

            target_employee = request.user
            if can_log_on_behalf and on_behalf_of_id:
                try:
                    target_employee = exclude_staff_movement_ineligible(
                        User.objects.exclude(role="ceo")
                    ).get(id=int(on_behalf_of_id))
                except (ValueError, User.DoesNotExist):
                    errors.append("Please select a valid employee to log this visit for.")

            movement_date = None
            if date_str:
                try:
                    movement_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    errors.append("Invalid date format.")

            if not errors:
                movement = StaffMovement.objects.create(
                    employee=target_employee,
                    logged_by=request.user if target_employee != request.user else None,
                    date=movement_date,
                    client=client_str,
                    out_time=out_time,
                    in_time=None,
                    purpose_type=purpose_type,
                    purpose=purpose,
                    problem_description=problem_description,
                    resolution_status="",
                )
                if assistant_ids:
                    movement.assistants.set(
                        exclude_staff_movement_ineligible(
                            User.objects.filter(id__in=assistant_ids)
                        ).exclude(id=target_employee.id)
                    )
                if target_employee == request.user:
                    messages.success(request, "Staff movement record logged successfully.")
                else:
                    messages.success(
                        request,
                        f"Movement logged on behalf of {target_employee.get_full_name() or target_employee.username}."
                    )
                return redirect("staff_movement")

            for err in errors:
                messages.error(request, err)

        movements = list(
            StaffMovement.objects.filter(
                Q(employee=request.user) | Q(assistants=request.user) | Q(logged_by=request.user)
            ).distinct().select_related("employee", "logged_by").prefetch_related("assistant_links__employee")
        )

        my_links = {
            l.movement_id: l for l in StaffMovementAssistant.objects.filter(
                movement__in=movements, employee=request.user
            )
        }
        for m in movements:
            m.my_assistant_link = my_links.get(m.id)
            m.is_primary_for_me = request.user.id in (m.employee_id, m.logged_by_id)

        context = {
            "movements": movements,
            "is_manager": False,
            "today": today,
            "other_employees": other_employees,
            "purpose_choices": StaffMovement.PURPOSE_CHOICES,
            "resolution_choices": StaffMovement.RESOLUTION_CHOICES,
            "can_log_on_behalf": can_log_on_behalf,
            "proxy_employees": proxy_employees,
            "is_staff_movement_admin": is_staff_movement_admin,
        }

        # Full-visibility admin table — everyone's records, same filter pattern
        # as the manager view, but reachable without needing manager role.
        if is_staff_movement_admin:
            admin_filter_date = request.GET.get("admin_date")
            admin_filter_employee_id = request.GET.get("admin_employee")
            admin_filter_client = request.GET.get("admin_client", "").strip()
            admin_show_all = request.GET.get("admin_all") == "1"

            admin_movements = StaffMovement.objects.all().select_related(
                "employee", "logged_by"
            ).prefetch_related("assistant_links__employee")

            if not admin_filter_date and not admin_show_all and not admin_filter_employee_id and not admin_filter_client:
                admin_filter_date = today.strftime("%Y-%m-%d")

            admin_filter_date_obj = None
            if admin_filter_date:
                try:
                    admin_filter_date_obj = datetime.strptime(admin_filter_date, "%Y-%m-%d").date()
                    admin_movements = admin_movements.filter(date=admin_filter_date_obj)
                except ValueError:
                    pass

            if admin_filter_employee_id:
                try:
                    admin_filter_employee_id = int(admin_filter_employee_id)
                    admin_movements = admin_movements.filter(employee_id=admin_filter_employee_id)
                except ValueError:
                    admin_filter_employee_id = None

            if admin_filter_client:
                admin_movements = admin_movements.filter(client__icontains=admin_filter_client)

            admin_employees = exclude_staff_movement_ineligible(
                User.objects.exclude(role="ceo")
            ).order_by("first_name", "username")

            context.update({
                "admin_movements": admin_movements,
                "admin_employees": admin_employees,
                "admin_filter_date": admin_filter_date,
                "admin_filter_date_obj": admin_filter_date_obj,
                "admin_filter_employee_id": admin_filter_employee_id,
                "admin_filter_client": admin_filter_client,
                "admin_show_all": admin_show_all,
            })

        return render(request, "leaves/staff_movement.html", context)


@login_required
def staff_movement_edit(request, id):
    from accounts.models import User
    from accounts.utils import exclude_staff_movement_ineligible
    from django.conf import settings
    from django.db.models import Q

    is_staff_movement_admin = request.user.username in getattr(settings, "STAFF_MOVEMENT_PROXY_LOGGER_USERNAMES", [])

    if is_staff_movement_admin:
        # Admins can reach and fix any record, not just ones they're party to.
        movement = get_object_or_404(
            StaffMovement.objects.select_related("employee", "logged_by").prefetch_related("assistant_links__employee"),
            id=id
        )
    else:
        movement = get_object_or_404(
            StaffMovement.objects.filter(
                Q(employee=request.user) | Q(logged_by=request.user) | Q(assistants=request.user)
            ).distinct().select_related("employee").prefetch_related("assistant_links__employee"),
            id=id
        )

    is_primary = request.user.id in (movement.employee_id, movement.logged_by_id)
    acting_as_primary = is_primary or is_staff_movement_admin

    my_assistant_link = None
    if not is_primary and not is_staff_movement_admin:
        my_assistant_link = get_object_or_404(StaffMovementAssistant, movement=movement, employee=request.user)

    # Hard lock: once a person's own in_time is set, it's final for that person,
    # and old records close after the day ends. Staff movement admins are exempt
    # from both — they're the designated fallback for people who can't self-correct.
    if not is_staff_movement_admin:
        if is_primary:
            if movement.in_time:
                messages.error(request, "This record already has a return time and can no longer be edited.")
                return redirect("staff_movement")
        else:
            if my_assistant_link.in_time:
                messages.error(request, "You've already recorded your return time for this visit and it can no longer be edited.")
                return redirect("staff_movement")

        if movement.date != date.today():
            messages.error(
                request,
                "This record is from a previous day, so the self-service correction "
                "window has closed. Please contact your manager to update it."
            )
            return redirect("staff_movement")

    other_employees = exclude_staff_movement_ineligible(
        User.objects.exclude(id=request.user.id).exclude(role="ceo")
    ).order_by("first_name", "username")

    # Admins see and can correct every participant's slot, filled or not.
    # A regular primary logger can still only fill slots that are blank.
    if is_staff_movement_admin:
        open_assistant_links = list(movement.assistant_links.all())
    elif is_primary:
        open_assistant_links = list(movement.assistant_links.filter(in_time__isnull=True))
    else:
        open_assistant_links = []

    if request.method == "POST":
        in_time_str = request.POST.get("in_time")
        resolution_status = request.POST.get("resolution_status", "").strip()
        completion_notes = request.POST.get("completion_notes", "").strip()
        separate_returns = request.POST.get("separate_returns") == "1"

        errors = []
        in_time = None
        if not in_time_str:
            errors.append("Please enter the return time.")
        else:
            try:
                in_time = datetime.strptime(in_time_str, "%H:%M").time()
            except ValueError:
                try:
                    in_time = datetime.strptime(in_time_str, "%H:%M:%S").time()
                except ValueError:
                    errors.append("Invalid return time format.")

        # Compare against the record's actual date, not just today's clock —
        # otherwise a clock-time comparison alone wrongly flags a perfectly
        # valid past-day time (e.g. 5:30 PM yesterday) as "in the future"
        # whenever it's currently earlier in the day than that.
        now_dt = datetime.now()
        if in_time is not None:
            if in_time <= movement.out_time:
                errors.append("Return time must be later than the departure time.")
            if datetime.combine(movement.date, in_time) > now_dt:
                errors.append("Return time can't be in the future.")

        if movement.purpose_type == "problem_solving":
            if resolution_status not in dict(StaffMovement.RESOLUTION_CHOICES):
                errors.append("Please select whether the problem was solved.")

        # Validate per-assistant entries typed by the primary/admin (only for open ones)
        assistant_updates = {}
        assistant_still_out = set()
        if acting_as_primary and separate_returns:
            for link in open_assistant_links:
                name = link.employee.get_full_name() or link.employee.username
                still_out = request.POST.get(f"assistant_still_out_{link.id}") == "1"
                field = f"assistant_in_time_{link.id}"
                val = request.POST.get(field, "").strip()

                if still_out:
                    if val:
                        errors.append(f"{name} can't have both a return time and 'Still out' checked.")
                        continue
                    assistant_still_out.add(link.id)
                    continue

                if not val:
                    if is_staff_movement_admin:
                        # Admin left this one untouched — whether it already has a
                        # time or is still blank, don't force a re-entry.
                        continue
                    # Neither a time nor "still out" was given — ambiguous, must be explicit.
                    errors.append(
                        f"Please enter a return time for {name}, or check 'Still out' if they haven't returned."
                    )
                    continue

                try:
                    a_time = datetime.strptime(val, "%H:%M").time()
                except ValueError:
                    errors.append(f"Invalid return time for {name}.")
                    continue
                if a_time <= movement.out_time:
                    errors.append(f"{name}'s return time must be after departure.")
                    continue
                if datetime.combine(movement.date, a_time) > now_dt:
                    errors.append(f"{name}'s return time can't be in the future.")
                    continue
                assistant_updates[link.id] = a_time

        if not errors:
            if acting_as_primary:
                movement.in_time = in_time
                movement.resolution_status = resolution_status
                movement.completion_notes = completion_notes
                movement.save()

                for link in open_assistant_links:
                    if link.id in assistant_still_out:
                        if is_staff_movement_admin:
                            # Admin correction: revert this person to "not returned".
                            link.in_time = None
                            link.save()
                        continue
                    if link.id in assistant_updates:
                        link.in_time = assistant_updates[link.id]
                        link.save()
                    elif link.in_time is None:
                        link.in_time = in_time
                        link.save()
                    # else: already had a time and admin didn't provide an update —
                    # leave it untouched rather than silently overwriting it.
            else:
                my_assistant_link.in_time = in_time
                my_assistant_link.save()

                movement.resolution_status = resolution_status
                movement.completion_notes = completion_notes
                movement.save(update_fields=["resolution_status", "completion_notes"])

            messages.success(request, "Staff movement record updated successfully.")
            return redirect("staff_movement")

        for err in errors:
            messages.error(request, err)

    return render(request, "leaves/staff_movement.html", {
        "movement": movement,
        "is_edit": True,
        "is_manager": False,
        "is_primary": is_primary,
        "is_staff_movement_admin": is_staff_movement_admin,
        "my_assistant_link": my_assistant_link,
        "other_employees": other_employees,
        "open_assistant_links": open_assistant_links,
        "selected_assistant_ids": list(movement.assistants.values_list("id", flat=True)),
        "purpose_choices": StaffMovement.PURPOSE_CHOICES,
        "resolution_choices": StaffMovement.RESOLUTION_CHOICES,
    })