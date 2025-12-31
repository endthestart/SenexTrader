"""
QualityScore dataclass and level determination.

Provides the core quality scoring infrastructure used by all strategy builders.
"""

from __future__ import annotations

from dataclasses import dataclass


def determine_quality_level(score: float) -> str:
    """
    Determine quality level string from numeric score.

    Args:
        score: Quality score (0-100)

    Returns:
        Level string: "excellent", "good", "fair", or "poor"
    """
    if score >= 80.0:
        return "excellent"
    if score >= 60.0:
        return "good"
    if score >= 40.0:
        return "fair"
    return "poor"


@dataclass(frozen=True)
class QualityScore:
    """
    Immutable quality score for a strategy or strike selection.

    This dataclass represents the quality assessment of a strategy,
    supporting the "always-generate" pattern where strategies are
    created with quality visibility rather than rejected silently.

    Attributes:
        score: Overall quality score (0-100)
        level: Quality level ("excellent", "good", "fair", "poor")
        warnings: List of quality concern messages
        component_scores: Breakdown of score by component

    Example:
        >>> quality = QualityScore(
        ...     score=75.0,
        ...     level="good",
        ...     warnings=["Low open interest"],
        ...     component_scores={"liquidity": 60.0, "spread": 80.0},
        ... )
        >>> quality.score
        75.0
    """

    score: float
    level: str
    warnings: list[str]
    component_scores: dict[str, float]

    @classmethod
    def combine(cls, scores: list[QualityScore]) -> QualityScore:
        """
        Combine multiple QualityScores into one (for multi-spread strategies).

        Averages scores and merges warnings. Used when building strategies
        like Iron Condors that compose multiple spreads.

        Args:
            scores: List of QualityScore instances to combine

        Returns:
            Combined QualityScore with averaged scores and merged warnings

        Example:
            >>> put_quality = QualityScore(score=80.0, ...)
            >>> call_quality = QualityScore(score=60.0, ...)
            >>> combined = QualityScore.combine([put_quality, call_quality])
            >>> combined.score
            70.0
        """
        if not scores:
            return cls(
                score=0.0,
                level="poor",
                warnings=["No quality scores to combine"],
                component_scores={},
            )

        if len(scores) == 1:
            return scores[0]

        # Average the overall scores
        avg_score = sum(s.score for s in scores) / len(scores)

        # Merge all warnings (deduplicated)
        all_warnings: list[str] = []
        seen_warnings: set[str] = set()
        for s in scores:
            for warning in s.warnings:
                if warning not in seen_warnings:
                    all_warnings.append(warning)
                    seen_warnings.add(warning)

        # Average component scores
        component_keys: set[str] = set()
        for s in scores:
            component_keys.update(s.component_scores.keys())

        avg_components: dict[str, float] = {}
        for key in component_keys:
            values = [s.component_scores.get(key, 0.0) for s in scores if key in s.component_scores]
            if values:
                avg_components[key] = sum(values) / len(values)

        return cls(
            score=avg_score,
            level=determine_quality_level(avg_score),
            warnings=all_warnings,
            component_scores=avg_components,
        )

    @classmethod
    def minimum(cls, reason: str) -> QualityScore:
        """
        Create a minimum quality score with explanation.

        Used when quality cannot be assessed (e.g., no market data).

        Args:
            reason: Explanation for minimum score

        Returns:
            QualityScore with score=0, level="poor"
        """
        return cls(
            score=0.0,
            level="poor",
            warnings=[reason],
            component_scores={},
        )

    @classmethod
    def from_components(
        cls,
        component_scores: dict[str, float],
        warnings: list[str] | None = None,
    ) -> QualityScore:
        """
        Create QualityScore from component scores.

        Sums component scores to get overall score and determines level.

        Args:
            component_scores: Dict mapping component name to score
            warnings: Optional list of warning messages

        Returns:
            QualityScore with summed score

        Example:
            >>> quality = QualityScore.from_components(
            ...     component_scores={
            ...         "market_alignment": 35.0,  # max 40
            ...         "strike_deviation": 25.0,  # max 30
            ...         "dte_optimality": 15.0,    # max 20
            ...         "liquidity": 8.0,          # max 10
            ...     },
            ...     warnings=["Slightly wide spread"],
            ... )
            >>> quality.score
            83.0
        """
        total_score = sum(component_scores.values())
        # Clamp to 0-100 range
        total_score = max(0.0, min(100.0, total_score))

        return cls(
            score=total_score,
            level=determine_quality_level(total_score),
            warnings=warnings or [],
            component_scores=component_scores,
        )
