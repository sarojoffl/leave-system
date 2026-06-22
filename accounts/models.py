from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = (
        ('employee', 'Employee'),
        ('manager', 'Manager'),
        ('system_admin', 'System Administrator'),
        ('ceo', 'CEO'),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    department = models.CharField(max_length=100, blank=True, null=True)
    position = models.CharField(max_length=100, blank=True, null=True)
    must_change_password = models.BooleanField(default=False)

    @property
    def initials(self):
        name = self.get_full_name() or self.username
        parts = name.split()[:2]
        return "".join(p[0] for p in parts).upper() or "U"

    @property
    def has_management_access(self):
        return self.role in ('manager', 'system_admin', 'ceo')