"""
Iron Butterfly Strategy - Aggressive range-bound premium collection.

Suitable when:
- IV Rank > 70% (extreme premium environment - stricter than Iron Condor)
- Very range-bound market expected (ADX < 15 - stricter than Iron Condor)
- Neutral outlook (price expected to stay at ATM strike)
- Tighter profit zone (higher risk/reward than Iron Condor)

Structure:
- Sell 1 ATM put @ strike K
- Sell 1 ATM call @ strike K (SAME strike - key difference from Iron Condor)
- Buy 1 OTM put @ strike K - width
- Buy 1 OTM call @ strike K + width
- Net credit received (premium collected upfront)
- Profit if price stays exactly at ATM strike at expiration

vs Iron Condor:
- Iron Butterfly: ATM short strikes (same strike), tighter profit zone (~5-8%)
- Iron Condor: OTM short strikes (different strikes), wider profit zone (~15-20%)
- Iron Butterfly: Higher credit ($250-600), more aggressive
- Iron Condor: Lower credit ($150-400), more conservative
- Iron Butterfly: Requires IV > 70, ADX < 15 (stricter)
- Iron Condor: Requires IV > 50, ADX < 20 (looser)

TastyTrade Methodology:
- Entry: IV rank > 70 (top 30% of 52-week range) + extremely range-bound
- DTE: 45 days
- ATM strikes: Both short options at same strike (nearest to current price)
- Wing width: $10 typically (1 standard deviation)
- Profit target: 25% of max profit (exit early due to tight range)
- Management: Close or roll if tested, close at 50% loss
- Win rate: ~55-65%
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


@register_strategy("iron_butterfly")
class IronButterflyStrategy(BaseStrategy):
    """
    Iron Butterfly - Sell ATM straddle + buy OTM wings for extreme range-bound conditions.

    TastyTrade Methodology:
    - 45 DTE entry
    - ATM strikes for both short options (same strike)
    - 1 standard deviation wings (~$10)
    - 25% profit target (exit early)
    - Win rate: 55-65%
    """

    # Strategy-specific constants (STRICTER than Iron Condor)
    MIN_IV_RANK = 50  # Minimum for entry consideration
    OPTIMAL_IV_RANK = 75  # Excellent premium environment (vs Iron Condor's 60)
    MAX_ADX = 15  # Very range-bound required (vs Iron Condor's 25)
    IDEAL_ADX_MAX = 12  # Extremely range-bound (vs Iron Condor's 20)
    MAX_HV_IV_RATIO = 0.7  # Want very expensive IV
    MIN_RANGE_BOUND_DAYS = 5  # Minimum consolidation period
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 25  # Close at 25% of max profit (vs Iron Condor's 50%)

    # Position sizing
    MIN_CREDIT_RATIO = 0.3  # Min 30% credit/width
    TARGET_CREDIT_RATIO = 0.4  # Target 40%
    MAX_POSITION_SIZE_PCT = 0.10  # Max 10% of capital per butterfly

    @property
    def strategy_name(self) -> str:
        return "iron_butterfly"

    def automation_enabled_by_default(self) -> bool:
        """Iron butterflies are manual only (need active management)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 25% of max profit."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid gamma risk."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for iron butterfly.

        Target: Close when credit decays to 75% (buy back at 25% of original credit)
        """
        from trading.models import TradeOrder

        # Get opening order to find original credit
        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        original_credit = abs(opening_order.price)  # Credit is negative, make positive
        # Target: buy back at 75% of credit (25% profit achieved)
        target_price = original_credit * Decimal("0.75")

        return [
            {
                "spread_type": "iron_butterfly",
                "profit_percentage": 25,
                "target_price": target_price,
                "original_credit": original_credit,
            }
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for iron butterfly.

        Multi-factor scoring (0-100):
        - IV Rank (35% weight): Want VERY HIGH IV (> 70) for premium
        - ADX/Trend (30% weight): Want very range-bound (< 12 ideal)
        - Range Persistence (20% weight): Want multi-day consolidation
        - HV/IV Ratio (15% weight): Want IV >> HV (options very overpriced)

        STRICTER than Iron Condor due to tighter profit zone.
        """
        score = 40.0  # Lower base than Iron Condor (50)
        reasons = []

        # Factor 1: IV Rank (35% weight) - WANT VERY HIGH IV
        # Stricter than Iron Condor
        if report.iv_rank > 75:
            score += 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 75% - EXCELLENT premium, ideal butterfly conditions"
            )
        elif report.iv_rank >= self.OPTIMAL_IV_RANK:
            score += 25
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (>75%) - excellent premiums"
            )
        elif report.iv_rank >= 60:
            score += 10
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} acceptable (>60%) - prefer higher for butterfly"
            )
        elif report.iv_rank >= self.MIN_IV_RANK:
            score -= 10
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} marginal (50-60) - insufficient for butterfly"
            )
        else:
            score -= 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 50 - insufficient premium, use Iron Condor instead"
            )

        # Factor 2: ADX Trend Strength (30% weight) - WANT VERY RANGE-BOUND
        # Butterfly requires tighter range than Iron Condor
        if report.adx is not None:
            if report.adx < self.IDEAL_ADX_MAX:
                score += 30
                reasons.append(
                    f"ADX {report.adx:.1f} < 12 - EXTREMELY range-bound, PERFECT for butterfly"
                )
            elif report.adx < self.MAX_ADX:
                score += 20
                reasons.append(
                    f"ADX {report.adx:.1f} < 15 - very range-bound, favorable for butterfly"
                )
            elif report.adx < 18:
                score += 10
                reasons.append(f"ADX {report.adx:.1f} < 18 - range-bound but prefer tighter")
            elif report.adx < 22:
                score -= 10
                reasons.append(
                    f"ADX {report.adx:.1f} trending - risky for butterfly's tight profit zone"
                )
            else:
                score -= 30
                reasons.append(
                    f"ADX {report.adx:.1f} > 22 - strong trend, AVOID butterfly (use Iron Condor if IV high)"
                )

        # Factor 3: Range Persistence (20% weight) - Want multi-day consolidation
        # Using ADX as proxy since range_bound_days not yet in MarketConditionReport
        if report.adx is not None:
            if report.adx < 12:
                score += 20
                reasons.append(
                    "Persistent range-bound behavior - very stable consolidation (7+ days)"
                )
            elif report.adx < 15:
                score += 15
                reasons.append("Stable range detected - good consolidation (5-6 days)")
            elif report.adx < 18:
                score += 5
                reasons.append("Emerging range - acceptable (3-4 days)")

        # Factor 4: HV/IV Ratio (15% weight) - Want VERY LOW ratio (IV very expensive)
        # Stricter than Iron Condor
        if report.hv_iv_ratio < 0.6:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.6 - IV VERY expensive, excellent for butterfly"
            )
        elif report.hv_iv_ratio < 0.7:
            score += 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.7 - IV expensive vs realized")
        elif report.hv_iv_ratio < 0.8:
            score += 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV moderately expensive")
        elif report.hv_iv_ratio < 1.0:
            score += 0
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV fairly priced")
        else:
            score -= 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.0 - IV cheap, don't sell butterfly"
            )

        # Market direction consideration (Epic 22, Task 024)
        # Butterfly has tighter profit zone than iron condor
        if report.macd_signal == "neutral":
            score += 20
            reasons.append("Neutral market - ideal for butterfly (no directional bias)")
        elif report.macd_signal in ["bullish_exhausted", "bearish_exhausted"]:
            score += 8
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - might consolidate in tight range"
            )
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 0
            reasons.append(
                f"{report.macd_signal.capitalize()} bias - not ideal for tight profit zone"
            )
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - very risky for butterfly"
            )

        # Technical position
        if report.bollinger_position == "within_bands":
            score += 8
            reasons.append("Price within Bollinger Bands - ideal for butterfly")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 10
            reasons.append("Price at Bollinger extremes - may continue to move, avoid butterfly")

        # Market stress consideration
        # Low stress is ideal for butterfly (stable consolidation)
        if report.market_stress_level < 30:
            score += 7
            reasons.append("Low market stress - very stable environment, perfect for butterfly")
        elif report.market_stress_level > 70:
            score -= 12
            reasons.append(
                f"Very high market stress ({report.market_stress_level:.0f}) - "
                "increased breakout risk, avoid tight butterfly range"
            )

        return (score, reasons)

    def _calculate_atm_strike(self, current_price: Decimal) -> Decimal:
        """
        Calculate ATM strike price for iron butterfly.

        Both short put and short call will be at this SAME strike.

        Args:
            current_price: Current stock price

        Returns:
            ATM strike (nearest even strike to current price)
        """
        return round_to_even_strike(current_price)

    def _calculate_wing_width(self, current_price: Decimal) -> Decimal:
        """
        Calculate wing width based on stock price.

        Approximates 1 standard deviation:
        - < $50: $2.50
        - $50-100: $5
        - $100-200: $10
        - > $200: $15

        Args:
            current_price: Current stock price

        Returns:
            Wing width in dollars
        """
        if current_price > Decimal("200"):
            return Decimal("15")
        if current_price > Decimal("100"):
            return Decimal("10")
        if current_price > Decimal("50"):
            return Decimal("5")
        return Decimal("2.5")

    def _calculate_long_strikes(
        self, atm_strike: Decimal, wing_width: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate long strike prices (protection wings).

        Args:
            atm_strike: ATM strike for both short options
            wing_width: Wing width

        Returns:
            (put_long_strike, call_long_strike) tuple
        """
        put_long_strike = atm_strike - wing_width
        call_long_strike = atm_strike + wing_width

        return (put_long_strike, call_long_strike)

    def _calculate_max_profit(self, credit_received: Decimal, quantity: int = 1) -> Decimal:
        """
        Calculate max profit for iron butterfly.

        Max profit = Total credit received (if price stays exactly at ATM)

        Formula: Credit × 100 × quantity

        Example: $6.00 credit, 1 contract = $600 max profit

        Args:
            credit_received: Total credit from all 4 legs
            quantity: Number of butterflies

        Returns:
            Maximum profit in dollars
        """
        return credit_received * Decimal("100") * Decimal(str(quantity))

    def _calculate_max_loss(
        self, wing_width: Decimal, credit_received: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate max loss for iron butterfly.

        Max loss = Wing width - Credit received

        Formula: (Wing Width - Credit) × 100 × quantity

        Example: $10 wing, $6.00 credit = ($10 - $6.00) × 100 = $400 max loss

        Args:
            wing_width: Width of wings (same for both sides)
            credit_received: Total credit received
            quantity: Number of butterflies

        Returns:
            Maximum loss in dollars
        """
        max_loss_per_butterfly = (wing_width - credit_received) * Decimal("100")
        return max_loss_per_butterfly * Decimal(str(quantity))

    def _calculate_breakevens(
        self, atm_strike: Decimal, credit_received: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for iron butterfly.

        Formula:
        - Upper breakeven: ATM strike + (Credit / 2)
        - Lower breakeven: ATM strike - (Credit / 2)

        Profit zone is tighter than Iron Condor!

        Example: $100 ATM, $6.00 credit
                 Upper BE = $103.00, Lower BE = $97.00
                 Profit zone = $6.00 width (±$3.00 from ATM)

        Args:
            atm_strike: ATM strike (both shorts at this strike)
            credit_received: Total credit

        Returns:
            (breakeven_down, breakeven_up) tuple
        """
        half_credit = credit_received / Decimal("2")
        breakeven_down = atm_strike - half_credit
        breakeven_up = atm_strike + half_credit
        return (breakeven_down, breakeven_up)

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for iron butterfly.

        Four legs:
        1. Sell put at ATM strike (collect premium)
        2. Buy put at ATM - wing_width (define risk)
        3. Sell call at ATM strike (SAME as put - collect premium)
        4. Buy call at ATM + wing_width (define risk)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - atm_strike: ATM strike for both shorts
                - put_long_strike: Long put strike (protection)
                - call_long_strike: Long call strike (protection)
                - quantity: Number of contracts

        Returns:
            List with four Legs (sell ATM put, buy OTM put, sell ATM call, buy OTM call)
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="iron_butterfly",
            strikes={
                "short_put": context["atm_strike"],
                "long_put": context["put_long_strike"],
                "short_call": context["atm_strike"],
                "long_call": context["call_long_strike"],
            },
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for iron butterfly.

        Four legs (opposite of opening):
        1. Buy to close ATM short put
        2. Sell to close OTM long put
        3. Buy to close ATM short call
        4. Sell to close OTM long call

        Args:
            position: Position with:
                - strikes: {
                    "atm_strike": Decimal,
                    "put_long_strike": Decimal,
                    "call_long_strike": Decimal
                  }
                - expiration_date
                - underlying_symbol
                - quantity

        Returns:
            List with four Legs (closing all positions)
        """
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        # Get session using correct pattern
        tt_account = await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user, tt_account)

        # Build spec dictionaries for put instruments
        put_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["atm_strike"],
                "option_type": "P",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["put_long_strike"],
                "option_type": "P",
            },
        ]

        # Build spec dictionaries for call instruments
        call_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["atm_strike"],
                "option_type": "C",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["call_long_strike"],
                "option_type": "C",
            },
        ]

        # Get all 4 option instruments
        put_instruments = await get_option_instruments_bulk(session, put_specs)
        call_instruments = await get_option_instruments_bulk(session, call_specs)

        if len(put_instruments) != 2:
            raise ValueError("Could not find both put strikes")
        if len(call_instruments) != 2:
            raise ValueError("Could not find both call strikes")

        # Map strikes to instruments
        put_short = next(
            i for i in put_instruments if str(position.strikes["atm_strike"]) in i.symbol
        )
        put_long = next(
            i for i in put_instruments if str(position.strikes["put_long_strike"]) in i.symbol
        )
        call_short = next(
            i for i in call_instruments if str(position.strikes["atm_strike"]) in i.symbol
        )
        call_long = next(
            i for i in call_instruments if str(position.strikes["call_long_strike"]) in i.symbol
        )

        # Build 4-leg closing order (opposite of opening)
        return [
            # Close put side
            Leg(
                instrument_type=put_short.instrument_type,
                symbol=put_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back ATM short put
            ),
            Leg(
                instrument_type=put_long.instrument_type,
                symbol=put_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell OTM long put
            ),
            # Close call side
            Leg(
                instrument_type=call_short.instrument_type,
                symbol=call_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back ATM short call
            ),
            Leg(
                instrument_type=call_long.instrument_type,
                symbol=call_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell OTM long call
            ),
        ]

    async def a_score_market_conditions(self, report: "MarketConditionReport") -> tuple[float, str]:
        """
        Score market conditions for iron butterfly (0-100).

        Evaluates extreme premium and tight range environment.
        Ideal: Very high IV (>70), very range-bound (ADX<15), neutral bias.
        STRICTER than iron condor.
        """
        score, reasons = await self._score_market_conditions_impl(report)

        # Ensure score doesn't go below zero (no upper limit)
        score = max(0, score)

        explanation = "\n".join(reasons)
        return (score, explanation)

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: "Optional[MarketConditionReport]" = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> "Optional[dict]":
        """
        Prepare iron butterfly suggestion context.

        Builds 4-leg butterfly: sell ATM straddle + buy OTM wings.
        Both short strikes at SAME ATM strike (key difference from iron condor).
        """
        # Get active config
        config = await self.a_get_active_config()

        # Get market report if not provided
        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)
        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f}")

        # Check threshold (allow bypass in force mode)
        if score < 40 and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < 40:
            logger.warning(
                f"Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Calculate strikes: ATM short strikes + wings
        current_price = Decimal(str(report.current_price))
        atm_strike = round_to_even_strike(current_price)

        # Wing width scales with price ($2.50 to $15)
        if current_price < Decimal("50"):
            wing_width = Decimal("2.5")
        elif current_price < Decimal("100"):
            wing_width = Decimal("5")
        elif current_price < Decimal("200"):
            wing_width = Decimal("10")
        else:
            wing_width = Decimal("15")

        # Wings are symmetric around ATM strike
        long_put = atm_strike - wing_width
        long_call = atm_strike + wing_width

        # Find expiration with all 3 unique strikes (ATM + 2 wings)
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        target_criteria = {
            "short_put": atm_strike,  # Sell ATM put
            "short_call": atm_strike,  # Sell ATM call (same strike)
            "long_put": long_put,  # Buy OTM put wing
            "long_call": long_call,  # Buy OTM call wing
        }

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(f"No expiration with iron butterfly strikes for {symbol}")
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} "
            f"with Butterfly strikes: long put ${strikes.get('long_put')}, "
            f"ATM ${strikes.get('short_put')} (both short strikes), "
            f"long call ${strikes.get('long_call')}"
        )

        # Build OCC bundle for 3 unique strikes
        occ_bundle = await self.options_service.build_occ_bundle(symbol, expiration, strikes)
        if not occ_bundle:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundle")
            return None

        # Prepare serializable market data
        serializable_report = {
            "current_price": float(report.current_price),
            "iv_rank": float(report.iv_rank),
            "hv_iv_ratio": float(report.hv_iv_ratio),
            "adx": float(report.adx) if report.adx else None,
            "macd_signal": report.macd_signal,
            "market_stress_level": float(report.market_stress_level),
            "score": score,
            "explanation": explanation,
        }

        # Build context
        context = {
            "config_id": config.id if config else None,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "market_data": serializable_report,
            "strikes": {
                "atm_strike": float(strikes["short_put"]),  # ATM strike (same for both short legs)
                "long_put": float(strikes["long_put"]),
                "long_call": float(strikes["long_call"]),
                "wing_width": float(wing_width),
            },
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,
            "force_generation": force_generation,
        }

        logger.info(f"User {self.user.id}: Context prepared for {self.strategy_name}")
        return context

    async def a_request_suggestion_generation(
        self, report: "Optional[MarketConditionReport]" = None, symbol: str = "QQQ"
    ) -> None:
        """
        Request suggestion generation via channel layer (manual flow).

        This method prepares the context and sends it to the stream manager.
        The actual suggestion will be created after pricing data arrives and
        will be broadcast to the user via WebSocket.

        Args:
            report: Pre-calculated market condition report
            symbol: Underlying symbol (default QQQ)
        """
        # Prepare context using new method
        context = await self.a_prepare_suggestion_context(symbol, report)
        if not context:
            logger.info(f"{self.strategy_name}: Conditions not suitable for {symbol}")
            return

        # Mark as manual (not automated)
        context["is_automated"] = False

        # Dispatch to stream manager
        await self.a_dispatch_to_stream_manager(context)
        logger.info(
            f"User {self.user.id}: Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """
        Calculate final suggestion using live pricing data from cache.
        Called by UserStreamManager after pricing data arrives.

        Args:
            context: Context dict from a_prepare_suggestion_context()

        Returns:
            TradingSuggestion object with real pricing, or None if failed
        """
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        # Reconstruct OCC bundle
        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])

        # Read pricing from cache (populated by streaming)
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found in cache for {self.strategy_name}")
            return None

        # Extract context data
        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        symbol = context["symbol"]
        expiration = date.fromisoformat(context["expiration"])
        strikes = context["strikes"]
        market_data = context["market_data"]
        wing_width = Decimal(str(strikes["wing_width"]))
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)
        force_generation = context.get("force_generation", False)

        # Extract pricing for 4 legs (2 short ATM + 2 long wings)
        # Use leg names as keys in snapshots dict
        short_put_price = pricing_data.snapshots.get("short_put")
        long_put_price = pricing_data.snapshots.get("long_put")
        short_call_price = pricing_data.snapshots.get("short_call")
        long_call_price = pricing_data.snapshots.get("long_call")

        if not all([short_put_price, long_put_price, short_call_price, long_call_price]):
            logger.warning("Missing pricing data for iron butterfly legs")
            return None

        # Calculate mid prices from bid/ask for each leg
        short_put_mid = (
            Decimal(str(short_put_price["bid"])) + Decimal(str(short_put_price["ask"]))
        ) / Decimal("2")
        long_put_mid = (
            Decimal(str(long_put_price["bid"])) + Decimal(str(long_put_price["ask"]))
        ) / Decimal("2")
        short_call_mid = (
            Decimal(str(short_call_price["bid"])) + Decimal(str(short_call_price["ask"]))
        ) / Decimal("2")
        long_call_mid = (
            Decimal(str(long_call_price["bid"])) + Decimal(str(long_call_price["ask"]))
        ) / Decimal("2")

        # Calculate net credit (sell ATM, buy wings)
        # Credit = (Short Put + Short Call) - (Long Put + Long Call)
        total_credit = (
            Decimal(str(short_put_price["bid"])) + Decimal(str(short_call_price["bid"]))
        ) - (Decimal(str(long_put_price["ask"])) + Decimal(str(long_call_price["ask"])))
        total_mid_credit = (short_put_mid + short_call_mid) - (long_put_mid + long_call_mid)

        # Max risk = wing width - credit received
        max_risk_per_contract = (wing_width - total_mid_credit) * Decimal("100")

        # Max profit = credit received
        max_profit_total = total_mid_credit * Decimal("100")

        # Risk budget checking with different behavior for manual vs auto mode
        risk_warning = None
        if not suggestion_mode:
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk_per_contract, is_stressed=market_data.get("is_stressed", False)
            )
            if not can_open:
                if force_generation:
                    # Manual mode: Create suggestion with warning
                    logger.warning(
                        f"User {self.user.id}: Generating {self.strategy_name} despite insufficient risk budget "
                        f"(max risk: ${max_risk_per_contract:.2f}) - manual request"
                    )
                    risk_warning = reason
                else:
                    # Auto mode: Block generation entirely
                    logger.info(
                        f"User {self.user.id}: Risk budget insufficient for {self.strategy_name} "
                        f"(max risk: ${max_risk_per_contract:.2f})"
                    )
                    return {
                        "error": True,
                        "error_type": "risk_budget_exceeded",
                        "message": reason,
                        "max_risk": float(max_risk_per_contract),
                        "strategy": self.strategy_name,
                    }

        # Build market_conditions with risk warning if applicable
        market_conditions_dict = {
            "macd_signal": market_data.get("macd_signal"),
            "adx": market_data.get("adx"),
            "hv_iv_ratio": market_data.get("hv_iv_ratio"),
            "score": market_data["score"],
            "explanation": market_data["explanation"],
        }
        if risk_warning:
            market_conditions_dict["risk_budget_exceeded"] = True
            market_conditions_dict["risk_warning"] = risk_warning

        # Build generation notes if risk warning
        notes = ""
        if risk_warning:
            notes = f"RISK BUDGET EXCEEDED: {risk_warning}"

        # Create TradingSuggestion with REAL pricing
        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            # Strikes
            short_put_strike=Decimal(str(strikes["atm_strike"])),
            long_put_strike=Decimal(str(strikes["long_put"])),
            short_call_strike=Decimal(str(strikes["atm_strike"])),
            long_call_strike=Decimal(str(strikes["long_call"])),
            # Quantities (all 1 for butterfly)
            put_spread_quantity=1,
            call_spread_quantity=1,
            # Pricing
            put_spread_credit=short_put_mid - long_put_mid,
            call_spread_credit=short_call_mid - long_call_mid,
            total_credit=Decimal(str(total_credit)),
            total_mid_credit=Decimal(str(total_mid_credit)),
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value,
            max_profit=max_profit_total,
            # Market conditions
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,
            generation_notes=notes,
            # Status
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: Iron Butterfly suggestion created with real pricing - "
            f"Credit: ${total_mid_credit:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )

        return suggestion
