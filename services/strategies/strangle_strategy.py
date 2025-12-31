"""
Unified Strangle Strategy - OTM call + OTM put with direction parameter.

Supports both LONG and SHORT strangles:
- LONG: Buy OTM call + OTM put (wants VERY LOW IV, expects massive move)
- SHORT: Sell OTM call + OTM put (wants HIGH IV, expects range-bound) - UNLIMITED RISK

"""

from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy
from services.strategies.core.types import Side
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


class StrangleStrategy(BaseStrategy):
    """
    Unified Strangle Strategy - Buy or Sell OTM call + OTM put.

    Direction determines behavior:
    - LONG: Buy OTM call + OTM put (debit, wants VERY LOW IV < 35, expects massive move)
    - SHORT: Sell OTM call + OTM put (credit, wants HIGH IV > 50, range-bound) - UNLIMITED RISK

    Structure:
    - Call strike: ~5% above current price
    - Put strike: ~5% below current price
    - Same expiration for both legs
    - Max loss (LONG): Total debit paid
    - Max loss (SHORT): UNLIMITED (naked short call)
    """

    # Shared constants
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    OTM_PERCENTAGE = 0.05  # 5% OTM on each side

    # LONG-specific constants (want VERY low IV - stricter than straddle)
    LONG_MAX_IV_RANK = 35
    LONG_OPTIMAL_IV_RANK = 20
    LONG_MIN_HV_IV_RATIO = 1.1
    LONG_OPTIMAL_HV_IV_RATIO = 1.4
    LONG_MIN_ADX_TREND = 25
    LONG_OPTIMAL_ADX = 35
    LONG_PROFIT_TARGET_PCT = 100

    # SHORT-specific constants (want high IV to sell expensive)
    SHORT_MIN_IV_RANK = 50
    SHORT_OPTIMAL_IV_RANK = 65
    SHORT_MAX_HV_IV_RATIO = 0.9
    SHORT_OPTIMAL_HV_IV_RATIO = 0.75
    SHORT_MAX_ADX = 25
    SHORT_IDEAL_ADX_MAX = 20
    SHORT_PROFIT_TARGET_PCT = 50

    def __init__(self, user, direction: Side = Side.LONG):
        """
        Initialize StrangleStrategy with direction.

        Args:
            user: User object
            direction: Side.LONG (buy) or Side.SHORT (sell)
        """
        super().__init__(user)
        self.direction = direction

    @property
    def strategy_name(self) -> str:
        """Return strategy name based on direction."""
        if self.direction == Side.LONG:
            return "long_strangle"
        return "short_strangle"

    def automation_enabled_by_default(self) -> bool:
        """
        Both directions have automation disabled.

        - LONG: Very high risk, timing critical, needs 10%+ move
        - SHORT: UNLIMITED RISK, requires active management
        """
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets for both directions."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Exit at 21 DTE to manage time decay/gamma risk."""
        return 21

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions based on direction.

        LONG: Wants VERY LOW IV (buy cheap OTM), very strong trend
        SHORT: Wants HIGH IV (sell expensive OTM), range-bound
        """
        if self.direction == Side.LONG:
            return await self._score_long_strangle(report)
        return await self._score_short_strangle(report)

    async def _score_long_strangle(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for LONG strangle - wants VERY LOW IV, very strong trend."""
        score = 50.0
        reasons = []

        # IV Rank - WANT VERY LOW (buy dirt cheap OTM options)
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

        # HV/IV Ratio - Want IV severely underpriced
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

        # ADX - Want VERY strong trend (needs massive move)
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

        # Market direction
        if report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score += 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - momentum suggests massive move potential"
            )
        elif report.macd_signal == "neutral":
            score += 8
            reasons.append("Neutral market - potential for massive move in either direction")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 10
            reasons.append(f"{report.macd_signal.capitalize()} direction - some potential for move")

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 5
            reasons.append("Price consolidating - potential for volatility expansion")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score += 3
            reasons.append("Price at extremes - trend continuation potential")

        # Market stress - high is good for long strangle
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

    async def _score_short_strangle(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for SHORT strangle - wants HIGH IV, range-bound."""
        score = 50.0
        reasons = []

        # IV Rank - WANT HIGH (sell expensive OTM options)
        if report.iv_rank > 70:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 70% - exceptional premium for selling OTM"
            )
        elif report.iv_rank > 60:
            score += 20
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (60-70%) - excellent for premium selling"
            )
        elif report.iv_rank > 50:
            score += 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} adequate (50-60%) - acceptable premium")
        elif report.iv_rank > 40:
            score -= 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} - low premium, not ideal")
        else:
            score -= 25
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 40% - insufficient premium for naked strangle"
            )

        # HV/IV Ratio - Want IV overpriced (ratio < 1.0)
        if report.hv_iv_ratio < 0.8:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - IV significantly overpriced, "
                "excellent for selling"
            )
        elif report.hv_iv_ratio < 0.9:
            score += 12
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.9 - IV moderately overpriced"
            )
        elif report.hv_iv_ratio < 1.0:
            score += 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - near fair value")
        elif report.hv_iv_ratio < 1.1:
            score -= 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - slightly underpriced")
        else:
            score -= 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.1 - IV underpriced, poor selling opportunity"
            )

        # ADX - Want WEAK trend (range-bound)
        if report.adx is not None:
            if report.adx < 20:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound, ideal for short strangle"
                )
            elif report.adx < 25:
                score += 15
                reasons.append(f"ADX {report.adx:.1f} weak trend - favorable for premium selling")
            elif report.adx < 30:
                score += 5
                reasons.append(f"ADX {report.adx:.1f} moderate trend - acceptable")
            elif report.adx < 35:
                score -= 10
                reasons.append(f"ADX {report.adx:.1f} strong trend - risky for short strangle")
            else:
                score -= 25
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - very strong trend, avoid short strangle"
                )

        # Market direction - neutral is ideal
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for short strangle, no directional bias")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 5
            reasons.append(f"{report.macd_signal.capitalize()} bias - manageable for short strangle")
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - dangerous for short strangle"
            )

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - ideal for range-bound trade")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 8
            reasons.append("Price at Bollinger extremes - risky for short strangle")

        # Market stress - want low
        if report.market_stress_level < 30:
            score += 5
            reasons.append(
                f"Low market stress ({report.market_stress_level:.0f}) - stable environment"
            )
        elif report.market_stress_level > 60:
            score -= 10
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - "
                "increased risk of big move"
            )

        return (score, reasons)

    def _find_otm_strikes(self, current_price: Decimal) -> tuple[Decimal, Decimal]:
        """
        Find OTM strikes for strangle (5% on each side).

        Returns:
            (call_strike, put_strike) tuple
            - call_strike: ~5% above current price
            - put_strike: ~5% below current price
        """
        call_target = current_price * Decimal("1.05")
        call_strike = round_to_even_strike(call_target)

        put_target = current_price * Decimal("0.95")
        put_strike = round_to_even_strike(put_target)

        return (call_strike, put_strike)

    def _calculate_breakevens(
        self, call_strike: Decimal, put_strike: Decimal, total_premium: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for strangle.

        For LONG: Call Strike + Debit, Put Strike - Debit
        For SHORT: Call Strike + Credit, Put Strike - Credit
        """
        breakeven_up = call_strike + total_premium
        breakeven_down = put_strike - total_premium
        return (breakeven_up, breakeven_down)

    def _calculate_max_loss(
        self, call_premium: Decimal, put_premium: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate maximum loss for LONG strangle.

        Max loss = Total debit paid (occurs if stock stays between strikes)
        Note: SHORT strangle has UNLIMITED loss potential.
        """
        total_premium = call_premium + put_premium
        return total_premium * Decimal("100") * Decimal(str(quantity))

    def _calculate_net_delta(self, call_delta: float, put_delta: float) -> float:
        """Calculate net delta for strangle (should be near zero with OTM options)."""
        return call_delta + put_delta

    def _calculate_move_required_pct(
        self, current_price: Decimal, breakeven_up: Decimal, breakeven_down: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Calculate percentage move required to reach breakevens."""
        upside_move = ((breakeven_up - current_price) / current_price) * Decimal("100")
        downside_move = ((current_price - breakeven_down) / current_price) * Decimal("100")
        return (upside_move, downside_move)

    async def a_score_market_conditions(
        self, report: MarketConditionReport
    ) -> tuple[float, str]:
        """Score market conditions for strangle entry."""
        score, reasons = await self._score_market_conditions_impl(report)
        score = max(0, score)
        explanation = "\n".join(reasons)
        return (score, explanation)

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for strangle based on direction.

        LONG: Target 100% gain (sell at 2x original debit) - needs big move
        SHORT: Target 50% of credit received
        """
        from trading.models import TradeOrder

        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        if self.direction == Side.LONG:
            original_debit = abs(opening_order.price)
            target_price = original_debit * Decimal("2.00")
            return [
                {
                    "spread_type": "long_strangle",
                    "profit_percentage": 100,
                    "target_price": target_price,
                    "original_debit": original_debit,
                }
            ]
        original_credit = abs(opening_order.price)
        target_price = original_credit * Decimal("0.50")
        return [
            {
                "spread_type": "short_strangle",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_credit": original_credit,
            }
        ]

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """Build opening legs for strangle."""
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
        """Build closing legs for strangle."""
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        call_strike = position.strikes["call_strike"]
        put_strike = position.strikes["put_strike"]

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

        call_instruments = await get_option_instruments_bulk(session, [call_spec])
        if not call_instruments:
            raise ValueError(f"No call found at strike {call_strike}")

        put_instruments = await get_option_instruments_bulk(session, [put_spec])
        if not put_instruments:
            raise ValueError(f"No put found at strike {put_strike}")

        # Closing action depends on direction
        if self.direction == Side.LONG:
            call_action = "Sell to Close"
            put_action = "Sell to Close"
        else:
            call_action = "Buy to Close"
            put_action = "Buy to Close"

        return [
            Leg(
                instrument_type=call_instruments[0].instrument_type,
                symbol=call_instruments[0].symbol,
                quantity=position.quantity,
                action=call_action,
            ),
            Leg(
                instrument_type=put_instruments[0].instrument_type,
                symbol=put_instruments[0].symbol,
                quantity=position.quantity,
                action=put_action,
            ),
        ]
