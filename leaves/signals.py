from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LeaveType, LeaveBalance


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_leave_balances_for_new_user(sender, instance, created, **kwargs):
    """
    When a new user is created, give them a LeaveBalance row for every
    existing LeaveType, seeded with that type's total_days.
    """
    if not created:
        return

    existing = set(
        LeaveBalance.objects.filter(employee=instance).values_list("leave_type_id", flat=True)
    )

    new_balances = [
        LeaveBalance(employee=instance, leave_type=lt, total=lt.total_days, used=0)
        for lt in LeaveType.objects.all()
        if lt.id not in existing
    ]

    if new_balances:
        LeaveBalance.objects.bulk_create(new_balances)

@receiver(post_save, sender=LeaveType)
def create_balances_for_new_leave_type(sender, instance, created, **kwargs):
    """
    When a new LeaveType is created, give every existing user a
    LeaveBalance row for it.
    """
    if not created:
        return

    User = settings.AUTH_USER_MODEL
    from django.apps import apps
    UserModel = apps.get_model(User)

    existing = set(
        LeaveBalance.objects.filter(leave_type=instance).values_list("employee_id", flat=True)
    )

    new_balances = [
        LeaveBalance(employee=user, leave_type=instance, total=instance.total_days, used=0)
        for user in UserModel.objects.all()
        if user.id not in existing
    ]

    if new_balances:
        LeaveBalance.objects.bulk_create(new_balances)