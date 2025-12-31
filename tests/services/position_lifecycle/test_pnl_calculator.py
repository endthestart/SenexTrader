"""Tests for PnLCalculator - unified P&L calculator."""

from decimal import Decimal
from unittest.mock import MagicMock, Mock

from services.positions.lifecycle.pnl_calculator import PnLCalculator


class TestRealizedPnL:
    """Test suite for calculate_realized_pnl."""

    def test_credit_spread_profit(self):
        """Test realized P&L for profitable credit spread."""
        # Opened for $5.00 credit, closed for $2.50 debit
        # Profit = ($5.00 - $2.50) * 1 * 100 = $250
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("2.50"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("250.00")

    def test_credit_spread_loss(self):
        """Test realized P&L for losing credit spread."""
        # Opened for $5.00 credit, closed for $7.00 debit
        # Loss = ($5.00 - $7.00) * 1 * 100 = -$200
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("7.00"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("-200.00")

    def test_credit_spread_breakeven(self):
        """Test realized P&L at breakeven."""
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("5.00"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("0.00")

    def test_credit_spread_multiple_contracts(self):
        """Test realized P&L with multiple contracts."""
        # Profit = ($5.00 - $2.50) * 5 * 100 = $1250
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("2.50"),
            quantity=5,
            is_credit=True,
        )
        assert pnl == Decimal("1250.00")

    def test_debit_spread_profit(self):
        """Test realized P&L for profitable debit spread."""
        # Opened for $3.00 debit, closed for $5.00 credit
        # Profit = ($5.00 - $3.00) * 1 * 100 = $200
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("3.00"),
            closing_price=Decimal("5.00"),
            quantity=1,
            is_credit=False,
        )
        assert pnl == Decimal("200.00")

    def test_debit_spread_loss(self):
        """Test realized P&L for losing debit spread."""
        # Opened for $5.00 debit, closed for $3.00 credit
        # Loss = ($3.00 - $5.00) * 1 * 100 = -$200
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("3.00"),
            quantity=1,
            is_credit=False,
        )
        assert pnl == Decimal("-200.00")

    def test_decimal_precision(self):
        """Test that decimal precision is maintained."""
        pnl = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.13"),
            closing_price=Decimal("2.47"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("266.00")

    def test_negative_quantity_treated_as_positive(self):
        """Test that negative quantity is treated as positive to prevent sign flip."""
        # If caller passes negative quantity, it should still work correctly
        pnl_positive = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("2.50"),
            quantity=1,
            is_credit=True,
        )
        pnl_negative = PnLCalculator.calculate_realized_pnl(
            opening_price=Decimal("5.00"),
            closing_price=Decimal("2.50"),
            quantity=-1,
            is_credit=True,
        )
        # Both should produce the same profit (not sign-flipped)
        assert pnl_positive == Decimal("250.00")
        assert pnl_negative == Decimal("250.00")


class TestUnrealizedPnL:
    """Test suite for calculate_unrealized_pnl."""

    def test_credit_spread_profit(self):
        """Test unrealized P&L for open credit position with profit."""
        # Opened for $5.00, currently at $3.00
        # Unrealized = ($5.00 - $3.00) * 1 * 100 = $200
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("5.00"),
            current_mark=Decimal("3.00"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("200.00")

    def test_credit_spread_loss(self):
        """Test unrealized P&L for open credit position with loss."""
        # Opened for $5.00, currently at $6.00
        # Unrealized = ($5.00 - $6.00) * 1 * 100 = -$100
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("5.00"),
            current_mark=Decimal("6.00"),
            quantity=1,
            is_credit=True,
        )
        assert pnl == Decimal("-100.00")

    def test_zero_quantity(self):
        """Test unrealized P&L with zero quantity."""
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("5.00"),
            current_mark=Decimal("3.00"),
            quantity=0,
            is_credit=True,
        )
        assert pnl == Decimal("0.00")

    def test_multiple_contracts(self):
        """Test unrealized P&L with multiple contracts."""
        # Unrealized = ($5.00 - $3.00) * 3 * 100 = $600
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("5.00"),
            current_mark=Decimal("3.00"),
            quantity=3,
            is_credit=True,
        )
        assert pnl == Decimal("600.00")

    def test_debit_spread_profit(self):
        """Test unrealized P&L for profitable debit spread."""
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("3.00"),
            current_mark=Decimal("5.00"),
            quantity=1,
            is_credit=False,
        )
        assert pnl == Decimal("200.00")

    def test_debit_spread_loss(self):
        """Test unrealized P&L for losing debit spread."""
        pnl = PnLCalculator.calculate_unrealized_pnl(
            opening_price=Decimal("5.00"),
            current_mark=Decimal("3.00"),
            quantity=1,
            is_credit=False,
        )
        assert pnl == Decimal("-200.00")


