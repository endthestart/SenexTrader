"""
Unified Straddle Strategy - ATM call + ATM put with direction parameter.

Supports both LONG and SHORT straddles:
- LONG: Buy ATM call + ATM put (wants LOW IV, expects big move)
- SHORT: Sell ATM call + ATM put (wants HIGH IV, expects range-bound) - UNLIMITED RISK

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


class StraddleStrategy(BaseStrategy):
    """
    Unified Straddle Strategy - Buy or Sell ATM call + ATM put.

    Direction determines behavior:
    - LONG: Buy ATM call + ATM put (debit, wants LOW IV < 40, expects big move)
    - SHORT: Sell ATM call + ATM put (credit, wants HIGH IV > 50, range-bound) - UNLIMITED RISK

    Structure:
    - Same strike for both call and put (ATM)
    - Same expiration for both legs
    - Max loss (LONG): Total debit paid
    - Max loss (SHORT): UNLIMITED (naked short call)
    """

    # Shared constants
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60

    # LONG-specific constants (want low IV to buy cheap)
    LONG_MAX_IV_RANK = 40
    LONG_OPTIMAL_IV_RANK = 25
    LONG_MIN_HV_IV_RATIO = 1.1
    LONG_OPTIMAL_HV_IV_RATIO = 1.3
    LONG_MIN_ADX_TREND = 20
    LONG_OPTIMAL_ADX = 30
    LONG_PROFIT_TARGET_PCT = 50

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
        Initialize StraddleStrategy with direction.

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
            return "long_straddle"
        return "short_straddle"

    def automation_enabled_by_default(self) -> bool:
        """
        Both directions have automation disabled.

        - LONG: High risk, timing critical
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

        LONG: Wants LOW IV (buy cheap options), strong trend
        SHORT: Wants HIGH IV (sell expensive options), range-bound
        """
        if self.direction == Side.LONG:
            return await self._score_long_straddle(report)
        return await self._score_short_straddle(report)

    async def _score_long_straddle(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for LONG straddle - wants LOW IV, strong trend."""
        score = 50.0
        reasons = []

        # IV Rank - WANT LOW (buy cheap options)
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

        # HV/IV Ratio - Want IV underpriced (ratio > 1.0)
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

        # ADX - Want strong trend for big move
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

        # Market direction
        if report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score += 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - momentum suggests big move potential"
            )
        elif report.macd_signal == "neutral":
            score += 8
            reasons.append("Neutral market - potential for move in either direction")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 10
            reasons.append(f"{report.macd_signal.capitalize()} direction - some potential for move")

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - consolidation before expansion")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score += 5
            reasons.append("Price at Bollinger extremes - potential for big move")

        # Market stress
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

    async def _score_short_straddle(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for SHORT straddle - wants HIGH IV, range-bound."""
        score = 50.0
        reasons = []

        # IV Rank - WANT HIGH (sell expensive options)
        if report.iv_rank > 70:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 70% - exceptional premium for selling"
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
                f"IV Rank {report.iv_rank:.1f} < 40% - insufficient premium for naked straddle"
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
                    f"ADX {report.adx:.1f} < 20 - range-bound, ideal for short straddle"
                )
            elif report.adx < 25:
                score += 15
                reasons.append(f"ADX {report.adx:.1f} weak trend - favorable for premium selling")
            elif report.adx < 30:
                score += 5
                reasons.append(f"ADX {report.adx:.1f} moderate trend - acceptable")
            elif report.adx < 35:
                score -= 10
                reasons.append(f"ADX {report.adx:.1f} strong trend - risky for short straddle")
            else:
                score -= 25
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - very strong trend, avoid short straddle"
                )

        # Market direction - neutral is ideal
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for short straddle, no directional bias")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 5
            reasons.append(f"{report.macd_signal.capitalize()} bias - manageable for short straddle")
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 15
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - dangerous for short straddle"
            )

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - ideal for range-bound trade")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 8
            reasons.append("Price at Bollinger extremes - risky for short straddle")

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

    def _find_atm_strike(self, current_price: Decimal) -> Decimal:
        """Find at-the-money strike for straddle."""
        return round_to_even_strike(current_price)

    def _calculate_breakevens(
        self, strike: Decimal, total_premium: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven prices for straddle.

        For LONG: Strike ± Total Debit
        For SHORT: Strike ± Total Credit
        """
        breakeven_up = strike + total_premium
        breakeven_down = strike - total_premium
        return (breakeven_up, breakeven_down)

    def _calculate_max_loss(
        self, call_premium: Decimal, put_premium: Decimal, quantity: int = 1
    ) -> Decimal:
        """
        Calculate maximum loss for LONG straddle.

        Max loss = Total debit paid (occurs if stock exactly at strike at expiration)
        Note: SHORT straddle has UNLIMITED loss potential.
        """
        total_premium = call_premium + put_premium
        return total_premium * Decimal("100") * Decimal(str(quantity))

    def _calculate_net_delta(self, call_delta: float, put_delta: float) -> float:
        """Calculate net delta for straddle (should be near zero)."""
        return call_delta + put_delta

    async def a_score_market_conditions(
        self, report: MarketConditionReport
    ) -> tuple[float, str]:
        """Score market conditions for straddle entry."""
        score, reasons = await self._score_market_conditions_impl(report)
        score = max(0, score)
        explanation = "\n".join(reasons)
        return (score, explanation)

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for straddle based on direction.

        LONG: Target 50% gain (sell at 1.5x original debit)
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
            target_price = original_debit * Decimal("1.50")
            return [
                {
                    "spread_type": "long_straddle",
                    "profit_percentage": 50,
                    "target_price": target_price,
                    "original_debit": original_debit,
                }
            ]
        original_credit = abs(opening_order.price)
        target_price = original_credit * Decimal("0.50")
        return [
            {
                "spread_type": "short_straddle",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_credit": original_credit,
            }
        ]

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """Build opening legs for straddle."""
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
        """Build closing legs for straddle."""
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        strike = position.strikes["strike"]

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

        call_instruments = await get_option_instruments_bulk(session, call_specs)
        if not call_instruments:
            raise ValueError(f"No call found at strike {strike}")

        put_instruments = await get_option_instruments_bulk(session, put_specs)
        if not put_instruments:
            raise ValueError(f"No put found at strike {strike}")

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
