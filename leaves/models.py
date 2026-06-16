from django.db import models
from django.conf import settings


class LeaveType(models.Model):
    name = models.CharField(max_length=50)
    total_days = models.IntegerField()
    color = models.CharField(max_length=7, default="#4299e1", help_text="Hex color for balance bar")

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    DURATION_CHOICES = [
        ('full', 'Full Day(s)'),
        ('am', 'Half Day – Morning'),
        ('pm', 'Half Day – Afternoon'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)

    start_date = models.DateField()
    end_date = models.DateField()
    duration = models.CharField(max_length=10, choices=DURATION_CHOICES, default='full')
    reason = models.TextField()
    handover_to = models.CharField(max_length=150, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decision_note = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.username} - {self.leave_type.name}"

    @property
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
            
        if self.duration in ('am', 'pm'):
            return 0.5 if working_days > 0 else 0.0
            
        return working_days

    @property
    def date_range(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime("%b %d")
        if self.start_date.month == self.end_date.month:
            return f"{self.start_date.strftime('%b %d')}–{self.end_date.strftime('%d')}"
        return f"{self.start_date.strftime('%b %d')} – {self.end_date.strftime('%b %d')}"


class LeaveBalance(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)

    total = models.FloatField(default=0)
    used = models.FloatField(default=0)

    class Meta:
        unique_together = ('employee', 'leave_type')

    def __str__(self):
        return f"{self.employee} – {self.leave_type}: {self.used}/{self.total}"

    @property
    def remaining(self):
        return max(self.total - self.used, 0)

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