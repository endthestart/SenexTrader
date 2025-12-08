"""
Management command to pre-load historical data from Stooq
Usage: python manage.py preload_historical --symbols SPY QQQ IWM --days 90

SIMPLICITY FIRST: Simple sync command using the sync HistoricalDataProvider
"""

from django.core.management.base import BaseCommand

from tqdm import tqdm

from services.market_data.historical import HistoricalDataProvider
from trading.models import HistoricalPrice


class Command(BaseCommand):
    help = "Pre-load historical data from Stooq for specified symbols"

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols",
            nargs="+",
            default=["SPY", "QQQ", "IWM", "IBIT", "XLF"],
            help="Symbols to pre-load (default: SPY QQQ IWM IBIT XLF)",
        )
        parser.add_argument(
            "--days", type=int, default=90, help="Number of days to pre-load (default: 90)"
        )
        parser.add_argument(
            "--force", action="store_true", help="Force re-download even if data exists"
        )
        parser.add_argument(
            "--resume", action="store_true", help="Skip symbols that already have sufficient data"
        )
        parser.add_argument(
            "--progress", action="store_true", default=True, help="Show progress bar"
        )

    def handle(self, *args, **options):
        symbols = options["symbols"]
        days = options["days"]
        force = options["force"]

        if force and options["resume"]:
            self.stdout.write(self.style.ERROR("Cannot use --force and --resume together."))
            return

        if force:
            self.stdout.write(self.style.WARNING("Force option enabled: clearing existing data..."))
            for symbol in symbols:
                deleted_count, _ = HistoricalPrice.objects.filter(symbol=symbol).delete()
                if deleted_count > 0:
                    self.stdout.write(f"Cleared {deleted_count} existing records for {symbol}")

        # Resume capability
        if options["resume"]:
            completed_symbols = self._get_completed_symbols(symbols, days)
            if completed_symbols:
                completed_str = ", ".join(completed_symbols)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Resuming... skipping {len(completed_symbols)} "
                        f"already completed symbols: {completed_str}"
                    )
                )
                symbols = [s for s in symbols if s not in completed_symbols]

        if not symbols:
            self.stdout.write(self.style.SUCCESS("All symbols are already up to date."))
            return

        self.stdout.write(f"Pre-loading {days} days of historical data for: {', '.join(symbols)}")

        provider = HistoricalDataProvider()

        # Progress bar
        iterator = tqdm(symbols, desc="Loading symbols") if options["progress"] else symbols

        results = {}
        for symbol in iterator:
            try:
                price_data = provider.fetch_historical_prices(symbol, days)
                if price_data:
                    stored_count = provider.store_in_database(symbol, price_data)
                    results[symbol] = stored_count
                else:
                    results[symbol] = 0
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[FAIL] {symbol}: {e}"))
                results[symbol] = 0
                if not options["resume"]:
                    raise  # Fail fast if not in resume mode

        # Report results
        total_records = sum(results.values())
        for symbol, count in results.items():
            if count > 0:
                self.stdout.write(self.style.SUCCESS(f"[OK] {symbol}: {count} records stored"))
            else:
                self.stdout.write(self.style.ERROR(f"[FAIL] {symbol}: Failed to load data"))

        self.stdout.write(
            self.style.SUCCESS(f"\nTotal: {total_records} historical records pre-loaded")
        )

        # Show data availability summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("Data Availability Summary:")
        self.stdout.write("=" * 50)

        # Use configured minimum from settings (default 90 days for full analysis)
        # Apply 5% tolerance to account for weekends/holidays
        from django.conf import settings

        min_days = getattr(settings, "MINIMUM_HISTORICAL_DAYS", 20)
        min_acceptable = int(min_days * 0.95)  # 5% tolerance

        for symbol in options["symbols"]:  # show all symbols from original list
            count = HistoricalPrice.objects.filter(symbol=symbol).count()
            if count >= min_acceptable:
                status = self.style.SUCCESS(f"[OK] {symbol}: {count} days (sufficient)")
            else:
                status = self.style.WARNING(
                    f"⚠ {symbol}: {count} days (need {min_acceptable}+ for analysis)"
                )
            self.stdout.write(status)

    def _get_completed_symbols(self, symbols, days):
        """Check which symbols already have sufficient data.
        Uses 5% tolerance to account for weekends/holidays."""
        completed = []
        min_acceptable = int(days * 0.95)  # 5% tolerance
        for symbol in symbols:
            count = HistoricalPrice.objects.filter(symbol=symbol).count()
            if count >= min_acceptable:
                completed.append(symbol)
        return completed
