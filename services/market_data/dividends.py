"""
Dividend Schedule Service - Track dividend events for strategy timing

Epic 22 Task 017: Integrates with TastyTrade MarketMetricInfo to provide:
- Ex-dividend date tracking
- Assignment risk assessment
- Strategy-specific dividend recommendations
"""

from dataclasses import dataclass
from datetime import date

from services.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DividendInfo:
    """Container for dividend information"""

    symbol: str
    has_upcoming_dividend: bool
    ex_dividend_date: date | None
    dividend_next_date: date | None
    days_until_ex_div: int | None
    days_until_next_div: int | None
    is_within_risk_window: bool  # Within 5 days of ex-div
    assignment_risk_level: str  # "low", "moderate", "high"


class DividendSchedule:
    """
    Dividend schedule service for strategy decision-making

    Provides:
    - Ex-dividend date detection
    - Assignment risk assessment
    - Strategy-specific recommendations
    """

    # Configuration
    RISK_WINDOW_DAYS = 5  # Assignment risk increases 5 days before ex-div
    HIGH_RISK_DAYS = 2  # Very high assignment risk 0-2 days before

    def __init__(self):
        pass

    async def get_dividend_info(self, symbol: str, metrics: dict) -> DividendInfo:
        """
        Get dividend information for a symbol

        Args:
            symbol: Stock symbol
            metrics: Market metrics from MarketDataService.get_market_metrics()

        Returns:
            DividendInfo with dates and risk assessment
        """
        today = date.today()

        # Extract dividend data from metrics
        has_dividend = False
        ex_div_date = None
        next_div_date = None
        days_until_ex = None
        days_until_next = None

        if metrics:
            # Ex-dividend date
            if metrics.get("dividend_ex_date"):
                from datetime import datetime

                ex_div_date = datetime.fromisoformat(metrics["dividend_ex_date"]).date()
                if ex_div_date > today:
                    has_dividend = True
                    days_until_ex = (ex_div_date - today).days

            # Next dividend date
            if metrics.get("dividend_next_date"):
                from datetime import datetime

                next_div_date = datetime.fromisoformat(metrics["dividend_next_date"]).date()
                if next_div_date > today:
                    has_dividend = True
                    days_until_next = (next_div_date - today).days

        # Use the closest upcoming date for risk assessment
        days_until = None
        if days_until_ex is not None and days_until_next is not None:
            days_until = min(days_until_ex, days_until_next)
        elif days_until_ex is not None:
            days_until = days_until_ex
        elif days_until_next is not None:
            days_until = days_until_next

        # Determine if within risk window
        is_within_risk = days_until is not None and 0 <= days_until <= self.RISK_WINDOW_DAYS

        # Assess assignment risk level
        risk_level = self._assess_assignment_risk(days_until)

        return DividendInfo(
            symbol=symbol,
            has_upcoming_dividend=has_dividend,
            ex_dividend_date=ex_div_date,
            dividend_next_date=next_div_date,
            days_until_ex_div=days_until_ex,
            days_until_next_div=days_until_next,
            is_within_risk_window=is_within_risk,
            assignment_risk_level=risk_level,
        )

    def _assess_assignment_risk(self, days_until: int | None) -> str:
        """
        Assess assignment risk level based on dividend timing

        Returns:
            "low" - More than 5 days away or no dividend
            "moderate" - 3-5 days before ex-div
            "high" - 0-2 days before ex-div (very high assignment risk)
        """
        if days_until is None:
            return "low"

        if 0 <= days_until <= self.HIGH_RISK_DAYS:
            return "high"
        if days_until <= self.RISK_WINDOW_DAYS:
            return "moderate"
        return "low"

    def should_avoid_dividend(
        self, dividend_info: DividendInfo, strategy_type: str
    ) -> tuple[bool, str]:
        """
        Determine if a strategy should avoid this dividend event

        Args:
            dividend_info: Dividend information
            strategy_type: Strategy name (e.g., "covered_call", "cash_secured_put")

        Returns:
            (should_avoid: bool, reason: str)
        """
        # Strategies with assignment risk from dividends
        high_risk_strategies = {
            "covered_call",  # Short call may get assigned before ex-div
            "bear_call_spread",  # Short call leg has assignment risk
        }

        # Strategies with moderate dividend considerations
        moderate_risk_strategies = {
            "cash_secured_put",  # Assignment more likely before ex-div
            "bull_put_spread",  # Short put may get assigned
        }

        if not dividend_info.has_upcoming_dividend:
            return (False, "No upcoming dividend")

        # High risk strategies (covered calls, short calls)
        if strategy_type in high_risk_strategies:
            if dividend_info.assignment_risk_level == "high":
                days = dividend_info.days_until_ex_div or dividend_info.days_until_next_div
                return (
                    True,
                    f"HIGH assignment risk - dividend in {days} days (close position before ex-div)",
                )
            if dividend_info.assignment_risk_level == "moderate":
                days = dividend_info.days_until_ex_div or dividend_info.days_until_next_div
                return (
                    True,
                    f"MODERATE assignment risk - dividend in {days} days (monitor closely)",
                )

        # Moderate risk strategies
        if strategy_type in moderate_risk_strategies:
            if dividend_info.assignment_risk_level == "high":
                days = dividend_info.days_until_ex_div or dividend_info.days_until_next_div
                return (
                    True,
                    f"Dividend in {days} days - increased assignment risk for {strategy_type}",
                )

        # Far enough away or low risk
        return (False, "Dividend risk acceptable")
