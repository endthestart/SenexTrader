"""
Greeks calculation and aggregation service.

Provides position-level and portfolio-level Greeks display for all strategies
(Senex Trident, Bull Put Spread, Bear Call Spread, etc).

ARCHITECTURE:
- Generic leg extraction from Trade.order_legs JSONField
- Works with 2-leg, 3-leg, 4-leg positions
- Uses cached DXFeed Greeks data from streaming service
- Follows SIMPLICITY FIRST principle - direct implementation
"""

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.core.cache import cache

from services.core.cache import CacheManager
from services.core.logging import get_logger
from trading.models import Position

logger = get_logger(__name__)


class GreeksService:
    """
    Calculate and aggregate Greeks for positions and portfolio.
    Uses cached DXFeed Greeks data from streaming service.
    """

    def get_position_greeks(self, position: Position) -> dict[str, Any] | None:
        """
        Get Greeks for a single position by aggregating all legs.

        Generic implementation that works for ANY multi-leg strategy:
        - 2-leg spreads (Bull Put, Bear Call)
        - 3-leg positions
        - 6-leg Senex Trident (2 put spreads + 1 call spread, NOT an iron condor)

        Data source:
        - Position.metadata.legs (broker-provided, always current)

        Note: metadata.legs quantities represent total position, not per-spread.
        We apply the standard options contract multiplier (100) to convert
        per-share Greeks to per-contract Greeks.

        Args:
            position: Position model instance

        Returns:
            Dict with delta, gamma, theta, vega, rho or None if no data
        """
        try:
            # Always use broker metadata as source of truth
            if not position.metadata or not position.metadata.get("legs"):
                logger.warning(
                    f"No legs data found in Position.metadata for position {position.id}"
                )
                return None

            legs = position.metadata["legs"]

            # Aggregate Greeks from all legs
            portfolio_greeks = {
                "delta": Decimal("0"),
                "gamma": Decimal("0"),
                "theta": Decimal("0"),
                "vega": Decimal("0"),
                "rho": Decimal("0"),
            }

            for leg in legs:
                # Each leg has: symbol (OCC), quantity, quantity_direction
                occ_symbol = leg.get("symbol")
                direction = leg.get("quantity_direction", "").lower()
                qty = leg.get("quantity", 0)

                if not occ_symbol:
                    logger.warning(f"Leg missing OCC symbol: {leg}")
                    continue

                # Determine action from quantity_direction or quantity sign
                action = "SELL" if direction == "short" or qty < 0 else "BUY"
                leg_quantity = abs(int(qty))

                # Fetch Greeks from cache
                leg_greeks = self._get_leg_greeks(occ_symbol)

                if leg_greeks:
                    # Direction multiplier: BUY = long (+1), SELL = short (-1)
                    multiplier = 1 if action == "BUY" else -1

                    # Aggregate Greeks (metadata.legs already contains total quantities)
                    for greek in portfolio_greeks:
                        value = leg_greeks.get(greek, 0)
                        portfolio_greeks[greek] += Decimal(str(value)) * multiplier * leg_quantity

            # Apply standard options contract multiplier
            OPTIONS_CONTRACT_MULTIPLIER = 100

            return {
                "delta": float(portfolio_greeks["delta"]) * OPTIONS_CONTRACT_MULTIPLIER,
                "gamma": float(portfolio_greeks["gamma"]) * OPTIONS_CONTRACT_MULTIPLIER,
                "theta": float(portfolio_greeks["theta"]) * OPTIONS_CONTRACT_MULTIPLIER,
                "vega": float(portfolio_greeks["vega"]) * OPTIONS_CONTRACT_MULTIPLIER,
                "rho": float(portfolio_greeks["rho"]) * OPTIONS_CONTRACT_MULTIPLIER,
                "source": "dxfeed_streaming",
            }

        except Exception as e:
            logger.error(f"Error calculating position Greeks: {e}", exc_info=True)
            return None

    def get_portfolio_greeks(self, user: AbstractBaseUser) -> dict[str, Any]:
        """
        Aggregate Greeks across all open positions for user.

        Args:
            user: User model instance

        Returns:
            Dict with aggregated portfolio Greeks
        """
        from trading.models import Position

        try:
            open_positions = Position.objects.filter(
                user=user,
                is_app_managed=True,
                lifecycle_state__in=["open_full", "open_partial", "closing"],
            )

            portfolio = {
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0,
                "position_count": 0,
            }

            for position in open_positions:
                pos_greeks = self.get_position_greeks(position)
                if pos_greeks:
                    for greek in ["delta", "gamma", "theta", "vega", "rho"]:
                        portfolio[greek] += pos_greeks[greek]
                    portfolio["position_count"] += 1

            return portfolio

        except Exception as e:
            logger.error(f"Error calculating portfolio Greeks: {e}", exc_info=True)
            return {
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0,
                "position_count": 0,
                "error": str(e),
            }

    def _get_leg_greeks(self, occ_symbol: str) -> dict[str, Any] | None:
        """
        Get Greeks for a single option leg from cache, with database fallback.

        Data priority:
        1. Redis cache (OCC format)
        2. Redis cache (streamer format)
        3. HistoricalGreeks database (< 60 min old)

        Tries OCC format first, then falls back to streamer format.
        This matches the pattern used in options_cache.py for quote lookups.

        Args:
            occ_symbol: OCC-formatted option symbol (e.g., 'SPY   251107P00591000')

        Returns:
            Dict with delta, gamma, theta, vega, rho or None
        """
        # Cache uses streamer format (matches DXFeed event_symbol)
        greeks: dict[str, Any] | None = None

        # Check for spaces to identify option symbols vs underlying symbols
        if " " in occ_symbol:
            try:
                from tastytrade.instruments import Option

                streamer_symbol = Option.occ_to_streamer_symbol(occ_symbol)
                streamer_key = CacheManager.dxfeed_greeks(streamer_symbol)
                greeks = cache.get(streamer_key)
            except Exception as e:
                logger.warning(f"Failed to convert OCC symbol {occ_symbol} to streamer format: {e}")
        else:
            # For underlying symbols, use symbol directly
            key = CacheManager.dxfeed_greeks(occ_symbol)
            greeks = cache.get(key)

        # Fall back to HistoricalGreeks database if cache miss
        if not greeks:
            greeks = self._get_greeks_from_database(occ_symbol)
            if greeks:
                logger.info(
                    f"Using database fallback for {occ_symbol} (age: {greeks.get('age_seconds')}s)"
                )

        return greeks

    def _get_greeks_from_database(self, occ_symbol: str) -> dict[str, Any] | None:
        """
        Fetch latest Greeks from HistoricalGreeks table with staleness checking.

        Staleness tolerance:
        - Prefer: < 10 minutes (fresh)
        - Accept: < 60 minutes (moderate staleness, per user preference)
        - Reject: >= 60 minutes (too old)

        Args:
            occ_symbol: OCC-formatted option symbol

        Returns:
            Dict with Greeks data and staleness metadata, or None if too old/not found
        """
        try:
            from django.utils import timezone

            from trading.models import HistoricalGreeks

            latest = (
                HistoricalGreeks.objects.filter(option_symbol=occ_symbol)
                .order_by("-timestamp")
                .first()
            )

            if not latest:
                logger.debug(f"No historical Greeks found for {occ_symbol}")
                return None

            age_seconds = (timezone.now() - latest.timestamp).total_seconds()

            # Reject data > 60 minutes old (user preference: moderate staleness tolerance)
            if age_seconds > 3600:
                logger.debug(f"Database Greeks too stale for {occ_symbol}: {int(age_seconds)}s old")
                return None

            # Mark as stale if > 10 minutes old
            is_stale = age_seconds > 600

            return {
                "delta": float(latest.delta),
                "gamma": float(latest.gamma),
                "theta": float(latest.theta),
                "vega": float(latest.vega),
                "rho": float(latest.rho) if latest.rho else 0,
                "is_stale": is_stale,
                "age_seconds": int(age_seconds),
                "source": "database_fallback",
            }

        except Exception as e:
            logger.error(
                f"Error fetching Greeks from database for {occ_symbol}: {e}", exc_info=True
            )
            return None

    def get_position_greeks_cached(self, position: Position) -> dict[str, Any] | None:
        """
        Get Greeks for a position with 5-second cache.

        Reduces load when multiple requests hit API quickly
        (e.g., page refreshes, multiple position cards).

        Args:
            position: Position model instance

        Returns:
            Dict with delta, gamma, theta, vega, rho or None if no data
        """
        cache_key: str = f"position_greeks_{position.id}"
        cached: dict[str, Any] | None = cache.get(cache_key)

        if cached:
            logger.debug(f"Cache hit for position {position.id} Greeks")
            return cached

        # Calculate fresh Greeks
        greeks: dict[str, Any] | None = self.get_position_greeks(position)

        # Cache result if available (5 second TTL)
        if greeks:
            cache.set(cache_key, greeks, 5)
            logger.debug(f"Cached Greeks for position {position.id}")

        return greeks

    def get_portfolio_greeks_cached(self, user: AbstractBaseUser) -> dict[str, Any]:
        """
        Get portfolio Greeks with 5-second cache.

        Reduces load when multiple requests hit API quickly
        (e.g., dashboard + positions page both loading).

        Args:
            user: User model instance

        Returns:
            Dict with aggregated portfolio Greeks
        """
        cache_key: str = f"portfolio_greeks_{user.id}"
        cached: dict[str, Any] | None = cache.get(cache_key)

        if cached:
            logger.debug(f"Cache hit for user {user.id} portfolio Greeks")
            return cached

        # Calculate fresh Greeks
        greeks: dict[str, Any] = self.get_portfolio_greeks(user)

        # Cache result (5 second TTL)
        cache.set(cache_key, greeks, 5)
        logger.debug(f"Cached portfolio Greeks for user {user.id}")

        return greeks
