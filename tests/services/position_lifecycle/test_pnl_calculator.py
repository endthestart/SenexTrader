"""Tests for PositionPnLCalculator."""

from decimal import Decimal

from services.positions.lifecycle.pnl_calculator import PositionPnLCalculator


class TestPositionPnLCalculator:
    """Test suite for PositionPnLCalculator."""

    def test_calculate_realized_pnl_profit(self):
        """Test realized P&L calculation for profitable trade."""
        calc = PositionPnLCalculator()

        # Opened for $5.00 credit, closed for $2.50 debit
        # Profit = ($5.00 - $2.50) * 1 * 100 = $250
        pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("5.00"),
            closing_debit=Decimal("2.50"),
            quantity=1,
            multiplier=100,
        )

        assert pnl == Decimal("250.00")

    def test_calculate_realized_pnl_loss(self):
        """Test realized P&L for losing trade."""
        calc = PositionPnLCalculator()

        # Opened for $5.00 credit, closed for $7.00 debit
        # Loss = ($5.00 - $7.00) * 1 * 100 = -$200
        pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("5.00"),
            closing_debit=Decimal("7.00"),
            quantity=1,
            multiplier=100,
        )

        assert pnl == Decimal("-200.00")

    def test_calculate_realized_pnl_breakeven(self):
        """Test realized P&L at breakeven (no profit or loss)."""
        calc = PositionPnLCalculator()

        # Opened for $5.00 credit, closed for $5.00 debit
        # P&L = ($5.00 - $5.00) * 1 * 100 = $0
        pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("5.00"),
            closing_debit=Decimal("5.00"),
            quantity=1,
            multiplier=100,
        )

        assert pnl == Decimal("0.00")

    def test_calculate_realized_pnl_multiple_contracts(self):
        """Test realized P&L with multiple contracts."""
        calc = PositionPnLCalculator()

        # Opened for $5.00 credit, closed for $2.50 debit, 5 contracts
        # Profit = ($5.00 - $2.50) * 5 * 100 = $1250
        pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("5.00"),
            closing_debit=Decimal("2.50"),
            quantity=5,
            multiplier=100,
        )

        assert pnl == Decimal("1250.00")

    def test_calculate_realized_pnl_decimal_precision(self):
        """Test that decimal precision is maintained."""
        calc = PositionPnLCalculator()

        # Opened for $5.13 credit, closed for $2.47 debit
        # Profit = ($5.13 - $2.47) * 1 * 100 = $266.00
        pnl = calc.calculate_realized_pnl(
            opening_credit=Decimal("5.13"),
            closing_debit=Decimal("2.47"),
            quantity=1,
            multiplier=100,
        )

        assert pnl == Decimal("266.00")

    def test_calculate_unrealized_pnl_profit(self):
        """Test unrealized P&L for open position with profit."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $3.00
        # Unrealized = ($5.00 - $3.00) * 1 * 100 = $200
        pnl = calc.calculate_unrealized_pnl(
            opening_credit=Decimal("5.00"), current_mark=Decimal("3.00"), quantity=1, multiplier=100
        )

        assert pnl == Decimal("200.00")

    def test_calculate_unrealized_pnl_loss(self):
        """Test unrealized P&L for open position with loss."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $6.00
        # Unrealized = ($5.00 - $6.00) * 1 * 100 = -$100
        pnl = calc.calculate_unrealized_pnl(
            opening_credit=Decimal("5.00"), current_mark=Decimal("6.00"), quantity=1, multiplier=100
        )

        assert pnl == Decimal("-100.00")

    def test_calculate_unrealized_pnl_zero_quantity(self):
        """Test unrealized P&L with zero quantity."""
        calc = PositionPnLCalculator()

        # Zero quantity should result in $0 P&L
        pnl = calc.calculate_unrealized_pnl(
            opening_credit=Decimal("5.00"), current_mark=Decimal("3.00"), quantity=0, multiplier=100
        )

        assert pnl == Decimal("0.00")

    def test_calculate_unrealized_pnl_multiple_contracts(self):
        """Test unrealized P&L with multiple contracts."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $3.00, 3 contracts
        # Unrealized = ($5.00 - $3.00) * 3 * 100 = $600
        pnl = calc.calculate_unrealized_pnl(
            opening_credit=Decimal("5.00"), current_mark=Decimal("3.00"), quantity=3, multiplier=100
        )

        assert pnl == Decimal("600.00")

    def test_calculate_leg_pnl_short_profit(self):
        """Test leg P&L for short position with profit."""
        calc = PositionPnLCalculator()

        # Short position: sold at $5, now at $3 (profit)
        # P&L = (5 - 3) * 1 * 100 = $200
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="short", multiplier=100
        )

        assert pnl == Decimal("200.00")

    def test_calculate_leg_pnl_short_loss(self):
        """Test leg P&L for short position with loss."""
        calc = PositionPnLCalculator()

        # Short position: sold at $5, now at $7 (loss)
        # P&L = (5 - 7) * 1 * 100 = -$200
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=7.0, quantity=1, quantity_direction="short", multiplier=100
        )

        assert pnl == Decimal("-200.00")

    def test_calculate_leg_pnl_long_profit(self):
        """Test leg P&L for long position with profit."""
        calc = PositionPnLCalculator()

        # Long position: bought at $3, now at $5 (profit)
        # P&L = (5 - 3) * 1 * 100 = $200
        pnl = calc.calculate_leg_pnl(
            avg_price=3.0, current_price=5.0, quantity=1, quantity_direction="long", multiplier=100
        )

        assert pnl == Decimal("200.00")

    def test_calculate_leg_pnl_long_loss(self):
        """Test leg P&L for long position with loss."""
        calc = PositionPnLCalculator()

        # Long position: bought at $5, now at $3 (loss)
        # P&L = (3 - 5) * 1 * 100 = -$200
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="long", multiplier=100
        )

        assert pnl == Decimal("-200.00")

    def test_calculate_leg_pnl_negative_quantity_treated_as_short(self):
        """Test that negative quantity is treated as short position."""
        calc = PositionPnLCalculator()

        # Negative quantity should behave like short
        # Sold at $5, now at $3 (profit)
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0,
            current_price=3.0,
            quantity=-1,  # Negative quantity
            quantity_direction="long",  # Direction says long, but quantity is negative
            multiplier=100,
        )

        # Should use SHORT logic (quantity < 0)
        assert pnl == Decimal("200.00")

    def test_calculate_leg_pnl_absolute_quantity_used(self):
        """Test that absolute value of quantity is used."""
        calc = PositionPnLCalculator()

        # Both should give same result
        pnl_positive = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=2, quantity_direction="short", multiplier=100
        )

        pnl_negative = calc.calculate_leg_pnl(
            avg_price=5.0,
            current_price=3.0,
            quantity=-2,  # Negative but abs() used
            quantity_direction="short",
            multiplier=100,
        )

        assert pnl_positive == pnl_negative == Decimal("400.00")

    def test_calculate_leg_pnl_case_insensitive_direction(self):
        """Test that direction is case-insensitive."""
        calc = PositionPnLCalculator()

        pnl_lowercase = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="short", multiplier=100
        )

        pnl_uppercase = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="SHORT", multiplier=100
        )

        pnl_mixedcase = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="Short", multiplier=100
        )

        assert pnl_lowercase == pnl_uppercase == pnl_mixedcase == Decimal("200.00")

    def test_calculate_leg_pnl_zero_price_difference(self):
        """Test leg P&L when price hasn't changed."""
        calc = PositionPnLCalculator()

        # Price unchanged, should be $0 P&L
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0, current_price=5.0, quantity=1, quantity_direction="short", multiplier=100
        )

        assert pnl == Decimal("0.00")

    def test_calculate_leg_pnl_with_different_multiplier(self):
        """Test leg P&L with non-standard multiplier."""
        calc = PositionPnLCalculator()

        # Some index options have multiplier of 10
        pnl = calc.calculate_leg_pnl(
            avg_price=5.0,
            current_price=3.0,
            quantity=1,
            quantity_direction="short",
            multiplier=10,  # Non-standard multiplier
        )

        # (5 - 3) * 1 * 10 = $20
        assert pnl == Decimal("20.00")

    def test_realized_pnl_matches_leg_pnl_formula(self):
        """Test that realized P&L formula matches leg P&L for short positions."""
        calc = PositionPnLCalculator()

        opening_credit = Decimal("5.00")
        closing_debit = Decimal("2.50")

        realized = calc.calculate_realized_pnl(opening_credit, closing_debit, 1)

        # For short: avg_price is what we sold for (opening_credit)
        # current_price is what we bought back for (closing_debit)
        leg = calc.calculate_leg_pnl(float(opening_credit), float(closing_debit), 1, "short")

        assert realized == leg == Decimal("250.00")


