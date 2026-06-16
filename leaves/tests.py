from datetime import date
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
            name="Annual Leave",
            total_days=10,
            color="#ff0000"
        )
        
        # Note: Signals create LeaveBalance for existing users when LeaveType is created.
        # Let's verify and grab it
        self.balance = LeaveBalance.objects.get(employee=self.employee, leave_type=self.annual_leave)
        
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
            duration="full",
            reason="Vacation"
        )
        self.assertEqual(req.days, 3.0)

    def test_overlapping_leave_validation(self):
        """
        Verify that we cannot apply for leaves that overlap existing ones.
        """
        self.client.login(username="employee", password="password123")
        
        # Apply for leave June 22 to June 23 (2 working days)
        response1 = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": "2026-06-22",
            "to_date": "2026-06-23",
            "duration": "full",
            "reason": "First request"
        })
        self.assertRedirects(response1, reverse("my_leaves"))
        self.assertTrue(LeaveRequest.objects.filter(employee=self.employee, reason="First request").exists())
        
        # Try to apply for overlapping leave June 23 to June 24
        response2 = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": "2026-06-23",
            "to_date": "2026-06-24",
            "duration": "full",
            "reason": "Overlapping request"
        })
        # Overlapping should cause validation failure and not redirect
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(LeaveRequest.objects.filter(employee=self.employee, reason="Overlapping request").exists())

    def test_insufficient_balance_validation(self):
        """
        Verify that an employee cannot request more leave than they have available.
        """
        self.client.login(username="employee", password="password123")
        
        # Employee has 10 days total balance. Let's request 12 working days.
        # June 15 to June 28 (14 calendar days)
        # Weekends (Saturdays): June 20, June 27 (2 Saturdays)
        # Working days = 12. Exceeds 10 days balance.
        response = self.client.post(reverse("apply_leave"), {
            "leave_type": self.annual_leave.id,
            "from_date": "2026-06-15",
            "to_date": "2026-06-28",
            "duration": "full",
            "reason": "Too long"
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeaveRequest.objects.filter(employee=self.employee, reason="Too long").exists())

    def test_approve_blocks_insufficient_balance(self):
        """
        Verify that a manager cannot approve a leave request if the employee's balance has become insufficient.
        """
        # Create request for 6 days
        req1 = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 21), # 7 calendar days, 1 Sat (20) -> 6 working days
            duration="full",
            reason="First"
        )
        # Create another request for 6 days
        req2 = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 22),
            end_date=date(2026, 6, 28), # 7 calendar days, 1 Sat (27) -> 6 working days
            duration="full",
            reason="Second"
        )
        
        # Log in as manager to approve
        self.client.login(username="manager", password="password123")
        
        # Approve first (succeeds)
        self.client.post(reverse("approve_leave", args=[req1.id]))
        req1.refresh_from_db()
        self.assertEqual(req1.status, "approved")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.used, 5.0)
        
        # Try to approve second (fails since only 5 days remain but request is 6)
        response = self.client.post(reverse("approve_leave", args=[req2.id]))
        req2.refresh_from_db()
        self.assertEqual(req2.status, "pending") # Status unchanged

    def test_cancel_approved_leave_refunds_balance(self):
        """
        Verify that cancelling an approved leave request refunds the employee's balance.
        """
        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 22),
            end_date=date(2026, 6, 25), # 4 working days (no Saturdays)
            duration="full",
            reason="Cancel test",
            status="approved"
        )
        # Setup balance used
        self.balance.used = 4.0
        self.balance.save()
        
        # Login as employee to cancel
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
        """
        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=self.annual_leave,
            start_date=date(2026, 6, 22),
            end_date=date(2026, 6, 25), # 4 working days
            duration="full",
            reason="Revoke test",
            status="approved"
        )
        self.balance.used = 4.0
        self.balance.save()
        
        # Login as manager to revoke
        self.client.login(username="manager", password="password123")
        
        response = self.client.post(reverse("reject_leave", args=[req.id]))
        self.assertRedirects(response, reverse("approvals"))
        
        req.refresh_from_db()
        self.assertEqual(req.status, "rejected")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.used, 0.0)
