"""
Pricing utilities for option order handling.

Handles price rounding requirements for different underlying symbols.
Different options require different price increments:
- SPX and other index options: $0.05
- Most equity options: $0.01
"""

from decimal import Decimal

# Index options that require 5-cent increments
# Source: CBOE and TastyTrade documentation
NICKEL_INCREMENT_SYMBOLS: set[str] = {
    "SPX",  # S&P 500 Index
    "NDX",  # Nasdaq-100 Index
    "RUT",  # Russell 2000 Index
    "VIX",  # Volatility Index
    "XSP",  # Mini-SPX Index
    "DJX",  # Dow Jones Index
    "OEX",  # S&P 100 Index
}


def get_price_increment(underlying_symbol: str) -> Decimal:
    """
    Return the correct price increment for option orders.

    Args:
        underlying_symbol: The underlying symbol (e.g., 'SPY', 'SPX')

    Returns:
        Decimal: The price increment ($0.05 for index options, $0.01 for equity options)
    """
    if underlying_symbol.upper() in NICKEL_INCREMENT_SYMBOLS:
        return Decimal("0.05")
    return Decimal("0.01")


def round_option_price(price: Decimal, underlying_symbol: str) -> Decimal:
    """
    Round price to the correct increment for TastyTrade orders.

    Args:
        price: The raw price to round
        underlying_symbol: The underlying symbol (e.g., 'SPY', 'SPX')

    Returns:
        Decimal: Price rounded to the correct increment

    Examples:
        >>> round_option_price(Decimal('1.234'), 'SPY')
        Decimal('1.23')
        >>> round_option_price(Decimal('1.234'), 'SPX')
        Decimal('1.25')
    """
    increment = get_price_increment(underlying_symbol)
    return price.quantize(increment)


def is_valid_price_increment(price: Decimal, underlying_symbol: str) -> bool:
    """
    Check if a price has the valid increment for the underlying symbol.

    Args:
        price: The price to validate
        underlying_symbol: The underlying symbol (e.g., 'SPY', 'SPX')

    Returns:
        bool: True if the price has valid increments, False otherwise
    """
    increment = get_price_increment(underlying_symbol)
    remainder = price % increment
    return remainder == 0
