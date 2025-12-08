"""
Historical data provider using Stooq.com
CRITICAL: Provides unlimited free access to historical OHLC data

Per REAL_DATA_IMPLEMENTATION_PLAN.md:
- Unlimited requests (vs Alpha Vantage's 25/day limit)
- No API key required
- 30+ years of historical data available
- Simple CSV format for easy parsing
- Rate limiting friendly with 1-second delays

URL Pattern: https://stooq.com/q/d/l/?s={symbol}.us&d1={start_yyyymmdd}&d2={end_yyyymmdd}&i=d

SIMPLICITY FIRST: Sync implementation using requests and direct ORM calls
"""

import csv
import io
import time
from datetime import datetime
from decimal import Decimal

from django.db import models
from django.utils import timezone as dj_timezone

import requests

from services.core.cache import CacheManager
from services.core.constants import API_TIMEOUT
from services.core.logging import get_logger
from services.market_data.calendar import MarketCalendar

logger = get_logger(__name__)


class HistoricalDataProvider:
    """
    Fetches historical OHLC data from Stooq.com
    Simple sync implementation - no async complexity needed
    """

    def __init__(self):
        self.calendar = MarketCalendar()

    STOOQ_BASE_URL = "https://stooq.com/q/d/l/"

    def _build_stooq_url(self, symbol: str, start_date: datetime, end_date: datetime) -> str:
        """
        Build Stooq CSV download URL
        Format: https://stooq.com/q/d/l/?s=spy.us&d1=20240624&d2=20240922&i=d

        Special handling:
        - Symbols with dots (VI.F, etc.): Use as-is (indices/special symbols)
        - US equities (SPY, QQQ, etc.): Add .us suffix
        """
        # Convert symbol to Stooq format
        # Symbols containing dots are index/special symbols - use as-is
        stooq_symbol = symbol.lower() if "." in symbol else f"{symbol.lower()}.us"

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        return f"{self.STOOQ_BASE_URL}?s={stooq_symbol}&d1={start_str}&d2={end_str}&i=d"

    def fetch_historical_prices(self, symbol: str, days: int = 90) -> list[dict] | None:
        """
        Fetch historical OHLC data from Stooq

        Args:
            symbol: Stock/ETF symbol (e.g., 'SPY')
            days: Number of TRADING days to fetch (default 90)
                  Note: Due to weekends/holidays, actual calendar days will be longer

        Returns:
            List of dicts with: date, open, high, low, close, volume
        """
        # First check if database already has sufficient AND FRESH data
        # TOLERANCE: Accept 95% of requested days since weekends/holidays reduce count
        from django.core.cache import cache
        from django.db import models
        from django.utils import timezone as dj_timezone

        from trading.models import HistoricalPrice

        # Check both count AND freshness in single query
        records = HistoricalPrice.objects.filter(symbol=symbol).aggregate(
            count=models.Count("id"), latest=models.Max("date")
        )
        db_count = records["count"] or 0
        latest_date = records["latest"]
        min_acceptable = int(days * 0.95)  # 5% tolerance for weekends/holidays

        # Data must be both sufficient AND fresh (within last 1 day for weekends)
        today = dj_timezone.now().date()
        is_fresh = latest_date and latest_date >= today - dj_timezone.timedelta(days=1)

        if db_count >= min_acceptable and is_fresh:
            logger.debug(
                f"{symbol} has {db_count} days in DB (need {min_acceptable}+), "
                f"latest={latest_date}, skipping fetch"
            )
            return None
        if db_count >= min_acceptable:
            logger.info(
                f"{symbol} has {db_count} days but stale (latest={latest_date}) - refetching"
            )
            # Fall through to fetch fresh data

        # Check if we've fetched this symbol recently (within last 24 hours)
        # Only honor cache if DB has SUFFICIENT data (>= min_acceptable)
        # If we don't have enough data, ignore cache and refetch (previous fetch may have been incomplete)
        cache_key = CacheManager.stooq_last_fetch(symbol)
        last_fetch = cache.get(cache_key)
        if (
            last_fetch
            and db_count >= min_acceptable
            and (dj_timezone.now() - last_fetch).total_seconds() < 86400
        ):
            logger.debug(
                f"Skipping Stooq fetch for {symbol} - fetched recently and have {db_count} days"
            )
            return None

        # Use market calendar for EXACT date range (no buffer!)
        start_date, end_date = self.calendar.get_trading_days_needed(symbol, days)

        logger.info(f"Fetching {days} trading days for {symbol}: {start_date} to {end_date}")

        url = self._build_stooq_url(symbol, start_date, end_date)

        try:
            logger.info(f"Fetching {days} days of historical data for {symbol} from Stooq")
            logger.info(f"Stooq URL: {url}")

            response = requests.get(url, timeout=API_TIMEOUT)

            logger.info(
                f"Stooq response: status={response.status_code}, length={len(response.text)}"
            )

            if response.status_code != 200:
                logger.error(f"Stooq request failed: HTTP {response.status_code}")
                logger.error(f"Response body: {response.text[:500]}")
                return None

            # Log first few lines of CSV response for debugging
            csv_preview = "\n".join(response.text.split("\n")[:5])
            logger.info(f"CSV preview:\n{csv_preview}")

            data = self._parse_csv_data(response.text, symbol)
            logger.info(f"Parsed {len(data) if data else 0} records from CSV")

            if data:
                # Cache successful fetch timestamp
                cache.set(cache_key, dj_timezone.now(), 86400)  # 24 hours
            else:
                logger.warning(f"CSV parsing returned no data for {symbol}")

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}", exc_info=True)
            return None

    def _parse_csv_data(self, csv_text: str, symbol: str) -> list[dict]:
        """Parse CSV response from Stooq into structured data"""
        data = []
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        for row in csv_reader:
            try:
                # Parse date string directly - for date-only values, no timezone needed
                date_parts = row["Date"].split("-")
                parsed_date = dj_timezone.datetime(
                    int(date_parts[0]),
                    int(date_parts[1]),
                    int(date_parts[2]),
                    tzinfo=dj_timezone.get_current_timezone(),
                ).date()
                data.append(
                    {
                        "symbol": symbol,
                        "date": parsed_date,
                        "open": Decimal(row["Open"]),
                        "high": Decimal(row["High"]),
                        "low": Decimal(row["Low"]),
                        "close": Decimal(row["Close"]),  # Adjusted close from Stooq
                        "volume": int(row["Volume"]) if row["Volume"] else None,
                    }
                )
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping invalid CSV row for {symbol}: {e}")
                continue

        # Sort by date ascending
        data.sort(key=lambda x: x["date"])
        logger.info(f"Parsed {len(data)} historical records for {symbol}")
        return data

    def store_in_database(self, symbol: str, price_data: list[dict]) -> int:
        """Store historical prices in database using bulk operations to reduce lock contention.

        Uses bulk_create with ignore_conflicts for new records, then bulk_update for existing ones.
        This significantly reduces database transactions and prevents SQLite lock errors.
        """
        from django.db import transaction

        from trading.models import HistoricalPrice

        if not price_data:
            return 0

        stored_count = 0

        try:
            with transaction.atomic():
                # Create HistoricalPrice objects for all records
                price_objects = []
                dates = []
                for data in price_data:
                    price_objects.append(
                        HistoricalPrice(
                            symbol=symbol,
                            date=data["date"],
                            open=data["open"],
                            high=data["high"],
                            low=data["low"],
                            close=data["close"],
                            volume=data["volume"],
                        )
                    )
                    dates.append(data["date"])

                # Bulk create with ignore_conflicts (inserts new records, ignores existing)
                # This handles the INSERT part efficiently
                created = HistoricalPrice.objects.bulk_create(price_objects, ignore_conflicts=True)
                stored_count = len(created)

                # Now update existing records that were skipped by ignore_conflicts
                # Get existing records for the date range
                existing_records = {
                    (rec.symbol, rec.date): rec
                    for rec in HistoricalPrice.objects.filter(symbol=symbol, date__in=dates)
                }

                # Prepare updates for records that already exist
                updates = []
                for data in price_data:
                    key = (symbol, data["date"])
                    if key in existing_records:
                        record = existing_records[key]
                        # Only update if values have changed
                        if (
                            record.open != data["open"]
                            or record.high != data["high"]
                            or record.low != data["low"]
                            or record.close != data["close"]
                            or record.volume != data["volume"]
                        ):
                            record.open = data["open"]
                            record.high = data["high"]
                            record.low = data["low"]
                            record.close = data["close"]
                            record.volume = data["volume"]
                            updates.append(record)

                # Bulk update existing records
                if updates:
                    HistoricalPrice.objects.bulk_update(
                        updates, ["open", "high", "low", "close", "volume"]
                    )
                    stored_count += len(updates)

        except Exception as e:
            logger.error(f"Error storing price data for {symbol}: {e}", exc_info=True)
            # Fallback to individual updates if bulk operations fail
            logger.warning(f"Falling back to individual updates for {symbol}")
            for data in price_data:
                try:
                    HistoricalPrice.objects.update_or_create(
                        symbol=symbol,
                        date=data["date"],
                        defaults={
                            "open": data["open"],
                            "high": data["high"],
                            "low": data["low"],
                            "close": data["close"],
                            "volume": data["volume"],
                        },
                    )
                    stored_count += 1
                except Exception as e2:
                    logger.error(f"Error storing price data for {symbol} {data['date']}: {e2}")

        logger.info(f"Stored {stored_count} historical prices for {symbol} in database")
        return stored_count

    def preload_historical_data(self, symbols: list[str], days: int = 90) -> dict[str, int]:
        """
        Pre-load historical data for multiple symbols
        Returns dict with symbol -> count of records stored
        """
        results = {}

        for symbol in symbols:
            try:
                # Fetch from Stooq
                price_data = self.fetch_historical_prices(symbol, days)

                if price_data:
                    # Store in database
                    stored_count = self.store_in_database(symbol, price_data)
                    results[symbol] = stored_count

                    # Rate limiting - be nice to Stooq
                    time.sleep(1)
                else:
                    logger.warning(f"No historical data fetched for {symbol}")
                    results[symbol] = 0

            except Exception as e:
                logger.error(f"Error pre-loading data for {symbol}: {e}")
                results[symbol] = 0

        return results

    def get_latest_date_for_symbol(self, symbol: str) -> datetime | None:
        """
        Get the latest date we have data for in the database
        Used to determine if we need to fetch recent data
        """
        from trading.models import HistoricalPrice

        try:
            latest_record = HistoricalPrice.objects.filter(symbol=symbol).order_by("-date").first()

            if latest_record:
                return latest_record.date
            return None

        except Exception as e:
            logger.error(f"Error getting latest date for {symbol}: {e}")
            return None

    def get_missing_date_range(self, symbol: str, target_days: int):
        """
        Identify missing date range for a symbol.

        Args:
            symbol: Stock symbol
            target_days: Number of trading days we want

        Returns:
            tuple: (start_date, end_date, missing_count) or None if no data needed
        """
        from django.utils import timezone as dj_timezone

        from trading.models import HistoricalPrice

        try:
            # Get existing data date range
            records = HistoricalPrice.objects.filter(symbol=symbol).aggregate(
                earliest=models.Min("date"), latest=models.Max("date"), count=models.Count("id")
            )

            current_count = records["count"] or 0
            min_acceptable = int(target_days * 0.95)
            latest_date = records["latest"]
            today = dj_timezone.now().date()

            # PRIORITY 1: If count is insufficient, fetch full historical range
            # This takes precedence over freshness checks
            if current_count < min_acceptable:
                start_date, _end_date = self.calendar.get_trading_days_needed(symbol, target_days)
                logger.info(
                    f"{symbol}: Insufficient data ({current_count}/{min_acceptable}) - "
                    f"fetching full {target_days} trading days"
                )
                return (start_date.date(), today, target_days)

            # PRIORITY 2: Count is sufficient - check freshness
            if latest_date and latest_date < today:
                days_gap = (today - latest_date).days
                logger.info(
                    f"{symbol}: Data stale (latest={latest_date}, gap={days_gap} days) - "
                    f"fetching recent data"
                )
                return (latest_date, today, days_gap)

            # Data is fresh and sufficient
            logger.debug(
                f"{symbol}: Data is fresh and sufficient ({current_count}/{min_acceptable})"
            )
            return None

        except Exception as e:
            logger.error(f"Error identifying missing dates for {symbol}: {e}")
            return None

    def update_recent_data(self, symbol: str, target_days: int = 90) -> int:
        """
        Update recent data for a symbol (fetch only missing days).

        Args:
            symbol: Stock symbol
            target_days: Target number of trading days (default 90)

        Returns:
            Count of new records added
        """
        missing_range = self.get_missing_date_range(symbol, target_days)

        if not missing_range:
            logger.debug(f"{symbol} data is up to date")
            return 0

        start_date, end_date, expected_days = missing_range

        logger.info(
            f"{symbol}: Fetching missing data from {start_date} to {end_date} "
            f"(~{expected_days} days)"
        )

        # Fetch data for the missing range
        url = self._build_stooq_url(
            symbol,
            dj_timezone.datetime.combine(start_date, dj_timezone.datetime.min.time()),
            end_date,
        )

        try:
            logger.info(f"Fetching missing data for {symbol} from Stooq")
            response = requests.get(url, timeout=API_TIMEOUT)

            if response.status_code != 200:
                logger.error(f"Stooq request failed: HTTP {response.status_code}")
                return 0

            data = self._parse_csv_data(response.text, symbol)

            if data:
                # Store all fetched data - store_in_database handles duplicates
                # via bulk_create with ignore_conflicts and bulk_update for changes
                stored = self.store_in_database(symbol, data)
                logger.info(f"{symbol}: Stored {stored} records (new + updated)")
                return stored

            return 0

        except Exception as e:
            logger.error(f"Error updating recent data for {symbol}: {e}", exc_info=True)
            return 0

    def ensure_minimum_data(self, symbol: str, min_days: int = 20) -> bool:
        """
        Ensure we have at least min_days of TRADING data for a symbol.
        Uses incremental fetch to avoid refetching entire date ranges.
        Always checks data freshness even if count is sufficient.

        Args:
            symbol: Stock symbol
            min_days: Minimum trading days needed (tolerates 5% less due to holidays)

        Returns:
            True if sufficient data exists or was fetched successfully
        """
        from django.utils import timezone as dj_timezone

        from trading.models import HistoricalPrice

        try:
            # TOLERANCE: Accept 95% of requested days (weekends/holidays reduce actual count)
            min_acceptable = int(min_days * 0.95)

            # Check current data count AND freshness
            records = HistoricalPrice.objects.filter(symbol=symbol).aggregate(
                count=models.Count("id"), latest=models.Max("date")
            )
            current_count = records["count"] or 0
            latest_date = records["latest"]
            today = dj_timezone.now().date()

            # Check if data is fresh (updated today or yesterday for weekends)
            is_fresh = latest_date and latest_date >= today - dj_timezone.timedelta(days=1)

            if current_count >= min_acceptable and is_fresh:
                logger.debug(
                    f"{symbol} has sufficient fresh data: {current_count} days "
                    f"(need {min_acceptable}+, latest={latest_date})"
                )
                return True

            if current_count >= min_acceptable and not is_fresh:
                logger.info(
                    f"{symbol} has sufficient count ({current_count}/{min_acceptable}) "
                    f"but data is stale (latest={latest_date}) - updating"
                )
            else:
                logger.info(
                    f"{symbol} has {current_count}/{min_acceptable} days - "
                    f"fetching missing data (target: {min_days} trading days)"
                )

            # Use incremental update to fetch only missing dates
            new_records = self.update_recent_data(symbol, min_days)

            # Verify we now have enough data
            final_count = HistoricalPrice.objects.filter(symbol=symbol).count()
            success = final_count >= min_acceptable

            logger.info(
                f"{symbol} now has {final_count}/{min_acceptable} days after adding {new_records} records "
                f"({'PASS: sufficient' if success else 'FAIL: still insufficient'})"
            )
            return success

        except Exception as e:
            logger.error(f"Error ensuring minimum data for {symbol}: {e}")
            return False
