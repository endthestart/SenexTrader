"""
Centralized cache management for the entire Senex Trader application.

This module provides:
1. Cache TTL configuration (CacheTTL class)
2. Cache key management (CacheManager class)

All cache keys use colon (:) as separators for consistency.
"""

from datetime import date


class CacheTTL:
    """
    Centralized cache TTL configuration with justification.

    Design Principles:
    1. Real-time data (5-30s): Streaming data that changes rapidly
    2. Near-real-time (1-5 min): Frequently changing but not critical
    3. Hourly (1-4 hours): Slow-changing reference data
    4. Daily (24 hours): Static or historical data
    """

    # REAL-TIME (5-30 seconds): Streaming data
    QUOTE = 15  # Was 5s, increased since we have streaming
    GREEKS = 30  # Greeks update with quote changes

    # NEAR-REAL-TIME (1-5 minutes): Frequently changing
    ACCOUNT_STATE = 300  # Was 120s, align with refresh interval
    MARKET_METRICS = 300  # IV rank/percentile updates slowly
    OPTION_CHAIN = 300  # Chains update periodically

    # HOURLY (1-4 hours): Slow-changing reference data
    PROFILE = 3600  # Company profiles rarely change
    SUMMARY = 3600  # Daily summaries

    # DAILY (24 hours): Static or historical data
    HISTORICAL = 86400  # Historical prices are immutable
    NESTED_CHAIN = 3600  # Option chains can update as new expirations become available
    EXPIRATION_LIST = 86400  # Expirations don't change intraday

    @classmethod
    def get_ttl_by_category(cls, category: str) -> int:
        """Get TTL value by category name."""
        return getattr(cls, category.upper(), cls.ACCOUNT_STATE)


