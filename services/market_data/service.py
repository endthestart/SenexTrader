"""
Market Data Service for Senex Trader

Centralized service for all market data access implementing Cache → API
fallback pattern.
CRITICAL: Always returns real data or None - NEVER mock data.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from asgiref.sync import sync_to_async

from services.core.cache import CacheManager, CacheTTL
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async

logger = get_logger(__name__)


class MarketDataService:
    """
    Centralized service for all market data access.
    Implements Cache → API fallback pattern per REAL_DATA_IMPLEMENTATION_PLAN.md

    Core Principle: Real data or fail - NEVER mock data
    """

    def __init__(self, user=None):
        """Initialize with optional user for account-specific data."""
        self.user = user

    def get_quote_sync(self, symbol: str) -> dict | None:
        """Synchronous wrapper for async get_quote."""
        return run_async(self.get_quote(symbol))

    def get_market_metrics_sync(self, symbol: str) -> dict | None:
        """Synchronous wrapper for async get_market_metrics."""
        return run_async(self.get_market_metrics(symbol))

    def get_historical_prices_sync(self, symbol: str, days: int = 20) -> list[dict] | None:
        """Synchronous wrapper for async get_historical_prices."""
        return run_async(self.get_historical_prices(symbol, days))

    async def get_quote(self, symbol: str) -> dict | None:
        """Get current quote for symbol from cache or API."""
        cache_key = CacheManager.quote(symbol)

        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Quote cache hit for {symbol}")
            return cached_data

        logger.info(f"No cached data, fetching quote from API for {symbol}")
        api_data = await self._fetch_quote_from_api(symbol)

        if api_data:
            cache.set(cache_key, api_data, CacheTTL.QUOTE)
            api_data["source"] = "tastytrade_api"
            return api_data

        logger.warning(f"Could not fetch quote for {symbol}")
        return None

    async def get_historical_prices(self, symbol: str, days: int = 20) -> list[dict] | None:
        """
        Get historical daily closes.
        1. Check database for recent data
        2. Fetch missing days from API
        3. Store in database
        4. Return data or None

        Returns list of dicts with: date, open, high, low, close, volume
        """
        # TOLERANCE: Accept 95% of requested days (weekends/holidays reduce count)
        min_acceptable = int(days * 0.95)

        db_data = await self._get_historical_from_database(symbol, days)
        db_count = len(db_data) if db_data else 0

        if db_data and db_count >= min_acceptable:
            logger.debug(f"PASS: {symbol}: {db_count} days in DB (need {min_acceptable}+)")
            return db_data

        logger.info(
            f"{symbol}: Insufficient DB data ({db_count}/{min_acceptable} days) - "
            f"fetching {days} days from Stooq"
        )
        api_data = await self._fetch_historical_from_api(symbol, days)

        if api_data:
            logger.info(f"PASS: {symbol}: Fetched {len(api_data)} days from Stooq")
            await self._store_historical_in_database(symbol, api_data)
            return api_data

        logger.warning(
            f"FAIL: {symbol}: Failed to fetch historical prices from Stooq - "
            f"returning insufficient DB data ({db_count} days) as fallback"
        )
        # Return partial data if available, better than None
        return db_data if db_data else None

    async def get_market_metrics(self, symbol: str) -> dict | None:
        """
        Get IV, volume, open interest.
        1. Check cache (1 minute TTL)
        2. Fetch from API
        3. Update cache
        4. Return data or None

        Returns dict with: iv30, iv_rank, volume, open_interest, source
        """
        cache_key = CacheManager.market_metrics(symbol)

        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Market metrics cache hit for {symbol}")
            cached_data["source"] = "cache"
            return cached_data

        logger.info(f"Fetching market metrics from API for {symbol}")
        api_data = await self._fetch_market_metrics_from_api(symbol)

        if api_data:
            cache.set(cache_key, api_data, CacheTTL.MARKET_METRICS)
            api_data["source"] = "tastytrade_api"
            await self._persist_market_metrics(symbol, api_data)
            return api_data

        logger.warning(f"Could not fetch market metrics for {symbol}")
        return None

    async def _fetch_quote_from_api(self, symbol: str) -> dict | None:
        """Fetch real-time quote from TastyTrade API using market data endpoint."""
        try:
            session = await self._get_session()
            if not session:
                return None

            # Use correct market data API (not instrument metadata API)
            from tastytrade.market_data import a_get_market_data
            from tastytrade.order import InstrumentType

            market_data = await a_get_market_data(session, symbol, InstrumentType.EQUITY)

            if not market_data:
                logger.warning(f"No market data returned for {symbol}")
                return None

            # Extract real-time pricing data
            quote_data = {
                "symbol": symbol,
                "bid": float(market_data.bid) if market_data.bid else None,
                "ask": float(market_data.ask) if market_data.ask else None,
                "last": float(market_data.last) if market_data.last else None,
                "bid_size": float(market_data.bid_size) if market_data.bid_size else None,
                "ask_size": float(market_data.ask_size) if market_data.ask_size else None,
                "open": float(market_data.open) if market_data.open else None,
                "close": float(market_data.prev_close) if market_data.prev_close else None,
                "volume": float(market_data.volume) if market_data.volume else None,
                "fetched_at": timezone.now().isoformat(),
            }

            quote_data["source"] = "tastytrade_api"
            quote_data["timestamp"] = timezone.now().isoformat()

            return quote_data

        except Exception as e:
            logger.error(f"Error fetching quote from API for {symbol}: {e}", exc_info=True)
            return None

    async def _fetch_historical_from_api(self, symbol: str, days: int) -> list[dict] | None:
        """Fetch historical price data using Stooq provider."""
        try:
            from services.market_data.historical import HistoricalDataProvider

            logger.info(f"Fetching historical data from Stooq for {symbol}")

            # Use sync provider in async context
            provider = HistoricalDataProvider()

            # Call sync method directly (no async wrapper needed)
            import asyncio

            price_data = await asyncio.get_event_loop().run_in_executor(
                None, provider.fetch_historical_prices, symbol, days
            )

            if price_data:
                # Store in database for future use
                await asyncio.get_event_loop().run_in_executor(
                    None, provider.store_in_database, symbol, price_data
                )

                # Convert to expected format
                return [
                    {
                        "date": p["date"].isoformat(),
                        "open": float(p["open"]),
                        "high": float(p["high"]),
                        "low": float(p["low"]),
                        "close": float(p["close"]),
                        "volume": p["volume"],
                    }
                    for p in price_data
                ]

            logger.warning(f"No historical data available from Stooq for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Error fetching historical data from Stooq: {e}", exc_info=True)
            return None

    async def _fetch_market_metrics_from_api(self, symbol: str) -> dict | None:
        """Fetch market metrics (IV Rank, etc.) from TastyTrade API."""
        try:
            session = await self._get_session()
            if not session:
                return None

            from tastytrade.metrics import a_get_market_metrics

            # The SDK expects a list of symbols
            metrics_list = await a_get_market_metrics(session, [symbol])
            if not metrics_list:
                logger.warning(f"No market metrics returned for {symbol}")
                return None

            metrics = metrics_list[0]

            # Extract IV Rank and multiply by 100 to get a 0-100 scale
            # Fix: Use explicit None check to handle IV=0.0 correctly (not truthy check)
            iv_rank_raw = getattr(metrics, "tos_implied_volatility_index_rank", None)
            iv_rank = float(iv_rank_raw) * 100 if iv_rank_raw is not None else None

            # Extract other useful metrics
            iv_percentile_raw = getattr(metrics, "implied_volatility_percentile", None)
            iv_percentile = (
                float(iv_percentile_raw) * 100 if iv_percentile_raw is not None else None
            )

            # FIX: SDK returns percentage format (22.15 for 22.15%), NOT decimal (0.2215)
            # Store as-is, no conversion needed
            iv_30_day_raw = getattr(metrics, "implied_volatility_30_day", None)
            iv_30_day = float(iv_30_day_raw) if iv_30_day_raw is not None else None

            # FIX: SDK returns percentage format (22.15 for 22.15%), NOT decimal (0.2215)
            # Store as-is, no conversion needed
            # Real data only - no clamping (market crashes can produce HV > 100)
            hv_30_day_raw = getattr(metrics, "historical_volatility_30_day", None)
            hv_30_day = float(hv_30_day_raw) if hv_30_day_raw is not None else None

            earnings_data = None
            if getattr(metrics, "earnings", None):
                earnings = metrics.earnings
                earnings_data = {
                    "expected_report_date": (
                        earnings.expected_report_date.isoformat()
                        if earnings.expected_report_date
                        else None
                    )
                }

            dividend_next_date = getattr(metrics, "dividend_next_date", None)
            dividend_ex_date = getattr(metrics, "dividend_ex_date", None)

            beta = getattr(metrics, "beta", None)

            return {
                "symbol": symbol,
                "iv_rank": iv_rank,
                "iv_percentile": iv_percentile,
                "iv_30_day": iv_30_day,  # Already float or None
                "hv_30_day": hv_30_day,  # Already float or None
                "earnings": earnings_data,
                "dividend_next_date": (
                    dividend_next_date.isoformat() if dividend_next_date else None
                ),
                "dividend_ex_date": dividend_ex_date.isoformat() if dividend_ex_date else None,
                "beta": float(beta) if beta else None,
                "fetched_at": timezone.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error fetching market metrics from API: {e}", exc_info=True)
            return None

    async def _get_session(self):
        """Get TastyTrade OAuth session for API calls."""
        # Check if user is None (direct check before lazy evaluation)
        if self.user is None:
            logger.error("No user specified for MarketDataService")
            return None

        # Safely get user_id in async context
        try:
            user_id = await sync_to_async(lambda: self.user.id)()
        except (AttributeError, TypeError):
            logger.error("User object invalid or missing id")
            return None

        from services.core.data_access import get_oauth_session

        session = await get_oauth_session(self.user)
        if not session:
            logger.error(f"Failed to get OAuth session for user {user_id}")
        return session

    def _find_closest_expiration(self, chains: list, target: date) -> date | None:
        """Find the expiration date closest to target."""
        if not chains:
            return None

        expirations = [chain.expiration_date.date() for chain in chains]
        expirations = [exp for exp in expirations if exp >= target]

        if not expirations:
            # If no future expirations, get the last available
            expirations = [chain.expiration_date.date() for chain in chains]

        if not expirations:
            return None

        # Find closest to target
        return min(expirations, key=lambda x: abs((x - target).days))

    async def _get_historical_from_database(self, symbol: str, days: int) -> list[dict] | None:
        """Get historical prices from database.
        Uses 5% tolerance to account for weekends/holidays."""
        try:
            # Check if HistoricalPrice model exists
            from trading.models import HistoricalPrice

            end_date = timezone.now().date()
            # Smart buffer: ~5 trading days per 7 calendar days + holidays
            buffer_days = max(14, int(days * 0.4) + 5)
            start_date = end_date - timedelta(days=days + buffer_days)

            # Use sync_to_async wrapper for database query
            prices = await sync_to_async(
                lambda: list(
                    HistoricalPrice.objects.filter(
                        symbol=symbol,
                        date__gte=start_date,
                        date__lte=end_date,
                    )
                    .order_by("date")  # Ascending order for proper analysis
                    .values("date", "open", "high", "low", "close", "volume")
                )
            )()

            # TOLERANCE: Accept 95% of requested days (weekends/holidays reduce count)
            min_acceptable = int(days * 0.95)

            if len(prices) >= min_acceptable:
                # Convert to expected format - return all available days
                return [
                    {
                        "date": p["date"].isoformat(),
                        "open": float(p["open"]),
                        "high": float(p["high"]),
                        "low": float(p["low"]),
                        "close": float(p["close"]),
                        "volume": p["volume"],
                        "source": "database",
                    }
                    for p in prices[-days:]  # Get most recent days (up to requested amount)
                ]

        except ImportError:
            # HistoricalPrice model doesn't exist yet
            logger.debug("HistoricalPrice model not available yet")
        except Exception as e:
            logger.error(f"Error fetching from database: {e}", exc_info=True)

        return None

    async def _store_historical_in_database(self, symbol: str, prices: list[dict]) -> None:
        """Store historical prices in database using provider."""
        try:
            from services.market_data.historical import HistoricalDataProvider

            # Convert format for provider
            provider_data = []
            for p in prices:
                provider_data.append(
                    {
                        "symbol": symbol,
                        "date": datetime.fromisoformat(p["date"]).date(),
                        "open": Decimal(str(p["open"])),
                        "high": Decimal(str(p["high"])),
                        "low": Decimal(str(p["low"])),
                        "close": Decimal(str(p["close"])),
                        "volume": p.get("volume"),
                    }
                )

            # Use provider's store method in executor
            provider = HistoricalDataProvider()
            import asyncio

            await asyncio.get_event_loop().run_in_executor(
                None, provider.store_in_database, symbol, provider_data
            )

        except Exception as e:
            logger.error(f"Error storing historical prices: {e}", exc_info=True)

    async def _persist_market_metrics(self, symbol: str, metrics_data: dict):
        """Persist market metrics to MarketMetricsHistory model (fire-and-forget)."""
        try:
            from decimal import Decimal

            from trading.models import MarketMetricsHistory

            today = timezone.now().date()

            # Extract metrics from data
            iv_rank = metrics_data.get("iv_rank")
            iv_percentile = metrics_data.get("iv_percentile")
            iv_30_day = metrics_data.get("iv_30_day")
            hv_30_day = metrics_data.get("hv_30_day")  # Optional field

            # Skip if essential metrics are missing
            if iv_rank is None or iv_percentile is None or iv_30_day is None:
                logger.debug(
                    f"Skipping market metrics persistence for {symbol} - missing essential fields"
                )
                return

            # Persist using aupdate_or_create (upsert pattern)
            await MarketMetricsHistory.objects.aupdate_or_create(
                symbol=symbol,
                date=today,
                defaults={
                    "iv_rank": Decimal(str(iv_rank)),
                    "iv_percentile": Decimal(str(iv_percentile)),
                    "iv_30_day": Decimal(str(iv_30_day)),
                    "hv_30_day": Decimal(str(hv_30_day)) if hv_30_day is not None else None,
                },
            )
            logger.debug(f"Persisted market metrics for {symbol} on {today}")

        except Exception as e:
            logger.error(f"Error persisting market metrics for {symbol}: {e}", exc_info=True)
