"""Calculate P&L for positions - Single Source of Truth.

This module contains the unified P&L calculator for all closure pathways.
All P&L calculation should flow through this class to ensure consistency.

Usage:
    from services.positions.lifecycle.pnl_calculator import PnLCalculator

    # For profit target fills
    pnl = PnLCalculator.calculate_profit_target_pnl(position, close_price, quantity)

    # From transactions
    pnl = PnLCalculator.calculate_from_transactions(opening_txns, closing_txns)

    # For unrealized P&L
    pnl = PnLCalculator.calculate_unrealized_pnl(
        opening_price, current_mark, quantity, is_credit=True
    )
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from services.core.utils.decimal_utils import to_decimal
from services.sdk.trading_utils import PriceEffect

if TYPE_CHECKING:
    from trading.models import Position, TastyTradeTransaction


_DECIMAL_PLACES = Decimal("0.01")
_CONTRACT_MULTIPLIER = Decimal("100")


class PnLCalculator:
    """
    Unified P&L calculator - single source of truth.

    This class consolidates all P&L calculation logic to ensure consistent
    results regardless of which closure pathway is used.

    P&L Formulas:
        Credit Spread: P&L = (entry_price - close_price) * quantity * 100
        Debit Spread:  P&L = (close_price - entry_price) * quantity * 100

    Transaction-based Formula:
        opening_value = sum(
            +tx.net_value if tx.action == "Sell to Open" else -tx.net_value
            for tx in opening_txns
        )
        closing_value = sum(
            -tx.net_value if tx.action == "Buy to Close" else +tx.net_value
            for tx in closing_txns
        )
        pnl = opening_value + closing_value
    """

    @staticmethod
    def calculate_profit_target_pnl(
        position: "Position",
        close_price: Decimal | None,
        quantity: int,
        multiplier: Decimal = _CONTRACT_MULTIPLIER,
        opening_price: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate realized P&L for a profit target fill.

        This is the primary method for calculating P&L when a profit target
        order fills.

        Args:
            position: Position being closed
            close_price: Price at which profit target filled
            quantity: Number of contracts closed
            multiplier: Contract multiplier (default 100)
            opening_price: Spread-specific opening price (e.g., original_credit from
                profit_target_details). If provided, uses this instead of position.avg_price.
                This is critical for multi-spread positions like Senex Trident where each
                spread has a different opening credit.

        Returns:
            Realized P&L for this profit target fill
        """
        if close_price is None or quantity == 0:
            return Decimal("0")

        # Use spread-specific opening_price if provided, otherwise fall back to avg_price
        if opening_price is not None:
            entry_price = to_decimal(opening_price)
        else:
            entry_price = to_decimal(position.avg_price)

        if entry_price is None:
            return Decimal("0")

        close_price = to_decimal(close_price)
        qty_multiplier = multiplier * Decimal(abs(quantity))

        # Credit spreads: profit when closing at lower price
        # Debit spreads: profit when closing at higher price
        if position.opening_price_effect == PriceEffect.CREDIT.value:
            pnl = (entry_price - close_price) * qty_multiplier
        else:
            pnl = (close_price - entry_price) * qty_multiplier

        return pnl.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_from_transactions(
        opening_txns: list["TastyTradeTransaction"],
        closing_txns: list["TastyTradeTransaction"],
    ) -> Decimal:
        """
        Calculate P&L from actual transaction data.

        This is the ground-truth calculation used by reconciliation and
        batch processing. Works directly with transaction net_values.

        Formula:
            opening_value = sum(
                +tx.net_value if tx.action == "Sell to Open" else -tx.net_value
                for tx in opening_txns
            )
            closing_value = sum(
                -tx.net_value if tx.action == "Buy to Close" else +tx.net_value
                for tx in closing_txns
            )
            pnl = opening_value + closing_value

        Args:
            opening_txns: Opening transactions
            closing_txns: Closing transactions (including assignments)

        Returns:
            Realized P&L
        """
        # Calculate opening value (credits positive, debits negative)
        opening_value = Decimal("0")
        for tx in opening_txns:
            if tx.net_value is None:
                continue
            if tx.action == "Sell to Open":
                opening_value += tx.net_value  # Credit received
            elif tx.action == "Buy to Open":
                opening_value -= abs(tx.net_value)  # Debit paid

        # Calculate closing value (opposite signs)
        closing_value = Decimal("0")
        for tx in closing_txns:
            if tx.net_value is None:
                continue
            if tx.action == "Buy to Close":
                closing_value -= abs(tx.net_value)  # Debit paid to close
            elif tx.action == "Sell to Close":
                closing_value += tx.net_value  # Credit received to close
            else:
                # Assignment/exercise - use net_value as-is
                # Assignments typically show as negative (you paid)
                closing_value += tx.net_value

        return opening_value + closing_value

    @staticmethod
    def calculate_unrealized_pnl(
        opening_price: Decimal,
        current_mark: Decimal,
        quantity: int,
        is_credit: bool = True,
        multiplier: Decimal = _CONTRACT_MULTIPLIER,
    ) -> Decimal:
        """
        Calculate unrealized P&L for open position.

        Args:
            opening_price: Entry price (credit or debit per contract)
            current_mark: Current market mark price (per contract)
            quantity: Number of contracts (uses absolute value)
            is_credit: True for credit spreads, False for debit spreads
            multiplier: Option multiplier (default 100)

        Returns:
            Unrealized P&L in dollars (positive = profit, negative = loss)

        Examples:
            # Credit spread: opened for $5.00, currently at $3.00
            >>> PnLCalculator.calculate_unrealized_pnl(
            ...     Decimal("5.00"), Decimal("3.00"), 1, is_credit=True
            ... )
            Decimal("200.00")  # Profit

            # Debit spread: opened for $3.00, currently at $5.00
            >>> PnLCalculator.calculate_unrealized_pnl(
            ...     Decimal("3.00"), Decimal("5.00"), 1, is_credit=False
            ... )
            Decimal("200.00")  # Profit
        """
        qty_multiplier = Decimal(abs(quantity)) * multiplier

        if is_credit:
            # Credit spread: profit when price goes DOWN
            pnl = (opening_price - current_mark) * qty_multiplier
        else:
            # Debit spread: profit when price goes UP
            pnl = (current_mark - opening_price) * qty_multiplier

        return pnl.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_realized_pnl(
        opening_price: Decimal,
        closing_price: Decimal,
        quantity: int,
        is_credit: bool = True,
        multiplier: Decimal = _CONTRACT_MULTIPLIER,
    ) -> Decimal:
        """
        Calculate realized P&L for closed position.

        Args:
            opening_price: Entry price (credit or debit per contract)
            closing_price: Close price paid/received (per contract)
            quantity: Number of contracts (uses absolute value)
            is_credit: True for credit spreads, False for debit spreads
            multiplier: Option multiplier (default 100)

        Returns:
            Realized P&L in dollars (positive = profit, negative = loss)
        """
        qty_multiplier = Decimal(abs(quantity)) * multiplier

        if is_credit:
            # Credit spread: profit = credit - debit_to_close
            pnl = (opening_price - closing_price) * qty_multiplier
        else:
            # Debit spread: profit = credit_at_close - debit_paid
            pnl = (closing_price - opening_price) * qty_multiplier

        return pnl.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

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
        """
        abs_quantity = abs(quantity)

        if quantity_direction.lower() == "short" or quantity < 0:
            # SHORT: Profit when price goes DOWN
            leg_pnl = (avg_price - current_price) * abs_quantity * multiplier
        else:
            # LONG: Profit when price goes UP
            leg_pnl = (current_price - avg_price) * abs_quantity * multiplier

        return Decimal(str(leg_pnl))

    @staticmethod
    def calculate_portfolio_pnl(positions: list) -> dict:
        """
        Calculate aggregate P&L across portfolio.

        Args:
            positions: List of Position instances

        Returns:
            Dict with total_realized, total_unrealized, net_pnl
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
