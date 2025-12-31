"""
Hierarchical parameter system for unified strategy architecture.

This module provides a composable parameter hierarchy where:
- BaseSpreadParams: Common parameters for ALL spread strategies
- VerticalSpreadParams: Parameters specific to vertical spreads (bull put, bear call, etc.)

Future phases will add:
- IronCondorParams: Composes two VerticalSpreadParams
- ButterflyParams: Center strike + wing width
- StraddleParams: ATM straddle/strangle parameters

Design Principle: Multi-leg strategies COMPOSE from simpler param types.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from services.strategies.core.types import Direction, OptionType, StrikeSelection


class GenerationMode(Enum):
    """
    Strategy generation quality modes.

    These modes control the quality threshold for strategy generation:
    - STRICT: 5% quality gate (highest quality only)
    - RELAXED: 15% quality gate (accept lower quality with warnings)
    - FORCE: Always generate (bypass quality gates, show quality score)
    """

    STRICT = "strict"
    RELAXED = "relaxed"
    FORCE = "force"

    def get_quality_threshold(self) -> float | None:
        """
        Get the quality threshold percentage for this mode.

        Returns:
            Quality threshold as percentage deviation (0.05 = 5%, 0.15 = 15%, None = no gate)
        """
        if self == GenerationMode.STRICT:
            return 0.05
        if self == GenerationMode.RELAXED:
            return 0.15
        return None


@dataclass
class BaseSpreadParams:
    """
    Base parameters common to ALL spread strategies.

    This is the foundation of the parameter hierarchy. All spread strategies
    share these parameters regardless of their specific structure.

    Attributes:
        dte_min: Minimum days to expiration
        dte_max: Maximum days to expiration
        dte_target: Target DTE (optional, defaults to midpoint)
        quantity: Number of contracts
        selection_method: How strikes are selected (DELTA, OTM_PERCENT, etc.)
        generation_mode: Quality mode (STRICT, RELAXED, FORCE)
        source: Where parameters came from ("market_report", "manual", "ui", "defaults")
        metadata: Additional context for debugging/logging
    """

    # Expiration Selection
    dte_min: int = 30
    dte_max: int = 45
    dte_target: int | None = None

    # Position Sizing
    quantity: int = 1

    # Strike Selection Method
    selection_method: StrikeSelection = StrikeSelection.OTM_PERCENT

    # Generation Control
    generation_mode: GenerationMode = GenerationMode.STRICT

    # Source Tracking
    source: str = "defaults"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate base parameter constraints."""
        if self.dte_min < 1:
            raise ValueError(f"dte_min must be at least 1, got {self.dte_min}")
        if self.dte_max < 1:
            raise ValueError(f"dte_max must be at least 1, got {self.dte_max}")
        if self.dte_min > self.dte_max:
            raise ValueError(
                f"dte_min ({self.dte_min}) cannot be greater than dte_max ({self.dte_max})"
            )
        if self.dte_target is not None:
            if self.dte_target < self.dte_min or self.dte_target > self.dte_max:
                raise ValueError(
                    f"dte_target ({self.dte_target}) must be between "
                    f"dte_min ({self.dte_min}) and dte_max ({self.dte_max})"
                )
        if self.quantity < 1:
            raise ValueError(f"quantity must be at least 1, got {self.quantity}")

    @property
    def effective_dte_target(self) -> int:
        """Return dte_target if set, otherwise midpoint of range."""
        if self.dte_target is not None:
            return self.dte_target
        return (self.dte_min + self.dte_max) // 2

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "dte_min": self.dte_min,
            "dte_max": self.dte_max,
            "dte_target": self.dte_target,
            "quantity": self.quantity,
            "selection_method": self.selection_method.value,
            "generation_mode": self.generation_mode.value,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class VerticalSpreadParams(BaseSpreadParams):
    """
    Parameters for vertical spread strategies.

    Vertical spreads are two-leg strategies with same expiration, different strikes.
    This includes: bull put spreads, bear call spreads, bull call spreads, bear put spreads.

    The direction + option_type combination determines the spread type:
    - BULLISH + PUT = Bull Put Spread (credit)
    - BEARISH + CALL = Bear Call Spread (credit)
    - BULLISH + CALL = Bull Call Spread (debit)
    - BEARISH + PUT = Bear Put Spread (debit)

    Attributes (in addition to BaseSpreadParams):
        direction: Market bias (BULLISH, BEARISH, NEUTRAL)
        option_type: Option type (PUT, CALL)
        width_min: Minimum spread width in points
        width_max: Maximum spread width in points
        width_target: Target width (optional, defaults to midpoint)
        otm_percent: Target OTM percentage (when selection_method=OTM_PERCENT)
        delta_target: Target delta for short strike (when selection_method=DELTA)
        profit_target_pct: Profit target as percentage of max profit
        support_buffer_pct: Buffer above support level (for put spreads)
        resistance_buffer_pct: Buffer below resistance level (for call spreads)
    """

    # Strategy Direction
    direction: Direction = Direction.BULLISH
    option_type: OptionType = OptionType.PUT

    # Width Parameters
    width_min: int = 5
    width_max: int = 5
    width_target: int | None = None

    # Strike Selection (depends on selection_method from base)
    otm_percent: float = 0.03  # 3% OTM default
    delta_target: float | None = None  # e.g., 0.30 for 30-delta

    # Risk Management
    profit_target_pct: int = 50
    support_buffer_pct: float = 2.0
    resistance_buffer_pct: float = 2.0

    # Optional Thresholds
    min_iv_rank: float | None = None
    min_score_threshold: float | None = None

    def __post_init__(self):
        """Validate vertical spread parameter constraints."""
        super().__post_init__()

        # Width validation
        if self.width_min < 1:
            raise ValueError(f"width_min must be at least 1, got {self.width_min}")
        if self.width_max < 1:
            raise ValueError(f"width_max must be at least 1, got {self.width_max}")
        if self.width_min > self.width_max:
            raise ValueError(
                f"width_min ({self.width_min}) cannot be greater than width_max ({self.width_max})"
            )
        if self.width_target is not None:
            if self.width_target < self.width_min or self.width_target > self.width_max:
                raise ValueError(
                    f"width_target ({self.width_target}) must be between "
                    f"width_min ({self.width_min}) and width_max ({self.width_max})"
                )

        # OTM percentage validation
        if self.otm_percent < 0 or self.otm_percent > 1:
            raise ValueError(f"otm_percent must be between 0 and 1, got {self.otm_percent}")

        # Delta validation (if provided)
        if self.delta_target is not None:
            if self.delta_target < 0 or self.delta_target > 1:
                raise ValueError(
                    f"delta_target must be between 0 and 1, got {self.delta_target}"
                )

        # Profit target validation
        if self.profit_target_pct < 0 or self.profit_target_pct > 100:
            raise ValueError(
                f"profit_target_pct must be between 0 and 100, got {self.profit_target_pct}"
            )

        # Buffer validation
        if self.support_buffer_pct < 0:
            raise ValueError(
                f"support_buffer_pct cannot be negative, got {self.support_buffer_pct}"
            )
        if self.resistance_buffer_pct < 0:
            raise ValueError(
                f"resistance_buffer_pct cannot be negative, got {self.resistance_buffer_pct}"
            )

        # IV rank validation (if provided)
        if self.min_iv_rank is not None:
            if self.min_iv_rank < 0 or self.min_iv_rank > 100:
                raise ValueError(f"min_iv_rank must be between 0 and 100, got {self.min_iv_rank}")

        # Score threshold validation (if provided)
        if self.min_score_threshold is not None:
            if self.min_score_threshold < 0 or self.min_score_threshold > 100:
                raise ValueError(
                    f"min_score_threshold must be between 0 and 100, got {self.min_score_threshold}"
                )

    @property
    def effective_width_target(self) -> int:
        """Return width_target if set, otherwise midpoint of range."""
        if self.width_target is not None:
            return self.width_target
        return (self.width_min + self.width_max) // 2

    @property
    def is_credit_spread(self) -> bool:
        """Return True if this is a credit spread (receive premium)."""
        return (self.direction == Direction.BULLISH and self.option_type == OptionType.PUT) or (
            self.direction == Direction.BEARISH and self.option_type == OptionType.CALL
        )

    @property
    def is_debit_spread(self) -> bool:
        """Return True if this is a debit spread (pay premium)."""
        return not self.is_credit_spread

    @property
    def spread_type_name(self) -> str:
        """Return human-readable spread type name."""
        if self.direction == Direction.BULLISH and self.option_type == OptionType.PUT:
            return "Bull Put Spread"
        if self.direction == Direction.BEARISH and self.option_type == OptionType.CALL:
            return "Bear Call Spread"
        if self.direction == Direction.BULLISH and self.option_type == OptionType.CALL:
            return "Bull Call Spread"
        if self.direction == Direction.BEARISH and self.option_type == OptionType.PUT:
            return "Bear Put Spread"
        return f"{self.direction.value.title()} {self.option_type.full_name} Spread"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "direction": self.direction.value,
                "option_type": self.option_type.value,
                "width_min": self.width_min,
                "width_max": self.width_max,
                "width_target": self.width_target,
                "otm_percent": self.otm_percent,
                "delta_target": self.delta_target,
                "profit_target_pct": self.profit_target_pct,
                "support_buffer_pct": self.support_buffer_pct,
                "resistance_buffer_pct": self.resistance_buffer_pct,
                "min_iv_rank": self.min_iv_rank,
                "min_score_threshold": self.min_score_threshold,
                "is_credit_spread": self.is_credit_spread,
                "spread_type_name": self.spread_type_name,
            }
        )
        return base_dict

    @classmethod
    def bull_put_defaults(cls, **overrides) -> "VerticalSpreadParams":
        """Factory method for Bull Put Spread with sensible defaults."""
        defaults = {
            "direction": Direction.BULLISH,
            "option_type": OptionType.PUT,
            "dte_min": 30,
            "dte_max": 45,
            "width_min": 5,
            "width_max": 5,
            "otm_percent": 0.03,
            "profit_target_pct": 50,
        }
        defaults.update(overrides)
        return cls(**defaults)

    @classmethod
    def bear_call_defaults(cls, **overrides) -> "VerticalSpreadParams":
        """Factory method for Bear Call Spread with sensible defaults."""
        defaults = {
            "direction": Direction.BEARISH,
            "option_type": OptionType.CALL,
            "dte_min": 30,
            "dte_max": 45,
            "width_min": 5,
            "width_max": 5,
            "otm_percent": 0.03,
            "profit_target_pct": 50,
        }
        defaults.update(overrides)
        return cls(**defaults)

    @classmethod
    def bull_call_defaults(cls, **overrides) -> "VerticalSpreadParams":
        """Factory method for Bull Call Spread (debit) with sensible defaults."""
        defaults = {
            "direction": Direction.BULLISH,
            "option_type": OptionType.CALL,
            "dte_min": 30,
            "dte_max": 45,
            "width_min": 5,
            "width_max": 5,
            "otm_percent": 0.02,  # Closer to ATM for debit spreads
            "profit_target_pct": 50,
        }
        defaults.update(overrides)
        return cls(**defaults)

    @classmethod
    def bear_put_defaults(cls, **overrides) -> "VerticalSpreadParams":
        """Factory method for Bear Put Spread (debit) with sensible defaults."""
        defaults = {
            "direction": Direction.BEARISH,
            "option_type": OptionType.PUT,
            "dte_min": 30,
            "dte_max": 45,
            "width_min": 5,
            "width_max": 5,
            "otm_percent": 0.02,  # Closer to ATM for debit spreads
            "profit_target_pct": 50,
        }
        defaults.update(overrides)
        return cls(**defaults)
