"""Match position legs to raw TastyTrade legs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.models import Position, TastyTradeOrderHistory

logger = logging.getLogger(__name__)


class LegMatcher:
    """Match position legs to raw position legs from TastyTrade.

    This utility helps match option symbols from opening orders to current
    position data from TastyTrade to get live pricing information.
    """

    def __init__(self, legs_by_symbol: dict):
        """
        Initialize with leg lookup map.

        Args:
            legs_by_symbol: Dict mapping OCC symbols to leg data.
                           Example: {"QQQ   251107P00594000": {...leg data...}}
        """
        self.legs_by_symbol = legs_by_symbol

    def match_legs(self, occ_symbols: list[str]) -> list[dict]:
        """
        Match OCC symbols to raw position legs.

        Args:
            occ_symbols: List of OCC option symbols from opening order
                        Example: ["QQQ   251107P00594000", "QQQ   251107P00589000"]

        Returns:
            List of matched leg data dicts. Returns only legs that were found.

        Example:
            >>> matcher = LegMatcher({
            ...     "QQQ   251107P00594000": {"symbol": "...", "mark_price": 5.50}
            ... })
            >>> matched = matcher.match_legs(["QQQ   251107P00594000"])
            >>> len(matched)
            1
        """
        matched = []
        for symbol in occ_symbols:
            if symbol in self.legs_by_symbol:
                matched.append(self.legs_by_symbol[symbol])
            else:
                logger.warning(
                    f"Leg {symbol} not found in TastyTrade positions " f"(may be expired or closed)"
                )
        return matched

    def match_leg(self, occ_symbol: str) -> dict | None:
        """
        Match a single OCC symbol to raw position leg.

        Args:
            occ_symbol: OCC option symbol from opening order

        Returns:
            Matched leg data dict or None if not found

        Example:
            >>> matcher = LegMatcher({
            ...     "QQQ   251107P00594000": {"symbol": "...", "mark_price": 5.50}
            ... })
            >>> leg = matcher.match_leg("QQQ   251107P00594000")
            >>> leg is not None
            True
        """
        leg = self.legs_by_symbol.get(occ_symbol)
        if not leg:
            logger.warning(
                f"Leg {occ_symbol} not found in TastyTrade positions " f"(may be expired or closed)"
            )
        return leg

    def has_leg(self, occ_symbol: str) -> bool:
        """
        Check if a leg exists in the lookup map.

        Args:
            occ_symbol: OCC option symbol to check

        Returns:
            True if leg exists, False otherwise
        """
        return occ_symbol in self.legs_by_symbol

    def get_missing_legs(self, occ_symbols: list[str]) -> list[str]:
        """
        Get list of symbols that are not in the lookup map.

        Useful for identifying expired or closed legs.

        Args:
            occ_symbols: List of OCC symbols to check

        Returns:
            List of symbols that were not found
        """
        return [symbol for symbol in occ_symbols if symbol not in self.legs_by_symbol]

    def get_matched_count(self, occ_symbols: list[str]) -> int:
        """
        Count how many symbols matched.

        Args:
            occ_symbols: List of OCC symbols to check

        Returns:
            Number of symbols found in lookup map
        """
        return sum(1 for symbol in occ_symbols if symbol in self.legs_by_symbol)


class OrderAwareLegMatcher:
    """
    Match positions to TastyTrade legs using order IDs for isolation.

    **Problem**: Symbol-only matching merges 4x identical spreads into 1 position
    because TastyTrade aggregates positions by symbol.

    **Solution**: Use Position.opening_order_id to:
    1. Look up the original order that opened the position
    2. Extract the specific leg quantities from that order
    3. Track which quantity belongs to which Position

    **Usage**:
        orders = TastyTradeOrderHistory.objects.filter(...)
        positions = Position.objects.filter(...)
        matcher = OrderAwareLegMatcher(orders, positions)

        # Get legs for a specific position (by its opening order)
        legs = matcher.get_position_legs(position)

        # Check if position is still open at TastyTrade
        is_open = matcher.is_position_open_at_tt(position, tt_positions)
    """

    def __init__(
        self,
        cached_orders: list[TastyTradeOrderHistory],
        positions: list[Position],
    ):
        """
        Initialize matcher with order history and positions.

        Args:
            cached_orders: List of TastyTradeOrderHistory records
            positions: List of Position records (should have opening_order_id set)
        """
        # Index orders by broker_order_id for fast lookup
        self.orders_by_id: dict[str, TastyTradeOrderHistory] = {
            str(o.broker_order_id): o for o in cached_orders
        }
        self.positions = positions

        # Build position -> legs mapping from opening orders
        self._position_legs: dict[int, list[dict]] = {}
        self._build_position_leg_allocations()

    def _build_position_leg_allocations(self) -> None:
        """
        For each Position, extract its allocated legs from its opening order.

        This is the key to isolation: we look up the specific order that
        opened each position and get the exact leg data from that order.
        """
        for position in self.positions:
            if not position.opening_order_id:
                logger.warning(
                    f"Position {position.id} ({position.symbol}) has no opening_order_id"
                )
                continue

            order = self.orders_by_id.get(position.opening_order_id)
            if not order:
                logger.warning(
                    f"Position {position.id}: Opening order {position.opening_order_id} "
                    f"not found in order cache"
                )
                continue

            # Extract leg data from the order's JSON
            order_data = order.order_data or {}
            legs = order_data.get("legs", [])

            if legs:
                self._position_legs[position.id] = legs
                logger.debug(
                    f"Position {position.id}: Mapped {len(legs)} legs "
                    f"from order {position.opening_order_id}"
                )
            else:
                logger.warning(
                    f"Position {position.id}: Order {position.opening_order_id} has no legs"
                )

    def get_position_legs(self, position: Position) -> list[dict]:
        """
        Get the specific legs that belong to this Position.

        Returns legs from the Position's opening order, not generic symbol match.

        Args:
            position: Position to get legs for

        Returns:
            List of leg dicts from the opening order.
            Each dict has: symbol, action, quantity, instrument_type, etc.
        """
        return self._position_legs.get(position.id, [])

    def get_position_occ_symbols(self, position: Position) -> list[str]:
        """
        Get the OCC option symbols for a position's legs.

        Args:
            position: Position to get symbols for

        Returns:
            List of OCC symbols (e.g., ["QQQ   251107P00594000"])
        """
        legs = self.get_position_legs(position)
        return [leg.get("symbol") for leg in legs if leg.get("symbol")]

    def get_position_quantity_by_symbol(self, position: Position) -> dict[str, int]:
        """
        Get quantity breakdown by symbol for a position.

        Useful for matching against TastyTrade aggregated positions.

        Args:
            position: Position to analyze

        Returns:
            Dict mapping OCC symbol -> quantity
            Positive = long, Negative = short
        """
        legs = self.get_position_legs(position)
        qty_map: dict[str, int] = {}

        for leg in legs:
            symbol = leg.get("symbol")
            quantity = leg.get("quantity", 0)
            action = leg.get("action", "").lower()

            if not symbol:
                continue

            # Determine sign based on action
            # Sell to Open = short = negative, Buy to Open = long = positive
            quantity = -abs(quantity) if "sell" in action else abs(quantity)

            qty_map[symbol] = qty_map.get(symbol, 0) + quantity

        return qty_map

    def is_position_still_open_at_tt(
        self,
        position: Position,
        tt_positions: list,  # List of CurrentPosition from TastyTrade
    ) -> bool:
        """
        Check if this Position's legs are still present at TastyTrade.

        A position is considered "open" if ANY of its original legs still
        exist at TastyTrade. This handles partial closes (e.g., closing
        just the call spread of a Trident while put spreads remain).

        Note: This checks presence, not exact quantity match.
        TastyTrade aggregates positions, so we can't match exact quantities
        when multiple app positions have identical strikes.

        Args:
            position: Position to check
            tt_positions: Current positions from TastyTrade API

        Returns:
            True if any of the position's legs are present at TT, False if all closed
        """
        position_symbols = self.get_position_occ_symbols(position)
        if not position_symbols:
            logger.warning(f"Position {position.id}: No OCC symbols found for open check")
            return False

        # Build lookup of TT positions by symbol
        tt_by_symbol = {p.symbol: p for p in tt_positions}

        # Check if ANY leg is still present at TT
        legs_found = 0
        for symbol in position_symbols:
            if symbol in tt_by_symbol:
                legs_found += 1
            else:
                logger.debug(f"Position {position.id}: Leg {symbol} not found at TastyTrade")

        if legs_found > 0:
            if legs_found < len(position_symbols):
                logger.info(
                    f"Position {position.id}: Partial close - "
                    f"{legs_found}/{len(position_symbols)} legs remain"
                )
            return True

        return False

    def get_remaining_legs_count(
        self,
        position: Position,
        tt_positions: list,  # List of CurrentPosition from TastyTrade
    ) -> tuple[int, int]:
        """
        Get count of legs remaining at TastyTrade vs original.

        Useful for detecting partial closes and tracking position decay.

        Args:
            position: Position to check
            tt_positions: Current positions from TastyTrade API

        Returns:
            Tuple of (remaining_legs, original_legs)
        """
        position_symbols = self.get_position_occ_symbols(position)
        if not position_symbols:
            return (0, 0)

        tt_by_symbol = {p.symbol: p for p in tt_positions}
        remaining = sum(1 for s in position_symbols if s in tt_by_symbol)

        return (remaining, len(position_symbols))

    def is_position_fully_closed(
        self,
        position: Position,
        tt_positions: list,  # List of CurrentPosition from TastyTrade
    ) -> bool:
        """
        Check if position is fully closed (all legs gone from TastyTrade).

        Opposite of is_position_still_open_at_tt - returns True only when
        ALL legs are closed.

        Args:
            position: Position to check
            tt_positions: Current positions from TastyTrade API

        Returns:
            True if all position's legs are closed, False if any remain
        """
        remaining, total = self.get_remaining_legs_count(position, tt_positions)
        if total == 0:
            return True  # No legs = fully closed (or invalid)
        return remaining == 0

    def get_positions_without_opening_order(self) -> list[Position]:
        """
        Get positions that don't have an opening_order_id set.

        These positions cannot be properly isolated and may cause
        merge issues during sync.

        Returns:
            List of Position objects without opening_order_id
        """
        return [p for p in self.positions if not p.opening_order_id]

    def get_positions_with_missing_orders(self) -> list[Position]:
        """
        Get positions whose opening_order_id doesn't match any cached order.

        These positions have an order ID but we don't have the order data.

        Returns:
            List of Position objects with unmatched order IDs
        """
        return [
            p
            for p in self.positions
            if p.opening_order_id and p.opening_order_id not in self.orders_by_id
        ]
