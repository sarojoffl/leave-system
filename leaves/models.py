from django.utils.functional import cached_property
from django.db import models
from django.conf import settings


class LeaveType(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)

    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decision_note = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.username} - {self.leave_type.name}"

    @cached_property
    def days(self):
        import datetime
        from django.apps import apps
        PublicHolidayModel = apps.get_model('leaves', 'PublicHoliday')

        holidays = set(
            PublicHolidayModel.objects.filter(
                date__range=(self.start_date, self.end_date)
            ).values_list('date', flat=True)
        )

        current = self.start_date
        working_days = 0
        while current <= self.end_date:
            if current.weekday() != 5 and current not in holidays:
                working_days += 1
            current += datetime.timedelta(days=1)

        return working_days

    @property
    def date_range(self) -> str:
        from leaves.bs_convert import ad_to_bs, bs_month_name
        bs_y1, bs_m1, bs_d1 = ad_to_bs(self.start_date)
        if self.start_date == self.end_date:
            return f"{bs_month_name(bs_m1)} {bs_d1}, {bs_y1}"
        bs_y2, bs_m2, bs_d2 = ad_to_bs(self.end_date)
        if bs_m1 == bs_m2 and bs_y1 == bs_y2:
            return f"{bs_month_name(bs_m1)} {bs_d1}–{bs_d2}, {bs_y1}"
        return f"{bs_month_name(bs_m1)} {bs_d1}, {bs_y1} – {bs_month_name(bs_m2)} {bs_d2}, {bs_y2}"


class LeaveBalance(models.Model):
    employee = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balance')

    total = models.FloatField(default=12)
    used = models.FloatField(default=0)

    def __str__(self):
        return f"{self.employee} – {self.used}/{self.total}"

    @property
    def remaining(self):
        return self.total - self.used

    @property
    def percent(self):
        if self.total <= 0:
            return 0
        return min(round((self.used / self.total) * 100), 100)


class PublicHoliday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.date}: {self.name}"


class BaseDayRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(class)s_requests'
    )
    date = models.DateField()
    reason = models.TextField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decision_note = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    @property
    def date_bs(self) -> str:
        from leaves.bs_convert import ad_to_bs_display
        return ad_to_bs_display(self.date)


class AttendanceRequest(BaseDayRequest):
    def __str__(self):
        return f"{self.employee.username} - Attendance {self.date}"


class HolidayWorkRequest(BaseDayRequest):
    def __str__(self):
        return f"{self.employee.username} - Holiday Work {self.date}"


class StaffMovement(models.Model):
    PURPOSE_CHOICES = [
        ("problem_solving", "Problem solving"),
        ("goods_bill_delivery", "Goods / bill delivery"),
        ("goods_pickup", "Goods pickup"),
    ]
    RESOLUTION_CHOICES = [
        ("solved", "Solved"),
        ("not_solved", "Not solved"),
    ]

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_movements"
    )
    date = models.DateField()
    client = models.CharField(max_length=200)
    out_time = models.TimeField()
    in_time = models.TimeField(null=True, blank=True)
    purpose_type = models.CharField(max_length=30, choices=PURPOSE_CHOICES, blank=True)
    purpose = models.TextField(blank=True)
    problem_description = models.TextField(blank=True)
    resolution_status = models.CharField(max_length=20, choices=RESOLUTION_CHOICES, blank=True)
    completion_notes = models.TextField(blank=True)
    assistants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="assisted_movements",
        blank=True,
        help_text="Other staff who accompanied this movement"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-out_time"]

    def __str__(self):
        return f"{self.employee.username} - {self.client} on {self.date}"

    @property
    def date_bs(self) -> str:
        from leaves.bs_convert import ad_to_bs_display
        return ad_to_bs_display(self.date)

    @property
    def assistants_display(self) -> str:
        return ", ".join(
            a.get_full_name() or a.username for a in self.assistants.all()
        ) or "—"
