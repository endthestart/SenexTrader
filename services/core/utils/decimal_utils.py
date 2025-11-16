"""Decimal conversion utilities for safe float-to-Decimal conversions.

This module provides utilities for converting numeric values to Decimal objects
safely by using string representation to avoid floating-point precision errors.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["to_decimal"]


def to_decimal(value: object | None) -> Decimal | None:
    """
    Safely convert a numeric value to Decimal via string representation.

    This pattern prevents floating-point precision errors by converting through
    string representation rather than directly from float.

    Args:
        value: Numeric value (float, int, str, Decimal) or None

    Returns:
        Decimal representation of the value, or None if input is None

    Examples:
        >>> to_decimal(1.23)
        Decimal('1.23')
        >>> to_decimal(None)
        None
        >>> to_decimal("45.67")
        Decimal('45.67')
        >>> to_decimal(Decimal("100.50"))
        Decimal('100.50')

    Note:
        This function uses str() conversion to avoid floating-point precision
        issues. For example:
        - Decimal(0.1) -> Decimal('0.10000000000000000555...')  # WRONG
        - Decimal(str(0.1)) -> Decimal('0.1')  # CORRECT
    """
    if value is None:
        return None
    return Decimal(str(value))