class TestLegPnL:
    """Test suite for calculate_leg_pnl."""

    def test_short_profit(self):
        """Test leg P&L for short position with profit."""
        # Short: sold at $5, now at $3 = profit
        pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="short"
        )
        assert pnl == Decimal("200.00")

    def test_short_loss(self):
        """Test leg P&L for short position with loss."""
        pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0, current_price=7.0, quantity=1, quantity_direction="short"
        )
        assert pnl == Decimal("-200.00")

    def test_long_profit(self):
        """Test leg P&L for long position with profit."""
        # Long: bought at $3, now at $5 = profit
        pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=3.0, current_price=5.0, quantity=1, quantity_direction="long"
        )
        assert pnl == Decimal("200.00")

    def test_long_loss(self):
        """Test leg P&L for long position with loss."""
        pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=1, quantity_direction="long"
        )
        assert pnl == Decimal("-200.00")

    def test_negative_quantity_treated_as_short(self):
        """Test that negative quantity is treated as short position."""
        pnl = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0,
            current_price=3.0,
            quantity=-1,
            quantity_direction="long",  # Ignored when qty < 0
        )
        assert pnl == Decimal("200.00")

    def test_absolute_quantity_used(self):
        """Test that absolute value of quantity is used."""
        pnl_positive = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=2, quantity_direction="short"
        )
        pnl_negative = PnLCalculator.calculate_leg_pnl(
            avg_price=5.0, current_price=3.0, quantity=-2, quantity_direction="short"
        )
        assert pnl_positive == pnl_negative == Decimal("400.00")

    def test_case_insensitive_direction(self):
        """Test that direction is case-insensitive."""
        pnl_lower = PnLCalculator.calculate_leg_pnl(5.0, 3.0, 1, "short")
        pnl_upper = PnLCalculator.calculate_leg_pnl(5.0, 3.0, 1, "SHORT")
        pnl_mixed = PnLCalculator.calculate_leg_pnl(5.0, 3.0, 1, "Short")
        assert pnl_lower == pnl_upper == pnl_mixed == Decimal("200.00")

    def test_zero_price_difference(self):
        """Test leg P&L when price hasn't changed."""
        pnl = PnLCalculator.calculate_leg_pnl(5.0, 5.0, 1, "short")
        assert pnl == Decimal("0.00")

    def test_different_multiplier(self):
        """Test leg P&L with non-standard multiplier."""
        pnl = PnLCalculator.calculate_leg_pnl(5.0, 3.0, 1, "short", multiplier=10)
        assert pnl == Decimal("20.00")


