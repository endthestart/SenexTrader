"""Integration tests for P&L calculation consistency across services.

This module verifies that P&L calculations produce identical results whether
calculated via:
- PositionPnLCalculator direct calls
- Position sync service calculations
- Individual leg calculations

Task 3.3: Extract P&L Calculation Utilities
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.positions.lifecycle.pnl_calculator import PositionPnLCalculator


@pytest.mark.integration
class TestPnLCalculationConsistency:
    """Test P&L calculations are consistent across all services."""

    def test_spread_pnl_matches_unrealized_pnl_credit(self):
        """Verify calculate_spread_pnl matches calculate_unrealized_pnl for credit spreads."""
        calc = PositionPnLCalculator()

        opening_credit = Decimal("5.00")
        current_mark = Decimal("2.50")
        quantity = 2

        # Calculate using both methods
        spread_pnl = calc.calculate_spread_pnl(
            opening_credit=opening_credit,
            current_mark=current_mark,
            quantity=quantity,
            spread_width=Decimal("5.00"),
            is_credit_spread=True,
        )

        unrealized_pnl = calc.calculate_unrealized_pnl(
            opening_credit=opening_credit, current_mark=current_mark, quantity=quantity
        )

        # Should be identical
        assert spread_pnl == unrealized_pnl
        assert spread_pnl == Decimal("500.00")  # (5 - 2.5) * 2 * 100

    def test_spread_pnl_matches_unrealized_pnl_debit(self):
        """Verify calculate_spread_pnl matches for debit spreads."""
        calc = PositionPnLCalculator()

        opening_debit = Decimal("3.00")
        current_mark = Decimal("5.00")
        quantity = 1

        # Debit spread: profit when mark goes UP
        spread_pnl = calc.calculate_spread_pnl(
            opening_credit=opening_debit,  # For debit, this is the debit paid
            current_mark=current_mark,
            quantity=quantity,
            spread_width=Decimal("5.00"),
            is_credit_spread=False,
        )

        # For debit: P&L = (current - opening) * qty * 100
        expected = (current_mark - opening_debit) * Decimal(quantity) * Decimal("100")

        assert spread_pnl == expected
        assert spread_pnl == Decimal("200.00")

    def test_leg_pnl_consistency_short_position(self):
        """Verify leg P&L calculation for short positions is consistent."""
        calc = PositionPnLCalculator()

        avg_price = 5.00
        current_price = 3.00
        quantity = 1

        # Calculate using leg_pnl
        leg_pnl = calc.calculate_leg_pnl(
            avg_price=avg_price,
            current_price=current_price,
            quantity=quantity,
            quantity_direction="short",
            multiplier=100,
        )

        # Calculate using unrealized_pnl (for short positions)
        unrealized = calc.calculate_unrealized_pnl(
            opening_credit=Decimal(str(avg_price)),
            current_mark=Decimal(str(current_price)),
            quantity=quantity,
            multiplier=100,
        )

        # Should match
        assert leg_pnl == unrealized
        assert leg_pnl == Decimal("200.00")

    def test_leg_pnl_consistency_long_position(self):
        """Verify leg P&L calculation for long positions is consistent."""
        calc = PositionPnLCalculator()

        avg_price = 3.00
        current_price = 5.00
        quantity = 1

        # Calculate using leg_pnl (long)
        leg_pnl = calc.calculate_leg_pnl(
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
        calc = PositionPnLCalculator()

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

        result = calc.calculate_portfolio_pnl(positions)

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
        calc = PositionPnLCalculator()

        opening_credit = Decimal("5.00")
        closing_debit = Decimal("2.50")
        quantity = 1

        # Calculate realized P&L (position closed)
        realized = calc.calculate_realized_pnl(
            opening_credit=opening_credit, closing_debit=closing_debit, quantity=quantity
        )

        # Calculate using leg P&L (short position)
        leg = calc.calculate_leg_pnl(
            avg_price=float(opening_credit),
            current_price=float(closing_debit),
            quantity=quantity,
            quantity_direction="short",
        )

        # Should be identical
        assert realized == leg
        assert realized == Decimal("250.00")

    def test_pnl_precision_consistency(self):
        """Verify P&L calculations maintain decimal precision consistently."""
        calc = PositionPnLCalculator()

        # Use prices with high precision
        opening = Decimal("5.1234")
        closing = Decimal("2.4567")
        quantity = 3

        realized = calc.calculate_realized_pnl(opening, closing, quantity)
        unrealized = calc.calculate_unrealized_pnl(opening, closing, quantity)

        # Both should produce the same result
        assert realized == unrealized

        # Verify precision is maintained (not rounded prematurely)
        expected = (opening - closing) * Decimal(quantity) * Decimal("100")
        assert realized == expected

    def test_zero_quantity_consistency(self):
        """Verify all P&L methods handle zero quantity consistently."""
        calc = PositionPnLCalculator()

        opening = Decimal("5.00")
        closing = Decimal("2.50")
        quantity = 0

        # All should return $0
        realized = calc.calculate_realized_pnl(opening, closing, quantity)
        unrealized = calc.calculate_unrealized_pnl(opening, closing, quantity)
        spread = calc.calculate_spread_pnl(opening, closing, quantity, Decimal("5"), True)

        assert realized == Decimal("0.00")
        assert unrealized == Decimal("0.00")
        assert spread == Decimal("0.00")

    def test_negative_pnl_consistency(self):
        """Verify losses are calculated consistently across all methods."""
        calc = PositionPnLCalculator()

        # Losing trade: opened for $5, currently at $7 (loss)
        opening = Decimal("5.00")
        current = Decimal("7.00")
        quantity = 1

        realized = calc.calculate_realized_pnl(opening, current, quantity)
        unrealized = calc.calculate_unrealized_pnl(opening, current, quantity)
        spread = calc.calculate_spread_pnl(opening, current, quantity, Decimal("5"), True)

        # All should show same loss
        assert realized == unrealized == spread
        assert realized == Decimal("-200.00")  # Negative = loss

    def test_multi_contract_consistency(self):
        """Verify P&L scales correctly with quantity across all methods."""
        calc = PositionPnLCalculator()

        opening = Decimal("5.00")
        current = Decimal("3.00")

        # Test with different quantities
        for quantity in [1, 2, 5, 10]:
            realized = calc.calculate_realized_pnl(opening, current, quantity)
            unrealized = calc.calculate_unrealized_pnl(opening, current, quantity)
            spread = calc.calculate_spread_pnl(opening, current, quantity, Decimal("5"), True)

            expected = Decimal("200.00") * Decimal(quantity)  # Base profit * quantity

            assert realized == expected
            assert unrealized == expected
            assert spread == expected


@pytest.mark.integration
class TestPnLEdgeCases:
    """Test edge cases in P&L calculations."""

    def test_none_values_handled_in_portfolio(self):
        """Verify portfolio calculation handles None values gracefully."""
        calc = PositionPnLCalculator()

        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=None, total_realized_pnl=None),
            Mock(
                lifecycle_state="closed", total_realized_pnl=Decimal("100.00"), unrealized_pnl=None
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        # None should be treated as 0
        assert result["total_unrealized"] == Decimal("0")
        assert result["total_realized"] == Decimal("100.00")
        assert result["net_pnl"] == Decimal("100.00")

    def test_very_small_prices(self):
        """Verify P&L calculations work with very small prices (penny stocks/options)."""
        calc = PositionPnLCalculator()

        opening = Decimal("0.05")
        current = Decimal("0.03")
        quantity = 100  # Many contracts

        pnl = calc.calculate_unrealized_pnl(opening, current, quantity)

        # (0.05 - 0.03) * 100 * 100 = $200
        assert pnl == Decimal("200.00")

    def test_very_large_prices(self):
        """Verify P&L calculations work with very large prices (index options)."""
        calc = PositionPnLCalculator()

        opening = Decimal("5000.00")
        current = Decimal("4500.00")
        quantity = 1

        pnl = calc.calculate_unrealized_pnl(opening, current, quantity)

        # (5000 - 4500) * 1 * 100 = $50,000
        assert pnl == Decimal("50000.00")
