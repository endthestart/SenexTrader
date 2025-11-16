from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from services.account.state import AccountStateService
from services.api.serializers import TradingSuggestionSerializer
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from services.orders.utils.order_builder_utils import build_closing_spread_legs
from services.positions.risk_calculator import PositionRiskCalculator
from services.sdk.trading_utils import PriceEffect
from services.strategies.base import BaseStrategy
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import (
    calculate_max_profit_credit_spread,
    round_to_even_strike,
)
from trading.models import StrategyConfiguration, TradingSuggestion

logger = get_logger(__name__)


@register_strategy("senex_trident")
class SenexTridentStrategy(BaseStrategy):
    """
    Senex Trident strategy implementation with streaming data integration.
    This is a simplified version that will be enhanced with full streaming support.
    """

    # Simple configuration constants (override defaults)
    MIN_IV_RANK = 25
    MIN_SPREAD_WIDTH = 3
    TARGET_DTE = 45

    def __init__(self, user):
        super().__init__(user)  # Get common dependencies from BaseStrategy
        # Add Senex-specific dependencies
        self.account_state_service = AccountStateService()
        self.position_calculator = PositionRiskCalculator()

    @property
    def strategy_name(self) -> str:
        return "senex_trident"

    def get_profit_target_config(self, position) -> list:
        config = self.get_active_config()
        params = config.get_senex_parameters() if config else {}

        return [
            {"percentage": params.get("put_spread_1_target", 40.0), "spread_type": "put_spread_1"},
            {"percentage": params.get("put_spread_2_target", 60.0), "spread_type": "put_spread_2"},
            {"percentage": params.get("call_spread_target", 40.0), "spread_type": "call_spread"},
        ]

    def should_place_profit_targets(self, position) -> bool:
        return True

    def get_dte_exit_threshold(self, position) -> int:
        config = self.get_active_config()
        params = config.get_senex_parameters() if config else {}
        return params.get("dte_close", 7)

    def generate_suggestion(self) -> None:
        """Synchronous wrapper for the async suggestion request method."""
        return run_async(self.a_request_suggestion_generation())

    async def a_score_market_conditions(self, report) -> tuple[float, str]:
        """
        Score market conditions for Senex Trident (0-100).

        Senex Trident (2 put spreads + 1 call spread) prefers:
        - Neutral to slightly bullish market conditions
        - High IV rank (good premium collection)
        - NOT range-bound (prevents stacking)
        - Moderate volatility (not extreme)

        NOTE: This is NOT an iron condor. All spreads are SHORT credit spreads.

        Args:
            report: MarketConditionReport with market data

        Returns:
            (score, explanation)
        """
        logger.info(
            "Scoring market conditions for %s: IV rank=%.1f%%, ADX=%.1f, RSI=%.1f, MACD=%s, stress=%.0f",
            report.symbol,
            report.iv_rank if report.iv_rank else 0,
            report.adx if report.adx else 0,
            report.rsi if report.rsi else 0,
            report.macd_signal if report.macd_signal else "unknown",
            report.market_stress_level if report.market_stress_level else 0,
        )

        score = 50.0  # Base score
        reasons = []

        # Hard stops (return 0)
        if not report.can_trade():
            logger.info("Hard stop: %s", report.get_no_trade_explanation())
            return (0.0, report.get_no_trade_explanation())

        # CRITICAL: Verify technical indicator data is available
        if not report.data_available:
            return (0.0, "Insufficient historical data for technical analysis")

        # HARD STOP: Range-bound market (Trident specific)
        if report.is_range_bound:
            return (
                0.0,
                f"Range-bound market ({report.range_bound_days} days at same strikes) - "
                f"Trident not suitable (prevents position stacking)",
            )

        # IV rank scoring (critical for premium collection)
        if report.iv_rank >= self.MIN_IV_RANK:
            bonus = min(30, (report.iv_rank - self.MIN_IV_RANK) * 0.5)
            score += bonus
            reasons.append(f"IV rank {report.iv_rank:.1f}% favorable for premium")
        else:
            penalty = (self.MIN_IV_RANK - report.iv_rank) * 0.8
            score -= penalty
            reasons.append(f"IV rank {report.iv_rank:.1f}% below minimum ({self.MIN_IV_RANK}%)")

        # ADX trend strength scoring (Epic 05, Task 001)
        # Senex Trident prefers range-bound markets (weak trends) like credit spreads
        if report.adx is not None:
            if report.adx > 30:
                score -= 20
                reasons.append(
                    f"Strong trend (ADX {report.adx:.1f}) - Senex Trident not suitable for trending markets"
                )
            elif report.adx < 20:
                score += 10
                reasons.append(
                    f"Weak trend (ADX {report.adx:.1f}) - favorable for range-bound credit strategy"
                )
            else:
                reasons.append(f"Moderate trend (ADX {report.adx:.1f}) - acceptable but not ideal")

        # HV/IV ratio scoring (Epic 05, Task 003)
        # Premium selling strategies prefer high IV relative to realized volatility
        if report.hv_iv_ratio < 0.8:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV high relative to realized, "
                "excellent premium selling opportunity"
            )
        elif report.hv_iv_ratio > 1.2:
            score -= 8
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV low relative to realized, "
                "poor premium collection"
            )

        # Neutral market preference (credit spreads benefit from sideways) - Epic 22, Task 024
        # Senex Trident has slight bearish tilt (2 put spreads + 1 call spread)
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market suits Senex Trident credit spread structure")
        elif report.macd_signal == "bearish_exhausted":
            score += 12
            reasons.append(
                "Bearish exhausted - potential consolidation favorable for Senex Trident"
            )
        elif report.macd_signal == "bullish_exhausted":
            score += 10
            reasons.append("Bullish exhausted - potential pullback suits slight bearish tilt")
        elif report.macd_signal == "bearish":
            score += 8
            reasons.append("Bearish direction - acceptable for Senex Trident's slight bearish tilt")
        elif report.macd_signal == "bullish":
            score += 5
            reasons.append("Bullish direction - manageable for Senex Trident")
        elif report.macd_signal == "strong_bullish":
            score -= 5
            reasons.append("Strong bullish trend - not ideal for Senex Trident")
        elif report.macd_signal == "strong_bearish":
            score += 0
            reasons.append("Strong bearish trend - neutral for Senex Trident")

        # Volatility environment
        if report.market_stress_level < 30:
            score += 10
            reasons.append("Low market stress - favorable for defined risk")
        elif report.market_stress_level > 70:
            score -= 15
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - increased risk"
            )

        # Price position (prefer within range)
        if report.bollinger_position == "within_bands":
            score += 5
            reasons.append("Price within Bollinger Bands")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 5
            reasons.append(
                f"Price at extreme ({report.bollinger_position}) - potential reversal risk"
            )

        # RSI extremes (Epic 22 Enhancement - increased mean reversion risk for neutral strategy)
        if report.rsi is not None:
            if report.rsi > 70 or report.rsi < 30:
                score -= 15
                reasons.append(
                    f"Extreme RSI ({report.rsi:.1f}) - high mean reversion risk "
                    "for neutral strategy"
                )
            elif report.rsi > 60 or report.rsi < 40:
                score -= 5
                reasons.append(f"RSI {report.rsi:.1f} shows directional bias")
            elif 45 <= report.rsi <= 55:
                score += 10
                reasons.append(f"Neutral RSI ({report.rsi:.1f}) - ideal for range-bound strategy")

        # Ensure score doesn't go below zero (no upper limit)
        score = max(0, score)

        explanation = " | ".join(reasons) if reasons else "Base scoring"

        logger.info(
            "Market scoring complete for %s: final_score=%.1f (base=50, factors=%d) - %s",
            report.symbol,
            score,
            len(reasons),
            "PASS" if score >= 40 else "REJECT",
        )

        return (score, explanation)

    async def a_prepare_suggestion_context(
        self, symbol: str | None = None, report: dict | None = None, suggestion_mode: bool = False
    ) -> dict | None:
        """
        Prepare suggestion context WITHOUT sending to channel layer.

        This method extracts the context preparation logic so automated
        tasks can call the stream manager directly instead of using
        channel layer messaging.

        Args:
            symbol: Optional symbol override (defaults to config value)
            report: Optional pre-computed market report
            suggestion_mode: If True, skip risk validation (for email suggestions)

        Returns:
            Optional[dict]: Context dict ready for a_process_suggestion_request(),
                            or None if conditions not suitable
        """
        config = await self.a_get_active_config()
        if not config:
            logger.info(f"No active Senex Trident configuration for user {self.user.id}")
            return None

        params = config.get_senex_parameters()
        # Use provided symbol or get from config
        if not symbol:
            symbol = params.get("underlying_symbol", "QQQ")

        # Validate market conditions
        if not report:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            # The validator fetches the snapshot and returns a report object
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        logger.info("User %s: Scoring market conditions for %s...", self.user.id, symbol)
        score, explanation = await self.a_score_market_conditions(report)

        if score < 40:
            logger.info(
                "User %s: Score too low (%.1f < 40) - %s not suitable for Senex Trident",
                self.user.id,
                score,
                symbol,
            )
            return None

        logger.info(
            "User %s: ✅ Market conditions acceptable for %s (score=%.1f)",
            self.user.id,
            symbol,
            score,
        )

        # Convert report to market_snapshot dict for downstream usage
        market_snapshot = asdict(report)
        # Add derived field: near_bollinger_band based on bollinger_position
        market_snapshot["near_bollinger_band"] = report.bollinger_position in [
            "above_upper",
            "below_lower",
        ]

        # Calculate position parameters
        tradeable_capital, is_available = await self.risk_manager.a_get_tradeable_capital()
        spread_width = config.get_spread_width(tradeable_capital) if is_available else 3

        current_price = self._get_current_price(market_snapshot)
        if not current_price:
            logger.warning(f"No current price available for {symbol}")
            return None

        # Calculate required strikes BEFORE expiration lookup
        logger.info(
            "User %s: Selecting strikes for %s at $%.2f (spread_width=%s)...",
            self.user.id,
            symbol,
            current_price,
            spread_width,
        )
        strikes = self._select_even_strikes(current_price, spread_width)
        if not strikes:
            logger.warning(
                "User %s: Could not select appropriate strikes for %s at $%.2f (spread_width=%s)",
                self.user.id,
                symbol,
                current_price,
                spread_width,
            )
            return None

        logger.info(
            "User %s: Selected strikes for %s: put_short=%s, put_long=%s, call_short=%s, call_long=%s",
            self.user.id,
            symbol,
            strikes.get("put_short"),
            strikes.get("put_long"),
            strikes.get("call_short"),
            strikes.get("call_long"),
        )

        # Find expiration with exact strikes (Senex Trident requires strict matching)
        logger.info(
            "User %s: Finding expiration for %s (min_dte=%s, max_dte=%s)...",
            self.user.id,
            symbol,
            params.get("min_dte", 30),
            params.get("max_dte", 45),
        )
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            strikes,
            min_dte=params.get("min_dte", 30),
            max_dte=params.get("max_dte", 45),
        )
        if not result:
            logger.warning(
                "User %s: No expiration found for %s with required strikes %s (min_dte=%s, max_dte=%s)",
                self.user.id,
                symbol,
                strikes,
                params.get("min_dte", 30),
                params.get("max_dte", 45),
            )
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using validated expiration {expiration} "
            f"with all required strikes available"
        )

        # Build OCC bundle (strikes already validated)
        logger.info(f"User {self.user.id}: Building OCC bundle for {symbol} {expiration}")
        occ_bundle = await self.options_service.build_occ_bundle(symbol, expiration, strikes)
        if not occ_bundle:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundle")
            return None

        # Prepare context (same structure as before)
        serializable_market_snapshot = TradingSuggestionSerializer.convert_decimals_to_floats(
            market_snapshot
        )

        context = {
            "config_id": config.id,
            "market_snapshot": serializable_market_snapshot,
            "spread_width": spread_width,
            "strikes": strikes,
            "current_price": current_price,
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,  # Pass through for risk bypass
            # NOTE: is_automated will be set by caller (manual=False, automated=True)
        }

        logger.info(f"User {self.user.id}: ✅ Context prepared for suggestion generation")
        return context

    async def a_request_suggestion_generation(self, report=None, symbol=None) -> None:
        """
        Request suggestion generation via channel layer (manual flow).

        This method is used by the UI-initiated flow where a WebSocket
        consumer will receive and process the request.

        Args:
            report: Optional market report (unused - Trident uses channel layer flow)
            symbol: Optional symbol (unused - Trident gets symbol from config)
        """
        # Prepare context using new method
        context = await self.a_prepare_suggestion_context()
        if not context:
            return

        # Mark as manual (not automated)
        context["is_automated"] = False

        # Dispatch to stream manager
        await self.a_dispatch_to_stream_manager(context)
        logger.info(f"User {self.user.id}: 🚀 Dispatched suggestion request to stream manager")

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """
        Calculates the final suggestion using live data from the cache.
        This method is called by the UserStreamManager.

        NEW: Returns TradingSuggestion object instead of dict
        NEW: Sets is_automated flag from context during creation
        """
        from services.streaming.dataclasses import SenexOccBundle

        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)

        if not pricing_data:
            logger.warning("Pricing data not found in cache for suggestion calculation.")
            return None

        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        market_snapshot = context["market_snapshot"]
        spread_width = context["spread_width"]
        strikes = context["strikes"]
        current_price = Decimal(str(context["current_price"]))
        symbol = occ_bundle.underlying
        expiration = occ_bundle.expiration

        # Extract is_automated flag from context (NEW)
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)

        call_quantity = 1  # Always 1 call spread for proper Trident structure

        # Pricing data returns per-spread credits
        # Senex Trident has 2 put spreads + 1 call spread, so calculate total accordingly
        put_credit = pricing_data.put_credit
        call_credit = pricing_data.call_credit
        total_credit = (put_credit * Decimal("2")) + call_credit

        # Mid-price credit (for UI display)
        put_mid_credit = pricing_data.put_mid_credit
        call_mid_credit = pricing_data.call_mid_credit
        total_mid_credit = (put_mid_credit * Decimal("2")) + call_mid_credit

        # Calculate max_risk using mid-price credits for UI consistency
        # (Max Profit uses mid-price, so Max Loss should match)
        max_risk = self.position_calculator.calculate_senex_trident_risk(
            spread_width, put_mid_credit, call_mid_credit, 2, call_quantity
        )

        # For internal risk management, we could calculate conservative risk separately:
        # conservative_risk = self.position_calculator.calculate_senex_trident_risk(
        #     spread_width, put_credit, call_credit, 2, call_quantity
        # )

        # Calculate max profit for credit spread
        # Senex Trident is a credit spread (2 put spreads + 1 call spread)
        total_max_profit = calculate_max_profit_credit_spread(
            total_mid_credit, quantity=(2 + call_quantity)  # 2 put spreads + call spread(s)
        )

        # CRITICAL FIX: Honor suggestion_mode flag (Epic 24 Task 006)
        if not suggestion_mode:
            # Only check risk budget when EXECUTING (not suggesting)
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk, is_stressed=market_snapshot.get("is_stressed", False)
            )
            if not can_open:
                logger.info(
                    f"User {self.user.id}: Risk budget insufficient for Senex Trident "
                    f"(max risk: ${max_risk:.2f})"
                )
                # Return error info dict instead of None for proper UI feedback
                return {
                    "error": True,
                    "error_type": "risk_budget_exceeded",
                    "message": reason,
                    "max_risk": float(max_risk),
                    "strategy": "senex_trident",
                }
        else:
            logger.info(
                f"User {self.user.id}: Suggestion mode enabled - skipping risk validation "
                f"for Senex Trident"
            )

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=current_price,
            expiration_date=expiration,
            short_put_strike=strikes["short_put"],
            long_put_strike=strikes["long_put"],
            short_call_strike=strikes["short_call"],  # Always present in Senex Trident
            long_call_strike=strikes["long_call"],  # Always present in Senex Trident
            put_spread_quantity=2,  # Two put spreads (each creates one profit target)
            call_spread_quantity=call_quantity,
            # Natural credit (for risk calculations)
            put_spread_credit=put_credit,
            call_spread_credit=call_credit,  # Always included
            total_credit=total_credit,
            # Mid-price credit (for UI display)
            put_spread_mid_credit=put_mid_credit,
            call_spread_mid_credit=call_mid_credit,
            total_mid_credit=total_mid_credit,
            max_risk=max_risk,
            price_effect=PriceEffect.CREDIT.value,  # Senex Trident always receives credit
            max_profit=total_max_profit,  # Calculated max profit
            iv_rank=market_snapshot.get("iv_rank"),
            is_near_bollinger_band=market_snapshot.get("near_bollinger_band", False),
            is_range_bound=market_snapshot.get("is_range_bound", False),
            market_stress_level=market_snapshot.get("market_stress_level"),
            market_conditions=market_snapshot,
            has_real_pricing=pricing_data.has_real_pricing,
            pricing_source=pricing_data.source,
            streaming_latency_ms=pricing_data.latency_ms,
            expires_at=timezone.now() + timedelta(hours=24),
            is_automated=is_automated,  # NEW - set during creation
        )

        # CRITICAL ASSERTION: Catch incorrect quantities immediately in development
        assert suggestion.put_spread_quantity == 2, (
            f"BUG: Senex Trident must have put_spread_quantity=2, got {suggestion.put_spread_quantity}. "
            f"This is a critical bug that will cause order submission failures."
        )
        assert suggestion.call_spread_quantity == call_quantity, (
            f"BUG: call_spread_quantity mismatch: expected {call_quantity}, "
            f"got {suggestion.call_spread_quantity}"
        )

        logger.info(f"Created suggestion {suggestion.id} (automated={is_automated})")

        # Always return TradingSuggestion object - stream manager handles serialization
        return suggestion

    def get_active_config(self) -> StrategyConfiguration | None:
        """Get active Senex Trident configuration for user"""
        return StrategyConfiguration.objects.filter(
            user=self.user, strategy_id="senex_trident", is_active=True
        ).first()

    async def a_get_active_config(self) -> StrategyConfiguration | None:
        """Get active Senex Trident configuration for user (async)"""
        return await StrategyConfiguration.objects.filter(
            user=self.user, strategy_id="senex_trident", is_active=True
        ).afirst()

    def _find_target_expiration(self, params: dict, available_dates: list[date]) -> date | None:
        """
        Finds the optimal expiration date from a list of available dates.
        The optimal date is the one closest to the target DTE, while still
        being within the min and max DTE range.
        """
        today = timezone.now().date()
        target_dte = params.get("target_dte", 45)
        min_dte = params.get("min_dte", 30)
        max_dte = params.get("max_dte", 45)  # User specified 30-45 day window

        # Filter for dates within the allowed DTE range
        valid_expirations = []
        for exp_date in available_dates:
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                valid_expirations.append(exp_date)

        if not valid_expirations:
            logger.warning(f"No expirations found between {min_dte} and {max_dte} DTE.")
            return None

        # From the valid dates, find the one closest to the target DTE
        best_date = min(valid_expirations, key=lambda d: abs((d - today).days - target_dte))

        logger.info(f"Found best expiration {best_date} with DTE of {(best_date - today).days}")
        return best_date

    def _get_current_price(self, market_snapshot: dict) -> Decimal | None:
        """Extract current price from market snapshot"""
        # Use direct real-time price, not from Bollinger bands
        current_price = market_snapshot.get("current_price")

        if current_price:
            return Decimal(str(current_price))

        return None

    def _select_even_strikes(
        self, current_price: Decimal, spread_width: int
    ) -> dict[str, Decimal] | None:
        """
        Select strikes for Senex Trident using correct inner body logic.

        Trident Structure:
        - Inner body (short strikes): round(price/2)*2 - ensures even strike
        - Both short put and short call use the SAME inner body strike
        - Long put = inner_body - spread_width
        - Long call = inner_body + spread_width
        - Results in 2:1 put to call spread ratio
        """
        # Calculate inner body using shared utility
        inner_strike = round_to_even_strike(current_price)

        # Trident structure: Both short strikes are the same (inner body)
        short_put = inner_strike
        short_call = inner_strike

        # Long strikes are offset by spread width
        long_put = short_put - Decimal(str(spread_width))
        long_call = short_call + Decimal(str(spread_width))

        return {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call,
        }

    def validate_strikes(
        self, strikes: dict[str, Decimal], available_strikes: list[Decimal]
    ) -> bool:
        """
        Validate that all required Senex Trident strikes exist in option chain.

        Args:
            strikes: Dict containing short_put, long_put, short_call, long_call
            available_strikes: List of available strikes from option chain

        Returns:
            bool: True if all required strikes are available
        """
        required_strikes = [
            strikes["short_put"],
            strikes["long_put"],
            strikes["short_call"],
            strikes["long_call"],
        ]
        available_set = set(available_strikes)
        return all(strike in available_set for strike in required_strikes)

    def calculate_base_strike(self, current_price: Decimal) -> Decimal:
        """
        Calculate even strike for Senex Trident inner body (short strikes).

        This is a public method exposed for testing and validation.
        Uses the mandatory Senex Trident formula: round(price/2)*2

        Args:
            current_price: Current underlying price

        Returns:
            Decimal: Even strike price for inner body
        """
        return Decimal(str(round(float(current_price) / 2) * 2))

    async def a_get_profit_target_specifications(self, position, trade) -> list:
        """
        Generate profit target order specifications for Senex Trident strategy.

        Profit targets are dynamically configured per strategy configuration.
        For credit spreads, X% profit means buying back at (100-X)% of original credit.

        Args:
            position: Position object with metadata
            trade: Opening trade object

        Returns:
            List[ProfitTargetSpec]: List of profit target specifications
        """
        from services.orders.spec import OrderSpec, ProfitTargetSpec
        from trading.models import TradingSuggestion

        try:
            # Get suggestion data from position metadata
            metadata = position.metadata or {}
            suggestion_id = metadata.get("suggestion_id")

            if not suggestion_id:
                logger.error(f"No suggestion_id in position {position.id} metadata")
                return []

            suggestion = await TradingSuggestion.objects.aget(id=suggestion_id)
            profit_targets = []

            # Get profit target percentages from configuration
            config = await self.a_get_active_config()
            params = config.get_senex_parameters() if config else {}
            put_spread_1_target = params.get("put_spread_1_target", 40.0)
            put_spread_2_target = params.get("put_spread_2_target", 60.0)
            call_spread_target = params.get("call_spread_target", 40.0)

            # 1. Put Spread #1 - configurable profit target
            if suggestion.put_spread_quantity >= 1 and suggestion.put_spread_mid_credit:
                from services.strategies.utils.pricing_utils import round_option_price

                closing_multiplier = (Decimal("100") - Decimal(str(put_spread_1_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.put_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_put": suggestion.short_put_strike,
                    "long_put": suggestion.long_put_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "put_spread_1",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Put Spread #1 - {int(put_spread_1_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,  # Closing a credit spread requires paying debit
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="put_spread_1",
                        profit_percentage=int(put_spread_1_target),
                        original_credit=suggestion.put_spread_mid_credit,
                    )
                )

            # 2. Put Spread #2 - configurable profit target
            if suggestion.put_spread_quantity >= 2 and suggestion.put_spread_mid_credit:
                closing_multiplier = (Decimal("100") - Decimal(str(put_spread_2_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.put_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_put": suggestion.short_put_strike,
                    "long_put": suggestion.long_put_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "put_spread_2",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Put Spread #2 - {int(put_spread_2_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,  # Closing a credit spread requires paying debit
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="put_spread_2",
                        profit_percentage=int(put_spread_2_target),
                        original_credit=suggestion.put_spread_mid_credit,
                    )
                )

            # 3. Call Spread - configurable profit target
            if suggestion.call_spread_quantity >= 1 and suggestion.call_spread_mid_credit:
                closing_multiplier = (Decimal("100") - Decimal(str(call_spread_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.call_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_call": suggestion.short_call_strike,
                    "long_call": suggestion.long_call_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "call_spread",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Call Spread - {int(call_spread_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,  # Closing a credit spread requires paying debit
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="call_spread",
                        profit_percentage=int(call_spread_target),
                        original_credit=suggestion.call_spread_mid_credit,
                    )
                )

            logger.info(
                f"Generated {len(profit_targets)} profit target specs for position {position.id}"
            )
            return profit_targets

        except Exception as e:
            logger.error(f"Failed to generate profit target specs for position {position.id}: {e}")
            return []

    def get_profit_target_specifications_sync(self, position, trade) -> list:
        """
        Synchronous version for getting profit target specifications.
        Uses sync DB calls to avoid async context issues.
        """
        from services.orders.spec import OrderSpec, ProfitTargetSpec
        from services.strategies.utils.pricing_utils import round_option_price

        try:
            suggestion_id = position.metadata.get("suggestion_id") if position.metadata else None
            if not suggestion_id:
                logger.warning(f"Position {position.id} has no suggestion_id in metadata")
                return []

            suggestion = TradingSuggestion.objects.get(id=suggestion_id)
            profit_targets = []

            # Get profit target percentages from configuration
            config = self.get_active_config()
            params = config.get_senex_parameters() if config else {}
            put_spread_1_target = params.get("put_spread_1_target", 40.0)
            put_spread_2_target = params.get("put_spread_2_target", 60.0)
            call_spread_target = params.get("call_spread_target", 40.0)

            # 1. Put Spread #1 - configurable profit target
            if suggestion.put_spread_quantity >= 1 and suggestion.put_spread_mid_credit:
                closing_multiplier = (Decimal("100") - Decimal(str(put_spread_1_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.put_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_put": suggestion.short_put_strike,
                    "long_put": suggestion.long_put_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "put_spread_1",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Put Spread #1 - {int(put_spread_1_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="put_spread_1",
                        profit_percentage=int(put_spread_1_target),
                        original_credit=suggestion.put_spread_mid_credit,
                    )
                )

            # 2. Put Spread #2 - configurable profit target
            if suggestion.put_spread_quantity >= 2 and suggestion.put_spread_mid_credit:
                closing_multiplier = (Decimal("100") - Decimal(str(put_spread_2_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.put_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_put": suggestion.short_put_strike,
                    "long_put": suggestion.long_put_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "put_spread_2",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Put Spread #2 - {int(put_spread_2_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="put_spread_2",
                        profit_percentage=int(put_spread_2_target),
                        original_credit=suggestion.put_spread_mid_credit,
                    )
                )

            # 3. Call Spread - configurable profit target
            if suggestion.call_spread_quantity >= 1 and suggestion.call_spread_mid_credit:
                closing_multiplier = (Decimal("100") - Decimal(str(call_spread_target))) / Decimal(
                    "100"
                )
                raw_price = suggestion.call_spread_mid_credit * closing_multiplier
                target_price = round_option_price(raw_price, suggestion.underlying_symbol)
                strikes = {
                    "short_call": suggestion.short_call_strike,
                    "long_call": suggestion.long_call_strike,
                }
                closing_legs = build_closing_spread_legs(
                    suggestion.underlying_symbol,
                    suggestion.expiration_date,
                    "call_spread",
                    strikes,
                    quantity=1,
                )

                order_spec = OrderSpec(
                    legs=closing_legs,
                    limit_price=target_price,
                    time_in_force="GTC",
                    description=f"Senex Call Spread - {int(call_spread_target)}% Profit Target",
                    price_effect=PriceEffect.DEBIT.value,
                )

                profit_targets.append(
                    ProfitTargetSpec(
                        order_spec=order_spec,
                        spread_type="call_spread",
                        profit_percentage=int(call_spread_target),
                        original_credit=suggestion.call_spread_mid_credit,
                    )
                )

            logger.info(
                f"Generated {len(profit_targets)} profit target specs for position {position.id}"
            )
            return profit_targets

        except Exception as e:
            logger.error(f"Failed to generate profit target specs for position {position.id}: {e}")
            return []

    async def build_opening_legs(self, context: dict):
        """
        Build 6 opening legs for Senex Trident: 2 put spreads + 1 call spread.

        Epic 22 Task 026: Strategy-owned order building.

        Senex Trident structure:
        - 2 contracts of put spread (sell 2 short puts, buy 2 long puts)
        - 1 contract of call spread (sell 1 short call, buy 1 long call)
        Total: 6 legs
        """
        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.sdk.instruments import get_option_instruments_bulk

        session = context["session"]
        underlying = context["underlying_symbol"]
        expiration = context["expiration_date"]
        strikes = context["strikes"]
        put_quantity = context.get("put_quantity", 2)  # Default: 2 put spreads
        call_quantity = context.get("call_quantity", 1)  # Default: 1 call spread

        # Build specs for all 4 unique options
        specs = [
            # Put spread
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["short_put"],
                "option_type": "P",
            },
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["long_put"],
                "option_type": "P",
            },
            # Call spread
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["short_call"],
                "option_type": "C",
            },
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["long_call"],
                "option_type": "C",
            },
        ]

        # Fetch instruments in bulk
        instruments = await get_option_instruments_bulk(session, specs)

        # Build 6 legs: 2 put spreads + 1 call spread
        return [
            # Put spread (quantity 2)
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.SELL_TO_OPEN,
                quantity=put_quantity,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.BUY_TO_OPEN,
                quantity=put_quantity,
            ),
            # Call spread (quantity 1)
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[2].symbol,
                action=OrderAction.SELL_TO_OPEN,
                quantity=call_quantity,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[3].symbol,
                action=OrderAction.BUY_TO_OPEN,
                quantity=call_quantity,
            ),
        ]

    async def build_closing_legs(self, position):
        """
        Build 6 closing legs for Senex Trident.

        Epic 22 Task 026: Strategy-owned order building.
        """
        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        # Extract position data
        underlying = position.underlying_symbol
        expiration = position.expiration_date
        strikes = position.strikes
        put_quantity = position.put_spread_quantity  # Usually 2
        call_quantity = position.call_spread_quantity  # Usually 1

        # Get session using correct pattern
        account = await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(account)

        # Build specs (same as opening)
        specs = [
            # Put spread
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["short_put"],
                "option_type": "P",
            },
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["long_put"],
                "option_type": "P",
            },
            # Call spread
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["short_call"],
                "option_type": "C",
            },
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes["long_call"],
                "option_type": "C",
            },
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        # Closing: opposite actions
        return [
            # Put spread (quantity 2)
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=put_quantity,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.SELL_TO_CLOSE,
                quantity=put_quantity,
            ),
            # Call spread (quantity 1)
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[2].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=call_quantity,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[3].symbol,
                action=OrderAction.SELL_TO_CLOSE,
                quantity=call_quantity,
            ),
        ]
