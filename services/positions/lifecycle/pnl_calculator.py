"""Calculate P&L for positions."""

from decimal import Decimal


class PositionPnLCalculator:
    """Calculate P&L for positions.

    This class provides utilities for calculating both realized and unrealized P&L
    for option positions. It handles direction-aware calculations for both long
    and short positions.
    """

    @staticmethod
    def calculate_realized_pnl(
        opening_credit: Decimal, closing_debit: Decimal, quantity: int, multiplier: int = 100
    ) -> Decimal:
        """
        Calculate realized P&L for closed position.

        Formula: (opening_credit - closing_debit) * quantity * multiplier

        Args:
            opening_credit: Credit received when opening position (per contract)
            closing_debit: Debit paid when closing position (per contract)
            quantity: Number of contracts (positive integer)
            multiplier: Option multiplier (typically 100 for standard options)

        Returns:
            Realized P&L in dollars (positive = profit, negative = loss)

        Examples:
            >>> calc = PositionPnLCalculator()
            >>> # Opened for $5.00 credit, closed for $2.50 debit
            >>> calc.calculate_realized_pnl(Decimal("5.00"), Decimal("2.50"), 1)
            Decimal("250.00")  # Profit of $250

            >>> # Opened for $5.00 credit, closed for $7.00 debit
            >>> calc.calculate_realized_pnl(Decimal("5.00"), Decimal("7.00"), 1)
            Decimal("-200.00")  # Loss of $200
        """
        return (opening_credit - closing_debit) * Decimal(quantity) * Decimal(multiplier)

    @staticmethod
    def calculate_unrealized_pnl(
        opening_credit: Decimal, current_mark: Decimal, quantity: int, multiplier: int = 100
    ) -> Decimal:
        """
        Calculate unrealized P&L for open position.

        Formula: (opening_credit - current_mark) * quantity * multiplier

        Args:
            opening_credit: Credit received when opening position (per contract)
            current_mark: Current market mark price (per contract)
            quantity: Number of contracts (positive integer)
            multiplier: Option multiplier (typically 100 for standard options)

        Returns:
            Unrealized P&L in dollars (positive = profit, negative = loss)

        Examples:
            >>> calc = PositionPnLCalculator()
            >>> # Opened for $5.00, currently at $3.00
            >>> calc.calculate_unrealized_pnl(Decimal("5.00"), Decimal("3.00"), 1)
            Decimal("200.00")  # Unrealized profit of $200

            >>> # Opened for $5.00, currently at $6.00
            >>> calc.calculate_unrealized_pnl(Decimal("5.00"), Decimal("6.00"), 1)
            Decimal("-100.00")  # Unrealized loss of $100
        """
        return (opening_credit - current_mark) * Decimal(quantity) * Decimal(multiplier)

    @staticmethod
    def calculate_leg_pnl(
        avg_price: float,
        current_price: float,
        quantity: int,
        quantity_direction: str,
        multiplier: int = 100,
    ) -> Decimal:
        """
        Calculate P&L for a single position leg (direction-aware).

        This method handles both SHORT and LONG positions:
        - SHORT: Profit when price goes DOWN (sold high, buy back low)
        - LONG: Profit when price goes UP (bought low, sell high)

        Args:
            avg_price: Average open price for this leg
            current_price: Current market price for this leg
            quantity: Number of contracts (will use absolute value)
            quantity_direction: Direction - "short" or "long"
            multiplier: Option multiplier (typically 100)

        Returns:
            P&L for this leg in dollars

        Examples:
            >>> calc = PositionPnLCalculator()
            >>> # Short position: sold at $5, now at $3 (profit)
            >>> calc.calculate_leg_pnl(5.0, 3.0, 1, "short")
            Decimal("200.00")

            >>> # Long position: bought at $3, now at $5 (profit)
            >>> calc.calculate_leg_pnl(3.0, 5.0, 1, "long")
            Decimal("200.00")
        """
        abs_quantity = abs(quantity)

        # Direction-aware P&L calculation
        if quantity_direction.lower() == "short" or quantity < 0:
            # SHORT: Profit when price goes DOWN
            # Sold high, buy back low = profit
            leg_pnl = (avg_price - current_price) * abs_quantity * multiplier
        else:
            # LONG: Profit when price goes UP
            # Bought low, sell high = profit
            leg_pnl = (current_price - avg_price) * abs_quantity * multiplier

        return Decimal(str(leg_pnl))

    @staticmethod
    def calculate_spread_pnl(
        opening_credit: Decimal,
        current_mark: Decimal,
        quantity: int,
        spread_width: Decimal,  # noqa: ARG004
        is_credit_spread: bool = True,
    ) -> Decimal:
        """
        Calculate P&L for option spread.

        This method provides a convenient wrapper around calculate_unrealized_pnl()
        that explicitly handles both credit and debit spreads. For most use cases,
        the underlying calculate_unrealized_pnl() method is sufficient.

        Args:
            opening_credit: Credit received when opening (or debit paid if debit)
            current_mark: Current market mark price
            quantity: Number of spreads
            spread_width: Width of spread (e.g., $5 for 440/445) - currently
                unused but kept for API compatibility
            is_credit_spread: True for credit, False for debit

        Returns:
            P&L in dollars

        Examples:
            >>> calc = PositionPnLCalculator()
            >>> # Credit spread: opened for $5.00, currently at $2.50
            >>> calc.calculate_spread_pnl(Decimal("5.00"), Decimal("2.50"), 1, Decimal("5"), True)
            Decimal("250.00")

            >>> # Debit spread: opened for $3.00, currently at $5.00
            >>> calc.calculate_spread_pnl(Decimal("3.00"), Decimal("5.00"), 1, Decimal("5"), False)
            Decimal("200.00")
        """
        if is_credit_spread:
            # For credit spreads: P&L = (opening_credit - current_mark) * qty * 100
            return (opening_credit - current_mark) * Decimal(quantity) * Decimal("100")

        # For debit spreads: P&L = (current_mark - opening_debit) * qty * 100
        return (current_mark - opening_credit) * Decimal(quantity) * Decimal("100")

    @staticmethod
    def calculate_portfolio_pnl(positions: list) -> dict:
        """
        Calculate aggregate P&L across portfolio.

        Args:
            positions: List of Position instances

        Returns:
            Dict with total_realized, total_unrealized, net_pnl

        Examples:
            >>> calc = PositionPnLCalculator()
            >>> # Mock positions
            >>> from unittest.mock import Mock
            >>> positions = [
            ...     Mock(lifecycle_state="closed", total_realized_pnl=Decimal("100.00")),
            ...     Mock(lifecycle_state="open_full", unrealized_pnl=Decimal("50.00")),
            ... ]
            >>> result = calc.calculate_portfolio_pnl(positions)
            >>> result["total_realized"]
            Decimal('100.00')
            >>> result["net_pnl"]
            Decimal('150.00')
        """
        total_realized = Decimal("0")
        total_unrealized = Decimal("0")

        for position in positions:
            if position.lifecycle_state == "closed":
                total_realized += position.total_realized_pnl or Decimal("0")
            else:
                total_unrealized += position.unrealized_pnl or Decimal("0")

        return {
            "total_realized": total_realized,
            "total_unrealized": total_unrealized,
            "net_pnl": total_realized + total_unrealized,
        }
