"""
Strike selection infrastructure for delta-based strategy generation.

Provides quality-aware delta targeting for strike selection:
- DeltaStrikeSelector: Main selector using streaming Greeks + model fallback
- StrikeQualityScorer: Liquidity-based quality scoring
- StrikeQualityMetrics/Result: Data structures for quality assessment

Usage:
    from services.strategies.strike_selection import (
        DeltaStrikeSelector,
        DeltaSelectionResult,
        StrikeQualityScorer,
        StrikeQualityMetrics,
        StrikeQualityResult,
    )

    selector = DeltaStrikeSelector(user)
    result = await selector.select_strikes(
        symbol="SPY",
        expiration=date(2025, 12, 19),
        chain_strikes=chain,
        spread_type="bull_put",
        spread_width=5,
        target_delta=0.25,
        current_price=Decimal("595"),
    )
"""

from services.strategies.strike_selection.delta_selector import (
    DeltaSelectionResult,
    DeltaStrikeSelector,
)
from services.strategies.strike_selection.quality_scorer import (
    StrikeQualityMetrics,
    StrikeQualityResult,
    StrikeQualityScorer,
)

__all__ = [
    "DeltaSelectionResult",
    "DeltaStrikeSelector",
    "StrikeQualityMetrics",
    "StrikeQualityResult",
    "StrikeQualityScorer",
]
