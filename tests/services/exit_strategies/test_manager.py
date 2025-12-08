"""Tests for ExitManager."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.exit_strategies.manager import ExitCombinationMode, ExitManager
from services.exit_strategies.profit_target import ProfitTargetExit
from services.exit_strategies.stop_loss import StopLossExit
from services.exit_strategies.time_based import TimeBasedExit


@pytest.mark.asyncio
class TestExitManager:
    """Test ExitManager orchestration."""

    async def test_any_mode_single_trigger(self):
        """Test ANY mode exits when one strategy triggers."""
        # Create strategies
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)

        # Create manager in ANY mode
        manager = ExitManager([profit_exit, stop_exit], mode=ExitCombinationMode.ANY)

        # Position with profit at target (triggers profit_exit)
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")
        position.initial_risk = Decimal("50.00")

        # Evaluate
        should_exit, reason, evaluations = await manager.should_exit(position)

        # Should exit (profit target met)
        assert should_exit is True
        assert "Exit triggered by" in reason
        assert "50% Profit Target" in reason
        assert len(evaluations) == 2

    async def test_any_mode_multiple_triggers(self):
        """Test ANY mode with multiple strategies triggering."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=50.0)

        manager = ExitManager([profit_exit, stop_exit], mode=ExitCombinationMode.ANY)

        # Position with large loss (triggers stop_exit but not profit_exit)
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("-30.00")
        position.initial_risk = Decimal("50.00")

        should_exit, reason, _evaluations = await manager.should_exit(position)

        # Should exit (stop loss triggered)
        assert should_exit is True
        assert "Exit triggered by" in reason
        assert "50% Stop Loss" in reason

    async def test_any_mode_no_triggers(self):
        """Test ANY mode when no strategies trigger."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)

        manager = ExitManager([profit_exit, stop_exit], mode=ExitCombinationMode.ANY)

        # Position with small profit (doesn't trigger either)
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("10.00")
        position.initial_risk = Decimal("50.00")

        should_exit, reason, evaluations = await manager.should_exit(position)

        # Should NOT exit
        assert should_exit is False
        assert "No exit strategies triggered" in reason
        assert len(evaluations) == 2

    async def test_all_mode_all_trigger(self):
        """Test ALL mode exits only when all strategies trigger."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)

        manager = ExitManager([profit_exit, stop_exit], mode=ExitCombinationMode.ALL)

        # Position with profit (only triggers profit_exit)
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")
        position.initial_risk = Decimal("50.00")

        should_exit, reason, _evaluations = await manager.should_exit(position)

        # Should NOT exit (only one strategy triggered)
        assert should_exit is False
        assert "Not all exit conditions met" in reason
        assert "100% Stop Loss" in reason  # Waiting on stop loss

    async def test_all_mode_all_met(self):
        """Test ALL mode with all conditions met."""
        # Both will trigger on large profit
        ProfitTargetExit(target_percentage=10.0)  # Low threshold
        # Note: Stop loss won't trigger on profit, so this test needs rethinking

        # Better example: Use time-based exits that can both trigger
        from datetime import timedelta

        from django.utils import timezone

        time_exit_1 = TimeBasedExit(min_dte=7)
        time_exit_2 = TimeBasedExit(max_holding_days=60)

        manager = ExitManager([time_exit_1, time_exit_2], mode=ExitCombinationMode.ALL)

        # Position with low DTE AND long holding period
        position = Mock()
        position.id = 1
        future_date = (timezone.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now() - timedelta(days=65)

        should_exit, reason, evaluations = await manager.should_exit(position)

        # Should exit (both conditions met)
        assert should_exit is True
        assert "All exit conditions met" in reason
        assert len(evaluations) == 2

    def test_add_strategy(self):
        """Test adding strategy dynamically."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        manager = ExitManager([profit_exit])

        # Add stop loss
        stop_exit = StopLossExit(max_loss_percentage=100.0)
        manager.add_strategy(stop_exit)

        # Should have 2 strategies
        assert len(manager.strategies) == 2
        assert "100% Stop Loss" in manager.get_strategy_names()

    def test_remove_strategy(self):
        """Test removing strategy."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)
        manager = ExitManager([profit_exit, stop_exit])

        # Remove stop loss
        removed = manager.remove_strategy(stop_exit)

        assert removed is True
        assert len(manager.strategies) == 1
        assert "100% Stop Loss" not in manager.get_strategy_names()

    def test_remove_nonexistent_strategy(self):
        """Test removing strategy that doesn't exist."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        manager = ExitManager([profit_exit])

        stop_exit = StopLossExit(max_loss_percentage=100.0)
        removed = manager.remove_strategy(stop_exit)

        assert removed is False
        assert len(manager.strategies) == 1

    def test_get_strategy_names(self):
        """Test getting list of strategy names."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)
        manager = ExitManager([profit_exit, stop_exit])

        names = manager.get_strategy_names()

        assert len(names) == 2
        assert "50% Profit Target" in names
        assert "100% Stop Loss" in names

    async def test_strategy_evaluation_error(self):
        """Test handling when a strategy raises an exception."""
        # Create a mock strategy that raises an error
        broken_strategy = Mock()
        broken_strategy.get_name = Mock(return_value="Broken Strategy")
        broken_strategy.evaluate = Mock(side_effect=Exception("Test error"))

        profit_exit = ProfitTargetExit(target_percentage=50.0)

        manager = ExitManager([broken_strategy, profit_exit], mode=ExitCombinationMode.ANY)

        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("25.00")
        position.initial_risk = Decimal("50.00")

        # Should handle error gracefully
        should_exit, _reason, evaluations = await manager.should_exit(position)

        # Should still exit (profit target triggered)
        assert should_exit is True
        assert len(evaluations) == 2
        # First evaluation should be marked as failed
        assert evaluations[0].should_exit is False
        assert "Evaluation failed" in evaluations[0].reason

    async def test_three_strategies_any_mode(self):
        """Test with three strategies in ANY mode."""
        from datetime import timedelta

        from django.utils import timezone

        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)
        time_exit = TimeBasedExit(min_dte=7)

        manager = ExitManager([profit_exit, stop_exit, time_exit], mode=ExitCombinationMode.ANY)

        # Position with low DTE (triggers time_exit)
        position = Mock()
        position.id = 1
        position.unrealized_pnl = Decimal("10.00")  # Small profit
        position.initial_risk = Decimal("50.00")
        future_date = (timezone.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now() - timedelta(days=10)

        should_exit, _reason, evaluations = await manager.should_exit(position)

        # Should exit (time-based triggered)
        assert should_exit is True
        assert len(evaluations) == 3

    def test_empty_strategies_list(self):
        """Test validation of empty strategies list."""
        with pytest.raises(ValueError, match="At least one exit strategy"):
            ExitManager([])

    def test_repr(self):
        """Test string representation."""
        profit_exit = ProfitTargetExit(target_percentage=50.0)
        stop_exit = StopLossExit(max_loss_percentage=100.0)
        manager = ExitManager([profit_exit, stop_exit], mode=ExitCombinationMode.ANY)

        repr_str = repr(manager)

        assert "ExitManager" in repr_str
        assert "mode=any" in repr_str
        assert "50% Profit Target" in repr_str
        assert "100% Stop Loss" in repr_str
