"""
Stop Loss Exit Strategy

Exits position when unrealized loss exceeds a threshold percentage of initial risk.
"""

from decimal import Decimal
from typing import Any

from services.core.logging import get_logger
from services.exit_strategies.base import ExitEvaluation, ExitStrategy

logger = get_logger(__name__)


class StopLossExit(ExitStrategy):
    """
    Exit when position loss exceeds threshold percentage of initial risk.

    For credit spreads: Loss can approach max loss (spread width * contracts * 100)
    For debit spreads: Loss is limited to debit paid

    Example:
        Bull put spread with $500 max loss and 100% stop loss
        → Exit when unrealized P&L <= -$500 (100% of max loss)

    Common thresholds:
        - 50%: Conservative (exit at half max loss)
        - 100%: Standard (exit at max loss to limit further slippage)
        - 200%: Aggressive (allow loss beyond max loss, risky)

    Attributes:
        max_loss_percentage: Maximum loss as percentage of initial risk
    """

    def __init__(self, max_loss_percentage: float = 100.0):
        """
        Initialize stop loss exit strategy.

        Args:
            max_loss_percentage: Max loss as percentage of initial risk
                Default: 100.0 (exit at max loss)

        Raises:
            ValueError: If max_loss_percentage is not positive
        """
        if max_loss_percentage <= 0:
            raise ValueError(f"max_loss_percentage must be positive, got {max_loss_percentage}")

        self.max_loss_percentage = Decimal(str(max_loss_percentage))

    async def evaluate(
        self, position: Any, market_data: dict[str, Any] | None = None
    ) -> ExitEvaluation:
        """
        Evaluate if position has exceeded stop loss threshold.

        Args:
            position: Position instance with unrealized_pnl and initial_risk
            market_data: Not used for stop loss (relies on position data)

        Returns:
            ExitEvaluation indicating whether stop loss triggered
        """
        # Get current P&L
        current_pnl = position.unrealized_pnl
        if current_pnl is None:
            logger.warning(
                f"Position {position.id} has no unrealized_pnl - cannot evaluate stop loss"
            )
            return ExitEvaluation(
                should_exit=False,
                reason="No P&L data available",
                metadata={"max_loss_percentage": float(self.max_loss_percentage)},
            )

        current_pnl = Decimal(str(current_pnl))

        # Get initial risk (max loss)
        initial_risk = position.initial_risk
        if initial_risk is None or initial_risk == 0:
            logger.warning(
                f"Position {position.id} has no initial_risk - cannot evaluate stop loss"
            )
            return ExitEvaluation(
                should_exit=False,
                reason="No initial risk data available",
                metadata={"max_loss_percentage": float(self.max_loss_percentage)},
            )

        initial_risk = Decimal(str(initial_risk))

        # Calculate stop loss threshold (negative value)
        # For credit spreads: initial_risk is positive (credit received)
        # Max loss is spread_width * contracts * 100 - credit
        # For simplicity, we'll use initial_risk as the reference
        stop_loss_threshold = -abs(initial_risk) * (self.max_loss_percentage / Decimal("100"))

        # Check if current loss meets or exceeds threshold (more negative)
        should_exit = current_pnl <= stop_loss_threshold

        # Calculate loss percentage
        loss_pct = (
            (current_pnl / abs(initial_risk)) * Decimal("100")
            if initial_risk != 0
            else Decimal("0")
        )

        if should_exit:
            reason = (
                f"Stop loss triggered: ${current_pnl:.2f} "
                f"({loss_pct:.1f}%) <= ${stop_loss_threshold:.2f} "
                f"({self.max_loss_percentage}% max loss)"
            )
        else:
            reason = (
                f"Stop loss not triggered: ${current_pnl:.2f} "
                f"({loss_pct:.1f}%) > ${stop_loss_threshold:.2f} "
                f"({self.max_loss_percentage}% max loss)"
            )

        return ExitEvaluation(
            should_exit=should_exit,
            reason=reason,
            metadata={
                "current_pnl": float(current_pnl),
                "stop_loss_threshold": float(stop_loss_threshold),
                "max_loss_percentage": float(self.max_loss_percentage),
                "loss_pct": float(loss_pct),
                "initial_risk": float(initial_risk),
            },
        )

    def get_name(self) -> str:
        """Return human-readable name."""
        # Format percentage without unnecessary decimal places
        pct = float(self.max_loss_percentage)
        if pct == int(pct):
            return f"{int(pct)}% Stop Loss"
        return f"{pct}% Stop Loss"
