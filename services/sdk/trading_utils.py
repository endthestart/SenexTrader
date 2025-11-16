"""
Trading utilities combining TastyTrade SDK utils with display formatting.

IMPORTANT:
- Format functions are ONLY for user display, never use in calculations
- Market hours checks are ONLY for order submission, not data retrieval
"""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

# Import and re-export TastyTrade utilities
from tastytrade.utils import PriceEffect

# Re-export for centralized access
__all__ = [
    "PriceEffect",
    "format_currency_for_display",
    "format_percentage_for_display",
    "get_market_hours_today",
    "is_after_market_hours",
    "is_extended_hours",
    "is_market_open_now",
    "is_pre_market_hours",
    "now_in_new_york",
]

# NYSE calendar instance for market hours checking
_nyse = mcal.get_calendar("NYSE")
_eastern = ZoneInfo("America/New_York")


def now_in_new_york() -> datetime:
    """
    Get current time in New York timezone.

    Returns:
        Current datetime in America/New_York timezone
    """
    return datetime.now(_eastern)


def get_market_hours_today() -> tuple[datetime, datetime] | None:
    """
    Get today's market open and close times in Eastern Time.

    Returns:
        Tuple of (market_open, market_close) datetimes in ET, or None if market is closed today

    Example:
        hours = get_market_hours_today()
        if hours:
            open_time, close_time = hours
            print(f"Market open: {open_time}, close: {close_time}")
    """
    today = datetime.now(_eastern).date()

    # Get market schedule for today
    schedule = _nyse.schedule(start_date=today, end_date=today)

    if schedule.empty:
        return None

    # Extract open and close times (pandas_market_calendars returns UTC times)
    market_open_utc = schedule.iloc[0]["market_open"]
    market_close_utc = schedule.iloc[0]["market_close"]

    # Convert from UTC to Eastern Time
    market_open = market_open_utc.tz_convert(_eastern).to_pydatetime()
    market_close = market_close_utc.tz_convert(_eastern).to_pydatetime()

    return market_open, market_close


def is_market_open_now() -> bool:
    """
    Check if the NYSE market is currently open for regular trading hours.

    Uses pandas_market_calendars to check both date and time accurately.
    This replaces the previous date-only check with proper time validation.

    Returns:
        True if market is currently open for regular trading, False otherwise
    """
    now = datetime.now(_eastern)
    hours = get_market_hours_today()

    if not hours:
        return False

    market_open, market_close = hours
    return market_open <= now <= market_close


def is_pre_market_hours() -> bool:
    """
    Check if currently in pre-market trading hours (4:00 AM - 9:30 AM ET).

    Returns:
        True if in pre-market hours, False otherwise
    """
    now = datetime.now(_eastern)
    current_time = now.time()

    # Pre-market: 4:00 AM to 9:30 AM ET
    pre_market_start = time(4, 0)
    pre_market_end = time(9, 30)

    # Check if it's a trading day
    hours = get_market_hours_today()
    if not hours:
        return False

    return pre_market_start <= current_time < pre_market_end


def is_after_market_hours() -> bool:
    """
    Check if currently in after-hours trading (4:00 PM - 8:00 PM ET).

    Returns:
        True if in after-hours trading, False otherwise
    """
    now = datetime.now(_eastern)
    current_time = now.time()

    # After-hours: 4:00 PM to 8:00 PM ET
    after_hours_start = time(16, 0)  # 4:00 PM
    after_hours_end = time(20, 0)  # 8:00 PM

    # Check if it's a trading day
    hours = get_market_hours_today()
    if not hours:
        return False

    return after_hours_start <= current_time <= after_hours_end


def is_extended_hours() -> bool:
    """
    Check if currently in extended trading hours (pre-market or after-hours).

    Extended hours: 4:00 AM - 8:00 PM ET on trading days.

    Returns:
        True if in extended hours (pre-market or after-hours), False otherwise
    """
    return is_pre_market_hours() or is_after_market_hours()


def format_currency_for_display(value: Decimal | None) -> str:
    """
    Format currency ONLY for user display - returns string.

    WARNING: Never use this in calculations! Only for presentation layer.

    Args:
        value: Decimal value to format

    Returns:
        Formatted string with 2 decimal places

    Examples:
        format_currency_for_display(Decimal("123.456")) -> "123.46"
        format_currency_for_display(None) -> "0.00"
    """
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def format_percentage_for_display(value: Decimal | None) -> str:
    """
    Format percentage ONLY for user display - returns string.

    WARNING: Never use this in calculations! Only for presentation layer.

    Args:
        value: Decimal value to format (as decimal, not percentage)

    Returns:
        Formatted string as percentage with 2 decimal places

    Examples:
        format_percentage_for_display(Decimal("0.1234")) -> "12.34%"
        format_percentage_for_display(None) -> "0.00%"
    """
    if value is None:
        return "0.00%"
    return f"{Decimal(str(value)) * 100:.2f}%"
