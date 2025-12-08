"""
Long Straddle Strategy - Volatility expansion play for big moves.

Suitable when:
- IV Rank < 30% (options cheap - OPPOSITE of credit spreads)
- HV/IV Ratio > 1.2 (implied volatility underpriced vs realized)
- ADX > 25 (strong trend suggests big move potential)
- Catalyst approaching (earnings, events)
- Neutral bias (don't know direction, but expect big move)

Structure:
- Buy ATM call + Buy ATM put (same strike, same expiration)
- Net debit (pay premium upfront)
- Profit from large price movements in either direction
- Max loss = total premium paid (if stock stays at strike)
- Breakevens: Strike ± total debit paid

TastyTrade Methodology:
- Entry: IV rank < 30 (bottom 30% of 52-week range)
- DTE: 45 days
- Strike: ATM (at-the-money)
- Profit target: 25-50% of debit paid
- Exit: 21 DTE or when IV expands
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


@register_strategy("long_straddle")
class LongStraddleStrategy(BaseStrategy):
    """
    Long Straddle - Buy ATM call + ATM put for volatility expansion.

    TastyTrade Methodology:
    - 45 DTE entry
    - ATM strikes (both call and put at same strike)
    - 25-50% profit target
    - Exit at 21 DTE or IV expansion
    - Win rate: 35-45% (needs big move)
    """

    # Strategy-specific constants
    MAX_IV_RANK = 40  # Too expensive above this (buying options)
    OPTIMAL_IV_RANK = 25  # Sweet spot for cheap options
    MIN_HV_IV_RATIO = 1.1  # Want IV underpriced vs HV
    OPTIMAL_HV_IV_RATIO = 1.3  # Excellent value
    MIN_ADX_TREND = 20  # Need decent trend for big move
    OPTIMAL_ADX = 30  # Strong trend
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 50  # Target 50% of max profit (debit paid)

    @property
    def strategy_name(self) -> str:
        return "long_straddle"

    def automation_enabled_by_default(self) -> bool:
        """Long straddles are manual only (high risk, timing critical)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 50% of debit paid."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid rapid time decay."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for long straddle.

        Target: Close when value increases by 50% (sell at 1.5x of original debit)
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
        # Target: sell when position value = 1.5x original debit
        target_price = original_debit * Decimal("1.50")

        return [
            {
                "spread_type": "long_straddle",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_debit": original_debit,
            }
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for long straddle entry.

        Multi-factor scoring (0-100):
        - IV Rank (30% weight): Want LOW IV (< 30) - OPPOSITE of credit spreads
        - HV/IV Ratio (25% weight): Want ratio > 1.0 (IV underpriced)
        - ADX Trend (20% weight): Want strong trend (> 25) for big move
        - Market Direction (15% weight): Neutral preferred
        - Technical Position (10% weight): Bollinger bands, support/resistance
        """
        score = 50.0  # Base score
        reasons = []

        # Factor 1: IV Rank (30% weight) - WANT LOW IV
        # This is OPPOSITE of credit spreads (which want high IV)
        if report.iv_rank < 20:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 20% - EXCELLENT value, options very cheap"
            )
        elif report.iv_rank < 30:
            score += 20
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (< 30%) - good value for buying"
            )
        elif report.iv_rank < 40:
            score += 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} acceptable (< 40%) - reasonable entry")
        elif report.iv_rank < 50:
            score += 0
            reasons.append(f"IV Rank {report.iv_rank:.1f} neutral - monitor for better entry")
        elif report.iv_rank < 60:
            score -= 15
            reasons.append(f"IV Rank {report.iv_rank:.1f} elevated - expensive for option buying")
        else:
            score -= 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 60% - VERY EXPENSIVE, avoid buying options"
            )

        # Factor 2: HV/IV Ratio (25% weight) - Want IV underpriced (ratio > 1.0)
        if report.hv_iv_ratio > 1.4:
            score += 25
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.4 - IV severely underpriced, "
                "excellent straddle entry"
            )
        elif report.hv_iv_ratio > 1.2:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.2 - IV underpriced vs realized volatility"
            )
        elif report.hv_iv_ratio > 1.0:
            score += 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.0 - fair value")
        elif report.hv_iv_ratio > 0.9:
            score -= 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - slightly expensive")
        else:
            score -= 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.9 - IV overpriced, "
                "poor buying opportunity"
            )

        # Factor 3: ADX Trend Strength (20% weight) - Want strong trend for big move
        if report.adx is not None:
            if report.adx > 35:
                score += 20
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - very strong trend, high probability of big move"
                )
            elif report.adx > 25:
                score += 15
                reasons.append(f"ADX {report.adx:.1f} > 25 - strong trend, favorable for straddle")
            elif report.adx > 20:
                score += 10
                reasons.append(f"ADX {report.adx:.1f} moderate trend - acceptable")
            elif report.adx > 15:
                score += 0
                reasons.append(f"ADX {report.adx:.1f} weak trend - uncertain direction")
            else:
                score -= 10
                reasons.append(
                    f"ADX {report.adx:.1f} < 15 - very weak trend, unlikely to see big move"
                )

        # Factor 4: Market Direction (15% weight) - Epic 22, Task 024
        # Straddle profits from big moves in either direction
        if report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score += 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - momentum suggests big move potential"
            )
        elif report.macd_signal in ["bullish_exhausted", "bearish_exhausted"]:
            score += 12
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - might reverse sharply (big move)"
            )
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 10
            reasons.append(f"{report.macd_signal.capitalize()} direction - some potential for move")
        elif report.macd_signal == "neutral":
            score += 8
            reasons.append("Neutral market - potential for move in either direction")

        # Factor 5: Volatility Compression (10% weight) - Bollinger squeeze
        # Price squeezing at bands suggests expansion coming
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - consolidation before expansion")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score += 5
            reasons.append("Price at Bollinger extremes - potential for big move")

        # Market stress consideration
        # High stress can mean volatility expansion (good for straddles)
        if report.market_stress_level > 60:
            score += 5
            reasons.append(
                f"Elevated market stress ({report.market_stress_level:.0f}) - "
                "volatility expansion potential"
            )
        elif report.market_stress_level < 20:
            score -= 5
            reasons.append("Very low market stress - may lack catalyst for big move")

        return (score, reasons)

    def _find_atm_strike(self, current_price: Decimal) -> Decimal:
        """
        Find at-the-money strike for straddle.

        For straddles, both call and put use the same ATM strike.

        Args:
            current_price: Current stock price

        Returns:
            ATM strike price (rounded to nearest standard strike)
        """
        # Round to nearest strike
        return round_to_even_strike(current_price)

    def _calculate_breakevens(
        self, strike: Decimal, total_debit: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for straddle.

        Formula:
        - Upper breakeven: Strike + Total Debit
        - Lower breakeven: Strike - Total Debit

        Example: $100 strike, $8 total debit
                 Upper BE = $108, Lower BE = $92

        Args:
            strike: ATM strike price
            total_debit: Total premium paid (call + put)

        Returns:
            (breakeven_up, breakeven_down) tuple
        """
        breakeven_up = strike + total_debit
        breakeven_down = strike - total_debit
        return (breakeven_up, breakeven_down)

    def _calculate_max_loss(
        self, call_premium: Decimal, put_premium: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate maximum loss for straddle.

        Max loss = Total debit paid (occurs if stock exactly at strike at expiration)

        Formula: (Call Premium + Put Premium) × 100 × quantity

        Example: $5 call + $3 put, 1 contract = $800 max loss

        Args:
            call_premium: Premium paid for call
            put_premium: Premium paid for put
            quantity: Number of straddles

        Returns:
            Maximum loss in dollars
        """
        total_debit = call_premium + put_premium
        return total_debit * Decimal("100") * Decimal(str(quantity))

    def _calculate_net_delta(self, call_delta: float, put_delta: float) -> float:
        """
        Calculate net delta for straddle.

        Should be near zero (delta-neutral position).

        Formula: Call Delta + Put Delta

        Example: Call delta +0.52, Put delta -0.48 = Net delta +0.04

        Args:
            call_delta: Delta of long call
            put_delta: Delta of long put (negative)

        Returns:
            Net delta (should be near 0)
        """
        return call_delta + put_delta

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for long straddle.

        Two legs:
        1. Buy call at ATM strike
        2. Buy put at ATM strike (same strike)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - strike: ATM strike for both call and put
                - quantity: Number of contracts

        Returns:
            List with two Legs (buy call, buy put)
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="straddle",
            strikes={"strike": context["strike"]},
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for long straddle.

        Two legs:
        1. Sell to close long call
        2. Sell to close long put

        Args:
            position: Position with:
                - strikes: {"strike": Decimal} (same for both call and put)
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

        # Get session
        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        strike = position.strikes["strike"]  # Same strike for both

        # Build spec dictionaries for bulk fetch
        call_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": strike,
                "option_type": "C",
            }
        ]

        put_specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": strike,
                "option_type": "P",
            }
        ]

        # Get call instrument
        call_instruments = await get_option_instruments_bulk(session, call_specs)

        if not call_instruments:
            raise ValueError(f"No call found at strike {strike}")

        call_instrument = call_instruments[0]

        # Get put instrument
        put_instruments = await get_option_instruments_bulk(session, put_specs)

        if not put_instruments:
            raise ValueError(f"No put found at strike {strike}")

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
        Score market conditions for long straddle (0-100).

        Evaluates volatility environment and trend strength.
        Ideal: Low IV (<30), strong trend (ADX>25), neutral bias.
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
        Prepare long straddle suggestion context.

        Builds context for buying ATM call + ATM put (same strike, same expiration).
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

        # Find ATM strike
        atm_strike = self._find_atm_strike(Decimal(str(report.current_price)))

        # Find expiration with both call and put at ATM strike
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        target_criteria = {
            "call_strike": atm_strike,
            "put_strike": atm_strike,
        }

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(f"No expiration with ATM call+put at ${atm_strike} for {symbol}")
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} "
            f"with ATM strike: ${strikes.get('call_strike')}"
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
            "strike": float(atm_strike),
            "strikes": {"atm_strike": float(atm_strike)},
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
        """Calculate suggestion from cached pricing data (long straddle = buy ATM call + put)."""
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

        # Extract pricing for ATM call and put
        strike = Decimal(str(strikes["atm_strike"]))
        call_payload = pricing_data.snapshots.get("call_strike")
        put_payload = pricing_data.snapshots.get("put_strike")

        if not call_payload or not put_payload:
            logger.warning(f"Missing pricing data for straddle at strike {strike}")
            return None

        # Calculate mid prices from bid/ask
        call_bid = call_payload.get("bid")
        call_ask = call_payload.get("ask")
        put_bid = put_payload.get("bid")
        put_ask = put_payload.get("ask")

        if any(x is None for x in [call_bid, call_ask, put_bid, put_ask]):
            logger.warning(f"Missing bid/ask for straddle at strike {strike}")
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
            long_call_strike=strike,
            long_put_strike=strike,
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
            f"User {self.user.id}: Long Straddle suggestion - "
            f"Debit: ${total_debit:.2f}, Strike: ${strike}"
        )
        return suggestion
