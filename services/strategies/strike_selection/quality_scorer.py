"""
Strike quality scoring for liquidity-aware strike selection.

Scores individual strikes based on:
- Liquidity (open interest)
- Spread (bid-ask)
- Activity (volume, last trade time)

Used by DeltaStrikeSelector to assess strike quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from services.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StrikeQualityMetrics:
    """
    Input metrics for evaluating strike quality.

    All fields are optional to support partial data scenarios.
    """

    open_interest: int | None = None
    bid: Decimal | float | None = None
    ask: Decimal | float | None = None
    volume: int | None = None
    last_trade_time: datetime | None = None
    delta: float | None = None
    implied_volatility: float | None = None


@dataclass(frozen=True)
class StrikeQualityResult:
    """
    Result of strike quality scoring.

    Attributes:
        score: Overall quality score (0-100)
        component_scores: Breakdown by component (liquidity, spread, activity)
        warnings: List of quality concerns
        level: Quality level string (excellent, good, fair, poor)
    """

    score: float
    component_scores: dict[str, float]
    warnings: list[str]
    level: str


class StrikeQualityScorer:
    """
    Score option strikes based on liquidity and market microstructure metrics.

    Weights can be customized for different strategy types (e.g., Senex Trident
    may weight liquidity higher due to 6 legs).

    Attributes:
        weights: Component weights (default: liquidity=0.40, spread=0.40, activity=0.20)
        MIN_OPEN_INTEREST: Threshold for acceptable open interest (default 500)
        MAX_SPREAD_PERCENT: Maximum acceptable bid-ask spread (default 10%)
        MIN_DAILY_VOLUME: Threshold for acceptable daily volume (default 50)

    Example:
        >>> scorer = StrikeQualityScorer()
        >>> metrics = StrikeQualityMetrics(
        ...     open_interest=1000,
        ...     bid=Decimal("1.20"),
        ...     ask=Decimal("1.25"),
        ...     volume=200,
        ... )
        >>> result = scorer.score_strike(metrics)
        >>> result.score
        85.0
    """

    MIN_OPEN_INTEREST = 500
    MAX_SPREAD_PERCENT = 0.10
    MIN_DAILY_VOLUME = 50

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {
            "liquidity": 0.40,
            "spread": 0.40,
            "activity": 0.20,
        }

    def score_strike(self, metrics: StrikeQualityMetrics) -> StrikeQualityResult:
        """
        Score a strike between 0-100 with component breakdown and warnings.

        Args:
            metrics: StrikeQualityMetrics with available data

        Returns:
            StrikeQualityResult with score, components, warnings, level
        """
        component_scores: dict[str, float] = {}
        warnings: list[str] = []

        # Score each component
        liquidity_score = self._score_liquidity(metrics.open_interest, warnings)
        component_scores["liquidity"] = liquidity_score

        spread_score = self._score_spread(metrics.bid, metrics.ask, warnings)
        component_scores["spread"] = spread_score

        activity_score = self._score_activity(
            metrics.volume, metrics.last_trade_time, warnings
        )
        component_scores["activity"] = activity_score

        # Calculate weighted total
        total_score = sum(
            component_scores[key] * self.weights.get(key, 0.0)
            for key in component_scores
        )

        # Determine quality level
        level = self._quality_level(total_score)

        # Add warnings for missing key data
        if metrics.delta is None:
            warnings.append("Missing delta data; selection uses theoretical model")
        if metrics.implied_volatility is None:
            warnings.append("Missing IV data; quality derived from streaming quotes only")

        return StrikeQualityResult(
            score=total_score,
            component_scores=component_scores,
            warnings=warnings,
            level=level,
        )

    def _score_liquidity(
        self, open_interest: int | None, warnings: list[str]
    ) -> float:
        """Score based on open interest (0-100)."""
        if open_interest is None:
            warnings.append("Open interest unavailable")
            return 40.0  # Partial credit

        if open_interest <= 0:
            warnings.append("Zero open interest")
            return 0.0

        if open_interest < self.MIN_OPEN_INTEREST:
            warnings.append(
                f"Low open interest: {open_interest} (<{self.MIN_OPEN_INTEREST})"
            )
            ratio = open_interest / self.MIN_OPEN_INTEREST
            return max(0.0, ratio * 50.0)

        # Scale 50-100 as OI increases beyond threshold
        bonus = min(50.0, (open_interest - self.MIN_OPEN_INTEREST) / 1000.0 * 50.0)
        return 50.0 + bonus

    def _score_spread(
        self,
        bid: Decimal | float | None,
        ask: Decimal | float | None,
        warnings: list[str],
    ) -> float:
        """Score based on bid-ask spread (0-100)."""
        if bid is None or ask is None:
            warnings.append("Missing bid/ask data")
            return 40.0  # Partial credit

        mid = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")
        if mid <= 0:
            warnings.append("Invalid mid price computed from bid/ask")
            return 0.0

        spread_pct = (Decimal(str(ask)) - Decimal(str(bid))) / mid
        spread_float = float(spread_pct)

        if spread_float > self.MAX_SPREAD_PERCENT:
            warnings.append(f"Wide spread: {spread_float:.1%}")
            penalty = min(100.0, spread_float * 1000.0)
            return max(0.0, 100.0 - penalty)

        return max(0.0, 100.0 - spread_float * 500.0)

    def _score_activity(
        self,
        volume: int | None,
        last_trade_time: datetime | None,
        warnings: list[str],
    ) -> float:
        """Score based on volume and trade recency (0-100)."""
        if volume is None:
            warnings.append("Missing volume data")
            return 40.0  # Partial credit

        if volume < self.MIN_DAILY_VOLUME:
            warnings.append(f"Low daily volume: {volume}")
            ratio = volume / self.MIN_DAILY_VOLUME
            return max(0.0, ratio * 80.0)

        score = min(100.0, volume / 500.0 * 100.0)

        # Penalize stale trades
        if last_trade_time:
            reference = datetime.now(UTC)
            candidate_time = (
                last_trade_time
                if last_trade_time.tzinfo
                else last_trade_time.replace(tzinfo=UTC)
            )
            age_minutes = (reference - candidate_time).total_seconds() / 60.0
            if age_minutes > 120:
                warnings.append("Last trade was over 2 hours ago")
                score *= 0.8

        return score

    @staticmethod
    def _quality_level(score: float) -> str:
        """Convert score to quality level string."""
        if score >= 80:
            return "excellent"
        if score >= 60:
            return "good"
        if score >= 40:
            return "fair"
        return "poor"
