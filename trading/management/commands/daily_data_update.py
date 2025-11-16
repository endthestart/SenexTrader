from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone


class Command(BaseCommand):
    help = "Daily data update orchestrator (run via cron)"

    def handle(self, *args, **options):
        start_time = dj_timezone.now()
        self.stdout.write(self.style.SUCCESS(f"Starting daily data update at {start_time}"))

        # 1. Update OHLC data (incremental)
        self.stdout.write("\n=== Updating OHLC Data ===")
        call_command("preload_historical", days=5, resume=True)

        # 2. Update market metrics (current only)
        self.stdout.write("\n=== Updating Market Metrics ===")
        call_command("preload_market_metrics")

        end_time = dj_timezone.now()
        duration = (end_time - start_time).total_seconds()
        self.stdout.write(self.style.SUCCESS(f"\nDaily update completed in {duration:.1f}s"))
