"""
Core type definitions for unified strategy architecture.

This module provides the foundational types used across all strategy builders:
- Type aliases for numeric fields (Strike, Premium, Delta, Quantity)
- Enums for strategy configuration (Direction, OptionType, Side, StrikeSelection, PriceEffect)
"""

from decimal import Decimal
from enum import Enum
from typing import TypeAlias

# Re-export PriceEffect from SDK for unified imports
from services.sdk.trading_utils import PriceEffect  # noqa: F401

# Type aliases for self-documenting code
Strike: TypeAlias = Decimal
Premium: TypeAlias = Decimal
Delta: TypeAlias = float
Quantity: TypeAlias = int


class Direction(str, Enum):
    """
    Market direction bias for a strategy.

    Consolidates the duplicate SpreadDirection enums from credit_spread_base.py
    and debit_spread_base.py into a single definition.
    """

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class OptionType(str, Enum):
    """Option instrument type."""

    CALL = "C"
    PUT = "P"

    @property
    def full_name(self) -> str:
        """Return full name for display."""
        return "Call" if self == OptionType.CALL else "Put"


class Side(str, Enum):
    """
    Position side - whether we own or owe the option.

    LONG: Bought the option, own it, paid premium
    SHORT: Sold the option, obligation, received premium
    """

    LONG = "long"
    SHORT = "short"

    @property
    def multiplier(self) -> int:
        """Return +1 for long, -1 for short (useful for P&L calculations)."""
        return 1 if self == Side.LONG else -1


class StrikeSelection(str, Enum):
    """
    Method for selecting option strikes.

    DELTA: Target delta value (e.g., 0.30 for 30-delta)
    OTM_PERCENT: Percentage out-of-the-money (e.g., 0.03 for 3%)
    FIXED_WIDTH: Fixed dollar width from reference strike
    ATM_OFFSET: Points offset from at-the-money
    """

    DELTA = "delta"
    OTM_PERCENT = "otm_pct"
    FIXED_WIDTH = "width"
    ATM_OFFSET = "atm"
