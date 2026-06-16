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

        return working_days

    @property
    def date_range(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime("%b %d")
        if self.start_date.month == self.end_date.month:
            return f"{self.start_date.strftime('%b %d')}–{self.end_date.strftime('%d')}"
        return f"{self.start_date.strftime('%b %d')} – {self.end_date.strftime('%b %d')}"


class LeaveBalance(models.Model):
    employee = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balance')

    total = models.FloatField(default=12)
    used = models.FloatField(default=0)

    def __str__(self):
        return f"{self.employee} – {self.used}/{self.total}"

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


class AttendanceRequest(BaseDayRequest):
    def __str__(self):
        return f"{self.employee.username} - Attendance {self.date}"


class HolidayWorkRequest(BaseDayRequest):
    def __str__(self):
        return f"{self.employee.username} - Holiday Work {self.date}"