"""Tests for ProfitTargetExit strategy."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.exit_strategies.profit_target import ProfitTargetExit


@pytest.mark.asyncio
class TestProfitTargetExit:
    """Test ProfitTargetExit strategy."""

    async def test_profit_target_reached(self):
        """Test exit when profit target is reached."""
        # Create strategy with 50% profit target
        strategy = ProfitTargetExit(target_percentage=50.0)

        # Create mock position with profit at target
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")  # $25 profit
        position.initial_risk = Decimal("50.00")  # $50 credit received

        # Evaluate
        result = await strategy.evaluate(position)

        # Should trigger exit (25/50 = 50%)
        assert result.should_exit is True
        assert "Profit target reached" in result.reason
        assert result.metadata["current_pnl"] == 25.0
        assert result.metadata["profit_target"] == 25.0
        assert result.metadata["target_percentage"] == 50.0
        assert result.metadata["profit_pct_achieved"] == 50.0

    async def test_profit_target_exceeded(self):
        """Test exit when profit exceeds target."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("30.00")  # $30 profit
        position.initial_risk = Decimal("50.00")  # $50 credit

        result = await strategy.evaluate(position)

        # Should trigger exit (30/50 = 60% > 50%)
        assert result.should_exit is True
        assert "Profit target reached" in result.reason
        assert result.metadata["profit_pct_achieved"] == 60.0

    async def test_profit_target_not_reached(self):
        """Test no exit when profit below target."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("20.00")  # $20 profit
        position.initial_risk = Decimal("50.00")  # $50 credit

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (20/50 = 40% < 50%)
        assert result.should_exit is False
        assert "Profit target not reached" in result.reason
        assert result.metadata["profit_pct_achieved"] == 40.0

    async def test_no_unrealized_pnl(self):
        """Test handling when unrealized_pnl is None."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = None
        position.initial_risk = Decimal("50.00")

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "No P&L data available" in result.reason

    async def test_no_initial_risk(self):
        """Test handling when initial_risk is None."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")
        position.initial_risk = None

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "No initial risk data available" in result.reason

    async def test_zero_initial_risk(self):
        """Test handling when initial_risk is zero."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")
        position.initial_risk = Decimal("0.00")

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "No initial risk data available" in result.reason

    async def test_negative_pnl(self):
        """Test handling when position is at a loss."""
        strategy = ProfitTargetExit(target_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-10.00")  # $10 loss
        position.initial_risk = Decimal("50.00")

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (negative profit)
        assert result.should_exit is False
        assert result.metadata["profit_pct_achieved"] == -20.0

    async def test_custom_target_percentage(self):
        """Test with custom profit target percentage."""
        # 75% profit target
        strategy = ProfitTargetExit(target_percentage=75.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("37.50")  # $37.50 profit
        position.initial_risk = Decimal("50.00")  # $50 credit

        result = await strategy.evaluate(position)

        # Should trigger exit (37.5/50 = 75%)
        assert result.should_exit is True
        assert result.metadata["target_percentage"] == 75.0
        assert result.metadata["profit_target"] == 37.5

    def test_invalid_target_percentage(self):
        """Test validation of target_percentage parameter."""
        # Zero percentage
        with pytest.raises(ValueError, match="must be positive"):
            ProfitTargetExit(target_percentage=0.0)

        # Negative percentage
        with pytest.raises(ValueError, match="must be positive"):
            ProfitTargetExit(target_percentage=-10.0)

    def test_get_name(self):
        """Test human-readable name generation."""
        strategy = ProfitTargetExit(target_percentage=50.0)
        assert strategy.get_name() == "50% Profit Target"

        strategy = ProfitTargetExit(target_percentage=75.5)
        assert strategy.get_name() == "75.5% Profit Target"
