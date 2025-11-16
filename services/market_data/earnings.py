"""
Earnings Calendar Service - Track upcoming earnings events

Epic 22 Task 016: Integrates with TastyTrade MarketMetricInfo to provide:
- Days until next earnings
- Earnings date detection
- Earnings window validation
- Strategy-specific earnings recommendations
"""

from dataclasses import dataclass
from datetime import date

from services.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EarningsInfo:
    """Container for earnings information"""

    symbol: str
    has_upcoming_earnings: bool
    earnings_date: date | None
    days_until_earnings: int | None
    is_within_danger_window: bool  # Within 7 days
    recommendation: str  # "avoid", "target", or "neutral"


class EarningsCalendar:
    """
    Earnings calendar service for strategy decision-making

    Provides:
    - Upcoming earnings detection
    - Days until earnings calculation
    - Strategy-specific recommendations
    """

    # Configuration
    DANGER_WINDOW_DAYS = 7  # Avoid entries within 7 days of earnings
    TARGET_WINDOW_DAYS = 3  # Optimal for earnings plays (1-3 days before)

    def __init__(self):
        pass

    async def get_earnings_info(self, symbol: str, metrics: dict) -> EarningsInfo:
        """
        Get earnings information for a symbol

        Args:
            symbol: Stock symbol
            metrics: Market metrics from MarketDataService.get_market_metrics()

        Returns:
            EarningsInfo with dates and recommendations
        """
        today = date.today()

        # Extract earnings data from metrics
        has_earnings = False
        earnings_date = None
        days_until = None

        if metrics and "earnings" in metrics:
            earnings = metrics["earnings"]
            if earnings and "expected_report_date" in earnings:
                earnings_date_str = earnings["expected_report_date"]
                if earnings_date_str:
                    # Parse ISO date string
                    from datetime import datetime

                    earnings_date = datetime.fromisoformat(earnings_date_str).date()

                    if earnings_date > today:
                        has_earnings = True
                        days_until = (earnings_date - today).days

        # Determine if within danger window
        is_within_danger = days_until is not None and 0 <= days_until <= self.DANGER_WINDOW_DAYS

        # Generate recommendation
        recommendation = self._generate_recommendation(days_until)

        return EarningsInfo(
            symbol=symbol,
            has_upcoming_earnings=has_earnings,
            earnings_date=earnings_date,
            days_until_earnings=days_until,
            is_within_danger_window=is_within_danger,
            recommendation=recommendation,
        )

    def _generate_recommendation(self, days_until: int | None) -> str:
        """
        Generate strategy recommendation based on earnings timing

        Returns:
            "avoid" - Most strategies should avoid
            "target" - Good for volatility plays
            "neutral" - Far enough away, no impact
        """
        if days_until is None:
            return "neutral"

        if 0 <= days_until <= self.TARGET_WINDOW_DAYS:
            # 1-3 days before earnings - TARGET for vol plays
            return "target"
        if days_until <= self.DANGER_WINDOW_DAYS:
            # 4-7 days before earnings - AVOID for most strategies
            return "avoid"
        # More than 7 days away - NEUTRAL
        return "neutral"

    def should_avoid_earnings(
        self, earnings_info: EarningsInfo, strategy_type: str
    ) -> tuple[bool, str]:
        """
        Determine if a strategy should avoid this earnings event

        Args:
            earnings_info: Earnings information
            strategy_type: Strategy name (e.g., "iron_condor", "long_straddle")

        Returns:
            (should_avoid: bool, reason: str)
        """
        # Strategies that TARGET earnings
        earnings_strategies = {
            "long_straddle",
            "long_strangle",
            "call_backspread",
        }

        # Strategies that AVOID earnings
        avoid_strategies = {
            "senex_trident",
            "bull_put_spread",
            "bear_call_spread",
            "bull_call_spread",
            "bear_put_spread",
            "short_iron_condor",
            "long_iron_condor",
            "iron_butterfly",
            "calendar_spread",
            "covered_call",
            "cash_secured_put",
        }

        if not earnings_info.has_upcoming_earnings:
            return (False, "No upcoming earnings")

        # Earnings targeting strategies
        if strategy_type in earnings_strategies:
            if earnings_info.recommendation == "target":
                return (
                    False,
                    f"Perfect timing for earnings play ({earnings_info.days_until_earnings} days)",
                )
            return (
                True,
                f"Too far from earnings ({earnings_info.days_until_earnings} days)",
            )

        # Earnings avoiding strategies
        if strategy_type in avoid_strategies:
            if earnings_info.is_within_danger_window:
                return (
                    True,
                    f"Earnings in {earnings_info.days_until_earnings} days - AVOID for {strategy_type}",
                )
            return (
                False,
                f"Earnings {earnings_info.days_until_earnings} days away - safe",
            )

        # Unknown strategy - default to caution
        if earnings_info.is_within_danger_window:
            return (
                True,
                f"Earnings in {earnings_info.days_until_earnings} days - caution",
            )

        return (False, "No earnings impact")
