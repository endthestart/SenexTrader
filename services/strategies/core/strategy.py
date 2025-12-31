"""
Strategy composition for unified strategy architecture.

This module provides the StrategyComposition class that combines multiple
StrategyLegs into a complete options strategy with risk/reward calculations.

StrategyComposition handles:
- Multi-leg strategy representation
- Net premium calculation
- Spread width computation (including asymmetric spreads)
- Max risk/profit calculations
- Conversion to order legs for execution
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.orders.spec import OrderLeg
from services.strategies.core.legs import StrategyLeg
from services.strategies.core.types import OptionType, PriceEffect

CONTRACT_MULTIPLIER = Decimal("100")


@dataclass(frozen=True)
class StrategyComposition:
    """
    A complete options strategy composed of multiple legs.

    This is the top-level strategy representation that combines legs
    and provides risk/reward calculations.

    Attributes:
        legs: Tuple of strategy legs (immutable)

    Example:
        >>> # Bull Put Spread: Sell higher strike, buy lower strike
        >>> short_put = StrategyLeg(contract=put_580, side=Side.SHORT, quantity=1)
        >>> long_put = StrategyLeg(contract=put_575, side=Side.LONG, quantity=1)
        >>> spread = StrategyComposition(legs=(short_put, long_put))
        >>> spread.max_spread_width()
        Decimal('5.00')
    """

    legs: tuple[StrategyLeg, ...]

    def __init__(self, legs: Sequence[StrategyLeg]):
        """
        Initialize with legs sequence, converting to immutable tuple.

        Args:
            legs: Sequence of StrategyLeg objects

        Raises:
            ValueError: If no legs provided or legs have mismatched underlyings
        """
        if not legs:
            raise ValueError("Strategy must have at least one leg")

        legs_tuple = tuple(legs)

        # Validate all legs have same underlying
        symbols = {leg.contract.symbol for leg in legs_tuple}
        if len(symbols) > 1:
            raise ValueError(f"All legs must have same underlying, got: {symbols}")

        # Use object.__setattr__ for frozen dataclass
        object.__setattr__(self, "legs", legs_tuple)

    @property
    def underlying(self) -> str:
        """Get the underlying symbol for this strategy."""
        return self.legs[0].contract.symbol

    @property
    def expiration(self) -> date:
        """
        Get the nearest expiration date.

        For calendar spreads with multiple expirations, returns the nearest.
        """
        return min(leg.contract.expiration for leg in self.legs)

    @property
    def expirations(self) -> set[date]:
        """Get all unique expiration dates in this strategy."""
        return {leg.contract.expiration for leg in self.legs}

    @property
    def leg_count(self) -> int:
        """Number of legs in the strategy."""
        return len(self.legs)

    @property
    def is_multi_expiration(self) -> bool:
        """Check if strategy spans multiple expirations (e.g., calendar spread)."""
        return len(self.expirations) > 1

    def net_premium(self, premiums: dict[str, Decimal]) -> Decimal:
        """
        Calculate net premium for the strategy.

        Args:
            premiums: Dict mapping OCC symbol to premium per contract

        Returns:
            Net premium (positive = credit, negative = debit)

        Example:
            >>> premiums = {
            ...     "SPY   250117P00580000": Decimal("3.00"),  # Short put
            ...     "SPY   250117P00575000": Decimal("2.00"),  # Long put
            ... }
            >>> spread.net_premium(premiums)
            Decimal('1.00')  # Net credit
        """
        total = Decimal("0")
        for leg in self.legs:
            premium = premiums.get(leg.occ_symbol, Decimal("0"))
            total += leg.premium_effect(premium)
        return total

    def price_effect(self, premiums: dict[str, Decimal]) -> PriceEffect:
        """
        Determine if strategy is a credit or debit.

        Args:
            premiums: Dict mapping OCC symbol to premium per contract

        Returns:
            PriceEffect.CREDIT or PriceEffect.DEBIT
        """
        net = self.net_premium(premiums)
        return PriceEffect.CREDIT if net >= 0 else PriceEffect.DEBIT

    def _get_legs_by_option_type(self) -> dict[OptionType, list[StrategyLeg]]:
        """Group legs by option type (CALL/PUT)."""
        grouped: dict[OptionType, list[StrategyLeg]] = {
            OptionType.CALL: [],
            OptionType.PUT: [],
        }
        for leg in self.legs:
            grouped[leg.contract.option_type].append(leg)
        return grouped

    def spread_widths(self) -> list[Decimal]:
        """
        Calculate width of each vertical spread component.

        For strategies with multiple spreads (Iron Condor, Trident),
        returns the width of each spread separately.

        Returns:
            List of spread widths (one per spread component)
        """
        widths = []
        grouped = self._get_legs_by_option_type()

        for _option_type, type_legs in grouped.items():
            if len(type_legs) >= 2:
                strikes = [leg.contract.strike for leg in type_legs]
                width = max(strikes) - min(strikes)
                if width > 0:
                    widths.append(width)

        return widths

    def max_spread_width(self) -> Decimal | None:
        """
        Get the largest spread width (for max risk calculation).

        For asymmetric strategies (e.g., $5 wide puts, $3 wide calls),
        returns the larger width since that determines worst-case loss.

        Returns:
            Largest spread width, or None if no spreads
        """
        widths = self.spread_widths()
        return max(widths) if widths else None

    def max_risk(self, net_premium: Decimal) -> Decimal:
        """
        Calculate maximum risk for the strategy.

        Formula depends on strategy type:
        - Credit spreads: (max_spread_width - net_credit) × 100
        - Debit spreads: net_debit × 100
        - Single leg: premium × 100 (for long) or theoretically unlimited (for short)

        Args:
            net_premium: Net premium (positive = credit, negative = debit)

        Returns:
            Maximum risk in dollars
        """
        width = self.max_spread_width()

        if width is not None:
            # Spread strategy
            if net_premium >= 0:
                # Credit spread: max loss = width - credit received
                return (width - net_premium) * CONTRACT_MULTIPLIER
            # Debit spread: max loss = debit paid
            return abs(net_premium) * CONTRACT_MULTIPLIER
        # Single leg or non-spread strategy
        if net_premium < 0:
            # Long option: max loss = premium paid
            return abs(net_premium) * CONTRACT_MULTIPLIER
        # Short naked option: theoretically unlimited
        # Return 0 as placeholder - requires margin/position limits
        return Decimal("0")

    def max_profit(self, net_premium: Decimal) -> Decimal:
        """
        Calculate maximum profit for the strategy.

        Formula depends on strategy type:
        - Credit spreads: net_credit × 100
        - Debit spreads: (max_spread_width - net_debit) × 100

        Args:
            net_premium: Net premium (positive = credit, negative = debit)

        Returns:
            Maximum profit in dollars
        """
        width = self.max_spread_width()

        if net_premium >= 0:
            # Credit strategy: max profit = credit received
            return net_premium * CONTRACT_MULTIPLIER
        # Debit strategy
        if width is not None:
            # Debit spread: max profit = width - debit
            return (width - abs(net_premium)) * CONTRACT_MULTIPLIER
        # Long option: theoretically unlimited
        # Return 0 as placeholder
        return Decimal("0")

    def to_order_legs(self, opening: bool = True) -> list[OrderLeg]:
        """
        Convert all strategy legs to order legs for execution.

        Args:
            opening: True for opening trades, False for closing

        Returns:
            List of OrderLeg objects ready for order construction
        """
        return [leg.to_order_leg(opening=opening) for leg in self.legs]

    def occ_symbols(self) -> list[str]:
        """
        Get all OCC symbols for streaming subscription.

        Returns:
            List of unique OCC symbols
        """
        return list({leg.occ_symbol for leg in self.legs})

    def closing_composition(self) -> "StrategyComposition":
        """
        Create the opposite composition for closing this strategy.

        Returns:
            New StrategyComposition with all legs reversed
        """
        return StrategyComposition(
            legs=tuple(leg.closing_leg() for leg in self.legs)
        )

    def long_legs(self) -> tuple[StrategyLeg, ...]:
        """Get all long (bought) legs."""
        return tuple(leg for leg in self.legs if leg.is_long)

    def short_legs(self) -> tuple[StrategyLeg, ...]:
        """Get all short (sold) legs."""
        return tuple(leg for leg in self.legs if leg.is_short)

    def put_legs(self) -> tuple[StrategyLeg, ...]:
        """Get all put legs."""
        return tuple(
            leg for leg in self.legs if leg.contract.option_type == OptionType.PUT
        )

    def call_legs(self) -> tuple[StrategyLeg, ...]:
        """Get all call legs."""
        return tuple(
            leg for leg in self.legs if leg.contract.option_type == OptionType.CALL
        )

    def total_quantity(self) -> int:
        """Get total quantity across all legs."""
        return sum(leg.quantity for leg in self.legs)

    def is_credit_strategy(self, premiums: dict[str, Decimal]) -> bool:
        """Check if this is a credit strategy (receives net premium)."""
        return self.net_premium(premiums) > 0

    def is_debit_strategy(self, premiums: dict[str, Decimal]) -> bool:
        """Check if this is a debit strategy (pays net premium)."""
        return self.net_premium(premiums) < 0
