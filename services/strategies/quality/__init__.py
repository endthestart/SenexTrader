"""
Quality scoring system for strategy generation.

This module provides multi-factor quality scoring for options strategies,
enabling the "always-generate" pattern where strategies are always created
with quality visibility rather than rejected silently.

Exports:
    QualityScore: Immutable dataclass representing strategy quality
    determine_quality_level: Convert numeric score to level string

Usage:
    from services.strategies.quality import QualityScore, determine_quality_level

    # Create from components
    quality = QualityScore.from_components(
        component_scores={
            "market_alignment": 35.0,
            "strike_deviation": 25.0,
            "dte_optimality": 18.0,
            "liquidity": 8.0,
        },
        warnings=["Low open interest"],
    )

    # Combine for multi-spread strategies
    combined = QualityScore.combine([put_quality, call_quality])
"""

from services.strategies.quality.score import QualityScore, determine_quality_level

__all__ = [
    "QualityScore",
    "determine_quality_level",
]
