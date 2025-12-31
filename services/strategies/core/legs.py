"""
Leg composition for unified strategy architecture.

This module provides the StrategyLeg class that combines an OptionContract
with a Side (LONG/SHORT) and quantity to represent a single leg of a strategy.

StrategyLeg is the bridge between strategy composition and order execution.
"""

from dataclasses import dataclass
from decimal import Decimal

from services.orders.spec import OrderLeg
from services.strategies.core.primitives import OptionContract
from services.strategies.core.types import Quantity, Side


@dataclass(frozen=True)
class StrategyLeg:
    """
    A single leg of an options strategy.

    Combines an OptionContract with position side and quantity.
    This is the strategy-level representation that can be converted
    to order-level legs for execution.

    Attributes:
        contract: The option contract being traded
        side: LONG (bought) or SHORT (sold)
        quantity: Number of contracts (always positive)

    Example:
        >>> from datetime import date
        >>> from decimal import Decimal
        >>> contract = OptionContract(
        ...     symbol="SPY",
        ...     option_type=OptionType.PUT,
        ...     strike=Decimal("580.00"),
        ...     expiration=date(2025, 1, 17)
        ... )
        >>> leg = StrategyLeg(contract=contract, side=Side.SHORT, quantity=1)
        >>> leg.is_short
        True
    """

    contract: OptionContract
    side: Side
    quantity: Quantity

    def __post_init__(self):
        """Validate quantity is positive."""
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")

    @property
    def occ_symbol(self) -> str:
        """Get OCC symbol from underlying contract."""
        return self.contract.occ_symbol

    @property
    def is_long(self) -> bool:
        """Check if this is a long (bought) position."""
        return self.side == Side.LONG

    @property
    def is_short(self) -> bool:
        """Check if this is a short (sold) position."""
        return self.side == Side.SHORT

    def premium_effect(self, premium_per_contract: Decimal) -> Decimal:
        """
        Calculate net premium effect for this leg.

        LONG positions pay premium (negative cash flow).
        SHORT positions receive premium (positive cash flow).

        Args:
            premium_per_contract: Premium per contract (always positive input)

        Returns:
            Net premium: negative for long, positive for short
        """
        # SHORT receives premium (+), LONG pays premium (-)
        return premium_per_contract * self.quantity * self.side.multiplier * -1

    def max_loss_at_expiry(self, premium_per_contract: Decimal) -> Decimal:
        """
        Calculate maximum loss for this leg at expiration.

        For LONG options: max loss = premium paid
        For SHORT options: max loss = theoretically unlimited (capped by strike for puts)

        This returns the premium-based loss only. For spread-level risk
        calculations, use the Strategy composition.

        Args:
            premium_per_contract: Premium per contract

        Returns:
            Maximum loss (always positive or zero)
        """
        if self.is_long:
            # Long options: max loss is premium paid
            return premium_per_contract * self.quantity
        # Short options: max loss is unlimited for calls, strike for puts
        # Return premium received as minimum (actual max is higher)
        return Decimal("0")  # Requires spread context for true max loss

    def to_order_leg(self, opening: bool = True) -> OrderLeg:
        """
        Convert to order-level leg for execution.

        Args:
            opening: True for opening trades, False for closing

        Returns:
            OrderLeg ready for order construction
        """
        if opening:
            action = "sell_to_open" if self.is_short else "buy_to_open"
        else:
            action = "buy_to_close" if self.is_short else "sell_to_close"

        return OrderLeg(
            instrument_type="equity_option",
            symbol=self.occ_symbol,
            action=action,
            quantity=self.quantity,
        )

    def closing_leg(self) -> "StrategyLeg":
        """
        Create the opposite leg for closing this position.

        Returns:
            New StrategyLeg with opposite side
        """
        opposite_side = Side.LONG if self.is_short else Side.SHORT
        return StrategyLeg(
            contract=self.contract,
            side=opposite_side,
            quantity=self.quantity,
        )
