"""
Core option primitives for unified strategy architecture.

This module provides immutable data structures representing options:
- OptionContract: Single option with strike, expiration, type

These primitives are the building blocks for legs and strategies.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.sdk.instruments import build_occ_symbol
from services.strategies.core.types import OptionType, Strike


@dataclass(frozen=True)
class OptionContract:
    """
    Immutable representation of a single option contract.

    This is the atomic unit of the strategy system - a specific option
    identified by underlying, strike, expiration, and type.

    Attributes:
        symbol: Underlying symbol (e.g., "SPY", "QQQ")
        option_type: CALL or PUT
        strike: Strike price
        expiration: Expiration date

    Example:
        >>> contract = OptionContract(
        ...     symbol="SPY",
        ...     option_type=OptionType.PUT,
        ...     strike=Decimal("580.00"),
        ...     expiration=date(2025, 1, 17)
        ... )
        >>> contract.occ_symbol
        'SPY   250117P00580000'
    """

    symbol: str
    option_type: OptionType
    strike: Strike
    expiration: date

    @property
    def occ_symbol(self) -> str:
        """
        Generate OCC-compliant symbol.

        Delegates to the battle-tested build_occ_symbol() function
        in services/sdk/instruments.py.
        """
        return build_occ_symbol(
            underlying=self.symbol,
            expiration=self.expiration,
            strike=self.strike,
            option_type=self.option_type.value,
        )

    def intrinsic_value(self, spot_price: Decimal) -> Decimal:
        """
        Calculate intrinsic value given current spot price.

        For calls: max(0, spot - strike)
        For puts: max(0, strike - spot)

        Args:
            spot_price: Current price of the underlying

        Returns:
            Intrinsic value (always >= 0)
        """
        if self.option_type == OptionType.CALL:
            return max(Decimal("0"), spot_price - self.strike)
        return max(Decimal("0"), self.strike - spot_price)

    def is_itm(self, spot_price: Decimal) -> bool:
        """
        Check if option is in-the-money.

        Args:
            spot_price: Current price of the underlying

        Returns:
            True if option has intrinsic value
        """
        return self.intrinsic_value(spot_price) > 0

    def is_otm(self, spot_price: Decimal) -> bool:
        """
        Check if option is out-of-the-money.

        Args:
            spot_price: Current price of the underlying

        Returns:
            True if option has no intrinsic value
        """
        return self.intrinsic_value(spot_price) == 0

    def moneyness(self, spot_price: Decimal) -> Decimal:
        """
        Calculate moneyness ratio (spot / strike).

        Values:
        - > 1.0: Call is ITM, Put is OTM
        - = 1.0: At-the-money
        - < 1.0: Call is OTM, Put is ITM

        Args:
            spot_price: Current price of the underlying

        Returns:
            Moneyness ratio
        """
        if self.strike == 0:
            return Decimal("0")
        return spot_price / self.strike

    def otm_percentage(self, spot_price: Decimal) -> Decimal:
        """
        Calculate percentage out-of-the-money.

        For calls: (strike - spot) / spot (positive when OTM)
        For puts: (spot - strike) / spot (positive when OTM)

        Args:
            spot_price: Current price of the underlying

        Returns:
            OTM percentage (positive = OTM, negative = ITM)
        """
        if spot_price == 0:
            return Decimal("0")
        if self.option_type == OptionType.CALL:
            return (self.strike - spot_price) / spot_price
        return (spot_price - self.strike) / spot_price
