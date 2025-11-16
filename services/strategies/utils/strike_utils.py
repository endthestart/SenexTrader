"""
Strike price calculation utilities for options strategies.

These utilities provide consistent strike selection and rounding
across all strategy implementations.
"""

from decimal import Decimal


def round_to_even_strike(price: Decimal) -> Decimal:
    """
    Round price to nearest even strike number (2, 4, 6, 8...).

    All three strategies use even strikes for consistency and liquidity.
    This is the single source of truth for strike rounding.

    Args:
        price: Price to round (Decimal)

    Returns:
        Decimal: Price rounded to nearest even number

    Examples:
        >>> round_to_even_strike(Decimal('449.23'))
        Decimal('450')
        >>> round_to_even_strike(Decimal('448.50'))
        Decimal('448')
    """
    return Decimal(str(round(float(price) / 2) * 2))


def calculate_max_profit_credit_spread(credit_received: Decimal, quantity: int = 1) -> Decimal:
    """
    Calculate max profit for credit spreads (Bull Put, Senex Trident).

    For credit spreads:
    - Max profit = Total credit received
    - Profit if position expires OTM (worthless)

    Args:
        credit_received: Credit per spread (mid-price or natural)
        quantity: Number of spreads

    Returns:
        Max profit in dollars

    Example:
        >>> calculate_max_profit_credit_spread(Decimal('1.25'), quantity=2)
        Decimal('250.00')  # $1.25 * 2 spreads * 100
    """
    return credit_received * Decimal(str(quantity)) * Decimal("100")


def find_nearest_available_strike(
    target_strike: Decimal,
    available_strikes: list[Decimal],
) -> Decimal | None:
    """
    Find closest available strike to target strike.

    Used by "exact strike" strategies (butterfly, straddle, strangle, etc.)
    when the ideal calculated strike doesn't exist in the option chain.

    Algorithm:
    - Finds strike with minimum absolute distance from target
    - No distance limit - always returns closest available
    - Returns None only if available_strikes is empty

    Args:
        target_strike: Desired strike price
        available_strikes: List of strikes from option chain

    Returns:
        Closest available strike, or None if list empty

    Examples:
        >>> strikes = [Decimal('610'), Decimal('612'), Decimal('615')]
        >>> find_nearest_available_strike(Decimal('611'), strikes)
        Decimal('610')  # 610 is closer than 612

        >>> find_nearest_available_strike(Decimal('613'), strikes)
        Decimal('612')  # 612 is closer than 615
    """
    if not available_strikes:
        return None

    # Find strike with minimum distance from target
    return min(available_strikes, key=lambda s: abs(s - target_strike))


def calculate_max_profit_debit_spread(
    spread_width: int, debit_paid: Decimal, quantity: int = 1
) -> Decimal:
    """
    Calculate max profit for debit spreads (Bear Put).

    For debit spreads:
    - Max profit = (Spread width - Debit paid) * 100 * quantity
    - Profit if spread reaches max width (ITM)

    Args:
        spread_width: Width of spread in points
        debit_paid: Debit per spread (positive number)
        quantity: Number of spreads

    Returns:
        Max profit in dollars

    Example:
        >>> calculate_max_profit_debit_spread(5, Decimal('1.08'), quantity=1)
        Decimal('392.00')  # (5 - 1.08) * 100
    """
    max_profit_per_spread = (Decimal(str(spread_width)) - debit_paid) * Decimal("100")
    return max_profit_per_spread * Decimal(str(quantity))
