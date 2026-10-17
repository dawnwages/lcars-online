from django.core.management.base import BaseCommand

from missions.models import Snapshot


class Command(BaseCommand):
    help = "Fetch the NASA Exoplanet Archive now and record a Snapshot (a Prefect flow run)."

    def handle(self, **options):
        from crew.ingest import archive_ingest

        snap = Snapshot.objects.get(pk=archive_ingest())
        changes = snap.changes or {}
        self.stdout.write(f"{snap}: +{changes.get('added', 0)} new, -{changes.get('removed', 0)} "
                          f"removed, {changes.get('revised', 0)} revised")
