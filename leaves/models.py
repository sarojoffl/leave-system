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
    comp_off_paid = models.BooleanField(default=False)
    comp_off_paid_at = models.DateTimeField(null=True, blank=True)
    comp_off_paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="comp_off_marked_paid",
    )

    def __str__(self):
        return f"{self.employee.username} - Holiday Work {self.date}"


from datetime import time as time_cls


class StaffMovement(models.Model):
    PURPOSE_CHOICES = [
        ("problem_solving", "Problem solving"),
        ("amc", "AMC Support"),
        ("repair", "Repair / Service"),
        ("goods_bill_delivery", "Goods / bill delivery"),
        ("goods_pickup", "Goods pickup"),
        ("document_delivery", "Document delivery"),
        ("bank", "Bank visit"),
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
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="movements_logged_on_behalf",
        null=True,
        blank=True,
        help_text="Set when this record was submitted by someone other than the employee (e.g. logged on their behalf)."
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
        through="StaffMovementAssistant",
        related_name="assisted_movements",
        blank=True,
        help_text="Other staff who accompanied this movement"
    )
    is_cancelled = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True)
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
    def logged_on_behalf(self) -> bool:
        return self.logged_by_id is not None and self.logged_by_id != self.employee_id

    def _all_in_times(self):
        """[(display_name, in_time_or_None), ...] for primary + every assistant."""
        primary_name = self.employee.get_full_name() or self.employee.username
        result = [(primary_name, self.in_time)]
        for link in self.assistant_links.all():
            name = link.employee.get_full_name() or link.employee.username
            result.append((name, link.in_time))
        return result

    @property
    def uniform_in_time(self):
        """
        Returns the shared TimeField if EVERY participant (primary + assistants)
        has the exact same non-null in_time. Returns None otherwise.
        """
        times = [t for _, t in self._all_in_times()]
        if not times:
            return None
        first = times[0]
        if first is not None and all(t == first for t in times):
            return first
        return None

    @property
    def all_out(self) -> bool:
        return all(t is None for _, t in self._all_in_times())

    @property
    def in_time_groups(self):
        """
        Groups participants by their in_time value, so people who returned
        together show up on one line instead of repeating the same time.
        Returns [(time_or_None, [name1, name2, ...]), ...] sorted with
        filled times first (earliest first), "still out" (None) last.
        """
        groups = {}
        for name, t in self._all_in_times():
            groups.setdefault(t, []).append(name)

        return sorted(
            groups.items(),
            key=lambda kv: (kv[0] is None, kv[0] or time_cls.min)
        )

    @property
    def assistants_display(self) -> str:
        """Names only — the In Time column already shows per-person/grouped times."""
        names = [
            link.employee.get_full_name() or link.employee.username
            for link in self.assistant_links.all()
        ]
        return ", ".join(names) or "—"

    @classmethod
    def get_currently_out_employee_ids(cls, employee_ids, for_date):
        """
        Of the given employee ids, returns the subset who are already 'out'
        on an unresolved movement for for_date — either as primary
        (in_time null) or as an assistant on someone else's movement
        (their StaffMovementAssistant.in_time null).
        """
        employee_ids = list(employee_ids)
        if not employee_ids:
            return set()
        primary_out = cls.objects.filter(
            employee_id__in=employee_ids, in_time__isnull=True, date=for_date, is_cancelled=False
        ).values_list("employee_id", flat=True)
        assistant_out = StaffMovementAssistant.objects.filter(
            employee_id__in=employee_ids, in_time__isnull=True, movement__date=for_date, movement__is_cancelled=False
        ).values_list("employee_id", flat=True)
        return set(primary_out) | set(assistant_out)


class StaffMovementAssistant(models.Model):
    """Per-assistant return record. out_time is shared with the parent
    movement (everyone leaves together); in_time is individual since
    people can return separately."""
    movement = models.ForeignKey(StaffMovement, on_delete=models.CASCADE, related_name="assistant_links")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_movement_links")
    in_time = models.TimeField(null=True, blank=True)
    resolution_status = models.CharField(max_length=20, choices=StaffMovement.RESOLUTION_CHOICES, blank=True)
    completion_notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("movement", "employee")

    def __str__(self):
        return f"{self.employee.username} assisting movement #{self.movement_id}"