class TestProfitTargetPnL:
    """Test suite for calculate_profit_target_pnl."""

    def test_credit_spread_profit_target(self):
        """Test P&L for credit spread profit target fill."""
        position = MagicMock()
        position.avg_price = Decimal("2.28")
        position.opening_price_effect = "Credit"

        pnl = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("1.14"),
            quantity=1,
        )
        # (2.28 - 1.14) * 1 * 100 = $114
        assert pnl == Decimal("114.00")

    def test_debit_spread_profit_target(self):
        """Test P&L for debit spread profit target fill."""
        position = MagicMock()
        position.avg_price = Decimal("3.00")
        position.opening_price_effect = "Debit"

        pnl = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("5.00"),
            quantity=1,
        )
        # (5.00 - 3.00) * 1 * 100 = $200
        assert pnl == Decimal("200.00")

    def test_none_close_price_returns_zero(self):
        """Test that None close_price returns zero."""
        position = MagicMock()
        position.avg_price = Decimal("2.28")

        pnl = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=None,
            quantity=1,
        )
        assert pnl == Decimal("0")

    def test_zero_quantity_returns_zero(self):
        """Test that zero quantity returns zero."""
        position = MagicMock()
        position.avg_price = Decimal("2.28")

        pnl = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("1.14"),
            quantity=0,
        )
        assert pnl == Decimal("0")

    def test_opening_price_overrides_avg_price(self):
        """Test that opening_price parameter overrides position.avg_price.

        This is critical for multi-spread positions like Senex Trident where
        each spread has a different original credit but position.avg_price
        is a blended average.

        Example: Senex Trident with:
        - Put spread 1: $2.50 credit
        - Put spread 2: $2.50 credit
        - Call spread: $1.75 credit
        - position.avg_price = $2.25 (blended)

        When put spread 1 closes at $1.45:
        - Without opening_price: P&L = (2.25 - 1.45) * 100 = $80 (WRONG)
        - With opening_price=$2.50: P&L = (2.50 - 1.45) * 100 = $105 (CORRECT)
        """
        position = MagicMock()
        position.avg_price = Decimal("2.25")  # Blended average
        position.opening_price_effect = "Credit"

        # Without opening_price - uses blended avg_price
        pnl_wrong = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("1.45"),
            quantity=1,
        )
        assert pnl_wrong == Decimal("80.00")  # (2.25 - 1.45) * 100

        # With opening_price - uses spread-specific credit
        pnl_correct = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("1.45"),
            quantity=1,
            opening_price=Decimal("2.50"),  # Spread-specific original_credit
        )
        assert pnl_correct == Decimal("105.00")  # (2.50 - 1.45) * 100

    def test_opening_price_with_call_spread(self):
        """Test opening_price for call spread with different credit than puts."""
        position = MagicMock()
        position.avg_price = Decimal("2.25")  # Blended average
        position.opening_price_effect = "Credit"

        # Call spread with $1.75 credit closes at $0.65
        pnl = PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=Decimal("0.65"),
            quantity=1,
            opening_price=Decimal("1.75"),
        )
        assert pnl == Decimal("110.00")  # (1.75 - 0.65) * 100


