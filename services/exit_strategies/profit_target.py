"""
Profit Target Exit Strategy

Exits position when unrealized profit reaches a target percentage of initial risk.
"""

from decimal import Decimal
from typing import Any

from services.core.logging import get_logger
from services.exit_strategies.base import ExitEvaluation, ExitStrategy

logger = get_logger(__name__)


class ProfitTargetExit(ExitStrategy):
    """
    Exit when position profit reaches target percentage of initial risk.

    For credit spreads: Profit target = X% of max profit (credit received)
    For debit spreads: Profit target = X% of max profit (spread width - debit paid)

    Example:
        Bull put spread collected $50 credit with 50% profit target
        → Exit when unrealized P&L >= $25 (50% of $50)

    Attributes:
        target_percentage: Profit target as percentage (e.g., 50.0 for 50%)
    """

    def __init__(self, target_percentage: float = 50.0):
        """
        Initialize profit target exit strategy.

        Args:
            target_percentage: Target profit as percentage of initial risk
                Default: 50.0 (industry standard for credit spreads)

        Raises:
            ValueError: If target_percentage is not positive
        """
        if target_percentage <= 0:
            raise ValueError(f"target_percentage must be positive, got {target_percentage}")

        self.target_percentage = Decimal(str(target_percentage))

    async def evaluate(
        self, position: Any, market_data: dict[str, Any] | None = None
    ) -> ExitEvaluation:
        """
        Evaluate if position has reached profit target.

        Args:
            position: Position instance with unrealized_pnl and initial_risk
            market_data: Not used for profit target (relies on position data)

        Returns:
            ExitEvaluation indicating whether profit target reached
        """
        current_pnl = position.unrealized_pnl
        if current_pnl is None:
            logger.warning(
                f"Position {position.id} has no unrealized_pnl - cannot evaluate profit target"
            )
            return ExitEvaluation(
                should_exit=False,
                reason="No P&L data available",
                metadata={"target_percentage": float(self.target_percentage)},
            )

        current_pnl = Decimal(str(current_pnl))

        initial_risk = position.initial_risk
        if initial_risk is None or initial_risk == 0:
            logger.warning(
                f"Position {position.id} has no initial_risk - cannot evaluate profit target"
            )
            return ExitEvaluation(
                should_exit=False,
                reason="No initial risk data available",
                metadata={"target_percentage": float(self.target_percentage)},
            )

        initial_risk = Decimal(str(initial_risk))

        profit_target = abs(initial_risk) * (self.target_percentage / Decimal("100"))

        should_exit = current_pnl >= profit_target

        profit_pct = (
            (current_pnl / abs(initial_risk)) * Decimal("100")
            if initial_risk != 0
            else Decimal("0")
        )

        if should_exit:
            reason = (
                f"Profit target reached: ${current_pnl:.2f} "
                f"({profit_pct:.1f}%) >= ${profit_target:.2f} "
                f"({self.target_percentage}% target)"
            )
        else:
            reason = (
                f"Profit target not reached: ${current_pnl:.2f} "
                f"({profit_pct:.1f}%) < ${profit_target:.2f} "
                f"({self.target_percentage}% target)"
            )

        return ExitEvaluation(
            should_exit=should_exit,
            reason=reason,
            metadata={
                "current_pnl": float(current_pnl),
                "profit_target": float(profit_target),
                "target_percentage": float(self.target_percentage),
                "profit_pct_achieved": float(profit_pct),
                "initial_risk": float(initial_risk),
            },
        )

    def get_name(self) -> str:
        """Return human-readable name."""
        pct = float(self.target_percentage)
        if pct == int(pct):
            return f"{int(pct)}% Profit Target"
        return f"{pct}% Profit Target"
