from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from leaves.models import LeaveType, LeaveBalance


class Command(BaseCommand):
    help = "Create missing LeaveBalance rows for every user/leave-type combination."

    def handle(self, *args, **options):
        UserModel = apps.get_model(settings.AUTH_USER_MODEL)

        users = list(UserModel.objects.all())
        leave_types = list(LeaveType.objects.all())

        existing = set(
            LeaveBalance.objects.values_list("employee_id", "leave_type_id")
        )

        to_create = []
        for user in users:
            for lt in leave_types:
                if (user.id, lt.id) not in existing:
                    to_create.append(
                        LeaveBalance(employee=user, leave_type=lt, total=lt.total_days, used=0)
                    )

        if to_create:
            LeaveBalance.objects.bulk_create(to_create)
            self.stdout.write(self.style.SUCCESS(f"Created {len(to_create)} leave balance row(s)."))
        else:
            self.stdout.write("Nothing to do — all balances already exist.")