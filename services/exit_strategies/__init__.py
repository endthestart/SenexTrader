"""
Exit Strategy Framework

Composable exit strategies for position management. This framework decouples exit
logic from entry strategies, enabling flexible exit criteria management.

Key Components:
- ExitStrategy: Abstract base class for all exit strategies
- ProfitTargetExit: Exit when position reaches profit percentage
- StopLossExit: Exit when position exceeds loss threshold
- TimeBasedExit: Exit based on DTE or time in position
- ExitManager: Orchestrates multiple exit strategies with AND/OR logic

Usage Example:
    from services.exit_strategies import (
        ExitManager,
        ProfitTargetExit,
        StopLossExit,
        TimeBasedExit,
    )

    # Create exit strategies
    profit_exit = ProfitTargetExit(target_percentage=50.0)
    stop_exit = StopLossExit(max_loss_percentage=100.0)
    time_exit = TimeBasedExit(min_dte=7)

    # Combine with ExitManager
    exit_manager = ExitManager([profit_exit, stop_exit, time_exit])

    # Evaluate if position should exit
    should_exit, reason = await exit_manager.should_exit(position, market_data)
"""

from services.exit_strategies.base import ExitStrategy
from services.exit_strategies.manager import ExitManager
from services.exit_strategies.profit_target import ProfitTargetExit
from services.exit_strategies.stop_loss import StopLossExit
from services.exit_strategies.time_based import TimeBasedExit

__all__ = [
    "ExitManager",
    "ExitStrategy",
    "ProfitTargetExit",
    "StopLossExit",
    "TimeBasedExit",
]
