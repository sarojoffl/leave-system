"""
Data migration: Backfill StaffMovementStop.in_time from parent StaffMovement.in_time.

Legacy records have in_time only on the parent movement, not on individual stops.
This copies the parent's in_time to all stops that are missing it.
"""
from django.db import migrations


def backfill_stop_in_time(apps, schema_editor):
    StaffMovement = apps.get_model("leaves", "StaffMovement")
    StaffMovementStop = apps.get_model("leaves", "StaffMovementStop")

    # Find all movements that have in_time set
    movements_with_in = StaffMovement.objects.filter(in_time__isnull=False)
    updated = 0
    for movement in movements_with_in:
        count = StaffMovementStop.objects.filter(
            movement=movement,
            in_time__isnull=True,
        ).update(in_time=movement.in_time)
        updated += count
    if updated:
        print(f"\n  Backfilled in_time on {updated} stop(s)")


def reverse_noop(apps, schema_editor):
    pass  # Cannot reliably reverse this


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0012_remove_staffmovement_problem_description_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_stop_in_time, reverse_noop),
    ]
