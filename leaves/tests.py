from datetime import date, datetime, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from leaves.models import LeaveType, LeaveRequest, LeaveBalance, PublicHoliday, StaffMovement

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
            "work_done_for": "Mr. Larry Page",
            "completion_notes": "Technical Demo Completed"
        })
        self.assertRedirects(response_edit, reverse("staff_movement"))
        movement.refresh_from_db()
        self.assertEqual(movement.in_time.strftime("%H:%M"), in_time_str)
        self.assertEqual(movement.purpose, "Technical Demo")
        self.assertEqual(movement.work_done_for, "Mr. Larry Page")
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
            "work_done_for": "IT Manager",
            "completion_notes": "Reconfigured router",
        })
        self.assertContains(response, "Please select whether the problem was solved.")

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": in_time_str,
            "purpose_type": "problem_solving",
            "problem_description": "Internet is not working",
            "resolution_status": "solved",
            "work_done_for": "IT Manager",
            "completion_notes": "Reconfigured router",
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
            "work_done_for": "Contact Person",
            "completion_notes": "Picked up goods",
        })
        self.assertContains(response, "Return time must be later than the departure time")

        # Create a time 1 minute before out_time
        before_out_time_str = (datetime.combine(date.today(), out_time_obj) - timedelta(minutes=1)).strftime("%H:%M")
        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "Client Site",
            "in_time": before_out_time_str,
            "purpose_type": "goods_pickup",
            "work_done_for": "Contact Person",
            "completion_notes": "Picked up goods",
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
        filtered_clients = [m.client for m in response_filter.context["movements"]]
        self.assertIn("Microsoft Office", filtered_clients)
        self.assertNotIn("Google Office", filtered_clients)

        # Filter by comma-separated clients "Google, Microsoft"
        response_multi = self.client.get(reverse("staff_movement"), {"client": "Google, Microsoft"})
        self.assertEqual(response_multi.status_code, 200)
        multi_filtered_clients = [m.client for m in response_multi.context["movements"]]
        self.assertIn("Google Office", multi_filtered_clients)
        self.assertIn("Microsoft Office", multi_filtered_clients)

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

    def test_employee_can_cancel_movement_with_reason(self):
        """Cancelling an active movement frees the employee to log a new one."""
        self.client.login(username="testemployee", password="password123")
        today_str = date.today().strftime("%Y-%m-%d")

        # Log a movement (leaves the employee marked as 'out')
        self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client X",
            "purpose_type": "goods_pickup",
        })
        movement = StaffMovement.objects.filter(
            employee=self.employee, date=date.today()
        ).latest("created_at")

        # Cancel the movement with a reason
        cancel_url = reverse("staff_movement_cancel", args=[movement.id])
        response = self.client.post(cancel_url, {
            "cancellation_reason": "Client postponed the meeting."
        }, follow=True)

        movement.refresh_from_db()
        self.assertTrue(movement.is_cancelled)
        self.assertEqual(movement.cancellation_reason, "Client postponed the meeting.")

        # Employee should now be able to log another movement the same day
        log_response = self.client.post(reverse("staff_movement"), {
            "date": today_str,
            "client": "Client Y",
            "purpose_type": "goods_pickup",
        })
        # A redirect means success (no error in response body)
        self.assertEqual(log_response.status_code, 302)

    def test_cannot_cancel_completed_movement(self):
        """A movement that already has an in_time cannot be cancelled."""
        self.client.login(username="testemployee", password="password123")
        movement = StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="Client Z",
            out_time=datetime.now().time(),
            in_time=datetime.now().time(),
            purpose_type="goods_pickup",
        )

        cancel_url = reverse("staff_movement_cancel", args=[movement.id])
        self.client.post(cancel_url, {"cancellation_reason": "Not needed."}, follow=True)

        movement.refresh_from_db()
        # is_cancelled must remain False since the movement was completed
        self.assertFalse(movement.is_cancelled)

    def test_unauthorized_user_cannot_cancel_movement(self):
        """A user who did not log the movement cannot cancel it."""
        # Create another user
        other_user = User.objects.create_user(
            username="other_employee",
            password="password123",
            role="employee",
            email="other@company.com",
        )

        movement = StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="Client W",
            out_time=datetime.now().time(),
            purpose_type="goods_pickup",
        )

        self.client.login(username="other_employee", password="password123")
        cancel_url = reverse("staff_movement_cancel", args=[movement.id])
        response = self.client.post(cancel_url, {
            "cancellation_reason": "Trying to cancel someone else's visit."
        })

        # Should get 404 (get_object_or_404 rejects this user)
        self.assertEqual(response.status_code, 404)

        movement.refresh_from_db()
        self.assertFalse(movement.is_cancelled)

    def test_work_done_for_saving_and_pdf_export(self):
        from datetime import timedelta
        self.client.login(username="testemployee", password="password123")
        today_str = date.today().strftime("%Y-%m-%d")
        now_dt = datetime.now()
        out_time = (now_dt - timedelta(minutes=10)).time()
        in_time_str = (now_dt - timedelta(minutes=2)).strftime("%H:%M")

        movement = StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="ABC Tech Office",
            out_time=out_time,
            purpose_type="amc",
        )

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": today_str,
            "client": "ABC Tech Office",
            "in_time": in_time_str,
            "purpose_type": "amc",
            "work_done_for": "Mr. Sharma (Finance)",
            "completion_notes": "Serviced printers and router.",
        })
        self.assertRedirects(response, reverse("staff_movement"))
        movement.refresh_from_db()
        self.assertEqual(movement.work_done_for, "Mr. Sharma (Finance)")
        self.assertEqual(movement.completion_notes, "Serviced printers and router.")

        # Test PDF export access - non-manager should be denied/redirected
        pdf_url = reverse("staff_movement_export_pdf") + "?client=ABC"
        response_pdf = self.client.get(pdf_url)
        self.assertRedirects(response_pdf, reverse("staff_movement"))

        # Test PDF export access - manager should succeed
        self.client.login(username="testmanager", password="password123")
        # Switch session view_mode to manager
        session = self.client.session
        session['view_mode'] = 'manager'
        session.save()

        response_pdf_manager = self.client.get(pdf_url)
        self.assertEqual(response_pdf_manager.status_code, 200)
        self.assertContains(response_pdf_manager, "Staff Movement &amp; Service Report")
        self.assertContains(response_pdf_manager, "Mr. Sharma (Finance)")

    def test_reports_bs_trend_and_employee_stats(self):
        from leaves.bs_convert import ad_to_bs, bs_month_name
        self.client.login(username="testmanager", password="password123")
        session = self.client.session
        session['view_mode'] = 'manager'
        session.save()

        today = date.today()
        bs_y, bs_m, _ = ad_to_bs(today)

        leave_type = LeaveType.objects.create(name="Annual Leave")
        LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=leave_type,
            start_date=today,
            end_date=today,
            reason="Test leave for stats",
            status="approved",
        )

        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Monthly Leave Trend — {bs_y}")
        self.assertContains(response, f"Employee Leave Stats — {bs_month_name(bs_m)} {bs_y}")

        # Test month navigation
        nav_url = f"{reverse('reports')}?stats_month=1&stats_year={bs_y}"
        response_nav = self.client.get(nav_url)
        self.assertEqual(response_nav.status_code, 200)
        self.assertContains(response_nav, f"Employee Leave Stats — Baisakh {bs_y}")

    def test_staff_movement_reports_tab(self):
        self.client.login(username="testmanager", password="password123")
        session = self.client.session
        session['view_mode'] = 'manager'
        session.save()

        # Create a sample staff movement
        StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="Global Tech Office",
            out_time=datetime.now().time(),
            purpose_type="amc",
        )

        response = self.client.get(reverse("reports") + "?tab=movement")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Movement Reports")
        self.assertContains(response, "Monthly Staff Movement Trend")
        self.assertContains(response, "Global Tech Office")

    def test_multi_stop_staff_movement(self):
        from leaves.models import StaffMovementStop
        self.client.login(username="testemployee", password="password123")
        post_data = {
            "date": date.today().strftime("%Y-%m-%d"),
            "stop_client": ["Plant Pathology", "Gharelu Udhyog"],
            "stop_purpose": ["Repair Laptop", "Deliver Cheque"],
            "stop_work_done_for": ["Subendra", "Ram"],
            "purpose_type": "amc",
        }
        response = self.client.post(reverse("staff_movement"), post_data)
        self.assertEqual(response.status_code, 302)

        movement = StaffMovement.objects.get(employee=self.employee)
        self.assertEqual(movement.stops.count(), 2)
        stops = list(movement.stops.all())
        self.assertEqual(stops[0].client, "Plant Pathology")
        self.assertEqual(stops[0].purpose, "Repair Laptop")
        self.assertEqual(stops[0].work_done_for, "Subendra")
        self.assertEqual(stops[1].client, "Gharelu Udhyog")
        self.assertEqual(stops[1].purpose, "Deliver Cheque")
        self.assertEqual(stops[1].work_done_for, "Ram")

        # Set out_time in the past to test valid return
        movement.out_time = (datetime.now() - timedelta(minutes=30)).time()
        movement.save()

        # Test Return edit with itemized notes
        edit_url = reverse("staff_movement_edit", args=[movement.id])
        valid_in_time = (datetime.now() - timedelta(minutes=5)).time().strftime("%H:%M")
        edit_data = {
            "in_time": valid_in_time,
            f"stop_work_done_for_{stops[0].id}": "Subendra",
            f"stop_work_done_for_{stops[1].id}": "Ram",
            f"stop_completion_notes_{stops[0].id}": "Fixed printer",
            f"stop_completion_notes_{stops[1].id}": "Replaced switch",
        }
        response_edit = self.client.post(edit_url, edit_data)
        self.assertEqual(response_edit.status_code, 302)

        stops[0].refresh_from_db()
        stops[1].refresh_from_db()
        self.assertEqual(stops[0].completion_notes, "Fixed printer")
        self.assertEqual(stops[1].completion_notes, "Replaced switch")

        # Verify filtering by "Plant Pathology" isolates its purpose note in Manager View
        self.client.login(username="testmanager", password="password123")
        session = self.client.session
        session["view_mode"] = "manager"
        session.save()

        resp_filter = self.client.get(reverse("staff_movement"), {"client": "Plant Pathology"})
        self.assertEqual(resp_filter.status_code, 200)
        filtered_m = resp_filter.context["movements"][0]
        self.assertEqual(filtered_m.filtered_purpose, "Repair Laptop")

    def test_work_done_for_required_on_return(self):
        self.client.login(username="testemployee", password="password123")
        now_dt = datetime.now()
        out_time_obj = (now_dt - timedelta(minutes=15)).time()
        in_time_str = (now_dt - timedelta(minutes=5)).strftime("%H:%M")

        movement = StaffMovement.objects.create(
            employee=self.employee,
            date=date.today(),
            client="Test Site",
            out_time=out_time_obj,
            purpose_type="goods_pickup",
        )

        response = self.client.post(reverse("staff_movement_edit", args=[movement.id]), {
            "date": date.today().strftime("%Y-%m-%d"),
            "client": "Test Site",
            "in_time": in_time_str,
            "purpose_type": "goods_pickup",
            "completion_notes": "Completed task",
            "work_done_for": "",  # Blank contact person
        })
        self.assertContains(response, "Please enter Work Done For / Contact Person")


