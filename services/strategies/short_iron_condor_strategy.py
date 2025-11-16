"""
Short Iron Condor Strategy - Premium collection from range-bound markets.

Suitable when:
- IV Rank > 50% (high premium environment - same as credit spreads)
- Range-bound market expected (low ADX < 20)
- Neutral outlook (price expected to stay between strikes)
- High probability trade (70% win rate typical)

Structure:
- Bull Put Spread: Sell OTM put spread below current price
  - Sell put at lower strike
  - Buy put at even lower strike (define risk)
- Bear Call Spread: Sell OTM call spread above current price
  - Sell call at higher strike
  - Buy call at even higher strike (define risk)
- Net credit received (premium collected upfront)
- Profit if price stays between short strikes at expiration

vs Senex Trident:
- Iron Condor: 4 legs (1 put spread + 1 call spread)
- Senex Trident: 6 legs (2 put spreads + 1 call spread)
- Iron Condor: Simpler, easier to manage
- Senex Trident: More complex, higher premium potential

TastyTrade Methodology:
- Entry: IV rank > 50% (high premium)
- DTE: 45 days
- Short strikes: 16 delta (~84% probability OTM)
- Wing width: $5 typically
- Profit target: 50% of max profit
- Management: Close or roll threatened side if tested
- Win rate: ~65-70%
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.sdk.trading_utils import PriceEffect
from services.strategies.base import BaseStrategy
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


@register_strategy("short_iron_condor")
class ShortIronCondorStrategy(BaseStrategy):
    """
    Short Iron Condor - Sell put spread + sell call spread for premium collection.

    TastyTrade Methodology:
    - 45 DTE entry
    - 16 delta short strikes (~16% chance of being ITM)
    - $5 wing width
    - 50% profit target
    - Win rate: 65-70%
    """

    # Strategy-specific constants
    MIN_IV_RANK = 45  # Need decent premium
    OPTIMAL_IV_RANK = 60  # Excellent premium environment
    MAX_ADX = 25  # Prefer range-bound (low directional movement)
    IDEAL_ADX_MAX = 20  # Perfect range-bound
    TARGET_DELTA = 0.16  # 16 delta for short strikes
    WING_WIDTH = 5  # $5 spread width
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 50  # Close at 50% of max profit

    @property
    def strategy_name(self) -> str:
        return "short_iron_condor"

    def automation_enabled_by_default(self) -> bool:
        """Iron condors are manual only (need active management)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 50% of max profit."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid gamma risk."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for short iron condor.

        Target: Close when credit decays to 50% (buy back at 50% of original credit)
        """
        from services.orders.spec import OrderSpec, ProfitTargetSpec
        from services.orders.utils.closing_legs import build_closing_spread_legs
        from services.strategies.utils.pricing_utils import round_option_price
        from trading.models import TradingSuggestion

        # Get original suggestion
        try:
            suggestion = await TradingSuggestion.objects.aget(id=position.metadata["suggestion_id"])
        except Exception as e:
            logger.error(f"Error fetching suggestion for profit target: {e}")
            return []

        original_credit = suggestion.total_mid_credit
        # Target: buy back at 50% of credit (50% profit achieved)
        closing_multiplier = Decimal("0.50")
        raw_price = original_credit * closing_multiplier
        target_price = round_option_price(raw_price, suggestion.underlying_symbol)

        # Build closing legs for all 4 legs of iron condor
        strikes = {
            "short_put": suggestion.short_put_strike,
            "long_put": suggestion.long_put_strike,
            "short_call": suggestion.short_call_strike,
            "long_call": suggestion.long_call_strike,
        }

        closing_legs = build_closing_spread_legs(
            suggestion.underlying_symbol,
            suggestion.expiration_date,
            "iron_condor",
            strikes,
            quantity=1,
        )

        order_spec = OrderSpec(
            legs=closing_legs,
            limit_price=target_price,
            time_in_force="GTC",
            description="Short Iron Condor - 50% Profit Target",
            price_effect=PriceEffect.DEBIT.value,  # Closing a credit spread requires paying debit
        )

        return [
            ProfitTargetSpec(
                order_spec=order_spec,
                spread_type="short_iron_condor",
                profit_percentage=50,
                original_credit=original_credit,
            )
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for short iron condor.

        Multi-factor scoring (0-100):
        - IV Rank (30% weight): Want HIGH IV (> 50) for premium
        - ADX/Trend (25% weight): Want range-bound (< 20 ideal)
        - HV/IV Ratio (20% weight): Want IV > HV (options overpriced)
        - Market Direction (15% weight): Neutral preferred
        - Technical Position (10% weight): Not at extremes
        """
        score = 50.0  # Base score
        reasons = []

        # Factor 1: IV Rank (30% weight) - WANT HIGH IV
        # Same as credit spreads - selling premium
        if report.iv_rank > 70:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 70% - exceptional premium collection opportunity"
            )
        elif report.iv_rank >= self.OPTIMAL_IV_RANK:
            score += 24
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (>60%) - excellent premiums"
            )
        elif report.iv_rank >= self.MIN_IV_RANK:
            score += 15
            reasons.append(f"IV Rank {report.iv_rank:.1f} adequate (>45%) - acceptable premiums")
        elif report.iv_rank >= 35:
            score += 5
            reasons.append(f"IV Rank {report.iv_rank:.1f} - marginal premium for iron condor")
        else:
            score -= 20
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 35 - insufficient premium, not worth risk"
            )

        # Factor 2: ADX Trend Strength (25% weight) - WANT RANGE-BOUND
        # Iron condor profits from lack of movement
        if report.adx is not None:
            if report.adx < self.IDEAL_ADX_MAX:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound market, IDEAL for iron condor"
                )
            elif report.adx < self.MAX_ADX:
                score += 18
                reasons.append(f"ADX {report.adx:.1f} < 25 - weak trend, favorable for iron condor")
            elif report.adx < 30:
                score += 10
                reasons.append(f"ADX {report.adx:.1f} moderate trend - manageable for iron condor")
            elif report.adx < 35:
                score -= 10
                reasons.append(f"ADX {report.adx:.1f} trending - increased risk of testing strikes")
            else:
                score -= 25
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - strong trend, AVOID iron condor (high breach risk)"
                )

        # Factor 3: HV/IV Ratio (20% weight) - Want IV > HV (overpriced options)
        # Lower ratio = higher IV relative to HV = good for sellers
        if report.hv_iv_ratio < 0.8:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - IV high, excellent for premium selling"
            )
        elif report.hv_iv_ratio < 0.9:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV moderately elevated vs realized"
            )
        elif report.hv_iv_ratio < 1.0:
            score += 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV slightly elevated")
        elif report.hv_iv_ratio < 1.1:
            score += 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - fair value")
        elif report.hv_iv_ratio < 1.2:
            score -= 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV slightly low")
        else:
            score -= 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.2 - IV underpriced, poor for premium selling"
            )

        # Factor 4: Market Direction (15% weight) - Neutral is ideal (Epic 22, Task 024)
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for iron condor (no directional bias)")
        elif report.macd_signal in ["bullish_exhausted", "bearish_exhausted"]:
            score += 12
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - favorable for consolidation"
            )
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 5
            reasons.append(
                f"{report.macd_signal.capitalize()} bias - manageable but watch threatened side"
            )
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 10
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - risky for range-bound strategy"
            )

        # Factor 5: Technical Position (10% weight) - Not at extremes
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - ideal for iron condor")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 8
            reasons.append(
                "Price at Bollinger extremes - may continue to move, risky for iron condor"
            )

        # Market stress consideration
        # Moderate stress OK, but very high = directional risk
        if report.market_stress_level < 40:
            score += 5
            reasons.append("Low market stress - stable environment for iron condor")
        elif report.market_stress_level > 70:
            score -= 10
            reasons.append(
                f"Very high market stress ({report.market_stress_level:.0f}) - "
                "increased directional movement risk"
            )

        return (score, reasons)

    def _calculate_short_strikes(self, current_price: Decimal) -> tuple[Decimal, Decimal]:
        """
        Calculate short strike prices for iron condor (16 delta targets).

        Args:
            current_price: Current stock price

        Returns:
            (put_short_strike, call_short_strike) tuple
            - put_short_strike: ~84% probability OTM (below current)
            - call_short_strike: ~84% probability OTM (above current)
        """
        # 16 delta approximates to ~84% probability OTM
        # Typically ~7-10% away from current price
        # Conservative estimate: 8% OTM

        # Short put: 8% below current price
        put_short_target = current_price * Decimal("0.92")
        put_short_strike = round_to_even_strike(put_short_target)

        # Short call: 8% above current price
        call_short_target = current_price * Decimal("1.08")
        call_short_strike = round_to_even_strike(call_short_target)

        return (put_short_strike, call_short_strike)

    def _calculate_long_strikes(
        self, put_short_strike: Decimal, call_short_strike: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate long strike prices (protection wings).

        Args:
            put_short_strike: Short put strike
            call_short_strike: Short call strike

        Returns:
            (put_long_strike, call_long_strike) tuple
        """
        # Long strikes are $5 wider (wing width)
        put_long_strike = put_short_strike - Decimal(str(self.WING_WIDTH))
        call_long_strike = call_short_strike + Decimal(str(self.WING_WIDTH))

        return (put_long_strike, call_long_strike)

    def _calculate_max_profit(self, credit_received: Decimal, quantity: int = 1) -> Decimal:
        """
        Calculate max profit for iron condor.

        Max profit = Total credit received

        Formula: Credit × 100 × quantity

        Example: $2.50 credit, 1 contract = $250 max profit

        Args:
            credit_received: Total credit from all 4 legs
            quantity: Number of iron condors

        Returns:
            Maximum profit in dollars
        """
        return credit_received * Decimal("100") * Decimal(str(quantity))

    def _calculate_max_loss(
        self, wing_width: int, credit_received: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate max loss for iron condor.

        Max loss = Wing width - Credit received (per spread)

        Formula: (Wing Width - Credit) × 100 × quantity

        Example: $5 wing, $2.50 credit = ($5 - $2.50) × 100 = $250 max loss

        Args:
            wing_width: Width of spreads (same for both sides)
            credit_received: Total credit received
            quantity: Number of iron condors

        Returns:
            Maximum loss in dollars
        """
        max_loss_per_spread = (Decimal(str(wing_width)) - credit_received) * Decimal("100")
        return max_loss_per_spread * Decimal(str(quantity))

    def _calculate_breakevens(
        self, put_short_strike: Decimal, call_short_strike: Decimal, credit_received: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for iron condor.

        Formula:
        - Lower breakeven: Put short strike - Credit
        - Upper breakeven: Call short strike + Credit

        Example: $95 short put, $105 short call, $2.50 credit
                 Lower BE = $92.50, Upper BE = $107.50

        Args:
            put_short_strike: Short put strike
            call_short_strike: Short call strike
            credit_received: Total credit

        Returns:
            (breakeven_down, breakeven_up) tuple
        """
        breakeven_down = put_short_strike - credit_received
        breakeven_up = call_short_strike + credit_received
        return (breakeven_down, breakeven_up)

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for short iron condor.

        Four legs:
        1. Sell put at lower strike (collect premium)
        2. Buy put at even lower strike (define risk)
        3. Sell call at higher strike (collect premium)
        4. Buy call at even higher strike (define risk)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - put_short_strike: Short put strike
                - put_long_strike: Long put strike (protection)
                - call_short_strike: Short call strike
                - call_long_strike: Long call strike (protection)
                - quantity: Number of contracts

        Returns:
            List with four Legs (sell put, buy put, sell call, buy call)
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        strikes = {
            "short_put": context["put_short_strike"],
            "long_put": context["put_long_strike"],
            "short_call": context["call_short_strike"],
            "long_call": context["call_long_strike"],
        }

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="iron_condor",
            strikes=strikes,
            quantity=context["quantity"],
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for short iron condor.

        Four legs (opposite of opening):
        1. Buy to close short put
        2. Sell to close long put
        3. Buy to close short call
        4. Sell to close long call

        Args:
            position: Position with:
                - strikes: {
                    "put_short_strike": Decimal,
                    "put_long_strike": Decimal,
                    "call_short_strike": Decimal,
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

        # Get session using the correct service
        account = await get_primary_tastytrade_account(position.user)
        if not account:
            raise ValueError(f"No TastyTrade account found for user {position.user.id}")

        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=position.user.id, refresh_token=account.refresh_token, is_test=account.is_test
        )

        if not session_result.get("success"):
            raise ValueError(f"Failed to get session: {session_result.get('error')}")

        session = session_result["session"]

        # Build specs for bulk fetch
        put_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["put_short_strike"],
                "option_type": "P",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["put_long_strike"],
                "option_type": "P",
            },
        ]

        call_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["call_short_strike"],
                "option_type": "C",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["call_long_strike"],
                "option_type": "C",
            },
        ]

        # Get all 4 option instruments with correct API
        put_instruments = await get_option_instruments_bulk(session, put_specs)
        call_instruments = await get_option_instruments_bulk(session, call_specs)

        if len(put_instruments) != 2:
            raise ValueError("Could not find both put strikes")
        if len(call_instruments) != 2:
            raise ValueError("Could not find both call strikes")

        # Map strikes to instruments
        put_short = next(
            i for i in put_instruments if str(position.strikes["put_short_strike"]) in i.symbol
        )
        put_long = next(
            i for i in put_instruments if str(position.strikes["put_long_strike"]) in i.symbol
        )
        call_short = next(
            i for i in call_instruments if str(position.strikes["call_short_strike"]) in i.symbol
        )
        call_long = next(
            i for i in call_instruments if str(position.strikes["call_long_strike"]) in i.symbol
        )

        # Build 4-leg closing order (opposite of opening)
        return [
            # Close bull put spread
            Leg(
                instrument_type=put_short.instrument_type,
                symbol=put_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back short put
            ),
            Leg(
                instrument_type=put_long.instrument_type,
                symbol=put_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell long put
            ),
            # Close bear call spread
            Leg(
                instrument_type=call_short.instrument_type,
                symbol=call_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back short call
            ),
            Leg(
                instrument_type=call_long.instrument_type,
                symbol=call_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell long call
            ),
        ]

    async def a_score_market_conditions(self, report: "MarketConditionReport") -> tuple[float, str]:
        """
        Score market conditions for short iron condor (0-100).

        Evaluates premium environment and range-bound characteristics.
        Ideal: High IV (>50), range-bound (ADX<20), neutral bias.
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
        Prepare short iron condor suggestion context.

        Builds 4-leg iron condor: sell put spread + sell call spread.
        Both spreads use 16 delta short strikes (~8% OTM) with $5 wings.
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
        if score < 35 and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < 35:
            logger.warning(
                f"⚠️ Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Calculate target strikes for iron condor
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        current_price = Decimal(str(report.current_price))
        otm_pct = Decimal("0.08")  # 16 delta ≈ 8% OTM
        wing_width = Decimal(str(self.WING_WIDTH))

        # Calculate short strikes (16 delta approximation)
        put_short_target = current_price * (Decimal("1") - otm_pct)
        call_short_target = current_price * (Decimal("1") + otm_pct)

        # Calculate long strikes (wing protection)
        put_long_target = put_short_target - wing_width
        call_long_target = call_short_target + wing_width

        # Target strikes for iron condor (will find nearest available)
        target_strikes = {
            "short_put": put_short_target,
            "long_put": put_long_target,
            "short_call": call_short_target,
            "long_call": call_long_target,
        }

        # Find expiration with all required strikes (exact or nearest)
        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_strikes,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )
        if not result:
            logger.warning(
                f"No expiration with suitable strikes for {symbol} iron condor "
                f"(DTE range: {self.MIN_DTE}-{self.MAX_DTE})"
            )
            return None

        expiration, strikes, _validated_chain = result

        # Validate wing widths
        actual_put_width = strikes["short_put"] - strikes["long_put"]
        actual_call_width = strikes["long_call"] - strikes["short_call"]

        logger.info(
            f"User {self.user.id}: Using expiration {expiration} with IC strikes: "
            f"put ${strikes['long_put']}/${strikes['short_put']} (width ${actual_put_width}), "
            f"call ${strikes['short_call']}/${strikes['long_call']} (width ${actual_call_width})"
        )

        # Build OCC bundle for all 4 strikes
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
                "short_put": float(strikes["short_put"]),
                "long_put": float(strikes["long_put"]),
                "short_call": float(strikes["short_call"]),
                "long_call": float(strikes["long_call"]),
            },
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,
            "force_generation": force_generation,
        }

        logger.info(f"User {self.user.id}: ✅ Context prepared for {self.strategy_name}")
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
            f"User {self.user.id}: 🚀 Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """Calculate suggestion from cached pricing data."""
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found for {self.strategy_name}")
            return None

        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        symbol = context["symbol"]
        expiration = date.fromisoformat(context["expiration"])
        strikes = context["strikes"]
        market_data = context["market_data"]
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)
        force_generation = context.get("force_generation", False)

        # Pricing data returns per-spread credits
        # Iron condor has 1 put spread + 1 call spread (both sold for credit)
        put_credit = pricing_data.put_mid_credit  # Credit from bull put spread
        call_credit = pricing_data.call_mid_credit  # Credit from bear call spread
        total_mid_credit = pricing_data.total_mid_credit  # Total premium collected

        # For iron condor:
        # - Max profit = total credit received
        # - Max loss = wing width - credit received
        wing_width = Decimal(str(strikes["short_put"])) - Decimal(str(strikes["long_put"]))
        max_profit_total = total_mid_credit * Decimal("100")
        max_risk_per_contract = (wing_width - total_mid_credit) * Decimal("100")

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
            notes = f"⚠️ RISK BUDGET EXCEEDED: {risk_warning}"

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            short_put_strike=Decimal(str(strikes["short_put"])),
            long_put_strike=Decimal(str(strikes["long_put"])),
            short_call_strike=Decimal(str(strikes["short_call"])),
            long_call_strike=Decimal(str(strikes["long_call"])),
            put_spread_quantity=1,
            call_spread_quantity=1,
            put_spread_credit=put_credit,
            call_spread_credit=call_credit,
            total_credit=total_mid_credit,
            total_mid_credit=total_mid_credit,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,
            generation_notes=notes,
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: ✅ Iron Condor suggestion - "
            f"Credit: ${total_mid_credit:.2f}, Max Profit: ${max_profit_total:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )
        return suggestion
