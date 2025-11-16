"""
Strategy parameter system for unified architecture.

This module provides the foundational parameter system that separates strategy
generation parameters from market analysis, enabling manual parameter specification
and preparing for UI controls.

Epic 50, Task 001: Create Parameter System
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport

logger = get_logger(__name__)


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
            return 0.05  # 5% threshold
        if self == GenerationMode.RELAXED:
            return 0.15  # 15% threshold
        # FORCE
        return None  # No threshold - always generate


@dataclass
class StrategyParameters:
    """
    Universal strategy generation parameters.

    This dataclass separates strategy parameters from market analysis,
    enabling manual parameter specification and UI controls.

    Attributes:
        # Expiration Selection
        dte_min: Minimum days to expiration (e.g., 30)
        dte_max: Maximum days to expiration (e.g., 45)

        # Strike Selection
        spread_width: Width of spread in points (e.g., 5 for $5 wide)
        otm_percentage: Out-of-the-money percentage (e.g., 0.03 for 3%)

        # Generation Control
        generation_mode: Quality mode (STRICT, RELAXED, or FORCE)

        # Risk Management
        profit_target_pct: Profit target as percentage (e.g., 50 for 50%)
        support_buffer_pct: Buffer above support level (bull put spreads)
        resistance_buffer_pct: Buffer below resistance level (bear call spreads)

        # Optional Overrides
        min_iv_rank: Minimum IV rank threshold (None = use strategy default)
        min_score_threshold: Minimum condition score (None = use strategy default)

        # Source Tracking
        source: Where these parameters came from ("market_report", "manual", "ui")
        metadata: Additional context for debugging
    """

    # Expiration Selection
    dte_min: int = 30
    dte_max: int = 45

    # Strike Selection
    spread_width: int = 5
    otm_percentage: float = 0.03  # 3% OTM by default

    # Generation Control
    generation_mode: GenerationMode = GenerationMode.STRICT

    # Risk Management
    profit_target_pct: int = 50
    support_buffer_pct: float = 2.0
    resistance_buffer_pct: float = 2.0

    # Optional Overrides
    min_iv_rank: float | None = None
    min_score_threshold: float | None = None

    # Source Tracking
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate parameter constraints."""
        # DTE validation
        if self.dte_min < 1:
            raise ValueError(f"dte_min must be at least 1, got {self.dte_min}")
        if self.dte_max < 1:
            raise ValueError(f"dte_max must be at least 1, got {self.dte_max}")
        if self.dte_min > self.dte_max:
            raise ValueError(
                f"dte_min ({self.dte_min}) cannot be greater than dte_max ({self.dte_max})"
            )

        # Spread width validation
        if self.spread_width < 1:
            raise ValueError(f"spread_width must be at least 1, got {self.spread_width}")

        # OTM percentage validation
        if self.otm_percentage < 0 or self.otm_percentage > 1:
            raise ValueError(f"otm_percentage must be between 0 and 1, got {self.otm_percentage}")

        # Profit target validation
        if self.profit_target_pct < 0 or self.profit_target_pct > 100:
            raise ValueError(
                f"profit_target_pct must be between 0 and 100, got {self.profit_target_pct}"
            )

        # Buffer percentage validation
        if self.support_buffer_pct < 0:
            raise ValueError(
                f"support_buffer_pct cannot be negative, got {self.support_buffer_pct}"
            )
        if self.resistance_buffer_pct < 0:
            raise ValueError(
                f"resistance_buffer_pct cannot be negative, got {self.resistance_buffer_pct}"
            )

        # Optional IV rank validation
        if self.min_iv_rank is not None:
            if self.min_iv_rank < 0 or self.min_iv_rank > 100:
                raise ValueError(f"min_iv_rank must be between 0 and 100, got {self.min_iv_rank}")

        # Optional score threshold validation
        if self.min_score_threshold is not None:
            if self.min_score_threshold < 0 or self.min_score_threshold > 100:
                raise ValueError(
                    f"min_score_threshold must be between 0 and 100, got {self.min_score_threshold}"
                )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert parameters to dictionary for serialization.

        Returns:
            Dictionary representation of parameters
        """
        return {
            "dte_min": self.dte_min,
            "dte_max": self.dte_max,
            "spread_width": self.spread_width,
            "otm_percentage": self.otm_percentage,
            "generation_mode": self.generation_mode.value,
            "profit_target_pct": self.profit_target_pct,
            "support_buffer_pct": self.support_buffer_pct,
            "resistance_buffer_pct": self.resistance_buffer_pct,
            "min_iv_rank": self.min_iv_rank,
            "min_score_threshold": self.min_score_threshold,
            "source": self.source,
            "metadata": self.metadata,
        }


class ParameterBuilder:
    """
    Builder for creating StrategyParameters from various sources.

    This class provides factory methods to create parameters from:
    - Market condition reports (automated analysis)
    - Manual user input (UI or API)
    - Default configurations
    """

    @staticmethod
    def from_market_report(
        report: MarketConditionReport,
        generation_mode: GenerationMode = GenerationMode.STRICT,
        overrides: dict[str, Any] | None = None,
    ) -> StrategyParameters:
        """
        Build parameters from a market condition report.

        This method extracts relevant parameters from a market analysis report,
        applying defaults and overrides as needed. This is the primary method
        for automated strategy generation.

        Args:
            report: Market condition report from MarketAnalyzer
            generation_mode: Quality mode for generation (STRICT, RELAXED, FORCE)
            overrides: Optional dict of parameter overrides

        Returns:
            StrategyParameters configured from the report

        Example:
            >>> from services.market_data.analysis import MarketAnalyzer
            >>> analyzer = MarketAnalyzer(user)
            >>> report = await analyzer.a_analyze_market_conditions(user, "SPY", {})
            >>> params = ParameterBuilder.from_market_report(report)
        """
        overrides = overrides or {}

        # Extract IV rank for threshold (if available)
        iv_rank = report.iv_rank if hasattr(report, "iv_rank") else None

        # Build base parameters
        params_dict = {
            "dte_min": overrides.get("dte_min", 30),
            "dte_max": overrides.get("dte_max", 45),
            "spread_width": overrides.get("spread_width", 5),
            "otm_percentage": overrides.get("otm_percentage", 0.03),
            "generation_mode": generation_mode,
            "profit_target_pct": overrides.get("profit_target_pct", 50),
            "support_buffer_pct": overrides.get("support_buffer_pct", 2.0),
            "resistance_buffer_pct": overrides.get("resistance_buffer_pct", 2.0),
            "min_iv_rank": overrides.get("min_iv_rank"),  # None = use strategy default
            "min_score_threshold": overrides.get(
                "min_score_threshold"
            ),  # None = use strategy default
            "source": "market_report",
            "metadata": {
                "symbol": report.symbol,
                "current_price": report.current_price,
                "iv_rank": iv_rank,
                "market_stress": report.market_stress_level,
            },
        }

        logger.debug(
            f"Built parameters from market report for {report.symbol}: "
            f"DTE {params_dict['dte_min']}-{params_dict['dte_max']}, "
            f"width {params_dict['spread_width']}, "
            f"mode {generation_mode.value}"
        )

        return StrategyParameters(**params_dict)

    @staticmethod
    def manual(
        dte_min: int = 30,
        dte_max: int = 45,
        spread_width: int = 5,
        otm_percentage: float = 0.03,
        generation_mode: GenerationMode = GenerationMode.FORCE,
        **kwargs: Any,
    ) -> StrategyParameters:
        """
        Build parameters from manual user input.

        This method is used when the user specifies parameters directly
        through the UI or API, bypassing automated market analysis.
        Defaults to FORCE mode since manual input implies intent to generate.

        Args:
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            spread_width: Width of spread in points
            otm_percentage: Out-of-the-money percentage
            generation_mode: Quality mode (defaults to FORCE for manual)
            **kwargs: Additional parameters (profit_target_pct, buffers, etc.)

        Returns:
            StrategyParameters configured from manual input

        Example:
            >>> # User manually requests 60 DTE, $10 wide spread
            >>> params = ParameterBuilder.manual(
            ...     dte_min=55,
            ...     dte_max=65,
            ...     spread_width=10,
            ...     otm_percentage=0.05,
            ... )
        """
        # Copy metadata to prevent mutation of caller's dict
        metadata = kwargs.get("metadata", {})
        metadata_copy = dict(metadata) if metadata else {}

        params_dict = {
            "dte_min": dte_min,
            "dte_max": dte_max,
            "spread_width": spread_width,
            "otm_percentage": otm_percentage,
            "generation_mode": generation_mode,
            "profit_target_pct": kwargs.get("profit_target_pct", 50),
            "support_buffer_pct": kwargs.get("support_buffer_pct", 2.0),
            "resistance_buffer_pct": kwargs.get("resistance_buffer_pct", 2.0),
            "min_iv_rank": kwargs.get("min_iv_rank"),
            "min_score_threshold": kwargs.get("min_score_threshold"),
            "source": "manual",
            "metadata": metadata_copy,
        }

        logger.info(
            f"Created manual parameters: "
            f"DTE {dte_min}-{dte_max}, "
            f"width {spread_width}, "
            f"OTM {otm_percentage*100:.1f}%, "
            f"mode {generation_mode.value}"
        )

        return StrategyParameters(**params_dict)

    @staticmethod
    def defaults(
        generation_mode: GenerationMode = GenerationMode.STRICT,
    ) -> StrategyParameters:
        """
        Build parameters using system defaults.

        This is primarily used for testing and as a fallback when no
        market report or manual input is available.

        Args:
            generation_mode: Quality mode (defaults to STRICT)

        Returns:
            StrategyParameters with default values
        """
        return StrategyParameters(
            generation_mode=generation_mode,
            source="defaults",
        )