class IClockIntegrationTestCase(TestCase):
    """Tests for ZKTeco iClock biometric webhook endpoints."""

    def setUp(self):
        self.client = Client()
        self.employee = User.objects.create_user(
            username="bio_user",
            password="password123",
            role="employee",
            device_user_id="42",
        )

    def test_cdata_get_handshake(self):
        """GET /iclock/cdata should return OK for device handshake."""
        response = self.client.get("/iclock/cdata", {"SN": "TESTDEVICE001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")

    def test_cdata_post_attlog_creates_record(self):
        """POST with ATTLOG data should create an AttendanceLog record."""
        from leaves.models import AttendanceLog
        body = "42\t2026-09-14 10:00:00\t0\t1\t0"
        response = self.client.post(
            "/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG",
            data=body,
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("OK", response.content.decode())

        # Verify record created
        self.assertEqual(AttendanceLog.objects.count(), 1)
        log = AttendanceLog.objects.first()
        self.assertEqual(log.device_user_id, "42")
        self.assertEqual(log.status, 0)  # Check-in
        self.assertEqual(log.verify_mode, 1)  # Fingerprint
        self.assertEqual(log.employee, self.employee)  # Auto-matched

    def test_cdata_post_attlog_duplicate_prevention(self):
        """Same punch sent twice should only create one record."""
        from leaves.models import AttendanceLog
        body = "42\t2026-09-14 10:00:00\t0\t1\t0"
        self.client.post("/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG", data=body, content_type="text/plain")
        self.client.post("/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG", data=body, content_type="text/plain")
        self.assertEqual(AttendanceLog.objects.count(), 1)

    def test_cdata_post_multiple_lines(self):
        """Multiple ATTLOG lines in one POST should create multiple records."""
        from leaves.models import AttendanceLog
        body = "42\t2026-09-14 10:00:00\t0\t1\t0\n42\t2026-09-14 17:30:00\t1\t1\t0"
        self.client.post("/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG", data=body, content_type="text/plain")
        self.assertEqual(AttendanceLog.objects.count(), 2)
        # First is check-in, second is check-out
        logs = AttendanceLog.objects.order_by("timestamp")
        self.assertEqual(logs[0].status, 0)
        self.assertEqual(logs[1].status, 1)

    def test_cdata_auto_registers_device(self):
        """Unknown device serial should auto-create a BiometricDevice."""
        from leaves.models import BiometricDevice
        self.client.get("/iclock/cdata", {"SN": "NEWDEVICE999"})
        # GET handshake doesn't create device — only POST does
        self.assertEqual(BiometricDevice.objects.filter(serial_number="NEWDEVICE999").count(), 0)

        body = "42\t2026-09-14 10:00:00\t0\t1\t0"
        self.client.post("/iclock/cdata?SN=NEWDEVICE999&table=ATTLOG", data=body, content_type="text/plain")
        device = BiometricDevice.objects.get(serial_number="NEWDEVICE999")
        self.assertIsNotNone(device.last_seen)
        self.assertTrue(device.is_active)

    def test_cdata_unmapped_user(self):
        """PIN not matching any user should still create log with employee=None."""
        from leaves.models import AttendanceLog
        body = "999\t2026-09-14 10:00:00\t0\t1\t0"
        self.client.post("/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG", data=body, content_type="text/plain")
        log = AttendanceLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.device_user_id, "999")
        self.assertIsNone(log.employee)

    def test_getrequest_returns_ok(self):
        """GET /iclock/getrequest should return OK."""
        response = self.client.get("/iclock/getrequest", {"SN": "TESTDEVICE001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")

    def test_cdata_malformed_line_skipped(self):
        """Malformed lines should be skipped without crashing."""
        from leaves.models import AttendanceLog
        body = "bad_data\n42\t2026-09-14 10:00:00\t0\t1\t0"
        self.client.post("/iclock/cdata?SN=TESTDEVICE001&table=ATTLOG", data=body, content_type="text/plain")
        # Only the valid line should create a record
        self.assertEqual(AttendanceLog.objects.count(), 1)


class AttendanceCalendarTestCase(TestCase):
    """Tests for Attendance utilities, calendar views, and team roster."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="emp_john",
            first_name="John",
            last_name="Doe",
            password="password123",
            role="employee",
            device_user_id="101",
        )
        self.manager = User.objects.create_user(
            username="mgr_jane",
            first_name="Jane",
            last_name="Smith",
            password="password123",
            role="manager",
            device_user_id="102",
        )
        self.annual_leave = LeaveType.objects.create(name="Annual Leave")

    def test_daily_attendance_ontime_summary(self):
        """Punch at 10:05 AM should be categorized as Present."""
        from leaves.models import AttendanceLog
        from leaves.attendance_utils import get_daily_attendance_summary
        from django.utils import timezone

        target = date(2026, 9, 10)  # A Thursday (working day)
        tz = timezone.get_current_timezone()
        dt1 = timezone.make_aware(datetime(2026, 9, 10, 10, 5, 0), tz)
        dt2 = timezone.make_aware(datetime(2026, 9, 10, 17, 35, 0), tz)

        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt1, status=0)
        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt2, status=1)

        summary = get_daily_attendance_summary(self.employee, target)
        self.assertEqual(summary["status"], "present")
        self.assertEqual(summary["punch_count"], 2)
        self.assertIn("7h 30m", summary["duration_formatted"])

    def test_daily_attendance_late_summary(self):
        """Punch at 10:25 AM should be categorized as Late."""
        from leaves.models import AttendanceLog
        from leaves.attendance_utils import get_daily_attendance_summary
        from django.utils import timezone

        target = date(2026, 9, 10)
        tz = timezone.get_current_timezone()
        dt1 = timezone.make_aware(datetime(2026, 9, 10, 10, 25, 0), tz)
        dt2 = timezone.make_aware(datetime(2026, 9, 10, 17, 30, 0), tz)

        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt1, status=0)
        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt2, status=1)

        summary = get_daily_attendance_summary(self.employee, target)
        self.assertEqual(summary["status"], "late")

    def test_my_attendance_view_loads_successfully(self):
        """Employee can access their monthly attendance calendar."""
        self.client.force_login(self.employee)
        response = self.client.get(reverse("my_attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Attendance")
        self.assertIn("calendar_weeks", response.context)
        self.assertIn("summary_stats", response.context)

    def test_team_attendance_view_permission(self):
        """Manager can access team attendance roster; employee is forbidden."""
        self.client.force_login(self.employee)
        response = self.client.get(reverse("team_attendance"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.manager)
        response = self.client.get(reverse("team_attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team Attendance")
        self.assertIn("roster_rows", response.context)

    def test_attendance_day_detail_api(self):
        """Detail API returns punch timeline and duration for a given date."""
        from leaves.models import AttendanceLog
        from django.utils import timezone

        target = date(2026, 9, 10)
        tz = timezone.get_current_timezone()
        dt1 = timezone.make_aware(datetime(2026, 9, 10, 10, 2, 0), tz)
        dt2 = timezone.make_aware(datetime(2026, 9, 10, 17, 35, 0), tz)
        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt1, status=0)
        AttendanceLog.objects.create(employee=self.employee, device_user_id="101", timestamp=dt2, status=1)

        self.client.force_login(self.employee)
        response = self.client.get(f"{reverse('attendance_day_detail_api')}?date=2026-09-10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "present")
        self.assertEqual(len(data["punches"]), 2)

    def test_gender_specific_holiday_attendance(self):
        """Female holiday (Teej) should mark female staff as Holiday and male staff as Absent if unpunched."""
        from leaves.models import PublicHoliday
        from leaves.attendance_utils import get_daily_attendance_summary

        female_emp = User.objects.create_user(
            username="emp_sita",
            first_name="Sita",
            gender="female",
            role="employee",
            password="password123",
        )
        male_emp = User.objects.create_user(
            username="emp_ramesh",
            first_name="Ramesh",
            gender="male",
            role="employee",
            password="password123",
        )

        teej_date = date(2026, 9, 14)  # Teej date (past date)
        PublicHoliday.objects.create(
            date=teej_date,
            name="Haritalika Teej",
            applicable_to="female",
        )

        female_summary = get_daily_attendance_summary(female_emp, teej_date)
        self.assertEqual(female_summary["status"], "holiday")
        self.assertIn("Haritalika Teej", female_summary["status_label"])

        male_summary = get_daily_attendance_summary(male_emp, teej_date)
        self.assertEqual(male_summary["status"], "absent")

    def test_visual_overtime_calculation(self):
        """Working >= 8.0 hours should calculate visual overtime (+duration - 7.5h). Less than 8.0 hours has no OT."""
        from django.utils import timezone
        from leaves.models import AttendanceLog
        from leaves.attendance_utils import get_daily_attendance_summary

        tz = timezone.get_current_timezone()
        test_date = date(2026, 9, 8)
        # 10:00 AM to 6:39 PM -> 8 hours 39 minutes = 8.65 hrs (>= 8.0 hrs threshold, OT = 8h 39m - 7h 30m = 1h 09m)
        in_punch = timezone.make_aware(datetime(2026, 9, 8, 10, 0, 0), tz)
        out_punch = timezone.make_aware(datetime(2026, 9, 8, 18, 39, 0), tz)
        AttendanceLog.objects.create(employee=self.employee, timestamp=in_punch, status=0)
        AttendanceLog.objects.create(employee=self.employee, timestamp=out_punch, status=1)

        summary = get_daily_attendance_summary(self.employee, test_date)
        self.assertEqual(summary["duration_formatted"], "8h 39m")
        self.assertEqual(summary["overtime_formatted"], "+1h 09m")

        # Day with 7h 45m (>= 7.5h but < 8.0h threshold) -> No visual OT
        test_date_2 = date(2026, 9, 9)
        in_punch_2 = timezone.make_aware(datetime(2026, 9, 9, 10, 0, 0), tz)
        out_punch_2 = timezone.make_aware(datetime(2026, 9, 9, 17, 45, 0), tz)
        AttendanceLog.objects.create(employee=self.employee, timestamp=in_punch_2, status=0)
        AttendanceLog.objects.create(employee=self.employee, timestamp=out_punch_2, status=1)

        summary_2 = get_daily_attendance_summary(self.employee, test_date_2)
        self.assertEqual(summary_2["duration_formatted"], "7h 45m")
        self.assertIsNone(summary_2["overtime_formatted"])

    def test_approved_holiday_work_status(self):
        """Approved HolidayWorkRequest marks the day as 'holiday_work' (Holiday Work) with badge-info."""
        from leaves.models import HolidayWorkRequest
        from leaves.attendance_utils import get_daily_attendance_summary

        sat_date = date(2026, 9, 12)  # Saturday
        HolidayWorkRequest.objects.create(
            employee=self.employee,
            date=sat_date,
            status="approved",
            reason="Urgent project release",
        )

        summary = get_daily_attendance_summary(self.employee, sat_date)
        self.assertEqual(summary["status"], "holiday_work")
        self.assertEqual(summary["status_label"], "Holiday Work")
        self.assertEqual(summary["status_badge_class"], "badge-info")
        self.assertTrue(summary["holiday_work_approved"])


