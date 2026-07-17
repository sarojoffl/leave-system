from datetime import date, datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from leaves.models import LeaveType, LeaveRequest, LeaveBalance, PublicHoliday

User = get_user_model()

class LeaveSystemTestCase(TestCase):
    def setUp(self):
        # Create user
        self.employee = User.objects.create_user(
            username="employee",
            password="password123",
            role="employee",
            email="employee@company.com"
        )
        self.manager = User.objects.create_user(
            username="manager",
            password="password123",
            role="manager",
            email="manager@company.com"
        )
        
        # Create Leave Type
        self.annual_leave = LeaveType.objects.create(
            name="Annual Leave"
        )
        
        # Note: Signals create LeaveBalance for existing users when they are created.
        # Let's verify and grab it
        self.balance = LeaveBalance.objects.get(employee=self.employee)
        self.balance.total = 10.0
        self.balance.save()
        
        # Set up a public holiday on Friday, June 19, 2026
        self.holiday_date = date(2026, 6, 19)
        self.holiday = PublicHoliday.objects.create(
            date=self.holiday_date,
            name="Public Holiday"
        )
        
        self.client = Client()

    def test_working_days_excludes_saturday_and_holidays(self):
        """
        Verify that our working days logic:
        - Excludes Saturdays (Saturday only weekend).
        - Excludes Public Holidays.
        - Includes Sundays and other weekdays.
        """
        # Thursday June 18, 2026 to Monday June 22, 2026
        # Thursday 18: working
        # Friday 19: holiday (excluded)
        # Saturday 20: Saturday (excluded)
        # Sunday 21: Sunday (working)
        # Monday 22: working
        # Total working days = 3 (Thursday, Sunday, Monday)
        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 18),
            end_date=date(2026, 6, 22),
            reason="Vacation"
        )
        self.assertEqual(req.days, 3.0)

    def test_overlapping_leave_validation(self):
        """
        Verify that we cannot apply for leaves that overlap existing ones.
        """
        from datetime import timedelta
        self.client.login(username="employee", password="password123")
        
        today = date.today()
        # Find a future date range starting next Monday
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_monday = today + timedelta(days=days_ahead)
        next_tuesday = next_monday + timedelta(days=1)
        next_wednesday = next_monday + timedelta(days=2)

        # Apply for leave next_monday to next_tuesday (2 working days)
        response1 = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": next_monday.strftime("%Y-%m-%d"),
            "to_date": next_tuesday.strftime("%Y-%m-%d"),
            "reason": "First request"
        })
        self.assertRedirects(response1, reverse("my_leaves"))
        self.assertTrue(LeaveRequest.objects.filter(employee=self.employee, reason="First request").exists())
        
        # Try to apply for overlapping leave next_tuesday to next_wednesday
        response2 = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": next_tuesday.strftime("%Y-%m-%d"),
            "to_date": next_wednesday.strftime("%Y-%m-%d"),
            "reason": "Overlapping request"
        })
        # Overlapping should cause validation failure and not redirect
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(LeaveRequest.objects.filter(employee=self.employee, reason="Overlapping request").exists())

    def test_insufficient_balance_validation(self):
        """
        Verify that an employee cannot request more leave than they have available.
        """
        from datetime import timedelta
        self.client.login(username="employee", password="password123")
        
        # We need a range of 14 calendar days starting from next Monday
        today = date.today()
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_monday = today + timedelta(days=days_ahead)
        end_date = next_monday + timedelta(days=13)  # 14 calendar days

        # Even though the range has 12 working days (exceeds 10 balance),
        # balance enforcement was relaxed in f058067, so the request now succeeds.
        response = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": next_monday.strftime("%Y-%m-%d"),
            "to_date": end_date.strftime("%Y-%m-%d"),
            "reason": "Too long"
        })
        # Should now redirect (302) because balance enforcement was removed
        self.assertRedirects(response, reverse("my_leaves"))
        self.assertTrue(LeaveRequest.objects.filter(employee=self.employee, reason="Too long").exists())

    def test_approve_always_succeeds_regardless_of_balance(self):
        """
        Since balance enforcement was relaxed (commit f058067),
        a manager can approve leave requests even when the employee's balance
        would be exceeded. Both requests should be approved.
        """
        req1 = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 21),  # 5 working days
            reason="First"
        )
        req2 = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 22),
            end_date=date(2026, 6, 28),  # 6 working days
            reason="Second"
        )

        self.client.login(username="manager", password="password123")

        # Approve first request — should succeed
        self.client.post(reverse("approve_leave", args=[req1.id]))
        req1.refresh_from_db()
        self.assertEqual(req1.status, "approved")

        # Approve second request — should also succeed (no balance check)
        self.client.post(reverse("approve_leave", args=[req2.id]))
        req2.refresh_from_db()
        self.assertEqual(req2.status, "approved")

    def test_cancel_approved_leave_refunds_balance(self):
        """
        Verify that cancelling an approved leave request refunds the employee's balance.
        Only future leaves (start_date > today) can be cancelled by employees.
        """
        from datetime import timedelta
        today = date.today()
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_monday = today + timedelta(days=days_ahead)
        next_thursday = next_monday + timedelta(days=3)  # 4 working days

        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=next_monday,
            end_date=next_thursday,  # 4 working days (Mon-Thu)
            reason="Cancel test",
            status="approved"
        )
        # Setup balance as if it was already deducted
        self.balance.used = 4.0
        self.balance.save()

        self.client.login(username="employee", password="password123")

        response = self.client.post(reverse("cancel_leave", args=[req.id]))
        self.assertRedirects(response, reverse("my_leaves"))

        req.refresh_from_db()
        self.assertEqual(req.status, "cancelled")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.used, 0.0)

    def test_revoke_approved_leave_refunds_balance(self):
        """
        Verify that a manager revoking an approved leave refunds the employee's balance.
        Revoke is only allowed if the leave has not yet ended.
        """
        from datetime import timedelta
        today = date.today()
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_monday = today + timedelta(days=days_ahead)
        next_thursday = next_monday + timedelta(days=3)  # 4 working days

        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=next_monday,
            end_date=next_thursday,
            reason="Revoke test",
            status="approved"
        )
        self.balance.used = 4.0
        self.balance.save()

        self.client.login(username="manager", password="password123")

        response = self.client.post(reverse("reject_leave", args=[req.id]))
        # Redirect goes to approvals with ?tab=leave (default tab)
        self.assertRedirects(response, f"{reverse('approvals')}?tab=leave")

        req.refresh_from_db()
        self.assertEqual(req.status, "rejected")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.used, 0.0)