class TestTransactionPnL:
    """Test suite for calculate_from_transactions."""

    def test_credit_spread_profit(self):
        """Test P&L from transactions for profitable credit spread."""
        open_tx = MagicMock()
        open_tx.action = "Sell to Open"
        open_tx.net_value = Decimal("228.00")

        close_tx = MagicMock()
        close_tx.action = "Buy to Close"
        close_tx.net_value = Decimal("50.00")

        pnl = PnLCalculator.calculate_from_transactions([open_tx], [close_tx])
        # 228 - 50 = 178
        assert pnl == Decimal("178.00")

    def test_credit_spread_loss(self):
        """Test P&L from transactions for losing credit spread."""
        open_tx = MagicMock()
        open_tx.action = "Sell to Open"
        open_tx.net_value = Decimal("100.00")

        close_tx = MagicMock()
        close_tx.action = "Buy to Close"
        close_tx.net_value = Decimal("250.00")

        pnl = PnLCalculator.calculate_from_transactions([open_tx], [close_tx])
        # 100 - 250 = -150
        assert pnl == Decimal("-150.00")

    def test_bull_put_spread_two_legs(self):
        """Test P&L for bull put spread with both legs."""
        # Opening
        open_tx1 = MagicMock()
        open_tx1.action = "Sell to Open"
        open_tx1.net_value = Decimal("1471.00")

        open_tx2 = MagicMock()
        open_tx2.action = "Buy to Open"
        open_tx2.net_value = Decimal("1357.00")

        # Closing
        close_tx1 = MagicMock()
        close_tx1.action = "Buy to Close"
        close_tx1.net_value = Decimal("50.00")

        close_tx2 = MagicMock()
        close_tx2.action = "Sell to Close"
        close_tx2.net_value = Decimal("30.00")

        pnl = PnLCalculator.calculate_from_transactions(
            [open_tx1, open_tx2],
            [close_tx1, close_tx2]
        )
        # Opening: +1471 - 1357 = +114
        # Closing: -50 + 30 = -20
        # Total: +114 - 20 = +94
        assert pnl == Decimal("94.00")

    def test_expired_worthless(self):
        """Test P&L for position that expired worthless."""
        open_tx1 = MagicMock()
        open_tx1.action = "Sell to Open"
        open_tx1.net_value = Decimal("1471.00")

        open_tx2 = MagicMock()
        open_tx2.action = "Buy to Open"
        open_tx2.net_value = Decimal("1243.00")

        pnl = PnLCalculator.calculate_from_transactions([open_tx1, open_tx2], [])
        # Full credit kept: 1471 - 1243 = 228
        assert pnl == Decimal("228.00")

    def test_assignment_transaction(self):
        """Test P&L includes assignment transaction value."""
        open_tx = MagicMock()
        open_tx.action = "Sell to Open"
        open_tx.net_value = Decimal("500.00")

        assign_tx = MagicMock()
        assign_tx.action = "Assignment"
        assign_tx.net_value = Decimal("-100.00")

        pnl = PnLCalculator.calculate_from_transactions([open_tx], [assign_tx])
        # 500 + (-100) = 400
        assert pnl == Decimal("400.00")


class TestPortfolioPnL:
    """Test suite for calculate_portfolio_pnl."""

    def test_all_open_positions(self):
        """Test portfolio P&L with all open positions."""
        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=Decimal("50.00")),
            Mock(lifecycle_state="open_partial", unrealized_pnl=Decimal("25.00")),
            Mock(lifecycle_state="closing", unrealized_pnl=Decimal("-10.00")),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("65.00")
        assert result["net_pnl"] == Decimal("65.00")

    def test_all_closed_positions(self):
        """Test portfolio P&L with all closed positions."""
        positions = [
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("100.00")),
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("50.00")),
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("-25.00")),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("125.00")
        assert result["total_unrealized"] == Decimal("0")
        assert result["net_pnl"] == Decimal("125.00")

    def test_mixed_positions(self):
        """Test portfolio P&L with mixed open and closed positions."""
        positions = [
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("100.00")),
            Mock(lifecycle_state="open_full", unrealized_pnl=Decimal("50.00")),
            Mock(lifecycle_state="open_partial", unrealized_pnl=Decimal("-25.00")),
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("-10.00")),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("90.00")
        assert result["total_unrealized"] == Decimal("25.00")
        assert result["net_pnl"] == Decimal("115.00")

    def test_empty_list(self):
        """Test portfolio P&L with no positions."""
        result = PnLCalculator.calculate_portfolio_pnl([])

        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("0")
        assert result["net_pnl"] == Decimal("0")

    def test_none_values(self):
        """Test portfolio P&L handles None values gracefully."""
        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=None),
            Mock(lifecycle_state="closed", total_realized_pnl=None),
            Mock(lifecycle_state="open_partial", unrealized_pnl=Decimal("50.00")),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("0")
        assert result["total_unrealized"] == Decimal("50.00")
        assert result["net_pnl"] == Decimal("50.00")

    def test_decimal_precision(self):
        """Test portfolio P&L maintains decimal precision."""
        positions = [
            Mock(lifecycle_state="open_full", unrealized_pnl=Decimal("123.45")),
            Mock(lifecycle_state="closed", total_realized_pnl=Decimal("678.90")),
        ]

        result = PnLCalculator.calculate_portfolio_pnl(positions)

        assert result["total_realized"] == Decimal("678.90")
        assert result["total_unrealized"] == Decimal("123.45")
        assert result["net_pnl"] == Decimal("802.35")

