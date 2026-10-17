import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Serve the archive-ingest flow on a Prefect schedule (default: daily at 06:00 "
            "Eastern). Runs until stopped. Needs a Prefect server: `uv run prefect server start`.")

    def add_arguments(self, parser):
        parser.add_argument("--cron", default="0 6 * * *", help="Cron schedule (default: 06:00 daily)")
        parser.add_argument("--timezone", default="America/New_York")
        parser.add_argument("--api-url", default=os.environ.get("PREFECT_API_URL",
                                                                 "http://127.0.0.1:4200/api"))

    def handle(self, cron, timezone, api_url, **options):
        import urllib.request

        # Schedules only fire on a persistent server, never on Prefect's temporary one
        os.environ["PREFECT_API_URL"] = api_url
        try:
            urllib.request.urlopen(f"{api_url}/health", timeout=3)
        except Exception:
            raise CommandError(f"No Prefect server at {api_url}. Start one: uv run prefect server start")

        from prefect.schedules import Cron

        from crew.ingest import archive_ingest

        self.stdout.write(f"Serving archive-ingest at {api_url} on {cron!r} ({timezone}). Ctrl-C to stop.")
        archive_ingest.serve(name="scheduled-archive-ingest", schedules=[Cron(cron, timezone=timezone)])