class PDFExportTestCase(TestCase):
    """Tests for PDF export endpoints under My Leaves."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="pdfuser",
            password="password123",
            role="employee",
            email="pdfuser@company.com"
        )
        self.client = Client()
        self.client.login(username="pdfuser", password="password123")

    def test_export_attendance_request_pdf_returns_pdf(self):
        """
        Verify that the attendance PDF export endpoint returns a 200 response
        with the correct content-type.
        """
        from leaves.models import AttendanceRequest
        req = AttendanceRequest.objects.create(
            employee=self.employee,
            date=date(2026, 6, 1),
            reason="Late login",
            status="approved"
        )
        response = self.client.get(reverse("export_attendance_request_pdf", args=[req.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_holiday_work_request_pdf_returns_pdf(self):
        """
        Verify that the holiday work PDF export endpoint returns a 200 response
        with the correct content-type.
        """
        from leaves.models import HolidayWorkRequest
        req = HolidayWorkRequest.objects.create(
            employee=self.employee,
            date=date(2026, 6, 5),
            reason="Office delivery",
            status="approved"
        )
        response = self.client.get(reverse("export_holiday_work_request_pdf", args=[req.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_leave_request_pdf_returns_pdf(self):
        """
        Verify that the leave request PDF export endpoint returns a 200 response
        with the correct content-type.
        """
        from leaves.models import LeaveType, LeaveRequest
        leave_type = LeaveType.objects.create(name="Annual Leave")
        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=leave_type,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            reason="Family event",
            status="approved"
        )
        response = self.client.get(reverse("export_leave_pdf", args=[req.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_endpoints_require_login(self):
        """
        Verify that the export endpoints require authentication.
        """
        from leaves.models import AttendanceRequest, HolidayWorkRequest, LeaveType, LeaveRequest
        att = AttendanceRequest.objects.create(
            employee=self.employee,
            date=date(2026, 6, 1),
            reason="Late login",
            status="approved"
        )
        hol = HolidayWorkRequest.objects.create(
            employee=self.employee,
            date=date(2026, 6, 5),
            reason="Office delivery",
            status="approved"
        )
        leave_type = LeaveType.objects.create(name="Annual Leave")
        lv = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=leave_type,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            reason="Family event",
            status="approved"
        )

        self.client.logout()
        for url_name, arg in [
            ("export_attendance_request_pdf", att.id),
            ("export_holiday_work_request_pdf", hol.id),
            ("export_leave_pdf", lv.id),
        ]:
            response = self.client.get(reverse(url_name, args=[arg]))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/login/", response["Location"])


class StaffMovementTestCase(TestCase):
    """Tests for Staff Movement logging, editing, and filtering."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="testemployee",
            password="password123",
            role="employee",
            email="testemployee@company.com"
        )
        self.manager = User.objects.create_user(
            username="testmanager",
            password="password123",
            role="manager",
            email="testmanager@company.com"
        )
        self.client = Client()

    def test_log_movement_requires_login(self):
        response = self.client.get(reverse("staff_movement"))
        self.assertEqual(response.status_code, 302)

    def test_employee_can_log_and_edit_movement(self):
        self.client.login(username="testemployee", password="password123")
        
        # Log new movement
        today_str = date.today().strftime("%Y-%m-%d")
        response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Google Office",
            "purpose_type": "goods_bill_delivery",
            "purpose": "Technical Demo"
        })
        self.assertRedirects(response, reverse("staff_movement"))
        
        from leaves.models import StaffMovement
        from datetime import timedelta
        movement = StaffMovement.objects.get(client="Google Office")
        self.assertEqual(movement.employee, self.employee)
        self.assertEqual(movement.purpose, "Technical Demo")
        self.assertIsNone(movement.in_time)

        # Set out_time programmatically to 10 minutes ago so we can return in the past
        now_dt = datetime.now()
        movement.out_time = (now_dt - timedelta(minutes=10)).time()
        movement.save()

        # Fill in return time (edit) - 5 minutes ago
        in_time_str = (now_dt - timedelta(minutes=5)).strftime("%H:%M")
        response_edit = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Google Office",
            "in_time": in_time_str,
            "purpose_type": "goods_bill_delivery",
            "purpose": "Technical Demo Completed",
            "completion_notes": "Technical Demo Completed"
        })
        self.assertRedirects(response_edit, reverse("staff_movement"))
        movement.refresh_from_db()
        self.assertEqual(movement.in_time.strftime("%H:%M"), in_time_str)
        self.assertEqual(movement.purpose, "Technical Demo")
        self.assertEqual(movement.completion_notes, "Technical Demo Completed")

    def test_problem_movement_requires_description_and_solve_status_on_return(self):
        self.client.login(username="testemployee", password="password123")
        today_str = date.today().strftime("%Y-%m-%d")

        response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client Site",
            "purpose_type": "problem_solving",
        })
        self.assertContains(response, "Please describe the problem being addressed.")

        response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client Site",
            "purpose_type": "problem_solving",
            "problem_description": "Internet is not working",
        })
        self.assertRedirects(response, reverse("staff_movement"))

        from leaves.models import StaffMovement
        from datetime import timedelta
        movement = StaffMovement.objects.get(client="Client Site")
        
        # Set out_time programmatically to 10 minutes ago
        now_dt = datetime.now()
        movement.out_time = (now_dt - timedelta(minutes=10)).time()
        movement.save()

        in_time_str = (now_dt - timedelta(minutes=5)).strftime("%H:%M")

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": in_time_str,
            "purpose_type": "problem_solving",
            "problem_description": "Internet is not working",
        })
        self.assertContains(response, "Please select whether the problem was solved.")

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": in_time_str,
            "purpose_type": "problem_solving",
            "problem_description": "Internet is not working",
            "resolution_status": "solved",
        })
        self.assertRedirects(response, reverse("staff_movement"))
        movement.refresh_from_db()
        self.assertEqual(movement.resolution_status, "solved")

    def test_return_time_must_be_filled_later_and_after_departure(self):
        self.client.login(username="testemployee", password="password123")
        from leaves.models import StaffMovement
        from datetime import timedelta
        today_str = date.today().strftime("%Y-%m-%d")

        now_dt = datetime.now()
        out_time_obj = (now_dt - timedelta(minutes=10)).time()
        out_time_str = out_time_obj.strftime("%H:%M")

        movement = StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="Client Site",
            out_time=out_time_obj,
            purpose_type="goods_pickup",
        )

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "purpose_type": "goods_pickup",
        })
        self.assertContains(response, "Please enter the return time.")

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": out_time_str,
            "purpose_type": "goods_pickup",
        })
        self.assertContains(response, "Return time must be later than the departure time")

        # Create a time 1 minute before out_time
        before_out_time_str = (datetime.combine(date.today(), out_time_obj) - timedelta(minutes=1)).strftime("%H:%M")
        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": before_out_time_str,
            "purpose_type": "goods_pickup",
        })
        self.assertContains(response, "Return time must be later than the departure time")

    def test_manager_can_view_and_filter_movements(self):
        from leaves.models import StaffMovement
        StaffMovement.objects.create(
            employee=self.employee,
            date=date(2026, 7, 10),
            client="Google Office",
            out_time=datetime.strptime("10:30", "%H:%M").time(),
            purpose="Demo"
        )
        StaffMovement.objects.create(
            employee=self.employee,
            date=date(2026, 7, 11),
            client="Microsoft Office",
            out_time=datetime.strptime("11:00", "%H:%M").time(),
            purpose="Meeting"
        )

        # Log in as manager
        self.client.login(username="testmanager", password="password123")
        
        # Set session view_mode to manager to pass is_manager check
        session = self.client.session
        session["view_mode"] = "manager"
        session.save()

        # Load manager view
        response = self.client.get(reverse("staff_movement"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Movement Logs")
        
        # Filter by client "Microsoft"
        response_filter = self.client.get(reverse("staff_movement"), {"client": "Microsoft"})
        self.assertEqual(response_filter.status_code, 200)
        self.assertContains(response_filter, "Microsoft Office")
        self.assertNotContains(response_filter, "Google Office")

    def test_block_movement_if_already_out(self):
        self.client.login(username="testemployee", password="password123")
        today_str = date.today().strftime("%Y-%m-%d")

        # Log first movement
        self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client A",
            "purpose_type": "goods_pickup",
        })

        # Try to log second movement on the same day without returning
        response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client B",
            "purpose_type": "goods_pickup",
        })
        self.assertContains(
            response,
            "is already logged as out on another movement today and must return first."
        )

    def test_block_movement_if_assistant_already_out(self):
        # Create another employee to act as assistant
        assistant = User.objects.create_user(
            username="assistant_user",
            password="password123",
            role="employee",
            email="assistant@company.com"
        )
        
        # Log a movement for the assistant so they are currently out
        from leaves.models import StaffMovement
        StaffMovement.objects.create(
            employee=assistant,
            date=date.today(),
            client="Assistant Client",
            out_time=datetime.now().time(),
            purpose_type="goods_pickup",
        )

        # Log in as testemployee and try to log a movement with assistant_user as assistant
        self.client.login(username="testemployee", password="password123")
        today_str = date.today().strftime("%Y-%m-%d")

        response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Google Office",
            "purpose_type": "goods_bill_delivery",
            "assistants": [assistant.id]
        })
        self.assertContains(
            response,
            "already out on another movement today"
        )