class CacheManager:
    """Centralized cache key management for all operations."""

    # Cache key prefixes for organization
    ACCOUNT_STATE_PREFIX = "acct_state"
    QUOTE_PREFIX = "quote"
    OPTION_CHAIN_PREFIX = "option_chain"
    MARKET_METRICS_PREFIX = "market_metrics"
    STREAM_PREFIX = "stream"
    DXFEED_PREFIX = "dxfeed"
    SESSION_PREFIX = "session"
    DATA_FETCH_PREFIX = "data_fetch"

    # Standard TTL values (seconds)
    SHORT_TTL = 300  # 5 minutes - real-time data
    MEDIUM_TTL = 900  # 15 minutes - session/auth data
    LONG_TTL = 3600  # 1 hour - option chains, market data
    DAILY_TTL = 86400  # 24 hours - historical/static data

    # === Account & Session Keys ===
    @staticmethod
    def account_state(user_id: int, account_number: str) -> str:
        """Cache key for account state data."""
        return f"{CacheManager.ACCOUNT_STATE_PREFIX}:{user_id}:{account_number}"

    @staticmethod
    def tastytrade_session(user_id: int) -> str:
        """Cache key for TastyTrade OAuth session."""
        return f"{CacheManager.SESSION_PREFIX}:tastytrade:{user_id}"

    # === Symbol Sanitization ===
    @staticmethod
    def _sanitize_symbol(symbol: str) -> str:
        """
        Sanitize symbol for cache key compatibility.

        Replaces spaces with underscores to prevent memcached key errors.
        OCC option symbols like 'QQQ   251114C00606000' become 'QQQ___251114C00606000'.

        Args:
            symbol: Raw symbol (may contain spaces)

        Returns:
            Sanitized symbol safe for cache keys
        """
        return symbol.replace(" ", "_")

    # === Quote & Market Data Keys ===
    @staticmethod
    def quote(symbol: str) -> str:
        """Cache key for basic quote data."""
        sanitized = CacheManager._sanitize_symbol(symbol)
        return f"{CacheManager.QUOTE_PREFIX}:{sanitized}"

    @staticmethod
    def market_metrics(symbol: str) -> str:
        """Cache key for market metrics and analysis."""
        return f"{CacheManager.MARKET_METRICS_PREFIX}:{symbol}"

    # === Option Chain Keys (Standardized) ===
    @staticmethod
    def option_chain_with_expiration(symbol: str, expiration: date) -> str:
        """
        Cache key for option chain with specific expiration.

        Includes current date suffix to ensure midnight rollover invalidates cached chains,
        preventing DTE calculation errors (Cache Bug 5).

        Args:
            symbol: Underlying symbol
            expiration: Option expiration date

        Returns:
            Cache key string
        """
        today = date.today()
        return f"{CacheManager.OPTION_CHAIN_PREFIX}:{symbol}:{expiration}:{today}"

    @staticmethod
    def option_chain_nested(symbol: str) -> str:
        """
        Cache key for nested option chain (all expirations).

        Args:
            symbol: Underlying symbol

        Returns:
            Cache key string
        """
        return f"{CacheManager.OPTION_CHAIN_PREFIX}:nested:{symbol}"

    @staticmethod
    def option_chain_expirations(symbol: str) -> str:
        """
        Cache key for available expiration dates.

        Args:
            symbol: Underlying symbol

        Returns:
            Cache key string
        """
        return f"{CacheManager.OPTION_CHAIN_PREFIX}:expirations:{symbol}"

    @staticmethod
    def option_chain_with_dte(symbol: str, target_dte: int) -> str:
        """
        Cache key for option chain with target DTE.

        Includes current date suffix to ensure midnight rollover invalidates cached chains.

        Args:
            symbol: Underlying symbol
            target_dte: Target days to expiration

        Returns:
            Cache key string
        """
        today = date.today()
        return f"{CacheManager.OPTION_CHAIN_PREFIX}:{symbol}:dte_{target_dte}:{today}"

    # === DXFeed Streaming Keys ===
    @staticmethod
    def dxfeed_underlying(symbol: str) -> str:
        """Cache key for DXFeed underlying quote."""
        sanitized = CacheManager._sanitize_symbol(symbol)
        return f"{CacheManager.DXFEED_PREFIX}:underlying:{sanitized}"

    @staticmethod
    def dxfeed_greeks(occ_symbol: str) -> str:
        """Cache key for DXFeed option Greeks."""
        sanitized = CacheManager._sanitize_symbol(occ_symbol)
        return f"{CacheManager.DXFEED_PREFIX}:greeks:{sanitized}"

    @staticmethod
    def dxfeed_quote(occ_symbol: str) -> str:
        """Cache key for DXFeed option quote."""
        sanitized = CacheManager._sanitize_symbol(occ_symbol)
        return f"{CacheManager.DXFEED_PREFIX}:quote:{sanitized}"

    # === Data Fetching Lock Keys ===
    @staticmethod
    def data_fetch_lock(resource_id: str) -> str:
        """Cache key for data fetch lock to prevent thundering herd."""
        return f"{CacheManager.DATA_FETCH_PREFIX}:lock:{resource_id}"

    @staticmethod
    def stooq_last_fetch(symbol: str) -> str:
        """Cache key for last Stooq fetch timestamp."""
        return f"{CacheManager.DATA_FETCH_PREFIX}:stooq:{symbol}"

    # === Position & Stock Keys ===
    @staticmethod
    def stock_positions(user_id: int, account_number: str) -> str:
        """Cache key for stock positions."""
        return f"stock_positions:{user_id}:{account_number}"

    @staticmethod
    def position_status_hash(user_id: int, account_number: str) -> str:
        """Cache key for position status hash."""
        return f"position_status:{user_id}:{account_number}"

    # === Stream Manager Keys ===
    @staticmethod
    def stream_manager_health(user_id: int) -> str:
        """Cache key for stream manager health status."""
        return f"{CacheManager.STREAM_PREFIX}:health:{user_id}"

    @staticmethod
    def stream_manager_subscriptions(user_id: int) -> str:
        """Cache key for stream manager active subscriptions."""
        return f"{CacheManager.STREAM_PREFIX}:subscriptions:{user_id}"

    # === Historical Data Keys ===
    @staticmethod
    def historical_prices(symbol: str, days: int) -> str:
        """Cache key for historical price data."""
        return f"historical:{symbol}:{days}days"

    # === Utility Methods ===
    @staticmethod
    def clear_pattern(pattern: str) -> None:
        """
        Clear all cache keys matching a pattern.

        Note: Actual implementation depends on cache backend.
        This is a placeholder for documentation purposes.

        Args:
            pattern: Cache key pattern to match
        """
        pass  # Implementation would use cache backend's pattern matching
