"""Integration tests for P&L calculation consistency across services.

This module verifies that P&L calculations produce identical results whether
calculated via:
- PnLCalculator direct calls
- Position sync service calculations
- Individual leg calculations
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.positions.lifecycle.pnl_calculator import PnLCalculator


@pytest.mark.integration
class TestPnLCalculationConsistency:
    """Test P&L calculations are consistent across all services."""

    def test_unrealized_pnl_credit_spread(self):
        """Verify calculate_unrealized_pnl for credit spreads."""
        opening_price = Decimal("5.00")
        current_mark = Decimal("2.50")
        quantity = 2

        unrealized_pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening_price,
            current_mark=current_mark,
            quantity=quantity,
            is_credit=True,
        )

        assert unrealized_pnl == Decimal("500.00")  # (5 - 2.5) * 2 * 100

    def test_unrealized_pnl_debit_spread(self):
        """Verify calculate_unrealized_pnl for debit spreads."""
        opening_price = Decimal("3.00")
        current_mark = Decimal("5.00")
        quantity = 1

        # Debit spread: profit when mark goes UP
        unrealized_pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening_price,
            current_mark=current_mark,
            quantity=quantity,
            is_credit=False,
        )

        # For debit: P&L = (current - opening) * qty * 100
        assert unrealized_pnl == Decimal("200.00")

    def test_leg_pnl_consistency_short_position(self):
        """Verify leg P&L calculation for short positions is consistent."""
        avg_price = 5.00
        current_price = 3.00
        quantity = 1

        # Calculate using leg_pnl
        leg_pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=avg_price,
            current_price=current_price,
            quantity=quantity,
            quantity_direction="short",
            multiplier=100,
        )

        # Calculate using unrealized_pnl (for credit/short positions)
        unrealized = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal(str(avg_price)),
            current_mark=Decimal(str(current_price)),
            quantity=quantity,
            is_credit=True,
        )

        # Should match
        assert leg_pnl == unrealized
        assert leg_pnl == Decimal("200.00")

    def test_leg_pnl_consistency_long_position(self):
        """Verify leg P&L calculation for long positions is consistent."""
        avg_price = 3.00
        current_price = 5.00
        quantity = 1

        # Calculate using leg_pnl (long)
        leg_pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=avg_price,
            current_price=current_price,
            quantity=quantity,
            quantity_direction="long",
            multiplier=100,
        )

        # For long: P&L = (current - avg) * qty * multiplier
        expected = Decimal(str((current_price - avg_price) * quantity * 100))

        assert leg_pnl == expected
        assert leg_pnl == Decimal("200.00")

    def test_portfolio_pnl_aggregation_accuracy(self):
        """Verify portfolio P&L correctly aggregates individual positions."""
        # Create mock positions with known P&L values
        positions = [
            Mock(
                lifecycle_state="open_full",
                unrealized_pnl=Decimal("100.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="open_partial",
                unrealized_pnl=Decimal("50.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("200.00"),
                unrealized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("-25.00"),
                unrealized_pnl=Decimal("0"),
            ),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        # Verify individual components
        assert result["total_unrealized"] == Decimal("150.00")  # 100 + 50
        assert result["total_realized"] == Decimal("175.00")  # 200 - 25
        assert result["net_pnl"] == Decimal("325.00")  # 150 + 175

        # Verify manual calculation matches
        manual_unrealized = sum(
            p.unrealized_pnl
            for p in positions
            if p.lifecycle_state in ["open_full", "open_partial", "closing"]
        )
        manual_realized = sum(
            p.total_realized_pnl for p in positions if p.lifecycle_state == "closed"
        )

        assert result["total_unrealized"] == manual_unrealized
        assert result["total_realized"] == manual_realized

    def test_realized_pnl_matches_leg_pnl_for_closed_position(self):
        """Verify realized P&L formula matches leg P&L for closed short positions."""
        opening_price = Decimal("5.00")
        closing_price = Decimal("2.50")
        quantity = 1

        # Calculate realized P&L (position closed)
        realized = PnLCalculator.calculate_realized_pnl(
            opening_price=opening_price,
            closing_price=closing_price,
            quantity=quantity,
            is_credit=True,
        )

        # Calculate using leg P&L (short position)
        leg = PnLCalculator.calculate_leg_pnl(
            avg_price=float(opening_price),
            current_price=float(closing_price),
            quantity=quantity,
            quantity_direction="short",
        )

        # Should be identical
        assert realized == leg
        assert realized == Decimal("250.00")

    def test_pnl_precision_consistency(self):
        """Verify P&L calculations maintain decimal precision consistently."""
        # Use prices with high precision
        opening = Decimal("5.1234")
        closing = Decimal("2.4567")
        quantity = 3

        realized = PnLCalculator.calculate_realized_pnl(
            opening_price=opening,
            closing_price=closing,
            quantity=quantity,
            is_credit=True,
        )
        unrealized = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening,
            current_mark=closing,
            quantity=quantity,
            is_credit=True,
        )

        # Both should produce the same result
        assert realized == unrealized

    def test_zero_quantity_consistency(self):
        """Verify all P&L methods handle zero quantity consistently."""
        opening = Decimal("5.00")
        closing = Decimal("2.50")
        quantity = 0

        # All should return $0
        realized = PnLCalculator.calculate_realized_pnl(
            opening_price=opening,
            closing_price=closing,
            quantity=quantity,
            is_credit=True,
        )
        unrealized = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening,
            current_mark=closing,
            quantity=quantity,
            is_credit=True,
        )

        assert realized == Decimal("0.00")
        assert unrealized == Decimal("0.00")

    def test_negative_pnl_consistency(self):
        """Verify losses are calculated consistently across all methods."""
        # Losing trade: opened for $5, currently at $7 (loss)
        opening = Decimal("5.00")
        current = Decimal("7.00")
        quantity = 1

        realized = PnLCalculator.calculate_realized_pnl(
            opening_price=opening,
            closing_price=current,
            quantity=quantity,
            is_credit=True,
        )
        unrealized = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening,
            current_mark=current,
            quantity=quantity,
            is_credit=True,
        )

        # All should show same loss
        assert realized == unrealized
        assert realized == Decimal("-200.00")  # Negative = loss

    def test_multi_contract_consistency(self):
        """Verify P&L scales correctly with quantity across all methods."""
        opening = Decimal("5.00")
        current = Decimal("3.00")

        # Test with different quantities
        for quantity in [1, 2, 5, 10]:
            realized = PnLCalculator.calculate_realized_pnl(
                opening_price=opening,
                closing_price=current,
                quantity=quantity,
                is_credit=True,
            )
            unrealized = PnLCalculator.calculate_unrealized_pnl(
                opening_price=opening,
                current_mark=current,
                quantity=quantity,
                is_credit=True,
            )

            expected = Decimal("200.00") * Decimal(quantity)  # Base profit * quantity

            assert realized == expected
            assert unrealized == expected


@pytest.mark.integration
class TestPnLEdgeCases:
    """Test edge cases in P&L calculations."""

    def test_none_values_handled_in_portfolio(self):
        """Verify portfolio calculation handles None values gracefully."""
        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=None, total_realized_pnl=None),
            Mock(
                lifecycle_state="closed", total_realized_pnl=Decimal("100.00"), unrealized_pnl=None
            ),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        # None should be treated as 0
        assert result["total_unrealized"] == Decimal("0")
        assert result["total_realized"] == Decimal("100.00")
        assert result["net_pnl"] == Decimal("100.00")

    def test_very_small_prices(self):
        """Verify P&L calculations work with very small prices (penny stocks/options)."""
        opening = Decimal("0.05")
        current = Decimal("0.03")
        quantity = 100  # Many contracts

        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening,
            current_mark=current,
            quantity=quantity,
            is_credit=True,
        )

        # (0.05 - 0.03) * 100 * 100 = $200
        assert pnl == Decimal("200.00")

    def test_very_large_prices(self):
        """Verify P&L calculations work with very large prices (index options)."""
        opening = Decimal("5000.00")
        current = Decimal("4500.00")
        quantity = 1

        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=opening,
            current_mark=current,
            quantity=quantity,
            is_credit=True,
        )

        # (5000 - 4500) * 1 * 100 = $50,000
        assert pnl == Decimal("50000.00")
