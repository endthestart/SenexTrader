"""Tests for StopLossExit strategy."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.exit_strategies.stop_loss import StopLossExit


@pytest.mark.asyncio
class TestStopLossExit:
    """Test StopLossExit strategy."""

    async def test_stop_loss_triggered_at_max(self):
        """Test exit when loss exactly at max threshold."""
        # Create strategy with 100% stop loss
        strategy = StopLossExit(max_loss_percentage=100.0)

        # Create mock position with loss at max
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-50.00")  # $50 loss
        position.initial_risk = Decimal("50.00")  # $50 max risk

        # Evaluate
        result = await strategy.evaluate(position)

        # Should trigger exit (-50/50 = -100%)
        assert result.should_exit is True
        assert "Stop loss triggered" in result.reason
        assert result.metadata["current_pnl"] == -50.0
        assert result.metadata["stop_loss_threshold"] == -50.0
        assert result.metadata["max_loss_percentage"] == 100.0
        assert result.metadata["loss_pct"] == -100.0

    async def test_stop_loss_exceeded(self):
        """Test exit when loss exceeds threshold."""
        strategy = StopLossExit(max_loss_percentage=100.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-60.00")  # $60 loss (worse than max)
        position.initial_risk = Decimal("50.00")  # $50 max risk

        result = await strategy.evaluate(position)

        # Should trigger exit (-60 < -50)
        assert result.should_exit is True
        assert "Stop loss triggered" in result.reason
        assert result.metadata["loss_pct"] == -120.0

    async def test_stop_loss_not_triggered(self):
        """Test no exit when loss below threshold."""
        strategy = StopLossExit(max_loss_percentage=100.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-25.00")  # $25 loss
        position.initial_risk = Decimal("50.00")  # $50 max risk

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (-25/50 = -50% > -100%)
        assert result.should_exit is False
        assert "Stop loss not triggered" in result.reason
        assert result.metadata["loss_pct"] == -50.0

    async def test_stop_loss_with_profit(self):
        """Test no exit when position is profitable."""
        strategy = StopLossExit(max_loss_percentage=100.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")  # $25 profit
        position.initial_risk = Decimal("50.00")

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (positive P&L)
        assert result.should_exit is False
        assert result.metadata["loss_pct"] == 50.0  # Positive percentage

    async def test_conservative_stop_loss(self):
        """Test 50% stop loss (exit at half max loss)."""
        strategy = StopLossExit(max_loss_percentage=50.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-25.00")  # $25 loss
        position.initial_risk = Decimal("50.00")  # $50 max risk

        result = await strategy.evaluate(position)

        # Should trigger exit at 50% max loss
        assert result.should_exit is True
        assert result.metadata["stop_loss_threshold"] == -25.0
        assert result.metadata["max_loss_percentage"] == 50.0

    async def test_aggressive_stop_loss(self):
        """Test 200% stop loss (allow loss beyond max)."""
        strategy = StopLossExit(max_loss_percentage=200.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-100.00")  # $100 loss (2x max)
        position.initial_risk = Decimal("50.00")  # $50 max risk

        result = await strategy.evaluate(position)

        # Should trigger exit at 200% max loss
        assert result.should_exit is True
        assert result.metadata["stop_loss_threshold"] == -100.0
        assert result.metadata["loss_pct"] == -200.0

    async def test_no_unrealized_pnl(self):
        """Test handling when unrealized_pnl is None."""
        strategy = StopLossExit(max_loss_percentage=100.0)

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
        strategy = StopLossExit(max_loss_percentage=100.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-25.00")
        position.initial_risk = None

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "No initial risk data available" in result.reason

    async def test_zero_initial_risk(self):
        """Test handling when initial_risk is zero."""
        strategy = StopLossExit(max_loss_percentage=100.0)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-25.00")
        position.initial_risk = Decimal("0.00")

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "No initial risk data available" in result.reason

    def test_invalid_max_loss_percentage(self):
        """Test validation of max_loss_percentage parameter."""
        # Zero percentage
        with pytest.raises(ValueError, match="must be positive"):
            StopLossExit(max_loss_percentage=0.0)

        # Negative percentage
        with pytest.raises(ValueError, match="must be positive"):
            StopLossExit(max_loss_percentage=-10.0)

    def test_get_name(self):
        """Test human-readable name generation."""
        strategy = StopLossExit(max_loss_percentage=100.0)
        assert strategy.get_name() == "100% Stop Loss"

        strategy = StopLossExit(max_loss_percentage=50.0)
        assert strategy.get_name() == "50% Stop Loss"
