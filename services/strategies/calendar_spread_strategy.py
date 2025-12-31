"""
Calendar Spread Strategy - Time decay differential play.

This strategy exploits theta acceleration between near-term and longer-term options.
It sells a near-term option (20-30 DTE) and buys a longer-term option (50-60 DTE)
at the same strike to profit from theta differential.

Strategy Characteristics:
- Different expirations: Near-term vs Long-term (same strike)
- Theta advantage: Near-term decays 2-3x faster
- IV expansion benefits: Long leg gains from IV increase
- Low IV entry: Opposite of credit spreads (want cheap options to buy)
- Neutral directional: Profit maximized at strike price

When to Use:
- IV rank < 40 (low IV, cheap to buy long option)
- ADX < 20 (neutral/range-bound market)
- HV/IV ratio > 1.1 (room for IV expansion)
- No near-term catalysts (earnings, etc.)
- Price stable near target strike

"""

from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.market_data.option_chains import OptionChainService
from services.strategies.base import BaseStrategy
from services.strategies.utils.strike_utils import round_to_even_strike
from trading.models import Position

logger = get_logger(__name__)


class CalendarSpreadStrategy(BaseStrategy):
    """
    Unified Calendar Spread Strategy with option_type parameter.

    Supports both CALL and PUT calendar spreads:
    - CALL: Sell near-term call, buy longer-term call (same strike)
    - PUT: Sell near-term put, buy longer-term put (same strike)

    Structure:
    - Sell 1 option @ strike K, DTE 20-30 (near-term)
    - Buy 1 option @ strike K, DTE 50-60 (long-term)
    - Same strike, different expirations, same option type

    """

    # Strategy constants - IV Environment (want LOW IV)
    MIN_IV_RANK = 0
    MAX_IV_RANK = 40
    OPTIMAL_IV_RANK = 25

    # DTE Targets
    NEAR_TERM_DTE_TARGET = 25
    NEAR_TERM_DTE_MIN = 15
    NEAR_TERM_DTE_MAX = 35

    LONG_TERM_DTE_TARGET = 55
    LONG_TERM_DTE_MIN = 45
    LONG_TERM_DTE_MAX = 75

    # DTE ratio should be roughly 2:1 (long:near)
    MIN_DTE_RATIO = 1.6
    IDEAL_DTE_RATIO = 2.2
    MAX_DTE_RATIO = 3.0

    # Market Conditions
    MAX_ADX_NEUTRAL = 20
    OPTIMAL_ADX = 15
    MIN_HV_IV_RATIO = 1.1
    OPTIMAL_HV_IV_RATIO = 1.3

    def __init__(self, user, option_type: str = "CALL"):
        """
        Initialize calendar spread strategy with option type.

        Args:
            user: User object
            option_type: "CALL" or "PUT"
        """
        super().__init__(user)
        self.option_type = option_type
        self.option_chain_service = OptionChainService()

    @property
    def strategy_name(self) -> str:
        """Return strategy name based on option type."""
        if self.option_type == "CALL":
            return "call_calendar"
        return "put_calendar"

    def automation_enabled_by_default(self) -> bool:
        """Calendar spreads are manual (timing sensitive)."""
        return False

    def should_place_profit_targets(self, position: Position) -> bool:
        """Enable profit targets."""
        return True

    def get_dte_exit_threshold(self, position: Position) -> int:
        """Exit at 7 DTE on near-term leg."""
        return 7

    async def a_score_market_conditions(
        self, report: MarketConditionReport
    ) -> tuple[float, str]:
        """Score market conditions for Calendar Spread entry (0-100)."""
        score = 50.0
        reasons = []

        # IV RANK SCORING - WANT LOW
        iv_score, iv_reasons = self._score_iv_environment(report)
        score += iv_score
        reasons.extend(iv_reasons)

        # ADX NEUTRAL SCORING
        adx_score, adx_reasons = self._score_neutral_market(report)
        score += adx_score
        reasons.extend(adx_reasons)

        # HV/IV RATIO SCORING
        hv_iv_score, hv_iv_reasons = self._score_iv_expansion_potential(report)
        score += hv_iv_score
        reasons.extend(hv_iv_reasons)

        # PRICE PROXIMITY
        proximity_score = 7.0
        reasons.append("Price positioning suitable for calendar spread")
        score += proximity_score

        # Ensure score doesn't go below zero
        score = max(0, score)

        explanation = "\n".join(reasons)
        logger.info(f"{self.strategy_name} scoring for {report.symbol}: {score:.1f}/100")

        return (score, explanation)

    def _score_iv_environment(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score IV rank environment (want LOW IV)."""
        iv_rank = report.iv_rank
        reasons = []

        if iv_rank < 25:
            score = 35.0
            reasons.append(
                f"IV rank {iv_rank:.1f} - EXCELLENT value, cheap to buy calendar spread"
            )
        elif iv_rank < 30:
            score = 25.0
            reasons.append(f"IV rank {iv_rank:.1f} - Very good value for calendar")
        elif iv_rank < 40:
            score = 15.0
            reasons.append(f"IV rank {iv_rank:.1f} - Good value for calendar entry")
        elif iv_rank < 50:
            score = 0.0
            reasons.append(f"IV rank {iv_rank:.1f} - Neutral, prefer lower IV")
        elif iv_rank < 60:
            score = -20.0
            reasons.append(f"IV rank {iv_rank:.1f} - Expensive to buy, poor value")
        else:
            score = -35.0
            reasons.append(f"IV rank {iv_rank:.1f} - VERY EXPENSIVE, avoid buying")

        return (score, reasons)

    def _score_neutral_market(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score ADX for neutral/range-bound market."""
        adx = report.adx
        reasons = []

        if adx is None:
            score = 0.0
            reasons.append("ADX unavailable - cannot assess trend strength")
        elif adx < 15:
            score = 25.0
            reasons.append(
                f"ADX {adx:.1f} - Extremely neutral, perfect for calendar spread"
            )
        elif adx < 20:
            score = 20.0
            reasons.append(f"ADX {adx:.1f} - Neutral/range-bound market, favorable")
        elif adx < 25:
            score = 10.0
            reasons.append(f"ADX {adx:.1f} - Weak trend, acceptable")
        elif adx < 30:
            score = -10.0
            reasons.append(f"ADX {adx:.1f} - Moderate trend, risky for calendar")
        else:
            score = -25.0
            reasons.append(f"ADX {adx:.1f} - Strong trend, AVOID calendar spreads")

        return (score, reasons)

    def _score_iv_expansion_potential(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score HV/IV ratio for IV expansion potential."""
        hv_iv = report.hv_iv_ratio
        reasons = []

        if hv_iv > 1.3:
            score = 20.0
            reasons.append(
                f"HV/IV {hv_iv:.2f} - Excellent IV expansion potential"
            )
        elif hv_iv > 1.1:
            score = 15.0
            reasons.append(f"HV/IV {hv_iv:.2f} - Good room for IV expansion")
        elif hv_iv > 1.0:
            score = 5.0
            reasons.append(f"HV/IV {hv_iv:.2f} - Moderate expansion potential")
        elif hv_iv > 0.9:
            score = 0.0
            reasons.append(f"HV/IV {hv_iv:.2f} - Limited expansion room")
        else:
            score = -10.0
            reasons.append(f"HV/IV {hv_iv:.2f} - IV elevated, expansion unlikely")

        return (score, reasons)

    async def build_opening_legs(self, context: dict) -> list:
        """Build opening legs for calendar spread."""
        raise NotImplementedError("CalendarSpreadStrategy.build_opening_legs requires full implementation")

    async def build_closing_legs(self, position: Position) -> list:
        """Build closing legs for calendar spread."""
        raise NotImplementedError("CalendarSpreadStrategy.build_closing_legs requires full implementation")

    async def a_get_profit_target_specifications(self, position: Position, *args) -> list:
        """Return profit target specifications for calendar spread."""
        from trading.models import TradeOrder

        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        original_debit = abs(opening_order.price)
        # Target: close when position value = 1.25x original debit (25% gain)
        target_price = original_debit * Decimal("1.25")

        return [
            {
                "spread_type": self.strategy_name,
                "profit_percentage": 25,
                "target_price": target_price,
                "original_debit": original_debit,
            }
        ]

