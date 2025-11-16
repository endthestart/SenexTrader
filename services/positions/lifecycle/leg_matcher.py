"""Match position legs to raw TastyTrade legs."""

import logging

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
