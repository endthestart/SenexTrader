"""Integration tests for refactored position sync.

These tests verify that the refactored position sync maintains
the same behavior as before, ensuring P&L calculations are accurate.
"""

from decimal import Decimal

import pytest

from services.positions.lifecycle.leg_matcher import LegMatcher
from services.positions.lifecycle.pnl_calculator import PositionPnLCalculator
from services.positions.sync import PositionSyncService


class TestPositionSyncRefactored:
    """Test refactored position sync behavior."""

    def test_pnl_calculator_integration(self):
        """Verify P&L calculator produces expected results for real scenarios."""
        calc = PositionPnLCalculator()

        # Scenario 1: Bear put spread - opened for $2.50, now at $1.25
        realized_pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("2.50"),
            closing_debit=Decimal("1.25"),
            quantity=1,
            multiplier=100,
        )
        # Expected: ($2.50 - $1.25) * 1 * 100 = $125
        assert realized_pnl == Decimal("125.00")

        # Scenario 2: Unrealized - opened for $5.00, currently at $3.50
        unrealized_pnl = calc.calculate_unrealized_pnl(
            opening_credit=Decimal("5.00"), current_mark=Decimal("3.50"), quantity=1, multiplier=100
        )
        # Expected: ($5.00 - $3.50) * 1 * 100 = $150
        assert unrealized_pnl == Decimal("150.00")

    def test_leg_matcher_integration(self):
        """Verify leg matcher correctly matches option symbols."""
        # Simulate real TastyTrade position data
        raw_position_data = {
            "QQQ   251107P00594000": {
                "symbol": "QQQ   251107P00594000",
                "quantity": -1,
                "quantity_direction": "short",
                "average_open_price": 5.50,
                "mark_price": 3.25,
                "close_price": 3.20,
                "multiplier": 100,
                "instrument_type": "Equity Option",
            },
            "QQQ   251107P00589000": {
                "symbol": "QQQ   251107P00589000",
                "quantity": 1,
                "quantity_direction": "long",
                "average_open_price": 3.00,
                "mark_price": 1.75,
                "close_price": 1.70,
                "multiplier": 100,
                "instrument_type": "Equity Option",
            },
        }

        matcher = LegMatcher(raw_position_data)

        # Test matching both legs of a spread
        symbols = ["QQQ   251107P00594000", "QQQ   251107P00589000"]
        matched = matcher.match_legs(symbols)

        assert len(matched) == 2
        assert matched[0]["symbol"] == "QQQ   251107P00594000"
        assert matched[0]["mark_price"] == 3.25
        assert matched[1]["symbol"] == "QQQ   251107P00589000"
        assert matched[1]["mark_price"] == 1.75

    def test_combined_pnl_calculation_for_spread(self):
        """Test calculating total P&L for a multi-leg spread."""
        calc = PositionPnLCalculator()

        # Bear put spread:
        # - Short 594 put at $5.50, now $3.25 (profit)
        # - Long 589 put at $3.00, now $1.75 (profit)

        short_pnl = calc.calculate_leg_pnl(
            avg_price=5.50,
            current_price=3.25,
            quantity=1,
            quantity_direction="short",
            multiplier=100,
        )
        # Short: (5.50 - 3.25) * 1 * 100 = $225

        long_pnl = calc.calculate_leg_pnl(
            avg_price=3.00,
            current_price=1.75,
            quantity=1,
            quantity_direction="long",
            multiplier=100,
        )
        # Long: (1.75 - 3.00) * 1 * 100 = -$125

        total_pnl = short_pnl + long_pnl
        # Total: $225 - $125 = $100

        assert short_pnl == Decimal("225.00")
        assert long_pnl == Decimal("-125.00")
        assert total_pnl == Decimal("100.00")

    def test_pnl_matches_tastytrade_formula(self):
        """
        Verify our P&L calculation matches TastyTrade's formula.

        TastyTrade P&L for spreads:
        - Unrealized P&L = (Opening Credit - Current Mark) * Quantity * Multiplier
        """
        calc = PositionPnLCalculator()

        # Real example: Opened spread for $2.80 credit, currently at $1.50
        opening_credit = Decimal("2.80")
        current_mark = Decimal("1.50")
        quantity = 1

        our_pnl = calc.calculate_unrealized_pnl(opening_credit, current_mark, quantity)

        # TastyTrade formula: (2.80 - 1.50) * 1 * 100 = $130
        expected_pnl = (opening_credit - current_mark) * quantity * 100

        assert our_pnl == expected_pnl == Decimal("130.00")

    def test_position_sync_service_uses_utilities(self):
        """Verify PositionSyncService can be instantiated with new utilities."""
        # This test verifies imports and initialization work correctly
        service = PositionSyncService()

        # The service should be able to create utility instances
        legs_map = {"QQQ   251107P00594000": {"mark_price": 5.50}}
        matcher = LegMatcher(legs_map)
        calc = PositionPnLCalculator()

        assert matcher is not None
        assert calc is not None
        assert service is not None

    def test_leg_pnl_calculation_accuracy(self):
        """Test leg P&L calculation precision for various scenarios."""
        calc = PositionPnLCalculator()

        # Scenario 1: Small price movement
        pnl = calc.calculate_leg_pnl(
            avg_price=5.13,
            current_price=5.01,
            quantity=1,
            quantity_direction="short",
            multiplier=100,
        )
        # Short: (5.13 - 5.01) * 1 * 100 = $12
        # Use quantize to handle floating point precision
        assert pnl.quantize(Decimal("0.01")) == Decimal("12.00")

        # Scenario 2: Large position
        pnl = calc.calculate_leg_pnl(
            avg_price=10.00,
            current_price=8.00,
            quantity=5,
            quantity_direction="short",
            multiplier=100,
        )
        # Short: (10.00 - 8.00) * 5 * 100 = $1000
        assert pnl == Decimal("1000.00")

    def test_missing_leg_handling(self):
        """Test that missing legs are handled gracefully."""
        legs_map = {"QQQ   251107P00594000": {"mark_price": 5.50}}
        matcher = LegMatcher(legs_map)

        # Try to match a leg that doesn't exist
        symbols = ["QQQ   251107P00594000", "QQQ   251107P00999000"]
        matched = matcher.match_legs(symbols)

        # Should only match the existing leg
        assert len(matched) == 1
        assert matched[0] is not None

        # Check missing leg detection
        missing = matcher.get_missing_legs(symbols)
        assert len(missing) == 1
        assert "QQQ   251107P00999000" in missing


@pytest.mark.integration
class TestRealWorldScenarios:
    """Test real-world position sync scenarios."""

    def test_senex_trident_pnl_calculation(self):
        """Test P&L calculation for Senex Trident strategy (2 put spreads + 1 call spread)."""
        calc = PositionPnLCalculator()

        # Senex Trident:
        # - Put spread 1: Opened $2.50, now $1.50
        # - Put spread 2: Opened $2.50, now $1.50
        # - Call spread: Opened $0.75, now $0.50

        put1_pnl = calc.calculate_unrealized_pnl(Decimal("2.50"), Decimal("1.50"), 1)
        put2_pnl = calc.calculate_unrealized_pnl(Decimal("2.50"), Decimal("1.50"), 1)
        call_pnl = calc.calculate_unrealized_pnl(Decimal("0.75"), Decimal("0.50"), 1)

        total_pnl = put1_pnl + put2_pnl + call_pnl

        assert put1_pnl == Decimal("100.00")
        assert put2_pnl == Decimal("100.00")
        assert call_pnl == Decimal("25.00")
        assert total_pnl == Decimal("225.00")
