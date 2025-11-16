"""
Scoring utilities for strategy scoring calculations.

Provides shared utilities for normalizing and capping strategy scores.
"""


def clamp_score(score: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    """
    Clamp score to valid range (0-100 by default).

    Args:
        score: Raw score value
        min_value: Minimum allowed value (default 0.0)
        max_value: Maximum allowed value (default 100.0)

    Returns:
        float: Clamped score within [min_value, max_value]

    Example:
        >>> clamp_score(150.0)
        100.0
        >>> clamp_score(-10.0)
        0.0
        >>> clamp_score(42.5)
        42.5
    """
    return max(min_value, min(max_value, score))
