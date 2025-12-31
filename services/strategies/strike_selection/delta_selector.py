"""
Delta-based strike selector.

Provides delta-targeted strike selection with:
- Streaming Greeks primary data source
- Black-Scholes model fallback
- Quality scoring integration
- Spread width resolution

This replaces the delta selection in StrikeOptimizer, providing a cleaner
interface for the unified strategy architecture.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

from services.core.logging import get_logger
from services.market_data.greeks_fetcher import GreeksFetcher
from services.strategies.strike_selection.quality_scorer import (
    StrikeQualityMetrics,
    StrikeQualityResult,
    StrikeQualityScorer,
)

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class _StrikeCandidate:
    """Internal candidate for strike selection."""

    strike: Decimal
    occ_symbol: str | None = None


@dataclass
class DeltaSelectionResult:
    """
    Result of delta-based strike selection.

    Attributes:
        strikes: Dict with strike keys (e.g., {"short_put": 580, "long_put": 575})
        delta: Actual delta of selected short strike
        delta_source: Source of delta ("streaming", "model", "database")
        quality: Quality assessment of selected strikes
    """

    strikes: dict[str, Decimal]
    delta: float
    delta_source: str
    quality: StrikeQualityResult


class DeltaStrikeSelector:
    """
    Select strikes by target delta with quality scoring.

    Uses GreeksFetcher for streaming/historical Greeks, falls back to
    Black-Scholes model when Greeks unavailable.

    Attributes:
        user: Django user for API access
        min_quality_score: Minimum quality to accept without warning (default 40)
        greeks_fetcher: GreeksFetcher instance
        quality_scorer: StrikeQualityScorer instance

    Example:
        >>> selector = DeltaStrikeSelector(user)
        >>> result = await selector.select_strikes(
        ...     symbol="SPY",
        ...     expiration=date(2025, 12, 19),
        ...     chain_strikes=chain,
        ...     spread_type="bull_put",
        ...     spread_width=5,
        ...     target_delta=0.25,
        ...     current_price=Decimal("595"),
        ... )
        >>> result.strikes
        {"short_put": Decimal("580"), "long_put": Decimal("575")}
    """

    def __init__(
        self,
        user,
        min_quality_score: float = 40.0,
        greeks_fetcher: GreeksFetcher | None = None,
        quality_scorer: StrikeQualityScorer | None = None,
    ) -> None:
        self.user = user
        self.min_quality_score = min_quality_score
        self.greeks_fetcher = greeks_fetcher or GreeksFetcher(user)
        self.quality_scorer = quality_scorer or StrikeQualityScorer()

    async def select_strikes(
        self,
        symbol: str,
        expiration: date,
        chain_strikes: list[dict],
        spread_type: str,
        spread_width: int,
        target_delta: float,
        current_price: Decimal,
        market_context: dict | None = None,
        max_candidates: int = 18,
    ) -> DeltaSelectionResult | None:
        """
        Select strikes using delta targeting with quality scoring.

        Args:
            symbol: Underlying symbol
            expiration: Option expiration date
            chain_strikes: List of strike dicts from option chain
            spread_type: "bull_put", "bear_call", etc.
            spread_width: Width of spread in points
            target_delta: Target delta for short strike (e.g., 0.25)
            current_price: Current underlying price
            market_context: Optional market context (IV, stress level)
            max_candidates: Max strikes to evaluate (default 18)

        Returns:
            DeltaSelectionResult on success, None if no valid selection
        """
        option_type = "put" if "put" in spread_type else "call"
        candidates = self._build_candidates(chain_strikes, option_type)

        if not candidates:
            logger.warning(f"No strike candidates available for {option_type}")
            return None

        sorted_candidates = self._prioritize_candidates(
            current_price, candidates, max_candidates
        )
        if not sorted_candidates:
            logger.warning("No prioritized strike candidates computed")
            return None

        market_context = market_context or {}

        # Fetch Greeks for all candidates
        greeks_map = await self.greeks_fetcher.fetch_greeks(
            symbol,
            expiration,
            [c.occ_symbol for c in sorted_candidates if c.occ_symbol],
            market_context.get("market_stress_level"),
        )

        # Calculate time to expiration
        dte_days = max((expiration - timezone.now().date()).days, 1)
        time_years = dte_days / 365.0
        implied_vol = self._normalize_volatility(market_context.get("current_iv"))

        # Find best strike by delta
        best: _StrikeCandidate | None = None
        best_error: float | None = None
        delta_sources: dict[Decimal, tuple[float, str]] = {}

        for candidate in sorted_candidates:
            delta_value, delta_source = self._resolve_delta(
                candidate,
                greeks_map,
                target_delta,
                current_price,
                option_type,
                time_years,
                implied_vol,
            )
            if delta_value is None:
                continue

            delta_sources[candidate.strike] = (delta_value, delta_source)
            error = abs(abs(delta_value) - target_delta)

            if best is None or error < best_error:
                best = candidate
                best_error = error

        if not best:
            logger.warning("Failed to compute delta-based strike, no valid candidates")
            return None

        # Find compliment leg
        long_strike = self._resolve_long_strike(
            option_type,
            best.strike,
            spread_width,
            [cand.strike for cand in candidates],
        )
        if long_strike is None:
            logger.warning(f"Cannot find compliment leg for spread width {spread_width}")
            return None

        # Get delta info for selected strike
        delta_value, delta_source = delta_sources.get(best.strike, (0.0, "model"))

        # Score quality
        quality = self._score_strike(best, delta_value, greeks_map)

        if quality.score < self.min_quality_score:
            logger.warning(
                f"Strike quality {quality.score:.1f} ({quality.level}) below threshold "
                f"for {best.strike}. Warnings: {quality.warnings}"
            )

        strikes = self._format_strike_dict(option_type, best.strike, long_strike)

        return DeltaSelectionResult(
            strikes=strikes,
            delta=delta_value,
            delta_source=delta_source,
            quality=quality,
        )

    def _build_candidates(
        self,
        chain_strikes: list[dict],
        option_type: str,
    ) -> list[_StrikeCandidate]:
        """Build candidate list from chain strikes."""
        candidates: list[_StrikeCandidate] = []
        option_key = "put" if option_type == "put" else "call"

        for strike_entry in chain_strikes:
            strike_price = strike_entry.get("strike_price")
            occ_symbol = strike_entry.get(option_key)

            if not strike_price:
                continue

            try:
                price_decimal = Decimal(str(strike_price))
            except Exception:
                continue

            candidates.append(
                _StrikeCandidate(strike=price_decimal, occ_symbol=occ_symbol)
            )

        return candidates

    @staticmethod
    def _prioritize_candidates(
        current_price: Decimal,
        candidates: list[_StrikeCandidate],
        limit: int,
    ) -> list[_StrikeCandidate]:
        """Sort candidates by proximity to current price and limit."""
        sorted_candidates = sorted(
            candidates,
            key=lambda c: abs(c.strike - current_price),
        )
        return sorted_candidates[:limit]

    def _resolve_delta(
        self,
        candidate: _StrikeCandidate,
        greeks_map: dict[str, dict],
        target_delta: float,
        current_price: Decimal,
        option_type: str,
        time_years: float,
        implied_vol: float,
    ) -> tuple[float | None, str]:
        """Resolve delta from Greeks or model."""
        # Try streaming/cached Greeks first
        if candidate.occ_symbol and candidate.occ_symbol in greeks_map:
            data = greeks_map[candidate.occ_symbol]
            if data.get("delta") is not None:
                return float(data["delta"]), data.get("source", "streaming")

        # Fall back to Black-Scholes model
        theo_delta = self._black_scholes_delta(
            float(current_price),
            float(candidate.strike),
            implied_vol,
            time_years,
            option_type,
        )

        if theo_delta is None:
            return None, "unknown"

        # Align sign direction
        if option_type == "put" and theo_delta > 0:
            theo_delta = -theo_delta
        if option_type == "call" and theo_delta < 0:
            theo_delta = -theo_delta

        return theo_delta, "model"

    @staticmethod
    def _black_scholes_delta(
        spot: float,
        strike: float,
        volatility: float,
        time_years: float,
        option_type: str,
        risk_free_rate: float = 0.02,
    ) -> float | None:
        """Calculate Black-Scholes delta."""
        if spot <= 0 or strike <= 0 or volatility <= 0 or time_years <= 0:
            return None

        vol = max(volatility, 0.01)

        try:
            d1 = (
                math.log(spot / strike)
                + (risk_free_rate + 0.5 * vol * vol) * time_years
            ) / (vol * math.sqrt(time_years))
        except ValueError:
            return None

        # Standard normal CDF approximation
        nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))

        if option_type == "call":
            return nd1
        return nd1 - 1.0

    @staticmethod
    def _normalize_volatility(volatility: float | None) -> float:
        """Normalize volatility to decimal format."""
        if volatility is None:
            return 0.25  # Default

        # If > 1, assume percentage format
        if volatility > 1:
            return float(volatility) / 100.0

        return max(float(volatility), 0.10)  # Floor at 10%

    @staticmethod
    def _resolve_long_strike(
        option_type: str,
        short_strike: Decimal,
        spread_width: int,
        available: Iterable[Decimal],
    ) -> Decimal | None:
        """Find long strike for spread."""
        target = (
            short_strike - Decimal(str(spread_width))
            if option_type == "put"
            else short_strike + Decimal(str(spread_width))
        )

        available_sorted = sorted(set(available))

        # Prefer exact match
        if target in available_sorted:
            return target

        # Find nearest in correct direction
        if option_type == "put":
            candidates = [s for s in available_sorted if s < short_strike]
            return max(candidates) if candidates else None

        candidates = [s for s in available_sorted if s > short_strike]
        return min(candidates) if candidates else None

    def _score_strike(
        self,
        candidate: _StrikeCandidate,
        delta_value: float,
        greeks_map: dict[str, dict],
    ) -> StrikeQualityResult:
        """Score strike quality using available data."""
        # Get Greeks data if available
        greeks_data = {}
        if candidate.occ_symbol and candidate.occ_symbol in greeks_map:
            greeks_data = greeks_map[candidate.occ_symbol]

        metrics = StrikeQualityMetrics(
            open_interest=greeks_data.get("open_interest"),
            bid=greeks_data.get("bid"),
            ask=greeks_data.get("ask"),
            volume=greeks_data.get("volume"),
            last_trade_time=greeks_data.get("last_trade_time"),
            delta=delta_value,
            implied_volatility=greeks_data.get("implied_volatility"),
        )

        return self.quality_scorer.score_strike(metrics)

    @staticmethod
    def _format_strike_dict(
        option_type: str,
        short_strike: Decimal,
        long_strike: Decimal,
    ) -> dict[str, Decimal]:
        """Format strikes into result dict."""
        if option_type == "put":
            return {"short_put": short_strike, "long_put": long_strike}
        return {"short_call": short_strike, "long_call": long_strike}
