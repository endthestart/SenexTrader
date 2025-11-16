"""
Stock Position Detector Service

Detects existing stock positions from synced Position model.
Required for strategies like Covered Call that need stock holdings.

Epic 22 Task 010: Infrastructure for stock-based strategies.
Epic 28 Task 003: Added caching layer to prevent rate limit issues.
Epic 28 Task 009: Refactored to use Position model instead of direct API calls.
"""

from decimal import Decimal

from django.core.cache import cache

from services.core.cache import CacheManager
from services.core.logging import get_logger

logger = get_logger(__name__)


class StockPositionDetector:
    """
    Detect and query stock positions from brokerage account.

    Used by strategies that require stock ownership:
    - Covered Call (needs 100+ shares)
    - Wheel Strategy (tracks assignments)

    Epic 28: Implements 60s caching to prevent rate limit issues.
    """

    CACHE_TTL = 60  # 60 seconds - positions don't change rapidly

    def __init__(self, user):
        self.user = user

    def _get_cache_key(self, account) -> str:
        """Generate cache key for stock positions."""
        return CacheManager.stock_positions(self.user.id, account.account_number)

    async def _fetch_and_cache_positions(self, account) -> dict:
        """
        Fetch positions from database (synced by PositionSyncService) and cache them.

        Epic 28 Task 009: Eliminated duplicate API call.
        Now reads from Position model instead of direct TastyTrade API.

        Returns:
            Dict mapping symbol -> position data
        """
        cache_key = self._get_cache_key(account)

        # Try cache first
        cached_positions = cache.get(cache_key)
        if cached_positions:
            logger.debug(f"Using cached stock positions for user {self.user.id}")
            return cached_positions

        # Cache miss - query database
        logger.info(f"Querying stock positions from database for user {self.user.id}")

        from trading.models import Position

        # Get all open equity positions
        equity_positions = Position.objects.filter(
            user=self.user,
            trading_account=account,
            instrument_type="Equity",  # Stock only
            lifecycle_state__in=["open_full", "open_partial"],  # Open positions only
        ).values("symbol", "quantity", "avg_price", "unrealized_pnl", "metadata")

        # Build position dict
        positions_dict = {}
        async for position in equity_positions:
            qty = position.get("quantity", 0)
            if qty > 0:  # Only long positions
                # Extract current price from metadata if available
                metadata = position.get("metadata", {})
                tastytrade_data = metadata.get("tastytrade_data", {})
                close_price_str = tastytrade_data.get("close_price")

                positions_dict[position["symbol"]] = {
                    "quantity": qty,
                    "cost_basis": position.get("avg_price") or Decimal("0"),
                    "current_price": Decimal(close_price_str) if close_price_str else Decimal("0"),
                    "unrealized_pnl": position.get("unrealized_pnl") or Decimal("0"),
                }

        # If no positions found, trigger position sync as fallback
        if not positions_dict:
            logger.warning(
                f"No stock positions found in database for user {self.user.id}. "
                f"Triggering position sync as fallback..."
            )
            await self._trigger_position_sync()

            # Try again after sync
            equity_positions = Position.objects.filter(
                user=self.user,
                trading_account=account,
                instrument_type="Equity",
                lifecycle_state__in=["open_full", "open_partial"],
            ).values("symbol", "quantity", "avg_price", "unrealized_pnl", "metadata")

            async for position in equity_positions:
                qty = position.get("quantity", 0)
                if qty > 0:
                    metadata = position.get("metadata", {})
                    tastytrade_data = metadata.get("tastytrade_data", {})
                    close_price_str = tastytrade_data.get("close_price")

                    positions_dict[position["symbol"]] = {
                        "quantity": qty,
                        "cost_basis": position.get("avg_price") or Decimal("0"),
                        "current_price": (
                            Decimal(close_price_str) if close_price_str else Decimal("0")
                        ),
                        "unrealized_pnl": position.get("unrealized_pnl") or Decimal("0"),
                    }

        # Cache for 60 seconds
        cache.set(cache_key, positions_dict, timeout=self.CACHE_TTL)
        logger.debug(f"Cached {len(positions_dict)} stock positions for user {self.user.id}")
        return positions_dict

    async def _trigger_position_sync(self) -> None:
        """
        Trigger position sync if database is empty (fallback mechanism).

        Epic 28 Task 009: Ensures data availability by triggering sync when needed.
        """
        try:
            from services.positions.sync import PositionSyncService

            sync_service = PositionSyncService()
            result = await sync_service.sync_all_positions(self.user)

            logger.info(
                f"Position sync triggered: {result.get('imported', 0)} imported, "
                f"{result.get('updated', 0)} updated"
            )
        except Exception as e:
            logger.error(f"Failed to trigger position sync: {e}", exc_info=True)

    async def has_sufficient_shares(self, symbol: str, required: int = 100) -> bool:
        """
        Check if user owns required number of shares.

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            required: Minimum shares needed (default 100 for covered calls)

        Returns:
            True if user owns >= required shares
        """
        try:
            quantity = await self.get_stock_quantity(symbol)
            return quantity >= required
        except Exception as e:
            logger.error(f"Error checking stock quantity for {symbol}: {e}")
            return False

    async def get_stock_quantity(self, symbol: str) -> int:
        """
        Get current quantity of stock owned (with caching).

        Epic 28: Uses 60s cache to prevent rate limiting.

        Args:
            symbol: Stock symbol

        Returns:
            Number of shares owned (0 if none)
        """
        try:
            # Get account
            from services.core.data_access import get_primary_tastytrade_account

            account = await get_primary_tastytrade_account(self.user)
            if not account:
                logger.warning("No TastyTrade account found")
                return 0

            # Use cached positions
            positions = await self._fetch_and_cache_positions(account)
            position = positions.get(symbol, {})
            return position.get("quantity", 0)

        except Exception as e:
            logger.error(f"Error getting stock quantity for {symbol}: {e}")
            return 0

    async def get_stock_basis(self, symbol: str) -> Decimal | None:
        """
        Get average cost basis for stock position (with caching).

        Epic 28: Uses 60s cache to prevent rate limiting.

        Args:
            symbol: Stock symbol

        Returns:
            Average cost per share, or None if no position
        """
        try:
            # Get account
            from services.core.data_access import get_primary_tastytrade_account

            account = await get_primary_tastytrade_account(self.user)
            if not account:
                return None

            # Use cached positions
            positions = await self._fetch_and_cache_positions(account)
            position = positions.get(symbol, {})
            return position.get("cost_basis")

        except Exception as e:
            logger.error(f"Error getting cost basis for {symbol}: {e}")
            return None

    async def get_all_stock_positions(self) -> list[dict]:
        """
        Get all stock positions for the user (with caching).

        Epic 28: Uses 60s cache to prevent rate limiting.

        Returns:
            List of dicts with stock position info:
            [
                {
                    'symbol': 'SPY',
                    'quantity': 200,
                    'cost_basis': Decimal('450.25'),
                    'current_price': Decimal('455.00'),
                    'unrealized_pnl': Decimal('950.00')
                },
                ...
            ]
        """
        try:
            # Get account
            from services.core.data_access import get_primary_tastytrade_account

            account = await get_primary_tastytrade_account(self.user)
            if not account:
                return []

            # Use cached positions
            positions_dict = await self._fetch_and_cache_positions(account)

            # Convert to list format
            return [{"symbol": symbol, **data} for symbol, data in positions_dict.items()]

        except Exception as e:
            logger.error(f"Error getting all stock positions: {e}")
            return []

    def invalidate_cache(self):
        """
        Invalidate stock position cache (call after trade execution).

        Epic 28 Task 003: Cache invalidation for position updates.

        Should be called after:
        - Stock purchases/sales
        - Options assignments
        - Options exercises
        """
        from services.core.data_access import get_primary_tastytrade_account_sync

        account = get_primary_tastytrade_account_sync(self.user)
        if account:
            cache_key = self._get_cache_key(account)
            cache.delete(cache_key)
            logger.info(f"Invalidated stock position cache for user {self.user.id}")
