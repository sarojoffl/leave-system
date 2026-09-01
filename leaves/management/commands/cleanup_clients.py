from django.core.management.base import BaseCommand
from leaves.models import StaffMovement, StaffMovementStop


class Command(BaseCommand):
    help = "List unique client names or safely rename legacy client name variations in Staff Movement records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all unique client names currently in database with their occurrence count.",
        )
        parser.add_argument(
            "--old",
            type=str,
            help="The legacy/misspelled client name to replace.",
        )
        parser.add_argument(
            "--new",
            type=str,
            help="The standardized clean client name.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview records that will be changed without making any actual database edits.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if options["list"]:
            self.stdout.write(self.style.MIGRATE_HEADING("=== Current Unique Client Names in Database ==="))
            counts = {}

            # Count in StaffMovementStop
            for c in StaffMovementStop.objects.values_list("client", flat=True):
                if c:
                    name = c.strip()
                    counts[name] = counts.get(name, 0) + 1

            # Count in StaffMovement
            for c in StaffMovement.objects.values_list("client", flat=True):
                if c:
                    for part in c.split(","):
                        name = part.strip()
                        if name:
                            counts[name] = counts.get(name, 0) + 1

            if not counts:
                self.stdout.write("No client records found.")
                return

            sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
            for name, count in sorted_counts:
                self.stdout.write(f"  • {name} ({count} occurrence{'s' if count != 1 else ''})")
            return

        old_name = options.get("old")
        new_name = options.get("new")

        if not old_name or not new_name:
            self.stdout.write(self.style.ERROR("Error: Please provide both --old and --new arguments."))
            self.stdout.write("Usage examples:")
            self.stdout.write('  1. Dry-run preview: python manage.py cleanup_clients --old "ABC Tech" --new "ABC Tech Office" --dry-run')
            self.stdout.write('  2. Live cleanup:    python manage.py cleanup_clients --old "ABC Tech" --new "ABC Tech Office"')
            self.stdout.write('  3. List clients:    python manage.py cleanup_clients --list')
            return

        old_clean = old_name.strip()
        new_clean = new_name.strip()

        matching_stops = list(StaffMovementStop.objects.filter(client__iexact=old_clean).select_related("movement__employee"))
        matching_movements = []

        for m in StaffMovement.objects.filter(client__icontains=old_clean).select_related("employee"):
            parts = [p.strip() for p in m.client.split(",")]
            new_parts = [new_clean if p.lower() == old_clean.lower() else p for p in parts]
            updated_client = " , ".join(new_parts)
            if updated_client != m.client:
                matching_movements.append((m, updated_client))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"=== [DRY-RUN] Preview for '{old_clean}' → '{new_clean}' ==="))
            self.stdout.write(f"Destination stops to update ({len(matching_stops)}):")
            for s in matching_stops:
                emp_name = s.movement.employee.get_full_name() or s.movement.employee.username
                self.stdout.write(f"  • Stop ID #{s.id} (Date: {s.movement.date}, Staff: {emp_name}): '{s.client}' → '{new_clean}'")

            self.stdout.write(f"\nParent movement records to update ({len(matching_movements)}):")
            for m, new_c in matching_movements:
                emp_name = m.employee.get_full_name() or m.employee.username
                self.stdout.write(f"  • Movement ID #{m.id} (Date: {m.date}, Staff: {emp_name}): '{m.client}' → '{new_c}'")

            self.stdout.write(self.style.NOTICE("\n[DRY-RUN] No changes were made to the database."))
            return

        # Perform actual database updates
        stops_updated = StaffMovementStop.objects.filter(client__iexact=old_clean).update(client=new_clean)
        movements_updated = 0
        for m, new_c in matching_movements:
            m.client = new_c
            m.save()
            movements_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Renamed '{old_clean}' → '{new_clean}'\n"
                f"  - Updated {stops_updated} destination stop(s)\n"
                f"  - Updated {movements_updated} movement record(s)"
            )
        )
