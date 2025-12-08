"""
Long Strangle Strategy - Lower-cost volatility play for massive moves.

Suitable when:
- IV Rank < 25% (options EXTREMELY cheap - stricter than straddle)
- HV/IV Ratio > 1.3 (implied volatility severely underpriced)
- ADX > 30 (very strong trend - stricter than straddle)
- Major catalyst approaching (FDA decision, merger, major event)
- Expecting 10%+ move but uncertain of direction

Structure:
- Buy OTM call + Buy OTM put (different strikes, same expiration)
- Call: ~5% above current price
- Put: ~5% below current price
- Net debit (pay premium upfront)
- Lower cost than straddle (40-60% cheaper)
- Wider breakevens (need bigger move to profit)
- Max loss = total premium paid

vs Long Straddle:
- Strangle: Lower cost, wider breakevens, needs 10-15% move
- Straddle: Higher cost, tighter breakevens, needs 5-8% move
- Choose strangle when: IV extremely low, expecting massive move, want lower risk

TastyTrade Methodology:
- Entry: IV rank < 25 (bottom 25% - stricter than straddle's <30)
- DTE: 45 days
- Strikes: 5% OTM on each side
- Profit target: 50-100% of debit paid
- Exit: 21 DTE or significant IV expansion
- Win rate: 25-35% (lower than straddle)
- Avg return: 80-150% per winner (higher than straddle)
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


@register_strategy("long_strangle")
class LongStrangleStrategy(BaseStrategy):
    """
    Long Strangle - Buy OTM call + OTM put for extreme volatility expansion.

    TastyTrade Methodology:
    - 45 DTE entry
    - 5% OTM strikes on each side
    - 50-100% profit target
    - Exit at 21 DTE or IV expansion
    - Win rate: 25-35% (needs massive move)
    """

    # Strategy-specific constants (STRICTER than Long Straddle)
    MAX_IV_RANK = 35  # Even stricter than straddle's 40
    OPTIMAL_IV_RANK = 20  # Want VERY cheap options
    MIN_HV_IV_RATIO = 1.1  # Want IV underpriced vs HV
    OPTIMAL_HV_IV_RATIO = 1.4  # Excellent value (higher than straddle's 1.3)
    MIN_ADX_TREND = 25  # Higher than straddle's 20
    OPTIMAL_ADX = 35  # Higher than straddle's 30
    OTM_PERCENTAGE = 0.05  # 5% OTM on each side
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 100  # Target 100% return (higher than straddle's 50%)

    @property
    def strategy_name(self) -> str:
        return "long_strangle"

    def automation_enabled_by_default(self) -> bool:
        """Long strangles are manual only (very high risk, timing critical)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 100% of debit paid."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid rapid time decay."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for long strangle.

        Target: Close when value doubles (sell at 2x of original debit)
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
        # Target: sell when position value = 2x original debit (100% return)
        target_price = original_debit * Decimal("2.00")

        return [
            {
                "spread_type": "long_strangle",
                "profit_percentage": 100,
                "target_price": target_price,
                "original_debit": original_debit,
            }
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for long strangle entry.

        Multi-factor scoring (0-100):
        - IV Rank (35% weight): Want VERY LOW IV (< 25) - stricter than straddle
        - HV/IV Ratio (25% weight): Want ratio > 1.0 (IV underpriced)
        - ADX Trend (25% weight): Want very strong trend (> 30) - stricter than straddle
        - Market Direction (10% weight): Neutral preferred
        - Technical Position (5% weight): Bollinger bands
        """
        score = 50.0  # Base score
        reasons = []

        # Factor 1: IV Rank (35% weight) - WANT VERY LOW IV (stricter than straddle)
        if report.iv_rank < 20:
            score += 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 20% - EXCEPTIONAL value, OTM options dirt cheap"
            )
        elif report.iv_rank < 25:
            score += 25
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (< 25%) - excellent for strangle"
            )
        elif report.iv_rank < 30:
            score += 15
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} acceptable but straddle may be better choice"
            )
        elif report.iv_rank < 40:
            score += 5
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} - not ideal for strangle (consider straddle)"
            )
        elif report.iv_rank < 50:
            score -= 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} - too expensive for strangle")
        else:
            score -= 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 50% - VERY EXPENSIVE, avoid buying OTM options"
            )

        # Factor 2: HV/IV Ratio (25% weight) - Want IV severely underpriced
        if report.hv_iv_ratio > 1.5:
            score += 25
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.5 - IV severely underpriced, "
                "perfect for OTM option buying"
            )
        elif report.hv_iv_ratio > 1.3:
            score += 18
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.3 - IV significantly underpriced"
            )
        elif report.hv_iv_ratio > 1.1:
            score += 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.1 - IV underpriced")
        elif report.hv_iv_ratio > 1.0:
            score += 0
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - fair value, neutral")
        elif report.hv_iv_ratio > 0.9:
            score -= 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - slightly expensive")
        else:
            score -= 25
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.9 - IV overpriced, "
                "very poor for option buying"
            )

        # Factor 3: ADX Trend Strength (25% weight) - Want VERY strong trend
        # Strangle needs massive moves, so ADX requirement is stricter
        if report.adx is not None:
            if report.adx > 40:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} > 40 - extremely strong trend, massive move likely"
                )
            elif report.adx > 30:
                score += 20
                reasons.append(
                    f"ADX {report.adx:.1f} > 30 - very strong trend, favorable for strangle"
                )
            elif report.adx > 25:
                score += 12
                reasons.append(
                    f"ADX {report.adx:.1f} moderate-strong trend - acceptable, consider straddle"
                )
            elif report.adx > 20:
                score += 5
                reasons.append(f"ADX {report.adx:.1f} moderate trend - marginal for strangle")
            elif report.adx > 15:
                score -= 5
                reasons.append(
                    f"ADX {report.adx:.1f} weak trend - unlikely to see required 10%+ move"
                )
            else:
                score -= 15
                reasons.append(
                    f"ADX {report.adx:.1f} < 15 - very weak trend, AVOID strangle (big move very unlikely)"
                )

        # Factor 4: Market Direction (10% weight) - Epic 22, Task 024
        # Strangle profits from massive moves in either direction
        if report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score += 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - momentum suggests massive move potential"
            )
        elif report.macd_signal in ["bullish_exhausted", "bearish_exhausted"]:
            score += 12
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - might reverse sharply (massive move)"
            )
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 10
            reasons.append(f"{report.macd_signal.capitalize()} direction - some potential for move")
        elif report.macd_signal == "neutral":
            score += 8
            reasons.append("Neutral market - potential for massive move in either direction")

        # Factor 5: Volatility Compression (5% weight) - Extreme squeeze suggests expansion
        if report.bollinger_position == "within_bands":
            score += 5
            reasons.append("Price consolidating - potential for volatility expansion")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score += 3
            reasons.append("Price at extremes - trend continuation potential")

        # Market stress consideration
        # High stress can mean massive volatility expansion (ideal for strangles)
        if report.market_stress_level > 70:
            score += 8
            reasons.append(
                f"Very high market stress ({report.market_stress_level:.0f}) - "
                "extreme volatility expansion potential"
            )
        elif report.market_stress_level > 60:
            score += 5
            reasons.append(
                f"Elevated market stress ({report.market_stress_level:.0f}) - "
                "volatility expansion likely"
            )
        elif report.market_stress_level < 20:
            score -= 8
            reasons.append(
                "Very low market stress - may lack catalyst for 10%+ move required for strangle"
            )

        return (score, reasons)

    def _find_otm_strikes(self, current_price: Decimal) -> tuple[Decimal, Decimal]:
        """
        Find OTM strikes for strangle (5% on each side).

        Args:
            current_price: Current stock price

        Returns:
            (call_strike, put_strike) tuple
            - call_strike: ~5% above current price
            - put_strike: ~5% below current price
        """
        # Call strike: 5% above current price
        call_target = current_price * Decimal("1.05")
        call_strike = round_to_even_strike(call_target)

        # Put strike: 5% below current price
        put_target = current_price * Decimal("0.95")
        put_strike = round_to_even_strike(put_target)

        return (call_strike, put_strike)

    def _calculate_breakevens(
        self, call_strike: Decimal, put_strike: Decimal, total_debit: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for strangle.

        Formula:
        - Upper breakeven: Call Strike + Total Debit
        - Lower breakeven: Put Strike - Total Debit

        Example: $105 call, $95 put, $4 total debit
                 Upper BE = $109, Lower BE = $91

        Args:
            call_strike: OTM call strike
            put_strike: OTM put strike
            total_debit: Total premium paid (call + put)

        Returns:
            (breakeven_up, breakeven_down) tuple
        """
        breakeven_up = call_strike + total_debit
        breakeven_down = put_strike - total_debit
        return (breakeven_up, breakeven_down)

    def _calculate_max_loss(
        self, call_premium: Decimal, put_premium: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate maximum loss for strangle.

        Max loss = Total debit paid (occurs if stock stays between strikes)

        Formula: (Call Premium + Put Premium) × 100 × quantity

        Example: $2.50 call + $2.00 put, 1 contract = $450 max loss

        Args:
            call_premium: Premium paid for OTM call
            put_premium: Premium paid for OTM put
            quantity: Number of strangles

        Returns:
            Maximum loss in dollars
        """
        total_debit = call_premium + put_premium
        return total_debit * Decimal("100") * Decimal(str(quantity))

    def _calculate_net_delta(self, call_delta: float, put_delta: float) -> float:
        """
        Calculate net delta for strangle.

        Should be near zero (delta-neutral position).
        OTM options have lower deltas than ATM, so net delta closer to 0.

        Formula: Call Delta + Put Delta

        Example: Call delta +0.35, Put delta -0.30 = Net delta +0.05

        Args:
            call_delta: Delta of long OTM call (lower than ATM ~0.50)
            put_delta: Delta of long OTM put (negative, lower magnitude than ATM)

        Returns:
            Net delta (should be very close to 0)
        """
        return call_delta + put_delta

    def _calculate_move_required_pct(
        self, current_price: Decimal, breakeven_up: Decimal, breakeven_down: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate percentage move required to reach breakevens.

        Args:
            current_price: Current stock price
            breakeven_up: Upper breakeven
            breakeven_down: Lower breakeven

        Returns:
            (upside_move_pct, downside_move_pct) as percentages
        """
        upside_move = ((breakeven_up - current_price) / current_price) * Decimal("100")
        downside_move = ((current_price - breakeven_down) / current_price) * Decimal("100")
        return (upside_move, downside_move)

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for long strangle.

        Two legs:
        1. Buy OTM call (5% above current)
        2. Buy OTM put (5% below current)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - call_strike: OTM call strike
                - put_strike: OTM put strike
                - quantity: Number of contracts

        Returns:
            List with two Legs (buy call, buy put)
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="strangle",
            strikes={
                "call_strike": context["call_strike"],
                "put_strike": context["put_strike"],
            },
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for long strangle.

        Two legs:
        1. Sell to close long OTM call
        2. Sell to close long OTM put

        Args:
            position: Position with:
                - strikes: {"call_strike": Decimal, "put_strike": Decimal}
                - expiration_date
                - underlying_symbol
                - quantity

        Returns:
            List with two Legs (sell to close call and put)
        """
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        # Get session using TastyTradeSessionService
        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        call_strike = position.strikes["call_strike"]
        put_strike = position.strikes["put_strike"]

        # Build spec dictionaries for bulk call
        call_spec = {
            "underlying": position.underlying_symbol,
            "expiration": position.expiration_date,
            "strike": call_strike,
            "option_type": "C",
        }
        put_spec = {
            "underlying": position.underlying_symbol,
            "expiration": position.expiration_date,
            "strike": put_strike,
            "option_type": "P",
        }

        # Get call instrument
        call_instruments = await get_option_instruments_bulk(session, [call_spec])

        if not call_instruments:
            raise ValueError(f"No call found at strike {call_strike}")

        call_instrument = call_instruments[0]

        # Get put instrument
        put_instruments = await get_option_instruments_bulk(session, [put_spec])

        if not put_instruments:
            raise ValueError(f"No put found at strike {put_strike}")

        put_instrument = put_instruments[0]

        # Sell to close both call and put (opposite of opening)
        return [
            Leg(
                instrument_type=call_instrument.instrument_type,
                symbol=call_instrument.symbol,
                quantity=position.quantity,
                action="Sell to Close",
            ),
            Leg(
                instrument_type=put_instrument.instrument_type,
                symbol=put_instrument.symbol,
                quantity=position.quantity,
                action="Sell to Close",
            ),
        ]

    async def a_score_market_conditions(self, report: "MarketConditionReport") -> tuple[float, str]:
        """
        Score market conditions for long strangle (0-100).

        Evaluates volatility environment and trend strength.
        Ideal: Very low IV (<25), very strong trend (ADX>30), neutral bias.
        STRICTER than straddle (cheaper but needs bigger move).
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
        Prepare long strangle suggestion context.

        Builds context for buying OTM call + OTM put (different strikes, same expiration).
        Lower cost alternative to straddle but needs bigger move to profit.
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
                f"Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Find OTM strikes (5% on each side)
        call_strike, put_strike = self._find_otm_strikes(Decimal(str(report.current_price)))

        # Find expiration with both call and put OTM strikes
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        target_criteria = {
            "call_strike": call_strike,
            "put_strike": put_strike,
        }

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(
                f"No expiration with OTM call ${call_strike} + put ${put_strike} for {symbol}"
            )
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} "
            f"with OTM strikes: call ${strikes.get('call_strike')}, put ${strikes.get('put_strike')}"
        )

        # Build OCC bundle for both call and put
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
                "call_strike": float(call_strike),
                "put_strike": float(put_strike),
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
        """Calculate suggestion from cached pricing data (long strangle = buy OTM call + put)."""
        from datetime import date, timedelta
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

        # Extract pricing for OTM call and put (different strikes)
        call_strike = Decimal(str(strikes["call_strike"]))
        put_strike = Decimal(str(strikes["put_strike"]))
        call_payload = pricing_data.snapshots.get("call_strike")
        put_payload = pricing_data.snapshots.get("put_strike")

        if not call_payload or not put_payload:
            logger.warning("Missing pricing data for strangle")
            return None

        # Calculate mid prices from bid/ask
        call_bid = call_payload.get("bid")
        call_ask = call_payload.get("ask")
        put_bid = put_payload.get("bid")
        put_ask = put_payload.get("ask")

        if any(x is None for x in [call_bid, call_ask, put_bid, put_ask]):
            logger.warning("Missing bid/ask for strangle")
            return None

        call_mid = (Decimal(str(call_bid)) + Decimal(str(call_ask))) / Decimal("2")
        put_mid = (Decimal(str(put_bid)) + Decimal(str(put_ask))) / Decimal("2")

        # Total debit = cost of both legs
        call_debit = call_mid
        put_debit = put_mid
        total_debit = call_debit + put_debit

        # Max risk = debit paid * 100
        max_risk_per_contract = total_debit * Decimal("100")

        # Max profit = unlimited (theoretically)
        # Set to None to indicate unlimited profit potential
        max_profit_total = None

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
            notes = f"RISK BUDGET EXCEEDED: {risk_warning}"

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            long_call_strike=call_strike,
            long_put_strike=put_strike,
            call_spread_quantity=1,
            put_spread_quantity=1,
            call_spread_credit=-call_debit,  # Negative = debit
            put_spread_credit=-put_debit,
            total_credit=-total_debit,
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
            f"User {self.user.id}: Long Strangle suggestion - "
            f"Debit: ${total_debit:.2f}, Put: ${put_strike}, Call: ${call_strike}"
        )
        return suggestion
