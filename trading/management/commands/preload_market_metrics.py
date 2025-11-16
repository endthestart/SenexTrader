import asyncio

from tqdm import tqdm

from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from services.market_data.service import MarketDataService


class Command(AsyncCommand):
    help = "Preload current market metrics (IV Rank, IV Percentile)"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)
        parser.add_argument("--symbols", nargs="+", default=["QQQ", "SPY"])
        parser.add_argument("--delay", type=float, default=1.0)

    async def async_handle(self, *args, **options):
        symbols = options["symbols"]
        delay = options["delay"]

        # Get user using utility function
        user = await aget_user_from_options(options, require_user=True)

        self.stdout.write(f"Preloading market metrics for {len(symbols)} symbols...")
        self.stdout.write(f"Using user: {user.email}")
        self.stdout.write(self.style.WARNING("Note: TastyTrade API provides current metrics only."))

        await self._preload_current_metrics(user, symbols, delay)

    async def _preload_current_metrics(self, user, symbols, delay):
        service = MarketDataService(user=user)

        for symbol in tqdm(symbols, desc="Loading metrics"):
            try:
                metrics = await service.get_market_metrics(symbol)
                if metrics and metrics.get("iv_rank") is not None:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {symbol}: IV Rank {metrics['iv_rank']:.2f}")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"✗ {symbol}: Failed to fetch metrics or IV Rank is null.")
                    )
                await asyncio.sleep(delay)  # Rate limiting
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ {symbol}: {e}"))
