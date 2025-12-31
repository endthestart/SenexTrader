"""
Quality scoring calculators.

Provides individual scoring functions for different quality dimensions:
- Market alignment (0-40 points): Strategy direction vs market trend
- Strike deviation (0-30 points): Selected vs ideal strikes
- DTE optimality (0-20 points): Actual vs target DTE
- Liquidity (0-10 points): Bid-ask spread, volume, open interest

Each calculator returns (score, warnings) tuple, following the
"always-generate" pattern by never returning None.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal


def calculate_market_alignment_score(
    strategy_direction: Literal["bullish", "bearish"],
    market_trend: str,
    rsi: float | None = None,
    iv_rank: float | None = None,
) -> tuple[float, list[str]]:
    """
    Calculate market alignment score (0-40 points).

    Measures how well current market conditions align with the strategy's
    directional bias and volatility assumptions.

    Scoring breakdown:
    - Trend alignment: 0-25 points
    - RSI confirmation: 0-10 points
    - IV rank suitability: 0-5 points (credit spreads prefer higher IV)

    Args:
        strategy_direction: Strategy bias ("bullish" or "bearish")
        market_trend: Current market trend (e.g., "bullish", "bearish", "neutral")
        rsi: RSI value (0-100), optional
        iv_rank: Implied volatility rank (0-100), optional

    Returns:
        Tuple of (score, warnings)
    """
    score = 0.0
    warnings: list[str] = []

    # Normalize market_trend to canonical directions
    normalized_trend = "neutral"
    market_trend_lower = market_trend.lower()
    if "bullish" in market_trend_lower:
        normalized_trend = "bullish"
    elif "bearish" in market_trend_lower:
        normalized_trend = "bearish"

    # Trend alignment (0-25 points)
    if normalized_trend == strategy_direction:
        score += 25.0
    elif normalized_trend == "neutral":
        score += 15.0
    else:
        score += 5.0
        warnings.append(f"Counter-trend: {strategy_direction} strategy in {normalized_trend} market")

    # RSI confirmation (0-10 points)
    if rsi is not None:
        if strategy_direction == "bullish":
            if rsi >= 50:
                score += 10.0
            elif rsi >= 40:
                score += 7.0
            elif rsi >= 30:
                score += 4.0
            else:
                warnings.append(f"RSI {rsi:.0f} indicates oversold - high risk for bullish strategy")
        elif rsi <= 50:
            score += 10.0
        elif rsi <= 60:
            score += 7.0
        elif rsi <= 70:
            score += 4.0
        else:
            warnings.append(f"RSI {rsi:.0f} indicates overbought - high risk for bearish strategy")
    else:
        score += 7.0  # Partial credit
        warnings.append("RSI data unavailable")

    # IV rank suitability (0-5 points)
    if iv_rank is not None:
        if iv_rank >= 50:
            score += 5.0
        elif iv_rank >= 30:
            score += 3.0
        elif iv_rank >= 15:
            score += 1.0
        # Low IV gets 0 points (poor for credit spreads)
    else:
        score += 3.0  # Partial credit
        warnings.append("IV rank data unavailable")

    return min(score, 40.0), warnings


def calculate_strike_deviation_score(
    ideal_short_strike: Decimal,
    selected_short_strike: Decimal,
    ideal_long_strike: Decimal,
    selected_long_strike: Decimal,
) -> tuple[float, list[str]]:
    """
    Calculate strike deviation score (0-30 points).

    Measures how close selected strikes are to ideal calculated strikes.
    Short strike weighted more heavily (20 points) vs long (10 points).

    Args:
        ideal_short_strike: Theoretical ideal short strike
        selected_short_strike: Actual selected short strike
        ideal_long_strike: Theoretical ideal long strike
        selected_long_strike: Actual selected long strike

    Returns:
        Tuple of (score, warnings)
    """
    warnings: list[str] = []

    def deviation_score(ideal: Decimal, actual: Decimal, max_points: float) -> float:
        if ideal == 0:
            return 0.0
        deviation_pct = abs(float((actual - ideal) / ideal)) * 100

        if deviation_pct <= 1.0:
            return max_points
        if deviation_pct <= 3.0:
            return max_points * 0.8
        if deviation_pct <= 5.0:
            return max_points * 0.6
        if deviation_pct <= 10.0:
            return max_points * 0.4
        if deviation_pct <= 15.0:
            return max_points * 0.2
        return 0.0

    short_score = deviation_score(ideal_short_strike, selected_short_strike, 20.0)
    long_score = deviation_score(ideal_long_strike, selected_long_strike, 10.0)

    # Add warnings for large deviations
    if ideal_short_strike != 0:
        short_deviation = abs(float((selected_short_strike - ideal_short_strike) / ideal_short_strike)) * 100
        if short_deviation > 5.0:
            warnings.append(f"Short strike {short_deviation:.1f}% from ideal")

    if ideal_long_strike != 0:
        long_deviation = abs(float((selected_long_strike - ideal_long_strike) / ideal_long_strike)) * 100
        if long_deviation > 5.0:
            warnings.append(f"Long strike {long_deviation:.1f}% from ideal")

    return short_score + long_score, warnings


def calculate_dte_optimality_score(
    target_dte: int,
    actual_dte: int,
) -> tuple[float, list[str]]:
    """
    Calculate DTE optimality score (0-20 points).

    Measures how close selected expiration is to target DTE.

    Args:
        target_dte: Target days to expiration
        actual_dte: Actual days to expiration

    Returns:
        Tuple of (score, warnings)
    """
    warnings: list[str] = []
    dte_diff = abs(actual_dte - target_dte)

    if dte_diff == 0:
        score = 20.0
    elif dte_diff <= 5:
        score = 20.0 - (dte_diff / 5.0 * 2.0)
    elif dte_diff <= 10:
        score = 18.0 - ((dte_diff - 5) / 5.0 * 3.0)
    elif dte_diff <= 15:
        score = 15.0 - ((dte_diff - 10) / 5.0 * 5.0)
    else:
        score = max(0.0, 10.0 - ((dte_diff - 15) / 15.0 * 10.0))
        warnings.append(f"DTE {actual_dte} is {dte_diff} days from target {target_dte}")

    return score, warnings


def calculate_liquidity_score(
    bid: Decimal | None = None,
    ask: Decimal | None = None,
    volume: int | None = None,
    open_interest: int | None = None,
) -> tuple[float, list[str]]:
    """
    Calculate liquidity score (0-10 points).

    Measures trading liquidity based on spread, volume, and open interest.

    Scoring breakdown:
    - Bid-ask spread: 0-6 points
    - Volume: 0-2 points
    - Open interest: 0-2 points

    Args:
        bid: Bid price
        ask: Ask price
        volume: Trading volume
        open_interest: Open interest

    Returns:
        Tuple of (score, warnings)
    """
    score = 0.0
    warnings: list[str] = []

    # Bid-ask spread score (0-6 points)
    if bid is not None and ask is not None and bid > 0:
        spread_pct = float((ask - bid) / bid) * 100
        if spread_pct <= 2.0:
            score += 6.0
        elif spread_pct <= 5.0:
            score += 4.0
        elif spread_pct <= 10.0:
            score += 2.0
        else:
            warnings.append(f"Wide spread: {spread_pct:.1f}%")
    else:
        score += 3.0  # Partial credit
        if bid is None or ask is None:
            warnings.append("Missing bid/ask data")

    # Volume score (0-2 points)
    if volume is not None:
        if volume >= 100:
            score += 2.0
        elif volume >= 50:
            score += 1.5
        elif volume >= 10:
            score += 1.0
        else:
            warnings.append(f"Low volume: {volume}")
    else:
        score += 1.0  # Partial credit
        warnings.append("Missing volume data")

    # Open interest score (0-2 points)
    if open_interest is not None:
        if open_interest >= 500:
            score += 2.0
        elif open_interest >= 100:
            score += 1.5
        elif open_interest >= 10:
            score += 1.0
        else:
            warnings.append(f"Low open interest: {open_interest}")
    else:
        score += 1.0  # Partial credit
        warnings.append("Missing open interest data")

    return score, warnings
