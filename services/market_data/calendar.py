import pandas as pd
import pandas_market_calendars as mcal


class MarketCalendar:
    """Precise trading day calculations using NYSE calendar."""

    def __init__(self):
        self.nyse = mcal.get_calendar("NYSE")

    def get_trading_days_needed(self, symbol: str, target_days: int):
        """Calculate exact calendar days needed for N trading days.

        Args:
            symbol: Stock symbol (used for future exchange-specific logic)
            target_days: Number of trading days needed

        Returns:
            tuple: (start_date, end_date) - Exact date range, no buffer needed
        """
        today = pd.Timestamp.now()

        # Estimate calendar days needed using trading day ratio
        # Ratio of calendar days to trading days is roughly 365/252 ~= 1.45
        # Add buffer for holidays (10 days typical holidays + weekends)
        calendar_days_needed = int(target_days * 1.5) + 20

        # Get schedule for the estimated period
        # Use today + 1 to ensure today is included in the schedule
        schedule = self.nyse.schedule(
            start_date=today - pd.DateOffset(days=calendar_days_needed),
            end_date=today + pd.DateOffset(days=1),
        )

        # Get last N trading days (precise, no guessing)
        # Use min() to handle cases where schedule has fewer days than requested
        available_days = len(schedule)
        days_to_take = min(target_days, available_days)
        trading_days = schedule.index[-days_to_take:]
        start_date = trading_days[0]

        return start_date, today

    def count_trading_days(self, start_date, end_date) -> int:
        """Count actual trading days between start and end date.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            int: Number of trading days in the range
        """
        schedule = self.nyse.schedule(start_date=start_date, end_date=end_date)
        return len(schedule)

    def next_trading_day(self, date):
        """Get next trading day, handling holidays.

        Args:
            date: Current date

        Returns:
            pd.Timestamp: Next trading day
        """
        schedule = self.nyse.schedule(
            start_date=date, end_date=date + pd.DateOffset(days=10)  # Look ahead 10 days
        )
        return schedule.index[1] if len(schedule) > 1 else None

    def is_trading_day(self, date):
        """Check if given date is a trading day.

        Args:
            date: Date to check

        Returns:
            bool: True if trading day
        """
        schedule = self.nyse.schedule(start_date=date, end_date=date)
        return len(schedule) > 0

    def seconds_until_next_trading_day(self, from_time=None):
        """Calculate seconds until next trading day (for cache TTL).

        Args:
            from_time: Starting time (defaults to now)

        Returns:
            int: Seconds until next trading day
        """
        from_time = from_time or pd.Timestamp.now()
        next_day = self.next_trading_day(from_time)

        if next_day:
            return int((next_day - from_time).total_seconds())
        return 86400  # Default to 24 hours
