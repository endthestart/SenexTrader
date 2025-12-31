"""
Volatility Analyzer Service - Unified volatility analysis.

Provides comprehensive volatility metrics combining:
- Historical volatility (HV) - realized price movement
- Implied volatility (IV) - market's volatility expectations
- HV/IV ratio - option pricing opportunities
- Volatility percentile - current vs historical range
- Volatility trend - increasing/decreasing

"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser

from services.core.logging import get_logger
from services.strategies.utils.scoring_utils import clamp_score

logger = get_logger(__name__)


@dataclass
class VolatilityAnalysis:
    """
    Container for comprehensive volatility analysis.

    Provides actionable insights for option trading decisions.
    """

    # Current Metrics
    historical_volatility: float  # Annualized HV decimal (e.g., 0.255 = 25.5%)
    implied_volatility: float  # Current IV decimal (e.g., 0.25 = 25%)
    hv_iv_ratio: float  # HV/IV ratio (1.0 = equal)

    # Historical Context
    iv_rank: float  # 0-100 percentile
    iv_percentile: float  # Alternative percentile calc

    # Derived Insights
    volatility_regime: str  # "low", "normal", "elevated", "extreme"
    premium_environment: str  # "cheap", "fair", "expensive"
    trend: str  # "increasing", "stable", "decreasing"

    # Trading Recommendations
    is_good_for_selling: bool  # True if favorable for premium selling
    is_good_for_buying: bool  # True if favorable for option buying
    recommendation_score: int  # 0-100 score for current conditions

    # Explanation
    summary: str  # Human-readable summary of conditions


class VolatilityAnalyzer:
    """
    Unified volatility analysis service.

    Combines multiple volatility metrics to provide actionable insights
    for option trading strategies.
    """

    def __init__(self, user: AbstractBaseUser):
        self.user = user

    async def analyze(
        self,
        symbol: str,
        historical_volatility: float,
        implied_volatility: float,
        iv_rank: float,
        iv_percentile: float,
    ) -> VolatilityAnalysis:
        """
        Perform comprehensive volatility analysis.

        Args:
            symbol: Underlying symbol
            historical_volatility: Annualized HV percentage (e.g., 25.5 for 25.5%)
            implied_volatility: Current IV percentage (e.g., 25.0 for 25%)
            iv_rank: IV rank (0-100 percentile)
            iv_percentile: IV percentile (alternative calculation)

        Returns:
            VolatilityAnalysis with comprehensive metrics and insights
        """
        # Calculate HV/IV ratio (both values in percentage format: 25.5 for 25.5%)
        # Ratio is unit-independent: 35.0 / 25.0 = 1.4 (same as 0.35 / 0.25 = 1.4)
        if implied_volatility > 0 and historical_volatility > 0:
            hv_iv_ratio = historical_volatility / implied_volatility
        else:
            hv_iv_ratio = 1.0

        # Determine volatility regime based on IV rank
        volatility_regime = self._classify_volatility_regime(iv_rank)

        # Determine premium environment based on HV/IV ratio
        premium_environment = self._classify_premium_environment(hv_iv_ratio)

        # Analyze volatility trend (simplified - could be enhanced with time series)
        trend = self._analyze_trend(hv_iv_ratio, iv_rank)

        # Determine if conditions are good for selling or buying
        is_good_for_selling = self._is_good_for_selling(hv_iv_ratio, iv_rank)
        is_good_for_buying = self._is_good_for_buying(hv_iv_ratio, iv_rank)

        # Calculate recommendation score
        recommendation_score = self._calculate_recommendation_score(
            hv_iv_ratio, iv_rank, volatility_regime
        )

        # Generate summary
        summary = self._generate_summary(
            symbol,
            hv_iv_ratio,
            iv_rank,
            volatility_regime,
            premium_environment,
            is_good_for_selling,
        )

        return VolatilityAnalysis(
            historical_volatility=historical_volatility,
            implied_volatility=implied_volatility,
            hv_iv_ratio=hv_iv_ratio,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            volatility_regime=volatility_regime,
            premium_environment=premium_environment,
            trend=trend,
            is_good_for_selling=is_good_for_selling,
            is_good_for_buying=is_good_for_buying,
            recommendation_score=recommendation_score,
            summary=summary,
        )

    def _classify_volatility_regime(self, iv_rank: float) -> str:
        """
        Classify volatility regime based on IV rank.

        Returns: "low", "normal", "elevated", "extreme"
        """
        if iv_rank < 20:
            return "low"
        if iv_rank < 50:
            return "normal"
        if iv_rank < 80:
            return "elevated"
        return "extreme"

    def _classify_premium_environment(self, hv_iv_ratio: float) -> str:
        """
        Classify premium environment based on HV/IV ratio.

        Returns: "cheap", "fair", "expensive"
        """
        if hv_iv_ratio > 1.2:
            return "cheap"  # IV low relative to realized
        if hv_iv_ratio < 0.8:
            return "expensive"  # IV high relative to realized
        return "fair"

    def _analyze_trend(self, hv_iv_ratio: float, iv_rank: float) -> str:
        """
        Analyze volatility trend (simplified version).

        A more sophisticated implementation would use time series data.

        Returns: "increasing", "stable", "decreasing"
        """
        # Simplified: use HV/IV ratio and IV rank as proxies
        if iv_rank > 70:
            return "increasing"
        if iv_rank < 30:
            return "decreasing"
        return "stable"

    def _is_good_for_selling(self, hv_iv_ratio: float, iv_rank: float) -> bool:
        """
        Determine if conditions are favorable for premium selling.

        Good for selling when:
        - IV is high relative to realized (HV/IV < 0.8)
        - IV rank is elevated (> 50)
        """
        return hv_iv_ratio < 0.8 and iv_rank > 50

    def _is_good_for_buying(self, hv_iv_ratio: float, iv_rank: float) -> bool:
        """
        Determine if conditions are favorable for option buying.

        Good for buying when:
        - IV is low relative to realized (HV/IV > 1.2)
        - IV rank is low (< 40)
        """
        return hv_iv_ratio > 1.2 and iv_rank < 40

    def _calculate_recommendation_score(
        self, hv_iv_ratio: float, iv_rank: float, volatility_regime: str
    ) -> int:
        """
        Calculate overall recommendation score (0-100) for current conditions.

        Higher score = better conditions for premium selling.
        """
        score = 50  # Base score

        # HV/IV ratio contribution
        if hv_iv_ratio < 0.7:
            score += 30  # Excellent for selling
        elif hv_iv_ratio < 0.8:
            score += 20  # Very good for selling
        elif hv_iv_ratio < 0.9:
            score += 10  # Good for selling
        elif hv_iv_ratio > 1.3:
            score -= 30  # Poor for selling
        elif hv_iv_ratio > 1.2:
            score -= 20  # Bad for selling
        elif hv_iv_ratio > 1.1:
            score -= 10  # Not ideal for selling

        # IV rank contribution
        if iv_rank > 80:
            score += 20
        elif iv_rank > 60:
            score += 15
        elif iv_rank > 40:
            score += 5
        elif iv_rank < 20:
            score -= 15
        elif iv_rank < 30:
            score -= 10

        # Volatility regime bonus/penalty
        if volatility_regime == "extreme":
            score += 10  # Extreme vol = good premiums
        elif volatility_regime == "low":
            score -= 10  # Low vol = poor premiums

        # Clamp to 0-100
        return clamp_score(score)

    def _generate_summary(
        self,
        symbol: str,
        hv_iv_ratio: float,
        iv_rank: float,
        volatility_regime: str,
        premium_environment: str,
        is_good_for_selling: bool,
    ) -> str:
        """Generate human-readable summary of volatility conditions."""
        # Build summary string
        parts = []

        # Volatility regime
        parts.append(f"{volatility_regime.title()} volatility (IV rank {iv_rank:.0f}%)")

        # Premium environment
        if premium_environment == "expensive":
            parts.append(f"options {premium_environment} (HV/IV {hv_iv_ratio:.2f})")
        else:
            parts.append(f"premiums {premium_environment} (HV/IV {hv_iv_ratio:.2f})")

        # Recommendation
        if is_good_for_selling:
            parts.append("EXCELLENT for premium selling")
        elif hv_iv_ratio < 0.9 and iv_rank > 40:
            parts.append("Good for credit strategies")
        elif hv_iv_ratio > 1.1 and iv_rank < 40:
            parts.append("Consider debit strategies")
        else:
            parts.append("Neutral conditions")

        return f"{symbol}: {' | '.join(parts)}"
