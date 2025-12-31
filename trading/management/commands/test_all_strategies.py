"""
Management command to test all 14 strategies for suggestion generation.

Tests actual strategy logic (prepare context + generate via stream manager)
without needing HTTP/WebSocket complexity.

Usage:
    python manage.py test_all_strategies
    python manage.py test_all_strategies --email your@email.com --symbol SPY
    python manage.py test_all_strategies --verbose
"""

from datetime import datetime

from django.contrib.auth import get_user_model

from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from services.market_data.analysis import MarketAnalyzer
from services.strategies.factory import STRATEGY_DEFINITIONS, get_strategy

User = get_user_model()


class Command(AsyncCommand):
    help = "Test all strategies for suggestion generation"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)
        parser.add_argument(
            "--symbol",
            type=str,
            default="QQQ",
            help="Symbol to test with",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed logs",
        )

    async def async_handle(self, *args, **options):
        """Run the strategy tests."""
        # Suppress verbose logging unless --verbose flag provided
        if not options.get("verbose", False):
            import logging

            logging.getLogger("services").setLevel(logging.WARNING)
            logging.getLogger("streaming").setLevel(logging.WARNING)
            logging.getLogger("tastytrade").setLevel(logging.ERROR)
            logging.getLogger("httpx").setLevel(logging.ERROR)
            logging.getLogger("httpcore").setLevel(logging.ERROR)
            logging.getLogger("asyncio").setLevel(logging.WARNING)

        # Get user using utility function
        user = await aget_user_from_options(options, require_user=True)

        symbol = options["symbol"]
        self.stdout.write(f"Testing with user: {user.email}")
        self.stdout.write(f"Symbol: {symbol}")
        self.stdout.write(f"Total strategies: {len(STRATEGY_DEFINITIONS)}\n")

        # Run async tests
        await self.run_tests(user, symbol)

    async def run_tests(self, user, symbol):
        """Run tests for all strategies."""
        start_time = datetime.now()

        # Initialize streaming infrastructure
        from streaming.services.stream_manager import GlobalStreamManager

        stream_manager = await GlobalStreamManager.get_user_manager(user.id)

        self.stdout.write("=" * 80)
        self.stdout.write("Starting streaming infrastructure...")
        self.stdout.write("=" * 80)

        try:
            streaming_ready = await stream_manager.ensure_streaming_for_automation([symbol])

            if not streaming_ready:
                self.stdout.write(
                    self.style.ERROR("\nFailed to start streaming - cannot run tests\n")
                )
                return

            self.stdout.write(self.style.SUCCESS("Streaming ready\n"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nStreaming error: {e}\n"))
            return

        try:
            # Get market report once (shared by all strategies)
            analyzer = MarketAnalyzer(user)
            report = await analyzer.a_analyze_market_conditions(user, symbol, {})

            if not report.can_trade():
                self.stdout.write(
                    self.style.ERROR(
                        f"Cannot trade {symbol} - hard stops:\n"
                        f"{', '.join(report.no_trade_reasons)}\n"
                    )
                )
                return

            # Test each strategy
            results = []
            strategy_names = sorted(STRATEGY_DEFINITIONS.keys())

            self.stdout.write("=" * 80)
            self.stdout.write("Testing strategies...")
            self.stdout.write("=" * 80 + "\n")

            for idx, strategy_name in enumerate(strategy_names, 1):
                result = await self._test_strategy(
                    user, strategy_name, symbol, report, stream_manager, idx, len(strategy_names)
                )
                results.append(result)

            # Print summary
            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(results, elapsed)

        finally:
            # Cleanup
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write("Stopping streaming...")
            try:
                await stream_manager.stop_streaming()
                self.stdout.write(self.style.SUCCESS("Streaming stopped"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Error stopping: {e}"))
            self.stdout.write("=" * 80 + "\n")

    async def _test_strategy(self, user, strategy_name, symbol, report, stream_manager, idx, total):
        """Test a single strategy."""
        display_name = strategy_name.replace("_", " ").title()
        prefix = f"[{idx}/{total}] {display_name:<25}"

        try:
            # Get strategy instance
            strategy = get_strategy(strategy_name, user)

            # Prepare context
            context = await strategy.a_prepare_suggestion_context(
                symbol, report, suggestion_mode=True
            )

            if not context:
                error_msg = (
                    "Context preparation returned None (likely no suitable strikes/expirations)"
                )
                self.stdout.write(f"{prefix} {self.style.ERROR('[FAIL] FAIL')} - {error_msg}")
                return {"strategy": strategy_name, "passed": False, "error": error_msg}

            # Mark as automated
            context["is_automated"] = True
            context["suggestion_mode"] = True

            # Generate suggestion
            suggestion = await stream_manager.a_process_suggestion_request(context)

            if suggestion:
                self.stdout.write(f"{prefix} {self.style.SUCCESS('[OK] PASS')}")
                return {"strategy": strategy_name, "passed": True, "error": None}
            error_msg = "Stream manager returned None"
            self.stdout.write(f"{prefix} {self.style.ERROR('[FAIL] FAIL')} - {error_msg}")
            return {"strategy": strategy_name, "passed": False, "error": error_msg}

        except Exception as e:
            error_msg = str(e)
            self.stdout.write(f"{prefix} {self.style.ERROR('[FAIL] FAIL')} - {error_msg}")
            return {"strategy": strategy_name, "passed": False, "error": error_msg}

    def _print_summary(self, results, elapsed):
        """Print summary of test results."""
        passed = sum(1 for r in results if r["passed"])
        failed = sum(1 for r in results if not r["passed"])

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total:   {len(results)}")
        self.stdout.write(f"Passed:  {passed} {self.style.SUCCESS('[OK]')}")
        if failed > 0:
            self.stdout.write(f"Failed:  {failed} {self.style.ERROR('[FAIL]')}")
        self.stdout.write(f"Time:    {elapsed:.1f}s")

        # Show failed strategies
        if failed > 0:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.ERROR("FAILED STRATEGIES"))
            self.stdout.write("=" * 80)
            for r in results:
                if not r["passed"]:
                    display_name = r["strategy"].replace("_", " ").title()
                    self.stdout.write(f"{display_name:<25} {r['error']}")

        self.stdout.write("=" * 80 + "\n")
