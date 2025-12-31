"""
Time-Based Exit Strategy

Exits position based on time criteria (DTE, holding period, etc.).
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from services.core.logging import get_logger
from services.exit_strategies.base import ExitEvaluation, ExitStrategy

logger = get_logger(__name__)

# US Eastern timezone for market-aligned DTE calculations
ET_TIMEZONE = ZoneInfo("America/New_York")


class TimeBasedExit(ExitStrategy):
    """
    Exit when time-based criteria are met.

    Supports two modes:
    1. DTE-based: Exit when days to expiration falls below threshold
    2. Holding period: Exit after position held for minimum days

    Common use cases:
        - Exit credit spreads at 7 DTE to avoid gamma risk
        - Exit debit spreads at 21 DTE to preserve theta value
        - Hold wheel positions for minimum 30 days for tax treatment

    Attributes:
        min_dte: Minimum DTE before exit (None to disable)
        max_dte: Maximum DTE before exit (None to disable)
        min_holding_days: Minimum days to hold position (None to disable)
        max_holding_days: Maximum days to hold position (None to disable)
    """

    def __init__(
        self,
        min_dte: int | None = None,
        max_dte: int | None = None,
        min_holding_days: int | None = None,
        max_holding_days: int | None = None,
    ):
        """
        Initialize time-based exit strategy.

        Args:
            min_dte: Exit when DTE falls below this value (e.g., 7 for credit spreads)
            max_dte: Exit when DTE exceeds this value (rare, for adjustments)
            min_holding_days: Exit only after holding for this many days
            max_holding_days: Exit if held longer than this many days

        Raises:
            ValueError: If no time criteria specified or invalid ranges

        Examples:
            # Exit credit spread at 7 DTE
            TimeBasedExit(min_dte=7)

            # Hold wheel position for at least 30 days
            TimeBasedExit(min_holding_days=30)

            # Exit if held more than 60 days
            TimeBasedExit(max_holding_days=60)
        """
        if all(x is None for x in [min_dte, max_dte, min_holding_days, max_holding_days]):
            raise ValueError("At least one time criterion must be specified")

        if min_dte is not None and min_dte < 0:
            raise ValueError(f"min_dte must be non-negative, got {min_dte}")

        if max_dte is not None and max_dte < 0:
            raise ValueError(f"max_dte must be non-negative, got {max_dte}")

        if min_dte is not None and max_dte is not None and min_dte > max_dte:
            raise ValueError(f"min_dte ({min_dte}) must be <= max_dte ({max_dte})")

        if min_holding_days is not None and min_holding_days < 0:
            raise ValueError(f"min_holding_days must be non-negative, got {min_holding_days}")

        if max_holding_days is not None and max_holding_days < 0:
            raise ValueError(f"max_holding_days must be non-negative, got {max_holding_days}")

        if (
            min_holding_days is not None
            and max_holding_days is not None
            and min_holding_days > max_holding_days
        ):
            raise ValueError(
                f"min_holding_days ({min_holding_days}) must be <= max_holding_days ({max_holding_days})"
            )

        self.min_dte = min_dte
        self.max_dte = max_dte
        self.min_holding_days = min_holding_days
        self.max_holding_days = max_holding_days

    async def evaluate(
        self, position: Any, market_data: dict[str, Any] | None = None
    ) -> ExitEvaluation:
        """
        Evaluate if position meets time-based exit criteria.

        Args:
            position: Position instance with:
                - metadata: JSONField containing 'expiration_date' for DTE calculation
                - opened_at: Timestamp when position was opened
            market_data: Not used for time-based exits

        Returns:
            ExitEvaluation indicating whether time criteria met
        """
        reasons = []
        should_exit = False
        metadata_dict: dict[str, Any] = {}

        # Check DTE criteria
        if self.min_dte is not None or self.max_dte is not None:
            current_dte = self._get_dte(position)
            metadata_dict["current_dte"] = current_dte

            if current_dte is not None:
                if self.min_dte is not None:
                    metadata_dict["min_dte"] = self.min_dte
                    if current_dte < self.min_dte:
                        should_exit = True
                        reasons.append(
                            f"DTE {current_dte} < minimum {self.min_dte} (gamma risk increasing)"
                        )
                    else:
                        reasons.append(f"DTE {current_dte} >= minimum {self.min_dte}")

                if self.max_dte is not None:
                    metadata_dict["max_dte"] = self.max_dte
                    if current_dte > self.max_dte:
                        should_exit = True
                        reasons.append(f"DTE {current_dte} > maximum {self.max_dte}")
                    else:
                        reasons.append(f"DTE {current_dte} <= maximum {self.max_dte}")
            else:
                reasons.append("DTE not available (no expiration date in metadata)")

        # Check holding period criteria
        if self.min_holding_days is not None or self.max_holding_days is not None:
            holding_days = self._get_holding_days(position)
            metadata_dict["holding_days"] = holding_days

            if holding_days is not None:
                if self.min_holding_days is not None:
                    metadata_dict["min_holding_days"] = self.min_holding_days
                    # For min_holding_days, we DON'T exit until minimum is met
                    # This is a hold condition, not an exit condition
                    if holding_days < self.min_holding_days:
                        reasons.append(
                            f"Holding {holding_days} days < minimum {self.min_holding_days} "
                            f"(hold {self.min_holding_days - holding_days} more days)"
                        )
                    else:
                        reasons.append(
                            f"Holding {holding_days} days >= minimum {self.min_holding_days}"
                        )

                if self.max_holding_days is not None:
                    metadata_dict["max_holding_days"] = self.max_holding_days
                    if holding_days > self.max_holding_days:
                        should_exit = True
                        reasons.append(
                            f"Holding {holding_days} days > maximum {self.max_holding_days}"
                        )
                    else:
                        reasons.append(
                            f"Holding {holding_days} days <= maximum {self.max_holding_days}"
                        )
            else:
                reasons.append("Holding period not available (no opened_at timestamp)")

        combined_reason = "; ".join(reasons) if reasons else "No time criteria met"

        return ExitEvaluation(
            should_exit=should_exit,
            reason=combined_reason,
            metadata=metadata_dict,
        )

    def _get_dte(self, position: Any) -> int | None:
        """
        Calculate days to expiration from position metadata.

        Args:
            position: Position with metadata containing 'expiration_date'

        Returns:
            Days to expiration, or None if not available
        """
        if not hasattr(position, "metadata") or not position.metadata:
            return None

        expiration_str = position.metadata.get("expiration_date")
        if not expiration_str:
            return None

        try:
            # Parse expiration date (format: "YYYY-MM-DD")
            expiration_date = datetime.strptime(expiration_str, "%Y-%m-%d").date()
            today = timezone.now().astimezone(ET_TIMEZONE).date()
            dte = (expiration_date - today).days
            return max(0, dte)  # Don't return negative DTE
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Could not parse expiration_date '{expiration_str}' for position {position.id}: {e}"
            )
            return None

    def _get_holding_days(self, position: Any) -> int | None:
        """
        Calculate days position has been held.

        Args:
            position: Position with opened_at timestamp

        Returns:
            Days held, or None if not available
        """
        if not hasattr(position, "opened_at") or not position.opened_at:
            return None

        now = timezone.now()
        holding_time = now - position.opened_at
        return holding_time.days

    def get_name(self) -> str:
        """Return human-readable name."""
        parts = []

        if self.min_dte is not None:
            parts.append(f"DTE < {self.min_dte}")

        if self.max_dte is not None:
            parts.append(f"DTE > {self.max_dte}")

        if self.min_holding_days is not None:
            parts.append(f"Hold >= {self.min_holding_days}d")

        if self.max_holding_days is not None:
            parts.append(f"Hold <= {self.max_holding_days}d")

        return " AND ".join(parts) if parts else "Time-Based Exit"
