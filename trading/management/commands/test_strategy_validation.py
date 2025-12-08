"""
Management command to comprehensively test credit spread strategies against multiple equities.

This command validates strategy functionality by:
1. Generating market indicators for each equity
2. Scoring 2 credit spread strategies (Bull Put Spread, Bear Call Spread)
3. Attempting to generate suggestions for viable strategies (score >= 30)
4. Using fallback DTE ranges (30-45, 21-60, 14-90) to maximize success
5. Providing detailed error messages and failure pattern analysis

Note: Senex Trident is excluded (strict ATM strike requirements, tested separately)

Usage:
    python manage.py test_strategy_validation [--user EMAIL] [--symbols SYMBOL...]

Examples:
    # Test with default top 20 equities (requires superuser)
    python manage.py test_strategy_validation

    # Test with specific user
    python manage.py test_strategy_validation --user your@email.com

    # Test specific symbols
    python manage.py test_strategy_validation --user your@email.com --symbols SPY QQQ AAPL

Output includes:
    - Market indicators (price, IV, technical indicators, etc.)
    - Strategy rankings with scores and explanations
    - Generated suggestions with full details or detailed error messages
    - Summary with failure pattern analysis

Note: This command is designed for validation and debugging. It gracefully handles:
    - Missing price data
    - Unavailable option chains
    - Invalid strike availability
    - Market closed conditions
"""

from datetime import datetime

from django.contrib.auth import get_user_model

from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from services.market_data.analysis import MarketAnalyzer, MarketConditionReport
from services.strategies.selector import StrategySelector

User = get_user_model()


