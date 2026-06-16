from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LeaveBalance


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_leave_balance_for_new_user(sender, instance, created, **kwargs):
    """
    When a new user is created, give them a single LeaveBalance of 12 days.
    """
    if not created:
        return

    LeaveBalance.objects.get_or_create(
        employee=instance,
        defaults={"total": 12, "used": 0},
    )