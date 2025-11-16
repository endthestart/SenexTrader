"""
Long Iron Condor Strategy - Debit spread for low volatility environments.

Suitable when:
- IV Rank < 40 (options relatively cheap)
- Expecting price consolidation in defined range
- After volatility spike has settled
- ADX < 25 (weak or no trend)
- No major catalysts approaching

Structure:
- Buy OTM put (outer put)
- Sell closer-to-ATM put (inner put)
- Sell closer-to-ATM call (inner call)
- Buy OTM call (outer call)

Example: Stock at $100
- Buy $90 put
- Sell $95 put
- Sell $105 call
- Buy $110 call
- Pay $2.00 debit
- Max profit = $5 (spread width) - $2 (debit) = $3 if price stays between $95-$105
- Max loss = $2 (debit paid) if price moves beyond $90 or $110

TastyTrade Methodology:
- Entry: IV rank < 40 (after volatility spike settles)
- DTE: 45 days
- Inner strikes: ~5% OTM (short put and call)
- Spread width: ~5% each side
- Profit target: 50% of max profit
- Management: Close at 50% profit or 100% loss
- Win rate: ~40-50%
"""

from datetime import date
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


@register_strategy("long_iron_condor")
class LongIronCondorStrategy(BaseStrategy):
    """
    Long Iron Condor - Buy iron condor for low volatility plays.

    Opposite of Short Iron Condor (Senex Trident):
    - Short Iron Condor: Sells premium (credit) when IV is HIGH
    - Long Iron Condor: Buys premium (debit) when IV is LOW

    TastyTrade Methodology:
    - 45 DTE entry
    - 5% OTM inner strikes (short options)
    - 10% OTM outer strikes (long options)
    - 50% profit target
    - Win rate: 40-50%
    """

    # Strategy-specific constants
    MAX_IV_RANK = 40  # Above this, use Short Iron Condor instead
    OPTIMAL_IV_RANK = 25  # Sweet spot for cheap options
    IDEAL_ADX_MAX = 20  # Range-bound preferred
    MAX_ADX_TRENDING = 30  # Avoid strong trends
    MIN_PROFIT_ZONE_WIDTH = 10  # Minimum $10 profit zone
    TARGET_RISK_REWARD = 1.5  # Target 1.5:1 reward:risk ratio
    WING_WIDTH = 5  # $5 spread width
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 50  # Close at 50% of max profit

    # Position sizing
    MAX_POSITION_SIZE_PCT = 0.05  # Max 5% of capital per condor

    @property
    def strategy_name(self) -> str:
        return "long_iron_condor"

    def automation_enabled_by_default(self) -> bool:
        """Long iron condors are manual only (need active management)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 50% of max profit."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid gamma risk."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for long iron condor.

        Target: Close when debit value increases by 50% (sell back at 1.5x original debit)
        """
        from trading.models import TradeOrder

        # Get opening order to find original debit
        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        original_debit = abs(opening_order.price)  # Debit is positive
        # Target: sell back at 150% of debit (50% profit achieved)
        target_price = original_debit * Decimal("1.50")

        return [
            {
                "spread_type": "long_iron_condor",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_debit": original_debit,
            }
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for long iron condor.

        Multi-factor scoring (0-100):
        - IV Environment (35% weight): Low IV = cheap options to buy
        - Trend Strength (25% weight): Range-bound preferred
        - Volatility Contraction (20% weight): After spike settles
        - Range Definition (10% weight): Clear support/resistance
        - Catalyst Calendar (10% weight): Avoid major events
        """
        score = 50.0  # Base score
        reasons = []

        # HARD STOP: High IV environment (use Short Iron Condor instead)
        if report.iv_rank > 50:
            return (
                0.0,
                [
                    f"IV Rank {report.iv_rank:.1f} too HIGH for Long Iron Condor - "
                    "use SHORT Iron Condor to SELL premium instead"
                ],
            )

        # Factor 1: IV Environment (35% weight)
        # Lower IV = better (cheaper options to buy)
        if report.iv_rank < 20:
            score += 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 20% - exceptionally cheap options, "
                "IDEAL for long iron condor"
            )
        elif report.iv_rank < 30:
            score += 28
            reasons.append(f"IV Rank {report.iv_rank:.1f} < 30% - excellent low IV environment")
        elif report.iv_rank <= self.MAX_IV_RANK:
            score += 20
            reasons.append(f"IV Rank {report.iv_rank:.1f} ≤ 40% - acceptable for long iron condor")
        else:
            score -= 15
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} elevated - consider Short Iron Condor instead"
            )

        # Factor 2: Trend Strength (25% weight)
        # Range-bound market ideal (ADX < 20)
        if report.adx is not None:
            if report.adx < self.IDEAL_ADX_MAX:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound market, IDEAL for iron condor"
                )
            elif report.adx < 25:
                score += 20
                reasons.append(f"ADX {report.adx:.1f} weak trend - favorable for range play")
            elif report.adx < self.MAX_ADX_TRENDING:
                score += 10
                reasons.append(f"ADX {report.adx:.1f} moderate - acceptable but monitor trend")
            else:
                score -= 30
                reasons.append(
                    f"ADX {report.adx:.1f} strong trend - AVOID long iron condor, "
                    "high risk of directional move"
                )

        # Factor 3: Volatility Contraction (20% weight)
        # HV/IV ratio < 1 indicates volatility declining (IV > HV)
        if report.hv_iv_ratio < 0.8:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - volatility contracting after spike, "
                "excellent setup for long iron condor"
            )
        elif report.hv_iv_ratio < 1.0:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - moderate volatility contraction"
            )
        elif report.hv_iv_ratio > 1.3:
            score -= 10
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - realized volatility high, "
                "risky for range-bound play"
            )

        # Factor 4: Market Direction (preference for neutral) - Epic 22, Task 024
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for iron condor profit zone")
        elif report.macd_signal in ["bullish_exhausted", "bearish_exhausted"]:
            score += 10
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - favorable for consolidation"
            )
        elif report.macd_signal in ["bullish", "bearish"]:
            score -= 10
            reasons.append(f"Directional bias ({report.macd_signal}) - monitor for range play")
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 20
            reasons.append(
                f"Strong directional bias ({report.macd_signal}) - "
                "reduces probability of staying in profit zone"
            )

        # Factor 5: Range Definition (Bollinger Bands)
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - centered in range")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 5
            reasons.append(
                f"Price at Bollinger extreme ({report.bollinger_position}) - "
                "potential for continued move"
            )

        # Factor 6: Market Stress
        if report.market_stress_level < 40:
            score += 10
            reasons.append(
                f"Low market stress ({report.market_stress_level:.0f}) - "
                "stable environment for defined profit zone"
            )
        elif report.market_stress_level > 60:
            score -= 15
            reasons.append(
                f"Elevated market stress ({report.market_stress_level:.0f}) - "
                "increased risk of range breakout"
            )

        # Factor 7: Recent Price Movement
        if report.recent_move_pct is not None:
            if abs(report.recent_move_pct) < 2:
                score += 5
                reasons.append("Minimal recent movement - consolidating")
            elif abs(report.recent_move_pct) > 5:
                score -= 10
                reasons.append(
                    f"Large recent move ({report.recent_move_pct:+.1f}%) - may continue trending"
                )

        return (score, reasons)

    def _select_strikes(
        self, current_price: Decimal, target_profit_zone_pct: float = 10.0
    ) -> dict[str, Decimal]:
        """
        Select strikes for long iron condor.

        Target profit zone: ±5-10% from current price

        Structure:
        - Inner strikes (short): ~5% OTM on each side (profit zone boundaries)
        - Outer strikes (long): ~10% OTM on each side (risk definition)

        Args:
            current_price: Current underlying price
            target_profit_zone_pct: Width of profit zone (default 10% = ±5%)

        Returns:
            Dict with outer_put, inner_put, inner_call, outer_call
        """
        # Profit zone: ±5% from current (10% total width)
        half_zone = Decimal(str(target_profit_zone_pct / 200))  # 5% = 0.05

        # Inner strikes define profit zone (short options - we sell these)
        inner_put_target = current_price * (Decimal("1.0") - half_zone)
        inner_call_target = current_price * (Decimal("1.0") + half_zone)

        inner_put = round_to_even_strike(inner_put_target)
        inner_call = round_to_even_strike(inner_call_target)

        # Outer strikes define risk (long options - we buy these)
        # Place outer strikes ~5% further out for protection
        outer_put_target = inner_put * Decimal("0.95")
        outer_call_target = inner_call * Decimal("1.05")

        outer_put = round_to_even_strike(outer_put_target)
        outer_call = round_to_even_strike(outer_call_target)

        return {
            "outer_put": outer_put,
            "inner_put": inner_put,
            "inner_call": inner_call,
            "outer_call": outer_call,
        }

    def _calculate_profit_zone_width(self, strikes: dict[str, Decimal]) -> Decimal:
        """
        Calculate width of profit zone (distance between short strikes).

        Returns:
            Profit zone width in dollars
        """
        return strikes["inner_call"] - strikes["inner_put"]

    def _calculate_max_profit(
        self, put_spread_width: Decimal, call_spread_width: Decimal, debit_paid: Decimal
    ) -> Decimal:
        """
        Calculate max profit for long iron condor.

        Max profit occurs when price expires beyond one of the outer strikes,
        causing one spread to reach max value while the other expires worthless.

        Max Profit = (Wing Width - Debit) for one side
        Example: $5 wing, $2 total debit -> One spread gains $5-$2=$3 profit

        Note: We use put_spread_width, but call_spread_width would give same result
        since both wings are equal width.

        Achieved when price expires beyond outer put OR outer call strike.
        """
        # Max profit when ONE spread maxes out (price beyond outer strike)
        # The other spread expires worthless (loss = its portion of debit)
        # Net = (spread_width - total_debit) since we paid for both spreads
        return put_spread_width - debit_paid

    def _calculate_max_loss(self, debit_paid: Decimal) -> Decimal:
        """
        Calculate max loss for long iron condor.

        Max Loss = Total debit paid

        Occurs when price moves beyond outer strikes.
        """
        return debit_paid

    def _calculate_breakeven_points(
        self, strikes: dict[str, Decimal], debit_paid: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven points for long iron condor.

        Lower BE = Inner Put + (Debit / 2)
        Upper BE = Inner Call - (Debit / 2)

        Returns:
            (lower_breakeven, upper_breakeven)
        """
        half_debit = debit_paid / Decimal("2")

        lower_be = strikes["inner_put"] + half_debit
        upper_be = strikes["inner_call"] - half_debit

        return (lower_be, upper_be)

    def _calculate_risk_reward_ratio(self, max_profit: Decimal, max_loss: Decimal) -> Decimal:
        """
        Calculate risk-reward ratio.

        Target: 1.5:1 or better (risk $1 to make $1.50+)
        """
        if max_loss == 0:
            return Decimal("0")

        return max_profit / max_loss

    def _validate_risk_reward(
        self, strikes: dict[str, Decimal], estimated_debit: Decimal
    ) -> tuple[bool, str]:
        """
        Validate risk-reward ratio meets minimum threshold.

        Returns:
            (is_valid, reason)
        """
        put_spread_width = strikes["inner_put"] - strikes["outer_put"]
        call_spread_width = strikes["outer_call"] - strikes["inner_call"]

        max_profit = self._calculate_max_profit(
            put_spread_width, call_spread_width, estimated_debit
        )
        max_loss = self._calculate_max_loss(estimated_debit)

        risk_reward = self._calculate_risk_reward_ratio(max_profit, max_loss)

        if risk_reward < Decimal(str(self.TARGET_RISK_REWARD)):
            return (
                False,
                f"Risk-reward {risk_reward:.2f}:1 below minimum {self.TARGET_RISK_REWARD}:1",
            )

        return (True, f"Risk-reward {risk_reward:.2f}:1 acceptable")

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for long iron condor.

        Four legs:
        1. Buy put at outer_put (define risk)
        2. Sell put at inner_put (collect premium)
        3. Sell call at inner_call (collect premium)
        4. Buy call at outer_call (define risk)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - outer_put: Outer put strike
                - inner_put: Inner put strike
                - inner_call: Inner call strike
                - outer_call: Outer call strike
                - quantity: Number of contracts

        Returns:
            List with four Legs
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="long_iron_condor",
            strikes={
                "long_put": context["outer_put"],
                "short_put": context["inner_put"],
                "short_call": context["inner_call"],
                "long_call": context["outer_call"],
            },
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for long iron condor.

        Four legs (opposite of opening):
        1. Sell to close outer long put
        2. Buy to close inner short put
        3. Buy to close inner short call
        4. Sell to close outer long call

        Args:
            position: Position with:
                - strikes: {
                    "outer_put": Decimal,
                    "inner_put": Decimal,
                    "inner_call": Decimal,
                    "outer_call": Decimal
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

        # Get session
        account = await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user, account)

        # Build specs for put instruments
        put_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["outer_put"],
                "option_type": "P",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["inner_put"],
                "option_type": "P",
            },
        ]

        # Build specs for call instruments
        call_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["inner_call"],
                "option_type": "C",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["outer_call"],
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
        put_long = next(
            i for i in put_instruments if str(position.strikes["outer_put"]) in i.symbol
        )
        put_short = next(
            i for i in put_instruments if str(position.strikes["inner_put"]) in i.symbol
        )
        call_short = next(
            i for i in call_instruments if str(position.strikes["inner_call"]) in i.symbol
        )
        call_long = next(
            i for i in call_instruments if str(position.strikes["outer_call"]) in i.symbol
        )

        # Build 4-leg closing order (opposite of opening)
        return [
            # Close put side
            Leg(
                instrument_type=put_long.instrument_type,
                symbol=put_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell outer long put
            ),
            Leg(
                instrument_type=put_short.instrument_type,
                symbol=put_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back inner short put
            ),
            # Close call side
            Leg(
                instrument_type=call_short.instrument_type,
                symbol=call_short.symbol,
                quantity=position.quantity,
                action="Buy to Close",  # Buy back inner short call
            ),
            Leg(
                instrument_type=call_long.instrument_type,
                symbol=call_long.symbol,
                quantity=position.quantity,
                action="Sell to Close",  # Sell outer long call
            ),
        ]

    async def a_score_market_conditions(self, report: "MarketConditionReport") -> tuple[float, str]:
        """
        Score market conditions for long iron condor (0-100).

        Evaluates low volatility consolidation environment.
        Ideal: Low IV (<40), range-bound (ADX<25), post-volatility spike.
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
        Prepare long iron condor suggestion context.

        Builds 4-leg debit iron condor: buy OTM put spread + buy OTM call spread.
        Inner strikes at 5% OTM, outer strikes at 10% OTM.
        """
        # Entry logging
        logger.info(
            f"🔍 Long Iron Condor generation STARTED for {symbol} "
            f"(force_generation={force_generation}, suggestion_mode={suggestion_mode})"
        )

        # Get active config (optional for this strategy)
        config = await self.a_get_active_config()

        # Get market report if not provided
        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)
        logger.info(
            f"📊 {self.strategy_name} score for {symbol}: {score:.1f} "
            f"(threshold=35, force_generation={force_generation})"
        )

        # Check threshold (allow bypass in force mode)
        if score < 35 and not force_generation:
            logger.info(
                f"❌ EARLY EXIT: Score too low ({score:.1f}) - not generating {self.strategy_name}"
            )
            return None

        if force_generation and score < 35:
            logger.warning(
                f"⚠️ Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Calculate 4 strikes using fixed-width wings
        current_price = Decimal(str(report.current_price))
        otm_pct = Decimal("0.03")  # 3% OTM for short strikes (conservative for long IC)

        # Put spread (below current price)
        short_put_target = current_price * (Decimal("1") - otm_pct)
        short_put = round_to_even_strike(short_put_target)
        long_put = short_put - Decimal(str(self.WING_WIDTH))

        # Call spread (above current price)
        short_call_target = current_price * (Decimal("1") + otm_pct)
        short_call = round_to_even_strike(short_call_target)
        long_call = short_call + Decimal(str(self.WING_WIDTH))

        # Log calculated strikes
        logger.info(
            f"🎯 Calculated strikes for {symbol} @ ${current_price}: "
            f"Long Put={long_put}, Short Put={short_put}, "
            f"Short Call={short_call}, Long Call={long_call} "
            f"(OTM={otm_pct * 100}%, Wing Width={self.WING_WIDTH})"
        )

        # Find expiration with all 4 strikes
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        target_criteria = {
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call,
        }

        logger.info(
            f"🔎 Searching for expiration with all 4 strikes "
            f"(DTE range: {self.MIN_DTE}-{self.MAX_DTE})"
        )

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(
                f"❌ FAILURE POINT #1: No expiration with all 4 long iron condor strikes for {symbol}. "
                f"Searched for strikes: LP={long_put}, SP={short_put}, SC={short_call}, LC={long_call} "
                f"in DTE range {self.MIN_DTE}-{self.MAX_DTE}"
            )
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"✅ Found expiration {expiration} with Long IC strikes: "
            f"put {strikes.get('long_put')}/{strikes.get('short_put')}, "
            f"call {strikes.get('short_call')}/{strikes.get('long_call')}"
        )

        # Build OCC bundle for all 4 strikes
        logger.info(f"🔨 Building OCC bundle for {symbol} expiration {expiration}...")
        occ_bundle = await self.options_service.build_occ_bundle(symbol, expiration, strikes)
        if not occ_bundle:
            logger.warning(
                f"❌ FAILURE POINT #2: Failed to build OCC bundle for user {self.user.id}. "
                f"Symbol={symbol}, Expiration={expiration}, Strikes={strikes}"
            )
            return None

        logger.info("✅ OCC bundle built successfully")

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

        logger.info(
            f"✅ SUCCESS: Long Iron Condor context prepared for {symbol} "
            f"(user {self.user.id}, expiration {expiration})"
        )
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
        """Calculate suggestion from cached pricing data (DEBIT strategy)."""
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

        # Extract pricing for LONG iron condor (BUY inner strikes, SELL outer strikes)
        # Leg names refer to option position type, not strategy direction:
        # - long_put = outer put (lower strike) - we SELL this
        # - short_put = inner put (higher strike) - we BUY this
        # - short_call = inner call (lower strike) - we BUY this
        # - long_call = outer call (higher strike) - we SELL this
        long_put_payload = pricing_data.snapshots.get("long_put")
        short_put_payload = pricing_data.snapshots.get("short_put")
        short_call_payload = pricing_data.snapshots.get("short_call")
        long_call_payload = pricing_data.snapshots.get("long_call")

        if not all([long_put_payload, short_put_payload, short_call_payload, long_call_payload]):
            logger.warning("Missing pricing data for long iron condor legs")
            return None

        # Calculate mid prices
        long_put_mid = (
            Decimal(str(long_put_payload["bid"])) + Decimal(str(long_put_payload["ask"]))
        ) / Decimal("2")
        short_put_mid = (
            Decimal(str(short_put_payload["bid"])) + Decimal(str(short_put_payload["ask"]))
        ) / Decimal("2")
        short_call_mid = (
            Decimal(str(short_call_payload["bid"])) + Decimal(str(short_call_payload["ask"]))
        ) / Decimal("2")
        long_call_mid = (
            Decimal(str(long_call_payload["bid"])) + Decimal(str(long_call_payload["ask"]))
        ) / Decimal("2")

        # Calculate debits (positive values)
        # For LONG iron condor, we BUY inner strikes (short_put, short_call) and SELL outer strikes (long_put, long_call)
        # Put debit = BUY short_put - SELL long_put = short_put_mid - long_put_mid
        # Call debit = BUY short_call - SELL long_call = short_call_mid - long_call_mid
        put_debit = short_put_mid - long_put_mid
        call_debit = short_call_mid - long_call_mid
        total_debit = put_debit + call_debit

        # Max loss (when price stays in profit zone between inner strikes) = total debit paid
        max_risk_per_contract = total_debit * Decimal("100")
        # Max profit (when price moves beyond outer strikes) = wing width - total debit
        wing_width = Decimal(str(strikes["short_put"])) - Decimal(str(strikes["long_put"]))
        max_profit_total = (wing_width - total_debit) * Decimal("100")

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
            put_spread_credit=-put_debit,  # Negative for debit
            call_spread_credit=-call_debit,
            total_credit=-total_debit,  # Negative = debit
            total_mid_credit=-total_debit,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.DEBIT.value,
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
            f"User {self.user.id}: ✅ Long Iron Condor suggestion - "
            f"Debit: ${total_debit:.2f}, Max Profit: ${max_profit_total:.2f}"
        )
        return suggestion
