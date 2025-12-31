"""
Management command to create a test spread position for testing profit target automation.

Creates a bull put spread (short put vertical) with configurable DTE for testing:
- Profit target creation flow
- DTE automation (when DTE <= threshold)
- Order recovery mechanisms

Supports two strike selection modes:
- Delta-based (default): Finds strike with delta closest to target (e.g., 0.20)
- OTM-based: Uses fixed percentage OTM (legacy mode)

Usage:
    python manage.py create_test_spread --user EMAIL --symbol QQQ --dte 8
    python manage.py create_test_spread --user EMAIL --symbol QQQ --dte 8 --target-delta 0.25
    python manage.py create_test_spread --user EMAIL --symbol SPY --dte 3 --dry-run
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from streaming.services.stream_manager import GlobalStreamManager

User = get_user_model()


class Command(AsyncCommand):
    help = "Create a test bull put spread for testing profit target and DTE automation"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=True, allow_superuser_fallback=False)
        parser.add_argument(
            "--symbol",
            type=str,
            default="QQQ",
            help="Underlying symbol (default: QQQ)",
        )
        parser.add_argument(
            "--dte",
            type=int,
            default=8,
            help="Target days to expiration (default: 8)",
        )
        parser.add_argument(
            "--quantity",
            type=int,
            default=1,
            help="Number of spreads (default: 1)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without executing",
        )
        parser.add_argument(
            "--target-delta",
            type=float,
            default=0.20,
            help="Target delta for short strike (default: 0.20 = 20 delta)",
        )
        parser.add_argument(
            "--spread-width",
            type=int,
            default=5,
            help="Spread width in dollars (default: 5)",
        )
        parser.add_argument(
            "--use-otm-pct",
            action="store_true",
            help="Use OTM percentage instead of delta targeting (legacy mode)",
        )
        parser.add_argument(
            "--otm-pct",
            type=float,
            default=0.03,
            help="OTM percentage if --use-otm-pct (default: 0.03 = 3%%)",
        )

    async def async_handle(self, *args, **options):
        """Execute the test spread creation with delta-based strike selection."""
        import asyncio

        user = await aget_user_from_options(options, require_user=True)
        symbol = options["symbol"]
        target_dte = options["dte"]
        quantity = options["quantity"]
        dry_run = options["dry_run"]
        target_delta = options["target_delta"]
        spread_width = options["spread_width"]
        use_otm_pct = options["use_otm_pct"]
        otm_pct = options["otm_pct"]

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("CREATE TEST SPREAD (Delta-Based)")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"User:         {user.email}")
        self.stdout.write(f"Symbol:       {symbol}")
        self.stdout.write(f"DTE:          ~{target_dte} days")
        self.stdout.write(f"Quantity:     {quantity}")
        self.stdout.write(f"Spread Width: ${spread_width}")
        if use_otm_pct:
            self.stdout.write(f"Strike Mode:  OTM Percentage ({otm_pct*100:.1f}%)")
        else:
            self.stdout.write(f"Strike Mode:  Delta Targeting ({target_delta:.2f} delta)")
        self.stdout.write(f"Dry Run:      {dry_run}")
        self.stdout.write(f"{'=' * 60}\n")

        # Get trading account
        from accounts.models import TradingAccount

        account = await TradingAccount.objects.filter(
            user=user, is_primary=True, is_active=True
        ).afirst()

        if not account:
            self.stdout.write(self.style.ERROR("No active primary trading account found"))
            return

        self.stdout.write(f"Account: {account.account_number}")

        # Initialize streaming for market data
        self.stdout.write("\nStarting streaming infrastructure...")
        stream_manager = await GlobalStreamManager.get_user_manager(user.id)

        try:
            streaming_ready = await stream_manager.ensure_streaming_for_automation([symbol])
            if not streaming_ready:
                self.stdout.write(self.style.ERROR("Failed to start streaming"))
                return

            self.stdout.write(self.style.SUCCESS("Streaming ready"))

            # Get current price and market conditions
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(user)
            report = await analyzer.a_analyze_market_conditions(user, symbol, {})

            current_price = Decimal(str(report.current_price))
            self.stdout.write("\nMarket Data:")
            self.stdout.write(f"   Current Price: ${current_price:.2f}")
            self.stdout.write(f"   IV Rank:       {report.iv_rank:.1f}")

            if not report.can_trade():
                self.stdout.write(
                    self.style.ERROR(
                        f"Cannot trade: {', '.join(report.no_trade_reasons)}"
                    )
                )
                return

            # Find expiration
            from services.market_data.option_chains import OptionChainService

            chain_service = OptionChainService()
            all_expirations = await chain_service.a_get_all_expirations(user, symbol)

            if not all_expirations:
                self.stdout.write(self.style.ERROR(f"No expirations found for {symbol}"))
                return

            # Find closest expiration to target DTE
            today = date.today()
            target_date = today + timedelta(days=target_dte)

            best_exp = None
            best_diff = float("inf")

            for exp in all_expirations:
                diff = abs((exp - target_date).days)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp

            if not best_exp:
                self.stdout.write(self.style.ERROR("Could not find suitable expiration"))
                return

            actual_dte = (best_exp - today).days
            self.stdout.write(f"   Expiration:    {best_exp} ({actual_dte} DTE)")

            # Get option chain for this expiration
            from services.market_data.option_chains import extract_put_strikes
            from services.streaming.options_service import StreamingOptionsDataService

            options_service = StreamingOptionsDataService(user)
            chain = await options_service._get_option_chain(symbol, best_exp)

            if not chain:
                self.stdout.write(self.style.ERROR("Could not load option chain"))
                return

            available_strikes = sorted(extract_put_strikes(chain.get("strikes", [])))
            self.stdout.write(
                f"   Available Put Strikes: {len(available_strikes)} "
                f"(${min(available_strikes):.0f} - ${max(available_strikes):.0f})"
            )

            # Subscribe to option Greeks for delta-based selection
            if not use_otm_pct:
                self.stdout.write("\nFinding strike by delta...")

                # Build OCC symbols for candidate strikes (filter to reasonable range)
                # For a 20 delta put, typically 2-8% OTM
                from services.sdk.instruments import build_occ_symbol

                min_strike = current_price * Decimal("0.90")  # 10% OTM max
                max_strike = current_price * Decimal("0.99")  # 1% OTM min
                candidate_strikes = [
                    s for s in available_strikes if min_strike <= s <= max_strike
                ]

                self.stdout.write(
                    f"   Candidate strikes for delta search: {len(candidate_strikes)} "
                    f"(${min(candidate_strikes):.0f} - ${max(candidate_strikes):.0f})"
                )

                # Subscribe to Greeks for these strikes
                occ_symbols = [
                    build_occ_symbol(symbol, best_exp, strike, "P")
                    for strike in candidate_strikes
                ]

                # Subscribe and wait for data using stream manager's proper waiting logic
                self.stdout.write(f"   Subscribing to {len(occ_symbols)} option symbols...")
                await stream_manager.subscribe_to_new_symbols(occ_symbols)

                # Wait for Quote cache to be populated
                self.stdout.write("   Waiting for option data...")
                cache_ready = await stream_manager._wait_for_cache(occ_symbols, timeout=15)

                if not cache_ready:
                    self.stdout.write(
                        self.style.WARNING(
                            "Timeout waiting for option data - falling back to OTM percentage"
                        )
                    )
                    use_otm_pct = True
                else:
                    # Greeks arrive slightly after Quotes - wait a bit more
                    self.stdout.write("   Waiting for Greeks to populate...")
                    await asyncio.sleep(2)

                    # Find strike by delta
                    from services.strategies.utils.strike_optimizer import StrikeOptimizer

                    optimizer = StrikeOptimizer()
                    short_strike, actual_delta = await optimizer.find_strike_by_delta(
                        user=user,
                        symbol=symbol,
                        expiration=best_exp,
                        option_type="put",
                        target_delta=target_delta,
                        available_strikes=candidate_strikes,
                        options_service=options_service,
                    )

                    if not short_strike:
                        self.stdout.write(
                            self.style.WARNING(
                                "No Greeks available - falling back to OTM percentage"
                            )
                        )
                        use_otm_pct = True
                    else:
                        long_strike = short_strike - Decimal(str(spread_width))
                        # Find nearest available long strike
                        closest_long = min(
                            available_strikes,
                            key=lambda s: abs(s - long_strike)
                        )
                        long_strike = closest_long

                        self.stdout.write(
                            self.style.SUCCESS(
                                f"   Found: Short ${short_strike} (delta={actual_delta:.3f}), "
                                f"Long ${long_strike}"
                            )
                        )

            if use_otm_pct:
                # Fallback: Use OTM percentage
                self.stdout.write("\nFinding strike by OTM percentage...")
                short_strike = round(float(current_price * Decimal(str(1 - otm_pct))))
                short_strike = Decimal(str(short_strike))

                # Find nearest available strike
                short_strike = min(available_strikes, key=lambda s: abs(s - short_strike))
                long_strike = short_strike - Decimal(str(spread_width))
                long_strike = min(available_strikes, key=lambda s: abs(s - long_strike))

                self.stdout.write(
                    f"   Short strike: ${short_strike} ({otm_pct*100:.1f}% OTM)"
                )
                self.stdout.write(f"   Long strike:  ${long_strike}")
                actual_delta = None

            # Build OCC bundle for pricing (same format as strategy uses)
            from services.sdk.instruments import build_occ_symbol

            short_occ = build_occ_symbol(symbol, best_exp, short_strike, "P")
            long_occ = build_occ_symbol(symbol, best_exp, long_strike, "P")

            self.stdout.write("\n💰 Getting live pricing...")
            self.stdout.write(f"   Short OCC: {short_occ}")
            self.stdout.write(f"   Long OCC:  {long_occ}")

            # Build OCC bundle (same structure strategies use)
            from services.streaming.dataclasses import SenexOccBundle

            occ_bundle = SenexOccBundle(
                underlying=symbol,
                expiration=best_exp,
                legs={
                    "short_put": short_occ,
                    "long_put": long_occ,
                },
            )

            # Subscribe to leg symbols and wait for data
            leg_symbols = [short_occ, long_occ]
            await stream_manager.subscribe_to_new_symbols(leg_symbols)

            # Wait for cache with timeout
            cache_ready = await stream_manager._wait_for_cache(leg_symbols, timeout=15)

            if not cache_ready:
                self.stdout.write(
                    self.style.ERROR(
                        "Timeout waiting for live pricing data. "
                        "Check streaming logs for subscription issues."
                    )
                )
                return

            # Read pricing using the same method strategies use
            pricing = options_service.read_spread_pricing(occ_bundle)

            if not pricing:
                self.stdout.write(
                    self.style.ERROR(
                        "Failed to build pricing from cache. "
                        "Option quotes may not have bid/ask data."
                    )
                )
                return

            # Extract credit values
            net_credit = float(pricing.put_credit or 0)
            mid_credit = float(pricing.put_mid_credit or 0)

            if net_credit <= 0:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid pricing: net credit is ${net_credit:.2f} (must be positive)."
                    )
                )
                return

            self.stdout.write(f"   Natural Credit: ${net_credit:.2f} (conservative)")
            self.stdout.write(f"   Mid Credit:     ${mid_credit:.2f} (realistic)")

            # Calculate credit as % of spread width
            credit_pct = (net_credit / spread_width) * 100
            self.stdout.write(f"   Credit/Width:  {credit_pct:.1f}% (target: 25-33%)")

            # Calculate max risk
            actual_width = float(short_strike - long_strike)
            max_risk = (actual_width - net_credit) * 100 * quantity
            self.stdout.write(f"   Max Risk:      ${max_risk:.2f}")

            # Summary
            self.stdout.write("\nTrade Summary:")
            self.stdout.write("   Strategy:    Short Put Vertical (Bull Put Spread)")
            self.stdout.write(f"   Symbol:      {symbol}")
            self.stdout.write(f"   Expiration:  {best_exp} ({actual_dte} DTE)")
            self.stdout.write(f"   Short Put:   ${short_strike}")
            self.stdout.write(f"   Long Put:    ${long_strike}")
            self.stdout.write(f"   Width:       ${actual_width}")
            self.stdout.write(f"   Credit:      ${net_credit:.2f}")
            self.stdout.write(f"   Quantity:    {quantity}")
            if actual_delta:
                self.stdout.write(f"   Short Delta: {actual_delta:.3f}")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING("\nDRY RUN - No order will be placed")
                )
                return

            # Create suggestion and execute
            self.stdout.write("\n📝 Creating suggestion and executing...")

            from django.utils import timezone

            from trading.models import StrategyConfiguration, TradingSuggestion

            config, _ = await StrategyConfiguration.objects.aget_or_create(
                user=user,
                strategy_id="short_put_vertical",
                defaults={"parameters": {"profit_target_pct": 50}},
            )

            suggestion = await TradingSuggestion.objects.acreate(
                user=user,
                strategy_id="short_put_vertical",  # Required field for validation
                strategy_configuration=config,
                underlying_symbol=symbol,
                underlying_price=current_price,
                expiration_date=best_exp,
                short_put_strike=short_strike,
                long_put_strike=long_strike,
                short_call_strike=None,
                long_call_strike=None,
                put_spread_quantity=quantity,
                call_spread_quantity=0,
                put_spread_credit=Decimal(str(net_credit)),
                put_spread_mid_credit=Decimal(str(mid_credit)),
                call_spread_credit=Decimal("0"),
                call_spread_mid_credit=Decimal("0"),
                total_credit=Decimal(str(net_credit)),
                total_mid_credit=Decimal(str(mid_credit)),
                max_risk=Decimal(str(max_risk / 100)),
                status="approved",
                has_real_pricing=True,
                expires_at=timezone.now() + timedelta(hours=24),
            )

            self.stdout.write(f"   Suggestion ID: {suggestion.id}")

            # Execute the order
            from services.execution.order_service import OrderExecutionService

            order_service = OrderExecutionService(user)

            result = await order_service.execute_suggestion_async(
                suggestion, custom_credit=Decimal(str(net_credit))
            )

            if result:
                # Check if it's a DryRunResult or Position
                if hasattr(result, "is_dry_run") and result.is_dry_run:
                    self.stdout.write(self.style.WARNING("\n🧪 DRY-RUN MODE - Order validated but not submitted"))
                    self.stdout.write(f"   Order would be valid: {result.is_valid}")
                    if result.validation_message:
                        self.stdout.write(f"   Message: {result.validation_message}")
                else:
                    # It's a Position object
                    position = result
                    self.stdout.write(self.style.SUCCESS("\n✅ ORDER SUBMITTED SUCCESSFULLY"))
                    self.stdout.write(f"   Position ID: {position.id}")
                    self.stdout.write("\n📋 Next Steps:")
                    self.stdout.write("   1. Monitor order fill via TastyTrade or dashboard")
                    self.stdout.write("   2. Upon fill, profit targets should auto-create")
                    self.stdout.write(
                        f"   3. Check position {position.id} for profit_targets_created=True"
                    )
                    self.stdout.write("   4. At DTE <= 7, DTE automation will take over")
            else:
                self.stdout.write(self.style.ERROR("\n❌ Order execution returned None"))

        finally:
            # Cleanup streaming
            self.stdout.write("\nStopping streaming...")
            await stream_manager.stop_streaming()
            self.stdout.write(self.style.SUCCESS("Streaming stopped"))
