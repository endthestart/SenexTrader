"""
Position risk calculation utilities.

This module handles position-specific risk calculations for different strategy types.
This is DIFFERENT from EnhancedRiskManager which handles account-level risk allocation
and buying power management.

The distinction:
- Position Risk (this module): "What's the max loss on this specific trade?"
- Account Risk (EnhancedRiskManager): "How much of my buying power am I willing to allocate?"
"""

from decimal import Decimal


class PositionRiskCalculator:
    """Calculates position-specific risk for different strategy types."""

    @staticmethod
    def calculate_senex_trident_risk(
        spread_width: int,
        put_credit: Decimal,
        call_credit: Decimal,
        put_quantity: int,
        call_quantity: int,
    ) -> Decimal:
        """
        Calculate maximum risk for Senex Trident position.

        Risk Formula: max(put_side_total, call_side_total) - total_credit

        This calculates the maximum potential loss of a Senex Trident position
        based on the spread parameters and credits received.

        Args:
            spread_width: Width of the spreads in dollars
            put_credit: Credit received per put spread
            call_credit: Credit received per call spread
            put_quantity: Number of put spreads (typically 2 for Trident)
            call_quantity: Number of call spreads (typically 1 for Trident)

        Returns:
            Decimal: Maximum risk amount in dollars
        """
        # Put side total risk (width * quantity * 100 shares per contract)
        put_side_total = Decimal(str(spread_width)) * Decimal(str(put_quantity)) * Decimal("100")

        # Call side total risk
        call_side_total = Decimal("0")
        if call_quantity > 0:
            call_side_total = (
                Decimal(str(spread_width)) * Decimal(str(call_quantity)) * Decimal("100")
            )

        # Total credit received (in dollars)
        total_credit = (put_credit * put_quantity + call_credit * call_quantity) * Decimal("100")

        # Senex Risk Formula: Max exposure minus credit received
        max_side = max(put_side_total, call_side_total)
        return max_side - total_credit

    @staticmethod
    def calculate_iron_condor_risk(
        put_spread_width: int, call_spread_width: int, total_credit: Decimal
    ) -> Decimal:
        """
        Calculate maximum risk for Senex Trident position.

        Senex Trident: 2 put spreads + 1 call spread (NOT an iron condor)

        Args:
            put_spread_width: Width of the put spread
            call_spread_width: Width of the call spread
            total_credit: Total credit received for the position

        Returns:
            Decimal: Maximum risk amount in dollars
        """
        # Senex Trident risk calculation
        # Put side: 2 spreads, Call side: 1 spread
        # Risk = max(put_width * 200, call_width * 100) - total_credit * 100
        max_width = max(put_spread_width, call_spread_width)
        return Decimal(str(max_width)) * Decimal("100") - total_credit * Decimal("100")

    @staticmethod
    def calculate_spread_risk(
        spread_width: int, credit_per_spread: Decimal, quantity: int
    ) -> Decimal:
        """
        Calculate risk for generic spread positions.

        This is a general-purpose calculator that can be used by strategies
        that use simple spread structures.

        Args:
            spread_width: Width of the spread in dollars
            credit_per_spread: Credit received per spread
            quantity: Number of spreads

        Returns:
            Decimal: Maximum risk amount in dollars
        """
        max_loss_per_spread = Decimal(str(spread_width)) * Decimal("100")
        total_credit = credit_per_spread * quantity * Decimal("100")
        total_max_loss = max_loss_per_spread * quantity

        return total_max_loss - total_credit
