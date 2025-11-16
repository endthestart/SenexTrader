"""
Exit Manager

Orchestrates multiple exit strategies with flexible AND/OR logic.
"""

from enum import Enum
from typing import Any

from services.core.logging import get_logger
from services.exit_strategies.base import ExitEvaluation, ExitStrategy

logger = get_logger(__name__)


class ExitCombinationMode(Enum):
    """How to combine multiple exit strategies."""

    ANY = "any"  # Exit if ANY strategy triggers (OR logic)
    ALL = "all"  # Exit only if ALL strategies trigger (AND logic)


class ExitManager:
    """
    Orchestrates multiple exit strategies with AND/OR logic.

    The ExitManager evaluates all configured exit strategies and combines
    their results based on the combination mode (ANY or ALL).

    Common patterns:
        - ANY mode: Exit on first trigger (profit target OR stop loss OR time)
        - ALL mode: Exit only when all conditions met (profit target AND time AND ...)

    Attributes:
        strategies: List of exit strategies to evaluate
        mode: How to combine strategy results (ANY or ALL)
    """

    def __init__(
        self,
        strategies: list[ExitStrategy],
        mode: ExitCombinationMode = ExitCombinationMode.ANY,
    ):
        """
        Initialize exit manager with strategies.

        Args:
            strategies: List of exit strategies to evaluate
            mode: Combination mode (ANY = OR, ALL = AND)
                Default: ANY (exit on first trigger)

        Raises:
            ValueError: If strategies list is empty

        Examples:
            # Exit on first trigger (profit OR stop OR time)
            manager = ExitManager(
                [profit_exit, stop_exit, time_exit],
                mode=ExitCombinationMode.ANY
            )

            # Exit only when all conditions met (profit AND time)
            manager = ExitManager(
                [profit_exit, time_exit],
                mode=ExitCombinationMode.ALL
            )
        """
        if not strategies:
            raise ValueError("At least one exit strategy must be provided")

        self.strategies = strategies
        self.mode = mode

    async def should_exit(
        self, position: Any, market_data: dict[str, Any] | None = None
    ) -> tuple[bool, str, list[ExitEvaluation]]:
        """
        Evaluate all strategies and determine if position should exit.

        Args:
            position: Position instance to evaluate
            market_data: Optional market data for the position's symbol

        Returns:
            Tuple of (should_exit, combined_reason, all_evaluations):
                - should_exit: Whether position should exit based on mode
                - combined_reason: Human-readable explanation of decision
                - all_evaluations: List of all strategy evaluations for logging

        Note:
            All strategies are evaluated even if early exit could be determined.
            This ensures complete logging and debugging information.
        """
        # Evaluate all strategies
        evaluations: list[ExitEvaluation] = []
        for strategy in self.strategies:
            try:
                evaluation = await strategy.evaluate(position, market_data)
                evaluations.append(evaluation)
                logger.debug(
                    f"Exit strategy '{strategy.get_name()}' evaluated: "
                    f"should_exit={evaluation.should_exit}, reason={evaluation.reason}"
                )
            except Exception as e:
                logger.error(
                    f"Error evaluating exit strategy '{strategy.get_name()}': {e}",
                    exc_info=True,
                )
                # Create failed evaluation
                evaluations.append(
                    ExitEvaluation(
                        should_exit=False,
                        reason=f"Evaluation failed: {e!s}",
                        metadata={"error": str(e), "strategy": strategy.get_name()},
                    )
                )

        # Combine results based on mode
        if self.mode == ExitCombinationMode.ANY:
            # Exit if ANY strategy says to exit (OR logic)
            should_exit = any(e.should_exit for e in evaluations)

            if should_exit:
                # Find which strategies triggered
                triggered = [
                    (strategy.get_name(), eval.reason)
                    for strategy, eval in zip(self.strategies, evaluations)
                    if eval.should_exit
                ]
                combined_reason = "Exit triggered by: " + "; ".join(
                    f"{name} ({reason})" for name, reason in triggered
                )
            else:
                combined_reason = "No exit strategies triggered"

        elif self.mode == ExitCombinationMode.ALL:
            # Exit only if ALL strategies say to exit (AND logic)
            should_exit = all(e.should_exit for e in evaluations)

            if should_exit:
                combined_reason = "All exit conditions met: " + "; ".join(
                    f"{strategy.get_name()} ({eval.reason})"
                    for strategy, eval in zip(self.strategies, evaluations)
                )
            else:
                # Find which strategies NOT triggered
                not_triggered = [
                    strategy.get_name()
                    for strategy, eval in zip(self.strategies, evaluations)
                    if not eval.should_exit
                ]
                combined_reason = "Not all exit conditions met. Waiting on: " + ", ".join(
                    not_triggered
                )

        else:
            raise ValueError(f"Unknown combination mode: {self.mode}")

        logger.info(
            f"ExitManager evaluated position {position.id}: "
            f"should_exit={should_exit}, mode={self.mode.value}, "
            f"reason='{combined_reason}'"
        )

        return should_exit, combined_reason, evaluations

    def add_strategy(self, strategy: ExitStrategy) -> None:
        """
        Add an exit strategy to the manager.

        Args:
            strategy: Exit strategy to add

        Note:
            Strategies are evaluated in the order they were added.
        """
        self.strategies.append(strategy)
        logger.debug(f"Added exit strategy '{strategy.get_name()}' to manager")

    def remove_strategy(self, strategy: ExitStrategy) -> bool:
        """
        Remove an exit strategy from the manager.

        Args:
            strategy: Exit strategy to remove

        Returns:
            True if strategy was removed, False if not found
        """
        try:
            self.strategies.remove(strategy)
            logger.debug(f"Removed exit strategy '{strategy.get_name()}' from manager")
            return True
        except ValueError:
            logger.warning(
                f"Attempted to remove exit strategy '{strategy.get_name()}' but it was not found"
            )
            return False

    def get_strategy_names(self) -> list[str]:
        """
        Get names of all configured exit strategies.

        Returns:
            List of strategy names for logging/debugging
        """
        return [s.get_name() for s in self.strategies]

    def __repr__(self) -> str:
        """String representation for debugging."""
        strategy_names = ", ".join(self.get_strategy_names())
        return f"ExitManager(mode={self.mode.value}, strategies=[{strategy_names}])"
