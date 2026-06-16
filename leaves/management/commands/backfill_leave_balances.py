from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from leaves.models import LeaveBalance


class Command(BaseCommand):
    help = "Create missing LeaveBalance rows and optionally reset all balances for a new fiscal year."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset used=0 and total=12 for ALL employees (run at fiscal year start).',
        )
        parser.add_argument(
            '--total',
            type=float,
            default=12,
            help='Annual leave total to set when resetting (default: 12).',
        )

    def handle(self, *args, **options):
        UserModel = apps.get_model(settings.AUTH_USER_MODEL)

        # ── Reset existing balances if --reset flag passed ──
        if options['reset']:
            updated = LeaveBalance.objects.update(used=0, total=options['total'])
            self.stdout.write(self.style.SUCCESS(
                f"✓ Reset {updated} balance(s) → used=0, total={options['total']}."
            ))

        # ── Create missing rows for new employees ──
        users    = list(UserModel.objects.all())
        existing = set(LeaveBalance.objects.values_list("employee_id", flat=True))

        to_create = [
            LeaveBalance(employee=user, total=options['total'], used=0)
            for user in users
            if user.id not in existing
        ]

        if to_create:
            LeaveBalance.objects.bulk_create(to_create)
            self.stdout.write(self.style.SUCCESS(
                f"✓ Created {len(to_create)} missing balance row(s)."
            ))
        else:
            self.stdout.write("Nothing to create — all balances already exist.")