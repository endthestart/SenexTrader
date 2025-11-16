"""
Base Exit Strategy

Abstract base class for all exit strategies in the framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ExitEvaluation:
    """
    Result of evaluating an exit strategy.

    Attributes:
        should_exit: Whether the position should exit based on this strategy
        reason: Human-readable explanation of why exit was triggered (or not)
        metadata: Additional data about the evaluation (e.g., current vs target values)
    """

    should_exit: bool
    reason: str
    metadata: dict[str, Any] | None = None


class ExitStrategy(ABC):
    """
    Abstract base class for exit strategies.

    Exit strategies evaluate whether a position should be closed based on
    specific criteria (profit targets, stop losses, time, Greeks, etc.).

    Each exit strategy is independent and composable - they can be combined
    using ExitManager to create complex exit logic with AND/OR conditions.

    Subclasses must implement:
    - evaluate(): Core logic to determine if position should exit
    - get_name(): Human-readable strategy name for logging
    """

    @abstractmethod
    async def evaluate(
        self, position: Any, market_data: dict[str, Any] | None = None
    ) -> ExitEvaluation:
        """
        Evaluate whether the position should exit based on this strategy.

        Args:
            position: Position model instance with fields:
                - unrealized_pnl: Current profit/loss (Decimal)
                - initial_risk: Max loss amount (Decimal)
                - avg_price: Opening price (Decimal)
                - opened_at: Timestamp when position opened
                - metadata: JSONField with additional data (DTE, etc.)
            market_data: Optional current market data for the position's symbol

        Returns:
            ExitEvaluation with should_exit flag, reason, and optional metadata

        Note:
            This method should be fast (<100ms) since it may be called frequently
            during position monitoring. Avoid expensive computations or API calls.
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Return human-readable name for this exit strategy.

        Used for logging and debugging. Should be concise and descriptive.

        Examples:
            - "50% Profit Target"
            - "100% Stop Loss"
            - "DTE < 7 Days"
        """
        pass

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.__class__.__name__}(name='{self.get_name()}')"
