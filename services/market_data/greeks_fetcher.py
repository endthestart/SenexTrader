"""
Greeks fetcher for strike selection.

Provides Greeks data for delta-based strike selection with:
- Cache integration with configurable TTL (default 90s)
- Streaming + historical fallback
- Market stress bypass (bypass cache when stress > threshold)

This is distinct from GreeksService which handles position/portfolio Greeks.
GreeksFetcher is optimized for fetching Greeks for multiple strikes during
strategy generation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import TYPE_CHECKING

from django.core.cache import cache

from services.core.logging import get_logger
from services.market_data.greeks import GreeksService

if TYPE_CHECKING:
    from services.streaming.dataclasses import OptionGreeks

logger = get_logger(__name__)


class GreeksFetcher:
    """
    Fetch option Greeks for strike selection with cache + stress bypass.

    Designed for batch fetching Greeks during strategy generation,
    with intelligent caching and market stress awareness.

    Attributes:
        user: Django user for API access
        ttl_seconds: Cache TTL in seconds (default 90)
        stress_threshold: Market stress level to bypass cache (default 70.0)

    Example:
        >>> fetcher = GreeksFetcher(user, ttl_seconds=90)
        >>> greeks = await fetcher.fetch_greeks(
        ...     symbol="SPY",
        ...     expiration=date(2025, 12, 19),
        ...     occ_symbols=["SPY   251219P00580000", "SPY   251219P00575000"],
        ...     market_stress_level=50.0,
        ... )
        >>> greeks["SPY   251219P00580000"]["delta"]
        -0.25
    """

    CACHE_PREFIX = "greeks_fetcher"

    def __init__(
        self,
        user,
        ttl_seconds: int = 90,
        stress_bypass_threshold: float = 70.0,
    ) -> None:
        self.user = user
        self.ttl_seconds = ttl_seconds
        self.stress_threshold = stress_bypass_threshold
        self.greeks_service = GreeksService()

    async def fetch_greeks(
        self,
        symbol: str,
        expiration: date | None,
        occ_symbols: Iterable[str],
        market_stress_level: float | None = None,
    ) -> dict[str, dict]:
        """
        Fetch Greeks for the provided OCC symbols.

        Priority:
        1. Cache (unless stress bypass triggered)
        2. Streaming data
        3. Historical database

        Args:
            symbol: Underlying symbol (for logging/subscription)
            expiration: Option expiration for subscription tracking
            occ_symbols: Iterable of OCC symbols to fetch
            market_stress_level: Optional stress indicator (0-100)

        Returns:
            Mapping of OCC symbol -> Greeks dict (may be partial if data unavailable)
        """
        symbols = self._deduplicate_symbols(occ_symbols)
        if not symbols:
            return {}

        bypass_cache = (market_stress_level or 0.0) >= self.stress_threshold
        normalized_expiration = self._normalize_expiration(expiration)

        # Ensure streaming subscription (best effort)
        await self._ensure_subscription(symbol, normalized_expiration, symbols)

        results: dict[str, dict] = {}
        for occ_symbol in symbols:
            cache_key = f"{self.CACHE_PREFIX}:{occ_symbol}"

            # Check cache first (unless bypassing)
            if not bypass_cache:
                cached = cache.get(cache_key)
                if cached:
                    results[occ_symbol] = cached
                    continue

            # Try streaming data
            snapshot = self._read_streaming_greeks(occ_symbol)

            # Fallback to historical if streaming unavailable
            if not snapshot:
                snapshot = self._read_historical_greeks(occ_symbol)
                if snapshot:
                    logger.debug(
                        f"Using database fallback for {occ_symbol} "
                        f"(age: {snapshot.get('age_seconds', 'unknown')}s)"
                    )

            # Cache and add to results
            if snapshot:
                cache.set(cache_key, snapshot, self.ttl_seconds)
                results[occ_symbol] = snapshot

        return results

    def _read_streaming_greeks(self, occ_symbol: str) -> dict | None:
        """Read Greeks from streaming cache."""
        try:
            from services.streaming.options_service import StreamingOptionsDataService

            options_service = StreamingOptionsDataService(self.user)
            greeks = options_service.read_greeks(occ_symbol)

            if not greeks:
                return None

            return self._serialize_snapshot(greeks)
        except Exception as exc:
            logger.warning(f"Streaming Greeks lookup failed for {occ_symbol}: {exc}")
            return None

    def _read_historical_greeks(self, occ_symbol: str) -> dict | None:
        """Fetch Greeks from historical database."""
        try:
            return self.greeks_service._get_greeks_from_database(occ_symbol)
        except Exception as exc:
            logger.warning(f"Historical Greeks lookup failed for {occ_symbol}: {exc}")
            return None

    async def _ensure_subscription(
        self,
        symbol: str,
        expiration: date | None,
        occ_symbols: list[str],
    ) -> None:
        """Ensure streaming subscription for symbols (best effort)."""
        try:
            from services.streaming.options_service import StreamingOptionsDataService

            options_service = StreamingOptionsDataService(self.user)
            await options_service.a_ensure_leg_stream(symbol, expiration, occ_symbols)
        except Exception as exc:
            logger.warning(f"Failed to ensure leg stream for {symbol}: {exc}")

    @staticmethod
    def _deduplicate_symbols(symbols: Iterable[str]) -> list[str]:
        """Remove duplicate and empty symbols."""
        deduped: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            if not symbol or symbol in seen:
                continue
            deduped.append(symbol)
            seen.add(symbol)
        return deduped

    @staticmethod
    def _normalize_expiration(expiration: date | None) -> date | None:
        """Normalize expiration to date object."""
        if expiration is None:
            return None
        if isinstance(expiration, date) and not isinstance(expiration, datetime):
            return expiration
        if isinstance(expiration, datetime):
            return expiration.date()
        try:
            return datetime.fromisoformat(str(expiration)).date()
        except ValueError:
            return None

    @staticmethod
    def _serialize_snapshot(snapshot: OptionGreeks) -> dict:
        """Convert OptionGreeks to serializable dict."""

        def _to_float(value):
            if value is None:
                return None
            return float(value)

        return {
            "delta": _to_float(snapshot.delta),
            "gamma": _to_float(snapshot.gamma),
            "theta": _to_float(snapshot.theta),
            "vega": _to_float(snapshot.vega),
            "rho": _to_float(snapshot.rho),
            "implied_volatility": _to_float(snapshot.implied_volatility),
            "source": snapshot.source,
            "age_seconds": snapshot.age_seconds,
        }