class TestPositionPnLCalculatorExtended:
    """Test suite for extended PositionPnLCalculator methods (Task 3.3)."""

    def test_calculate_spread_pnl_credit_profit(self):
        """Test credit spread P&L calculation (profitable)."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $2.50
        # Profit = ($5.00 - $2.50) * 1 * 100 = $250
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("5.00"),
            current_mark=Decimal("2.50"),
            quantity=1,
            spread_width=Decimal("5.00"),
            is_credit_spread=True,
        )

        assert pnl == Decimal("250.00")

    def test_calculate_spread_pnl_credit_loss(self):
        """Test credit spread P&L calculation (loss)."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $7.00
        # Loss = ($5.00 - $7.00) * 1 * 100 = -$200
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("5.00"),
            current_mark=Decimal("7.00"),
            quantity=1,
            spread_width=Decimal("5.00"),
            is_credit_spread=True,
        )

        assert pnl == Decimal("-200.00")

    def test_calculate_spread_pnl_debit_profit(self):
        """Test debit spread P&L calculation (profitable)."""
        calc = PositionPnLCalculator()

        # Opened for $3.00, currently at $5.00
        # Profit = ($5.00 - $3.00) * 1 * 100 = $200
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("3.00"),
            current_mark=Decimal("5.00"),
            quantity=1,
            spread_width=Decimal("5.00"),
            is_credit_spread=False,
        )

        assert pnl == Decimal("200.00")

    def test_calculate_spread_pnl_debit_loss(self):
        """Test debit spread P&L calculation (loss)."""
        calc = PositionPnLCalculator()

        # Opened for $5.00, currently at $3.00
        # Loss = ($3.00 - $5.00) * 1 * 100 = -$200
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("5.00"),
            current_mark=Decimal("3.00"),
            quantity=1,
            spread_width=Decimal("5.00"),
            is_credit_spread=False,
        )

        assert pnl == Decimal("-200.00")

    def test_calculate_spread_pnl_multiple_contracts(self):
        """Test spread P&L with multiple contracts."""
        calc = PositionPnLCalculator()

        # Credit spread: $5.00 to $2.50, 3 contracts
        # Profit = ($5.00 - $2.50) * 3 * 100 = $750
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("5.00"),
            current_mark=Decimal("2.50"),
            quantity=3,
            spread_width=Decimal("5.00"),
            is_credit_spread=True,
        )

        assert pnl == Decimal("750.00")

    def test_calculate_spread_pnl_breakeven(self):
        """Test spread P&L at breakeven."""
        calc = PositionPnLCalculator()

        # Price unchanged
        pnl = calc.calculate_spread_pnl(
            opening_credit=Decimal("5.00"),
            current_mark=Decimal("5.00"),
            quantity=1,
            spread_width=Decimal("5.00"),
            is_credit_spread=True,
        )

        assert pnl == Decimal("0.00")

    def test_calculate_spread_pnl_matches_unrealized_pnl(self):
        """Test that spread P&L matches unrealized P&L for credit spreads."""
        calc = PositionPnLCalculator()

        opening_credit = Decimal("5.00")
        current_mark = Decimal("2.50")
        quantity = 1

        spread_pnl = calc.calculate_spread_pnl(
            opening_credit, current_mark, quantity, Decimal("5"), True
        )
        unrealized_pnl = calc.calculate_unrealized_pnl(opening_credit, current_mark, quantity)

        assert spread_pnl == unrealized_pnl == Decimal("250.00")

    def test_calculate_portfolio_pnl_all_open(self):
        """Test portfolio P&L with all open positions."""
        from unittest.mock import Mock

        calc = PositionPnLCalculator()

        positions = [
            Mock(
                lifecycle_state="open_full",
                unrealized_pnl=Decimal("50.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="open_partial",
                unrealized_pnl=Decimal("25.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closing",
                unrealized_pnl=Decimal("-10.00"),
                total_realized_pnl=Decimal("0"),
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("65.00")  # 50 + 25 - 10
        assert result["net_pnl"] == Decimal("65.00")

    def test_calculate_portfolio_pnl_all_closed(self):
        """Test portfolio P&L with all closed positions."""
        from unittest.mock import Mock

        calc = PositionPnLCalculator()

        positions = [
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("100.00"),
                unrealized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("50.00"),
                unrealized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("-25.00"),
                unrealized_pnl=Decimal("0"),
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("125.00")  # 100 + 50 - 25
        assert result["total_unrealized"] == Decimal("0")
        assert result["net_pnl"] == Decimal("125.00")

    def test_calculate_portfolio_pnl_mixed(self):
        """Test portfolio P&L with mixed open and closed positions."""
        from unittest.mock import Mock

        calc = PositionPnLCalculator()

        positions = [
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("100.00"),
                unrealized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="open_full",
                unrealized_pnl=Decimal("50.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="open_partial",
                unrealized_pnl=Decimal("-25.00"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("-10.00"),
                unrealized_pnl=Decimal("0"),
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("90.00")  # 100 - 10
        assert result["total_unrealized"] == Decimal("25.00")  # 50 - 25
        assert result["net_pnl"] == Decimal("115.00")  # 90 + 25

    def test_calculate_portfolio_pnl_empty_list(self):
        """Test portfolio P&L with no positions."""
        calc = PositionPnLCalculator()

        result = calc.calculate_portfolio_pnl([])

        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("0")
        assert result["net_pnl"] == Decimal("0")

    def test_calculate_portfolio_pnl_none_values(self):
        """Test portfolio P&L handles None values gracefully."""
        from unittest.mock import Mock

        calc = PositionPnLCalculator()

        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=None, total_realized_pnl=Decimal("0")),
            Mock(lifecycle_state="closed", total_realized_pnl=None, unrealized_pnl=Decimal("0")),
            Mock(
                lifecycle_state="open_partial",
                unrealized_pnl=Decimal("50.00"),
                total_realized_pnl=Decimal("0"),
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        # None values should be treated as 0
        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("50.00")
        assert result["net_pnl"] == Decimal("50.00")

    def test_calculate_portfolio_pnl_decimal_precision(self):
        """Test portfolio P&L maintains decimal precision."""
        from unittest.mock import Mock

        calc = PositionPnLCalculator()

        positions = [
            Mock(
                lifecycle_state="open_full",
                unrealized_pnl=Decimal("123.45"),
                total_realized_pnl=Decimal("0"),
            ),
            Mock(
                lifecycle_state="closed",
                total_realized_pnl=Decimal("678.90"),
                unrealized_pnl=Decimal("0"),
            ),
        ]

        result = calc.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("678.90")
        assert result["total_unrealized"] == Decimal("123.45")
        assert result["net_pnl"] == Decimal("802.35")