class Command(AsyncCommand):
    help = "Test all strategies against top 20 high-volume equities for validation"

    # Excluded strategies (tested separately due to specific requirements)
    EXCLUDED_STRATEGIES = [
        "senex_trident",  # Senex Trident has strict ATM strike requirements, tested separately
    ]

    # Top 20 equities by average daily volume
    DEFAULT_SYMBOLS = [
        "SPY",
        "QQQ",
        "IWM",  # Major ETFs
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
        "AMZN",
        "META",
        "TSLA",  # Mega caps
        "JPM",
        "V",
        "WMT",
        "JNJ",
        "UNH",  # Large caps
        "AMD",
        "NFLX",
        "DIS",
        "BA",
        "GS",  # Other high-volume
    ]

    # DTE ranges to try (primary -> fallback 1 -> fallback 2)
    DTE_RANGES = [
        (30, 45, "standard"),
        (21, 60, "wider"),
        (14, 90, "very wide"),
    ]

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)
        parser.add_argument(
            "--symbols",
            type=str,
            nargs="+",
            help="Override default symbol list (space-separated)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed logs (default: WARNING and above only)",
        )

    async def async_handle(self, *args, **options):
        """Run the strategy validation tests."""
        # Suppress verbose logging unless --verbose flag provided
        if not options.get("verbose", False):
            import logging

            # Set all loggers to WARNING level during test for clean output
            logging.getLogger("services").setLevel(logging.WARNING)
            logging.getLogger("streaming").setLevel(logging.WARNING)
            logging.getLogger("tastytrade").setLevel(logging.ERROR)  # Very noisy
            logging.getLogger("httpx").setLevel(logging.ERROR)
            logging.getLogger("httpcore").setLevel(logging.ERROR)
            logging.getLogger("asyncio").setLevel(logging.WARNING)

        # Get user using utility function
        user = await aget_user_from_options(options, require_user=True)

        # Get symbol list
        symbols = options.get("symbols") or self.DEFAULT_SYMBOLS

        self.stdout.write(f"Testing with user: {user.email}")
        self.stdout.write(f"Testing {len(symbols)} equities")

        # Run async tests
        await self.run_validation(user, symbols)

    async def run_validation(self, user, symbols):
        """Run comprehensive validation across all symbols."""
        start_time = datetime.now()

        # Start streaming infrastructure (same as production)
        from streaming.services.stream_manager import GlobalStreamManager

        stream_manager = await GlobalStreamManager.get_user_manager(user.id)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.WARNING(
                f"Starting streaming infrastructure for {len(symbols)} symbols..."
            )
        )
        self.stdout.write("=" * 80)

        # Start streamer and wait for data (same as production automation)
        try:
            streaming_ready = await stream_manager.ensure_streaming_for_automation(symbols)

            if not streaming_ready:
                self.stdout.write(
                    self.style.ERROR(
                        "\nFailed to start streaming - cannot run tests without real-time data\n"
                        "   Possible causes:\n"
                        "   - Invalid TastyTrade OAuth credentials\n"
                        "   - Network connectivity issues\n"
                        "   - Market data unavailable\n"
                    )
                )
                return

            self.stdout.write(
                self.style.SUCCESS(
                    "Streaming infrastructure ready - using real-time market data"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nFailed to initialize streaming: {e}\n"))
            return

        try:
            # Print header
            self._print_header(len(symbols))

            # Track statistics
            stats = {
                "total_tests": 0,
                "viable": 0,
                "below_threshold": 0,
                "generated": 0,
                "failed_generation": 0,
                "hard_stops": 0,
                "errors": [],
                "failure_patterns": {
                    "no_price": [],
                    "oauth_error": [],
                    "api_error": [],
                    "option_chain_unavailable": [],
                    "no_expirations": [],
                    "missing_strikes": [],
                    "generation_failed": [],
                    "context_failed": [],
                    "other": [],
                },
            }

            # Process each symbol
            for idx, symbol in enumerate(symbols, 1):
                try:
                    await self._process_symbol(user, symbol, idx, len(symbols), stats)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"\n[FAIL] Failed to process {symbol}: {e}"))
                    stats["errors"].append(f"{symbol}: {e}")

            # Print summary
            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(stats, elapsed)

        finally:
            # Cleanup - stop streamer
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.WARNING("Stopping streaming infrastructure..."))
            try:
                await stream_manager.stop_streaming()
                self.stdout.write(self.style.SUCCESS("Streaming stopped successfully"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Error stopping streaming: {e}"))
            self.stdout.write("=" * 80 + "\n")

    async def _process_symbol(self, user, symbol: str, idx: int, total: int, stats: dict):
        """Process a single symbol: analyze, score, generate."""
        self.stdout.write("\n")
        self.stdout.write("=" * 80)
        self.stdout.write(f"EQUITY {idx}/{total}: {symbol}")
        self.stdout.write("=" * 80)

        # 1. Analyze market conditions
        analyzer = MarketAnalyzer(user)
        report = await analyzer.a_analyze_market_conditions(user, symbol, {})

        # Check for hard stops
        if not report.can_trade():
            self._print_hard_stops(report)
            # All tested strategies blocked (2 strategies: bull_put + bear_call)
            stats["hard_stops"] += 2
            stats["total_tests"] += 2
            return

        # Check for price data availability
        has_price_data = report.current_price > 0

        # Print market indicators (with streaming context)
        self._print_market_indicators(report, has_price_data, symbol)

        # 2. Score all strategies (excluding those tested separately)
        selector = StrategySelector(user)
        scores = {}
        explanations = {}

        for name, strategy in selector.strategies.items():
            # Skip excluded strategies (tested separately)
            if name in self.EXCLUDED_STRATEGIES:
                continue

            try:
                score, explanation = await strategy.a_score_market_conditions(report)
                scores[name] = score
                explanations[name] = explanation
                stats["total_tests"] += 1

                if score >= selector.MIN_AUTO_SCORE:
                    stats["viable"] += 1
                else:
                    stats["below_threshold"] += 1
            except Exception as e:
                scores[name] = 0.0
                explanations[name] = f"Error: {e}"
                stats["total_tests"] += 1
                stats["below_threshold"] += 1
                stats["errors"].append(f"{symbol} - {name}: {e}")

        # Print rankings
        self._print_strategy_rankings(scores, explanations, selector.MIN_AUTO_SCORE)

        # 3. Generate suggestions for viable strategies
        self.stdout.write("\nGENERATED SUGGESTIONS")
        self.stdout.write("─" * 80)

        # Sort by score (highest first)
        sorted_strategies = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for strategy_name, score in sorted_strategies:
            if score >= selector.MIN_AUTO_SCORE:
                # Check price data first
                if not has_price_data:
                    error_detail = {
                        "type": "no_price",
                        "message": "No current price available",
                        "details": f"Market data shows ${report.current_price:.2f}",
                    }
                    self._print_generation_error(strategy_name, error_detail)
                    stats["failed_generation"] += 1
                    stats["failure_patterns"]["no_price"].append(f"{symbol}:{strategy_name}")
                    continue

                # Try generation with fallback DTE ranges
                suggestion, error = await self._generate_with_fallbacks(
                    user, strategy_name, selector, symbol, report
                )

                if suggestion:
                    self._print_suggestion(strategy_name, suggestion, score)
                    stats["generated"] += 1
                elif error:
                    self._print_generation_error(strategy_name, error)
                    stats["failed_generation"] += 1
                    # Track failure pattern
                    error_type = error.get("type", "other")
                    pattern_key = error_type if error_type in stats["failure_patterns"] else "other"
                    stats["failure_patterns"][pattern_key].append(f"{symbol}:{strategy_name}")
                else:
                    # Shouldn't happen, but handle gracefully
                    error_detail = {"type": "other", "message": "Unknown error"}
                    self._print_generation_error(strategy_name, error_detail)
                    stats["failed_generation"] += 1
                    stats["failure_patterns"]["other"].append(f"{symbol}:{strategy_name}")
            else:
                self._print_not_generated(strategy_name, score, selector.MIN_AUTO_SCORE)

    async def _generate_with_fallbacks(
        self,
        user,
        strategy_name: str,
        selector: StrategySelector,
        symbol: str,
        report: MarketConditionReport,
    ):
        """
        Generate a suggestion with fallback DTE ranges.

        Returns:
            (suggestion, None) if successful
            (None, error_dict) if failed with detailed classification
        """
        strategy = selector.strategies[strategy_name]
        attempted_ranges = []
        failure_details = []  # Track what actually failed and why

        # Try each DTE range
        for min_dte, max_dte, range_name in self.DTE_RANGES:
            range_label = f"{min_dte}-{max_dte} ({range_name})"
            attempted_ranges.append(range_label)

            # Save original values before try block (if strategy supports DTE ranges)
            has_dte_range = hasattr(strategy, "MIN_DTE") and hasattr(strategy, "MAX_DTE")
            if has_dte_range:
                original_min = strategy.MIN_DTE
                original_max = strategy.MAX_DTE

            try:
                # Temporarily modify strategy's DTE parameters (if supported)
                if has_dte_range:
                    strategy.MIN_DTE = min_dte
                    strategy.MAX_DTE = max_dte

                # Prepare context
                context = await strategy.a_prepare_suggestion_context(
                    symbol, report, suggestion_mode=True
                )

                # Restore original values (if modified)
                if has_dte_range:
                    strategy.MIN_DTE = original_min
                    strategy.MAX_DTE = original_max

                if context:
                    # Mark as automated
                    context["is_automated"] = True
                    context["suggestion_mode"] = True

                    # Generate via stream manager
                    from streaming.services.stream_manager import GlobalStreamManager

                    stream_manager = await GlobalStreamManager.get_user_manager(user.id)
                    suggestion = await stream_manager.a_process_suggestion_request(context)

                    if suggestion:
                        return (suggestion, None)
                    # Context prepared but suggestion generation failed
                    failure_details.append(
                        (range_label, "generation_failed", "Stream manager returned None")
                    )
                else:
                    # Context preparation returned None (most common - strikes/expiration issues)
                    failure_details.append(
                        (
                            range_label,
                            "context_failed",
                            "No suitable context (likely missing strikes/expirations)",
                        )
                    )

            except Exception as e:
                # Restore values on exception (if they were modified)
                if has_dte_range:
                    strategy.MIN_DTE = original_min
                    strategy.MAX_DTE = original_max

                # Classify the exception
                error_type, error_message = self._classify_exception(e)
                failure_details.append((range_label, error_type, error_message))

                # Continue to next range unless it's a fatal error
                if error_type in ["api_error", "oauth_error"]:
                    # Don't retry other ranges if API/auth is broken
                    break

        # All ranges failed - determine the most specific error type
        error_detail = self._build_error_detail(symbol, attempted_ranges, failure_details)
        return (None, error_detail)

    def _classify_exception(self, exception: Exception) -> tuple[str, str]:
        """
        Classify an exception into error type and message.

        Returns:
            (error_type, error_message)
        """
        error_str = str(exception).lower()
        exception_type = type(exception).__name__

        # OAuth/Authentication errors
        if "oauth" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            return ("oauth_error", f"Authentication failed: {exception}")

        # API/Network errors
        if "connection" in error_str or "timeout" in error_str or "api" in error_str:
            return ("api_error", f"API/Network error: {exception}")

        # Option chain specific errors
        if "option chain" in error_str or "chain" in error_str:
            return ("option_chain_unavailable", f"Option chain fetch failed: {exception}")

        # Expiration/DTE errors
        if "expiration" in error_str or "dte" in error_str:
            return ("no_expirations", f"No valid expirations: {exception}")

        # Strike validation errors
        if "strike" in error_str or "strikes" in error_str:
            return ("missing_strikes", f"Strike validation failed: {exception}")

        # Generic errors
        return ("other", f"{exception_type}: {exception}")

    def _build_error_detail(
        self, symbol: str, attempted_ranges: list[str], failure_details: list
    ) -> dict:
        """
        Build detailed error report based on failure patterns.

        Args:
            symbol: Equity symbol
            attempted_ranges: List of DTE range descriptions
            failure_details: List of (range_label, error_type, error_message) tuples

        Returns:
            Error detail dict with classified type and relevant details
        """
        if not failure_details:
            # Shouldn't happen, but handle gracefully
            return {
                "type": "other",
                "message": "Unknown error (no failure details captured)",
                "attempted_ranges": attempted_ranges,
            }

        # Count error types to find most common
        error_type_counts = {}
        for _, error_type, _ in failure_details:
            error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1

        # Prioritize error types (most serious first)
        priority_order = [
            "oauth_error",
            "api_error",
            "option_chain_unavailable",
            "no_expirations",
            "missing_strikes",
            "generation_failed",
            "context_failed",
            "other",
        ]

        # Find highest priority error that occurred
        primary_error_type = None
        for err_type in priority_order:
            if err_type in error_type_counts:
                primary_error_type = err_type
                break

        if not primary_error_type:
            primary_error_type = "other"

        # Build user-friendly message
        error_messages = {
            "oauth_error": "Authentication/OAuth error",
            "api_error": "API or network error",
            "option_chain_unavailable": "Option chain unavailable",
            "no_expirations": "No valid expirations found",
            "missing_strikes": "Required strikes not available",
            "generation_failed": "Suggestion generation failed",
            "context_failed": "Context preparation failed",
            "other": "Unknown error",
        }

        message = error_messages.get(primary_error_type, "Unknown error")

        # Include specific details from failures
        error_detail = {
            "type": primary_error_type,
            "message": message,
            "attempted_ranges": attempted_ranges,
            "failure_count": len(failure_details),
        }

        # Add the most relevant error message as details
        for range_label, error_type, error_message in failure_details:
            if error_type == primary_error_type:
                error_detail["details"] = error_message
                error_detail["failed_range"] = range_label
                break

        return error_detail

    def _print_header(self, symbol_count: int):
        """Print report header."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("STRATEGY VALIDATION REPORT"))
        self.stdout.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.stdout.write(f"Testing {symbol_count} equities with 2 strategies each")
        self.stdout.write("(Bull Put Spread + Bear Call Spread)")
        self.stdout.write("=" * 80)

    def _print_market_indicators(
        self, report: MarketConditionReport, has_price_data: bool, symbol: str
    ):
        """Print market indicators section."""
        self.stdout.write("\nMARKET INDICATORS")
        self.stdout.write("─" * 80)

        # Price data warning with streaming context
        if not has_price_data:
            # Check cache to provide better error message
            from django.core.cache import cache

            from services.core.cache import CacheManager

            quote_key = CacheManager.quote(symbol)
            cached_quote = cache.get(quote_key)

            self.stdout.write(
                self.style.WARNING("WARNING: No current price data in streaming cache")
            )
            if cached_quote:
                self.stdout.write(
                    f"    Cache Status: Symbol found but price = ${report.current_price:.2f}"
                )
            else:
                self.stdout.write(f"    Cache Status: Symbol {symbol} not in cache")
            self.stdout.write("    This may indicate a market data issue or symbol not subscribed")
            self.stdout.write("")

        # Price info
        self.stdout.write(f"Price:              ${report.current_price:.2f}")
        if report.open_price > 0:
            self.stdout.write(f"Open:               ${report.open_price:.2f}")

        # Technical indicators
        self.stdout.write(f"RSI:                {report.rsi:.1f}")
        self.stdout.write(f"MACD Signal:        {report.macd_signal}")
        self.stdout.write(f"Bollinger:          {report.bollinger_position}")
        if report.sma_20 > 0:
            self.stdout.write(f"SMA 20:             ${report.sma_20:.2f}")

        # Trend strength
        if report.adx is not None:
            self.stdout.write(f"ADX:                {report.adx:.1f} ({report.trend_strength})")

        # Volatility
        if report.historical_volatility > 0:
            self.stdout.write(f"Historical Vol:     {report.historical_volatility:.1f}%")
        self.stdout.write(f"IV Rank:            {report.iv_rank:.1f}")
        self.stdout.write(f"Current IV:         {report.current_iv:.1f}%")

        # HV/IV ratio interpretation
        if report.hv_iv_ratio < 0.8:
            ratio_desc = "IV elevated"
        elif report.hv_iv_ratio > 1.2:
            ratio_desc = "IV depressed"
        else:
            ratio_desc = "IV neutral"
        self.stdout.write(f"HV/IV Ratio:        {report.hv_iv_ratio:.2f} ({ratio_desc})")

        # Market state
        range_bound = "Yes" if report.is_range_bound else "No"
        self.stdout.write(f"Range Bound:        {range_bound} ({report.range_bound_days} days)")
        self.stdout.write(f"Market Stress:      {report.market_stress_level:.0f}/100")

        # Support/Resistance
        if report.support_level:
            self.stdout.write(f"Support:            ${report.support_level:.2f}")
        if report.resistance_level:
            self.stdout.write(f"Resistance:         ${report.resistance_level:.2f}")

    def _print_strategy_rankings(self, scores: dict, explanations: dict, threshold: int):
        """Print strategy rankings section."""
        self.stdout.write("\nSTRATEGY RANKINGS")
        self.stdout.write("─" * 80)

        # Sort by score (highest first)
        sorted_strategies = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for rank, (name, score) in enumerate(sorted_strategies, 1):
            # Format strategy name
            display_name = name.replace("_", " ").title()

            # Viable indicator
            viable = "[OK] VIABLE" if score >= threshold else "[FAIL] BELOW THRESHOLD"
            style = self.style.SUCCESS if score >= threshold else self.style.WARNING

            # Print ranking line
            self.stdout.write(style(f"{rank}. {display_name:<20} {score:>5.1f}  {viable}"))

            # Print explanation (split by delimiter)
            explanation = explanations.get(name, "")
            if explanation:
                reasons = explanation.split(" | ")
                reason_text = " | ".join(reasons[:3])  # First 3 reasons
                self.stdout.write(f"   {reason_text}")
            self.stdout.write("")

    def _print_suggestion(self, strategy_name: str, suggestion, score: float):
        """Print generated suggestion details."""
        display_name = strategy_name.replace("_", " ").title()
        self.stdout.write(self.style.SUCCESS(f"\n[OK] {display_name} (Score: {score:.1f})"))

        # Calculate DTE
        from django.utils import timezone

        today = timezone.now().date()
        dte = (suggestion.expiration_date - today).days

        # Extract suggestion details
        self.stdout.write(f"  Expiration:    {suggestion.expiration_date} " f"({dte} DTE)")

        # Strategy-specific formatting
        if strategy_name == "senex_trident":
            self.stdout.write(
                f"  Put Spread 1:  Short ${suggestion.short_put_strike} / "
                f"Long ${suggestion.long_put_strike} (×{suggestion.put_spread_quantity})"
            )
            # Senex Trident has 2 put spreads - check if there's a second one
            # (In current implementation, both put spreads use same strikes)
            self.stdout.write(
                f"  Call Spread:   Short ${suggestion.short_call_strike} / "
                f"Long ${suggestion.long_call_strike} (×{suggestion.call_spread_quantity})"
            )
        else:
            # Bull Put Spread or Bear Call Spread
            if suggestion.short_put_strike:
                self.stdout.write(
                    f"  Put Spread:    Short ${suggestion.short_put_strike} / "
                    f"Long ${suggestion.long_put_strike} (×{suggestion.put_spread_quantity})"
                )
            if suggestion.short_call_strike:
                self.stdout.write(
                    f"  Call Spread:   Short ${suggestion.short_call_strike} / "
                    f"Long ${suggestion.long_call_strike} (×{suggestion.call_spread_quantity})"
                )

        # Financial metrics
        self.stdout.write(f"  Credit:        ${suggestion.total_credit:.2f}")
        self.stdout.write(f"  Max Risk:      ${suggestion.max_risk:.2f}")

        # Calculate R/R ratio
        if suggestion.total_credit > 0:
            rr_ratio = suggestion.max_risk / suggestion.total_credit
            self.stdout.write(f"  R/R:           {rr_ratio:.2f}:1")

    def _print_not_generated(self, strategy_name: str, score: float, threshold: int):
        """Print message for strategies not generated (below threshold)."""
        display_name = strategy_name.replace("_", " ").title()
        self.stdout.write(
            self.style.WARNING(
                f"\n[FAIL] {display_name} - Not generated (score {score:.1f} < {threshold})"
            )
        )

    def _print_generation_error(self, strategy_name: str, error_detail: dict):
        """Print detailed error message for failed generation."""
        display_name = strategy_name.replace("_", " ").title()
        message = error_detail.get("message", "Unknown error")

        self.stdout.write(self.style.ERROR(f"\n[FAIL] {display_name} - {message}"))

        # Print additional details
        if "details" in error_detail:
            self.stdout.write(f"  {error_detail['details']}")

        # Show which range failed (if specific)
        if "failed_range" in error_detail:
            self.stdout.write(f"  Failed at: {error_detail['failed_range']}")

        # Show attempted ranges if multiple attempts were made
        if "attempted_ranges" in error_detail and len(error_detail["attempted_ranges"]) > 1:
            failure_count = error_detail.get("failure_count", len(error_detail["attempted_ranges"]))
            self.stdout.write(f"  Attempted {failure_count} DTE ranges:")
            for range_desc in error_detail["attempted_ranges"]:
                self.stdout.write(f"    - {range_desc}")

    def _print_hard_stops(self, report: MarketConditionReport):
        """Print hard stop reasons."""
        self.stdout.write("\n" + self.style.ERROR("HARD STOPS - CANNOT TRADE"))
        self.stdout.write("─" * 80)
        for reason in report.no_trade_reasons:
            self.stdout.write(f"  • {reason.replace('_', ' ').title()}")
        self.stdout.write("\n(Skipping all strategies for this equity)")

    def _print_summary(self, stats: dict, elapsed: float):
        """Print summary statistics."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)

        self.stdout.write(f"Total Strategy Tests:     {stats['total_tests']}")
        self.stdout.write(f"Viable (score >= 30):     {stats['viable']}")
        self.stdout.write(f"Below Threshold:          {stats['below_threshold']}")
        self.stdout.write(f"Suggestions Generated:    {stats['generated']}")
        self.stdout.write(f"Generation Failures:      {stats['failed_generation']}")
        self.stdout.write(f"Hard Stops (no trade):    {stats['hard_stops'] // 2}")  # 2 per equity

        self.stdout.write(f"\nProcessing Time:          {elapsed:.1f}s")

        # Print failure patterns if any
        failure_patterns = stats.get("failure_patterns", {})
        has_failures = any(len(v) > 0 for v in failure_patterns.values())

        if has_failures:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.WARNING("FAILURE PATTERNS"))
            self.stdout.write("=" * 80)

            pattern_labels = {
                "no_price": "No Current Price",
                "oauth_error": "Authentication/OAuth Error",
                "api_error": "API/Network Error",
                "option_chain_unavailable": "Option Chain Unavailable",
                "no_expirations": "No Option Expirations",
                "missing_strikes": "Missing Strikes",
                "generation_failed": "Suggestion Generation Failed",
                "context_failed": "Context Preparation Failed",
                "other": "Other Errors",
            }

            for pattern_key, pattern_label in pattern_labels.items():
                failures = failure_patterns.get(pattern_key, [])
                if failures:
                    # Count unique symbols (not strategy instances)
                    unique_symbols = {f.split(":")[0] for f in failures}
                    self.stdout.write(
                        f"{pattern_label:<30} {len(unique_symbols)} equities, {len(failures)} strategies"
                    )

                    # Show first few examples
                    examples = list(failures[:3])
                    if examples:
                        self.stdout.write("  Examples: " + ", ".join(examples))

        # Print errors if any
        if stats["errors"]:
            self.stdout.write("\n" + self.style.ERROR("ERRORS:"))
            for error in stats["errors"][:10]:  # First 10 errors
                self.stdout.write(f"  • {error}")
            if len(stats["errors"]) > 10:
                self.stdout.write(f"  ... and {len(stats['errors']) - 10} more")

        self.stdout.write("\n" + "=" * 80)
