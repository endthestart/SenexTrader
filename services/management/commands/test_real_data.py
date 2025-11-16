"""
Management command to test real data implementation.

Run with: python manage.py test_real_data
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.management.utils import (
    AsyncCommand,
    add_user_arguments,
    aget_user_from_options,
    configure_command_logging,
)
from services.market_data.analysis import MarketAnalyzer
from services.market_data.option_chains import (
    OptionChainService,
    extract_call_strikes,
    extract_put_strikes,
)
from services.market_data.service import MarketDataService

User = get_user_model()


class Command(AsyncCommand):
    help = "Test real data implementation with cache cleared"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)
        parser.add_argument(
            "--symbol",
            type=str,
            default="SPY",
            help="Symbol to test (default: SPY)",
        )
        parser.add_argument(
            "--skip-cache-clear",
            action="store_true",
            help="Skip clearing the cache",
        )

    async def async_handle(self, *args, **options):
        """Run the real data tests."""
        configure_command_logging(options)

        symbol = options["symbol"]

        # Clear cache unless skipped
        if not options["skip_cache_clear"]:
            await sync_to_async(cache.clear)()
            self.stdout.write(self.style.SUCCESS("✓ Cache cleared"))

        # Get user using utility function
        user = await aget_user_from_options(options, require_user=True)

        self.stdout.write(f"Testing with user: {user.email}")

        # Check for TastyTrade account
        account = await sync_to_async(
            TradingAccount.objects.filter(
                user=user, connection_type="TASTYTRADE", is_primary=True
            ).first
        )()

        if not account:
            self.stdout.write(
                self.style.WARNING(
                    "User has no primary TastyTrade account. " "Some tests will be limited."
                )
            )
        else:
            self.stdout.write(f"✓ Found TastyTrade account: {account.account_number}")

        # Run async tests
        await self.run_tests(user, symbol)

    async def run_tests(self, user, symbol):
        """Run all async tests."""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("REAL DATA IMPLEMENTATION TEST")
        self.stdout.write("=" * 60 + "\n")

        # Test 1: MarketDataService
        await self.test_market_data_service(user, symbol)

        # Test 2: MarketAnalyzer
        self.test_market_analyzer(symbol)

        # Test 3: OptionChainService
        await self.test_option_chain_service(user, symbol)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("✓ All tests completed"))
        self.stdout.write("=" * 60)

    async def test_market_data_service(self, user, symbol):
        """Test MarketDataService."""
        self.stdout.write("\n--- Testing MarketDataService ---")

        market_service = MarketDataService(user=user)

        # Test quote fetching
        self.stdout.write(f"\n1. Fetching quote for {symbol}...")
        quote = await market_service.get_quote(symbol)

        if quote:
            self.stdout.write(
                self.style.SUCCESS(f"✓ Quote fetched from {quote.get('source', 'unknown')}")
            )
            self.stdout.write(
                f"  Bid: {quote.get('bid')}, Ask: {quote.get('ask')}, " f"Last: {quote.get('last')}"
            )

            # Check source
            if quote.get("source") == "tastytrade_api":
                self.stdout.write(self.style.SUCCESS("✓ Data from REAL API"))
            elif quote.get("source") == "cache":
                self.stdout.write("  Data from cache (previously fetched from API)")
        else:
            self.stdout.write(self.style.WARNING("⚠ No quote data available"))

        # Test option chain fetching using OptionChainService
        self.stdout.write(f"\n2. Fetching option chain for {symbol}...")
        option_chain_service = OptionChainService()
        option_chain = await option_chain_service.get_option_chain(user, symbol, target_dte=45)

        if option_chain:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Option chain fetched from " f"{option_chain.get('source', 'unknown')}"
                )
            )
            self.stdout.write(f"  Expiration: {option_chain.get('expiration')}")
            strikes_list = option_chain.get("strikes", [])
            put_strikes = sorted(extract_put_strikes(strikes_list))
            call_strikes = sorted(extract_call_strikes(strikes_list))
            self.stdout.write(f"  Put strikes: {len(put_strikes)}")
            self.stdout.write(f"  Call strikes: {len(call_strikes)}")

            # Verify it's not mock data
            if len(put_strikes) == 41 and all(float(s) % 2 == 0 for s in put_strikes):
                self.stdout.write(
                    self.style.ERROR(
                        "✗ WARNING: This looks like MOCK DATA " "(exactly 41 even strikes)!"
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("✓ Confirmed REAL option chain"))
        else:
            self.stdout.write(
                self.style.WARNING("⚠ Option chain unavailable (check TastyTrade credentials)")
            )

        # Test market metrics
        self.stdout.write(f"\n3. Fetching market metrics for {symbol}...")
        metrics = await market_service.get_market_metrics(symbol)

        if metrics:
            self.stdout.write(
                self.style.SUCCESS(f"✓ Metrics fetched from {metrics.get('source', 'unknown')}")
            )
            if metrics.get("iv30"):
                self.stdout.write(f"  IV30: {metrics.get('iv30')}")
            if metrics.get("iv_rank"):
                self.stdout.write(f"  IV Rank: {metrics.get('iv_rank')}")
        else:
            self.stdout.write(
                self.style.WARNING("⚠ Market metrics unavailable (may need streaming data)")
            )

    def test_market_analyzer(self, symbol):
        """Test MarketAnalyzer."""
        self.stdout.write("\n--- Testing MarketAnalyzer ---")

        analyzer = MarketAnalyzer()

        # Test market conditions
        self.stdout.write(f"\n1. Getting market conditions for {symbol}...")
        conditions = analyzer.get_market_conditions(symbol)

        if conditions.get("data_available"):
            self.stdout.write(self.style.SUCCESS("✓ Market conditions retrieved"))

            bollinger = conditions.get("bollinger_bands", {})
            if bollinger.get("current_price"):
                self.stdout.write(f"  Current price: ${bollinger.get('current_price'):.2f}")
                self.stdout.write(f"  Bollinger position: {bollinger.get('position')}")

            self.stdout.write(f"  Is range bound: {conditions.get('is_range_bound')}")
            self.stdout.write(f"  Is stressed: {conditions.get('is_stressed')}")

            if conditions.get("iv_rank"):
                self.stdout.write(f"  IV Rank: {conditions.get('iv_rank')}")
        else:
            self.stdout.write(
                self.style.WARNING("⚠ Limited data (will fetch from API if configured)")
            )

        # Test real-time Bollinger Bands
        self.stdout.write(f"\n2. Calculating real-time Bollinger Bands for {symbol}...")
        bands = analyzer.calculate_bollinger_bands_realtime(symbol)

        if bands.get("current"):
            self.stdout.write(self.style.SUCCESS("✓ Bollinger Bands calculated"))
            self.stdout.write(f"  Upper: ${bands.get('upper'):.2f}")
            self.stdout.write(f"  Middle: ${bands.get('middle'):.2f}")
            self.stdout.write(f"  Lower: ${bands.get('lower'):.2f}")
            self.stdout.write(f"  Current: ${bands.get('current'):.2f}")
            self.stdout.write(f"  Position: {bands.get('position')}")
        else:
            self.stdout.write(self.style.WARNING("⚠ Cannot calculate (needs historical data)"))

    async def test_option_chain_service(self, user, symbol):
        """Test OptionChainService."""
        self.stdout.write("\n--- Testing OptionChainService ---")

        service = OptionChainService()

        # Test fetching option chain
        self.stdout.write(f"\n1. Fetching option chain for {symbol} (45 DTE)...")
        chain_data = await service.get_option_chain(user, symbol, 45)

        if chain_data:
            self.stdout.write(self.style.SUCCESS("✓ Option chain fetched"))
            self.stdout.write(f"  Symbol: {chain_data.get('symbol')}")
            self.stdout.write(f"  Expiration: {chain_data.get('expiration')}")

            strikes_list = chain_data.get("strikes", [])
            put_strikes = sorted(extract_put_strikes(strikes_list))
            call_strikes = sorted(extract_call_strikes(strikes_list))

            self.stdout.write(f"  Put strikes: {len(put_strikes)}")
            self.stdout.write(f"  Call strikes: {len(call_strikes)}")

            if chain_data.get("source") == "tastytrade_api":
                self.stdout.write(self.style.SUCCESS("✓ From TastyTrade API"))

            # Check for mock data pattern
            if len(put_strikes) == 41 and all(float(s) % 2 == 0 for s in put_strikes):
                self.stdout.write(self.style.ERROR("✗ ERROR: This appears to be MOCK DATA!"))
            else:
                self.stdout.write(self.style.SUCCESS("✓ Confirmed REAL option chain data"))

                # Show sample strikes
                if put_strikes:
                    self.stdout.write(f"  Sample put strikes: {list(put_strikes)[:5]}...")
        else:
            self.stdout.write(
                self.style.WARNING("⚠ Could not fetch option chain (check credentials)")
            )
