"""
Market Analysis Service for Senex Trader

Implements simple market analysis for the Senex Trident strategy including:
- Bollinger Bands (20-period SMA, 2 std dev)
- Range-bound market detection
- Pure Python implementation (no pandas/numpy dependencies)
- Epic 32: Enhanced context fields (regime, extremes, momentum)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from services.market_data.utils.indicator_utils import (
    calculate_bollinger_bands,
)
from services.market_data.utils.indicator_utils import (
    is_near_bollinger_band as check_near_band,
)

logger = get_logger(__name__)


class RegimeType(str, Enum):
    """
    Market regime classification.

    Inherits from str for JSON compatibility (no custom serialization needed).
    """

    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    CRISIS = "crisis"


class MomentumSignal(str, Enum):
    """
    Momentum signal classification.

    Inherits from str for JSON compatibility (no custom serialization needed).
    """

    CONTINUATION = "continuation"
    EXHAUSTION = "exhaustion"
    UNCLEAR = "unclear"


@dataclass
class MarketConditionReport:
    """
    Container for market condition analysis results.

    This is pure data - no business logic.
    Strategies score this data to determine appropriateness.
    """

    # Symbol
    symbol: str  # Underlying symbol (e.g., "SPY", "QQQ")

    # Price Information
    current_price: float  # Current underlying price
    open_price: float = 0.0  # Today's open price

    # Technical Indicators
    data_available: bool = True  # FALSE = insufficient data for analysis
    rsi: float = 50.0  # 0-100
    macd_signal: str = "neutral"  # 'bullish', 'bearish', 'neutral'
    bollinger_position: str = "within_bands"  # 'above_upper', 'within_bands', 'below_lower'
    sma_20: float = 0.0
    support_level: float | None = None
    resistance_level: float | None = None

    # Trend Strength (Epic 05, Task 001)
    adx: float | None = None  # 0-100 scale, None if unavailable
    trend_strength: str = "weak"  # "weak", "moderate", "strong"

    # Volatility Analysis (Epic 05, Task 002-003)
    historical_volatility: float = 0.0  # Annualized percentage (e.g., 25.5 for 25.5%)
    hv_iv_ratio: float = 1.0  # HV/IV ratio (1.0 = equal, <0.8 = IV high, >1.2 = IV low)

    # Range-Bound Detection (price-based)
    is_range_bound: bool = False
    range_bound_days: int = 0

    # IV (Implied Volatility) Metrics
    current_iv: float = 0.0  # Decimal format (e.g., 0.285 for 28.5%)
    iv_rank: float = 50.0  # 0-100 percentile (from TastyTrade API)
    iv_percentile: float = 50.0  # Alternative calculation

    # Market Stress
    market_stress_level: float = 0.0  # 0-100
    recent_move_pct: float = 0.0  # Recent price move percentage

    # Market Context (Epic 32 - Enhanced regime/extreme/momentum detection)
    # Regime Detection (Task 004)
    regime_primary: RegimeType | None = None  # Primary market regime
    regime_confidence: float = 0.0  # Confidence in regime classification (0-100)

    # Extreme Detection (Task 005)
    is_overbought: bool = False  # Multiple overbought signals present
    overbought_warnings: int = 0  # Count of overbought indicators (3+ = extreme)
    is_oversold: bool = False  # Multiple oversold signals present
    oversold_warnings: int = 0  # Count of oversold indicators (3+ = extreme)

    # Momentum Assessment (Task 006)
    momentum_signal: MomentumSignal = MomentumSignal.UNCLEAR  # Continuation vs exhaustion
    momentum_confidence: float = 0.0  # Confidence in momentum classification (0-100)

    # Data Quality
    is_data_stale: bool = False
    last_update: datetime | None = None

    # Hard No-Trade Flags (applicable to ALL strategies)
    no_trade_reasons: list[str] = field(default_factory=list)

    # Epic 22 Task 016: Earnings Information
    has_upcoming_earnings: bool = False
    earnings_date: datetime | None = None
    days_until_earnings: int | None = None
    earnings_within_danger_window: bool = False

    # Epic 22 Task 017: Dividend Information
    has_upcoming_dividend: bool = False
    dividend_ex_date: datetime | None = None
    dividend_next_date: datetime | None = None
    days_until_dividend: int | None = None
    dividend_within_risk_window: bool = False

    # Epic 22 Task 018: Beta (for beta-weighted delta calculations)
    beta: float | None = None

    def __post_init__(self):
        """Post-initialization to derive calculated fields from raw data."""
        # Classify trend strength based on ADX value (only if available)
        if self.adx is not None:
            if self.adx > 30:
                self.trend_strength = "strong"
            elif self.adx > 20:
                self.trend_strength = "moderate"
            else:
                self.trend_strength = "weak"
        else:
            # No ADX data available - default to weak
            self.trend_strength = "weak"

        # Calculate HV/IV ratio (Epic 05, Task 003)
        # Avoid division by zero - use current_iv as denominator
        if self.current_iv > 0 and self.historical_volatility and self.historical_volatility > 0:
            # Both current_iv and historical_volatility are in percentage format (28.5 for 28.5%)
            # Direct division produces correct ratio (e.g., 25.5 / 28.5 = 0.894)
            # Ratio is unit-independent, so percentage format works correctly
            self.hv_iv_ratio = self.historical_volatility / self.current_iv
        else:
            self.hv_iv_ratio = 1.0  # Neutral if data unavailable

        # Task 004: Regime Detection
        self._detect_regime()

        # Task 005: Extreme Detection (overbought/oversold with warning counts)
        self._detect_extremes()

        # Task 006: Momentum Assessment (continuation vs exhaustion)
        self._detect_momentum()

    def _detect_regime(self) -> None:
        """
        Epic 32 Task 004: Detect market regime (bull/bear/range/high-vol/crisis).

        Uses ONLY currently available data:
        - Price vs SMA (trend direction)
        - ADX (trend strength)
        - IV rank (volatility level)
        - Market stress (crisis detection)
        """
        confidence = 0.0

        # Crisis detection (market stress > 80)
        if self.market_stress_level >= 80:
            self.regime_primary = RegimeType.CRISIS
            self.regime_confidence = min(self.market_stress_level, 100.0)
            return

        # High volatility regime (IV rank > 75)
        if self.iv_rank >= 75:
            self.regime_primary = RegimeType.HIGH_VOL
            self.regime_confidence = min(self.iv_rank, 100.0)
            return

        # Range-bound detection (already calculated)
        if self.is_range_bound:
            self.regime_primary = RegimeType.RANGE
            # Confidence based on how long it's been range-bound
            self.regime_confidence = min(50.0 + (self.range_bound_days * 10), 100.0)
            return

        # Trend-based regime (requires strong trend)
        if self.trend_strength == "strong":
            if self.macd_signal in ["bullish", "strong_bullish"]:
                self.regime_primary = RegimeType.BULL
                confidence = 60.0
                # Boost confidence if ADX confirms
                if self.adx and self.adx > 30:
                    confidence += 20.0
                self.regime_confidence = min(confidence, 100.0)
                return
            if self.macd_signal in ["bearish", "strong_bearish"]:
                self.regime_primary = RegimeType.BEAR
                confidence = 60.0
                # Boost confidence if ADX confirms
                if self.adx and self.adx > 30:
                    confidence += 20.0
                self.regime_confidence = min(confidence, 100.0)
                return

        # No clear regime
        self.regime_primary = None
        self.regime_confidence = 0.0

    def _detect_extremes(self) -> None:
        """
        Epic 32 Task 005: Detect overbought/oversold extremes with warning counts.

        Uses ONLY existing indicators:
        - RSI (>70 overbought, <30 oversold)
        - Bollinger position
        - Price vs SMA extension
        - Volume (if available)

        3+ warnings = extreme condition flagged
        """
        overbought_count = 0
        oversold_count = 0

        # RSI signals
        if self.rsi > 70:
            overbought_count += 1
        if self.rsi > 80:
            overbought_count += 1  # Extra warning for extreme RSI
        if self.rsi < 30:
            oversold_count += 1
        if self.rsi < 20:
            oversold_count += 1  # Extra warning for extreme RSI

        # Bollinger Band position
        if self.bollinger_position == "above_upper":
            overbought_count += 1
        if self.bollinger_position == "below_lower":
            oversold_count += 1

        # Price extension from SMA (if SMA available)
        if self.sma_20 > 0:
            extension_pct = ((self.current_price - self.sma_20) / self.sma_20) * 100
            if extension_pct > 5.0:  # >5% above SMA
                overbought_count += 1
            if extension_pct < -5.0:  # >5% below SMA
                oversold_count += 1

        # Update fields
        self.overbought_warnings = overbought_count
        self.oversold_warnings = oversold_count
        self.is_overbought = overbought_count >= 3
        self.is_oversold = oversold_count >= 3

    def _detect_momentum(self) -> None:
        """
        Epic 32 Task 006: Assess momentum (continuation vs exhaustion).

        Uses ONLY available data:
        - RSI divergence from trend
        - Trend strength (ADX)
        - Extreme conditions

        Returns:
        - CONTINUATION: Strong trend with room to run
        - EXHAUSTION: Extreme conditions suggest reversal
        - UNCLEAR: Insufficient data or mixed signals
        """
        confidence = 0.0

        # Exhaustion signals (extreme + overbought/oversold)
        if (self.is_overbought or self.is_oversold) and self.trend_strength == "strong":
            # Strong trend but extreme conditions = exhaustion
            self.momentum_signal = MomentumSignal.EXHAUSTION
            confidence = 50.0 + (min(max(self.overbought_warnings, self.oversold_warnings), 5) * 10)
            self.momentum_confidence = min(confidence, 100.0)
            return

        # Continuation signals (strong trend, NOT extreme)
        if self.trend_strength == "strong":
            if not self.is_overbought and not self.is_oversold:
                self.momentum_signal = MomentumSignal.CONTINUATION
                confidence = 60.0
                # Boost if ADX is very strong
                if self.adx and self.adx > 40:
                    confidence += 20.0
                self.momentum_confidence = min(confidence, 100.0)
                return

        # No clear momentum signal
        self.momentum_signal = MomentumSignal.UNCLEAR
        self.momentum_confidence = 0.0

    def can_trade(self) -> bool:
        """
        Check if ANY strategy can trade.

        Hard stops that apply to all strategies:
        - Stale data
        - Exchange closed
        - System errors

        Returns:
            True if trading is possible, False if hard stop
        """
        return len(self.no_trade_reasons) == 0

    def get_no_trade_explanation(self) -> str:
        """Get human-readable explanation for no-trade condition"""
        if not self.no_trade_reasons:
            return ""
        return f"No trade: {', '.join(self.no_trade_reasons)}"


class MarketAnalyzer:
    """SIMPLE market analysis for Senex Trident strategy"""

    # Configuration constants (from MarketConditionValidator)
    MIN_IV_RANK_DEFAULT: int = 25
    RANGE_BOUND_DAYS_THRESHOLD: int = 3
    LARGE_MOVE_PCT_THRESHOLD: float = 3.0
    MARKET_STRESS_THRESHOLD: int = 80
    DATA_STALENESS_MINUTES: int = 5

    def __init__(self, user=None):
        self.user = user  # Required for MarketDataService API access

        # Initialize MarketDataService for quote and metrics access
        if user:
            from services.market_data.service import MarketDataService

            self.market_service = MarketDataService(user)
        else:
            self.market_service = None

        self.bollinger_period = 20
        self.bollinger_std = 2.0
        self.range_bound_threshold = 3  # days
        self.range_bound_points = 2.0  # price range

    def calculate_bollinger_bands(self, prices: list) -> dict:
        """
        Calculate Bollinger Bands using centralized utility.

        Returns bands with float values for compatibility with existing code.
        """
        bands = calculate_bollinger_bands(
            prices, period=self.bollinger_period, std_dev=self.bollinger_std
        )

        # Convert Decimal to float for consistency with existing interfaces
        return {
            "upper": float(bands["upper"]) if bands["upper"] is not None else None,
            "middle": float(bands["middle"]) if bands["middle"] is not None else None,
            "lower": float(bands["lower"]) if bands["lower"] is not None else None,
            "current_price": (
                float(bands["current_price"])
                if bands["current_price"] is not None
                else (prices[-1] if prices else None)
            ),
            "position": bands["position"],
        }

    def detect_range_bound(self, prices: list) -> tuple[bool, int]:
        """Detect if market is range-bound"""
        if len(prices) < self.range_bound_threshold:
            return False, 0

        # Check last N days for range-bound behavior
        recent_prices = prices[-self.range_bound_threshold :]
        price_range = max(recent_prices) - min(recent_prices)

        is_range_bound = price_range <= self.range_bound_points

        # Count consecutive range-bound days
        range_bound_days = 0
        if is_range_bound:
            # Simple implementation: just return threshold days if range-bound
            range_bound_days = self.range_bound_threshold

        return is_range_bound, range_bound_days

    def get_market_conditions(self, symbol: str) -> dict:
        """Synchronous wrapper for a_get_market_conditions."""
        return run_async(self.a_get_market_conditions(symbol))

    def calculate_bollinger_bands_realtime(self, symbol: str) -> dict:
        """Synchronous wrapper for a_calculate_bollinger_bands_realtime."""
        return run_async(self.a_calculate_bollinger_bands_realtime(symbol))

    def is_stressed_market(self, symbol: str) -> bool:
        """Synchronous wrapper for a_is_stressed_market."""
        return run_async(self.a_is_stressed_market(symbol))

    async def a_calculate_bollinger_bands_realtime(self, symbol: str) -> dict:
        """
        Calculate Bollinger Bands with real-time data.
        Per spec: 19 historical daily closes + 1 current intraday price
        """
        # Get 19 historical daily closes
        historical_closes = await self._get_historical_prices(symbol, days=19)
        if not historical_closes or len(historical_closes) < 19:
            return {
                "upper": None,
                "middle": None,
                "lower": None,
                "current": None,
                "position": "unknown",
            }

        # Get current intraday price (real-time)
        current_price = await self._get_current_quote(symbol)
        if current_price is None:
            return {
                "upper": None,
                "middle": None,
                "lower": None,
                "current": None,
                "position": "unknown",
            }

        # Combine for 20-period calculation
        prices = [*historical_closes[:19], current_price]

        # Use centralized Bollinger Bands calculation
        bands = calculate_bollinger_bands(
            prices, period=self.bollinger_period, std_dev=self.bollinger_std
        )

        # Convert to expected format (using 'current' key instead of 'current_price')
        return {
            "upper": float(bands["upper"]) if bands["upper"] is not None else None,
            "middle": float(bands["middle"]) if bands["middle"] is not None else None,
            "lower": float(bands["lower"]) if bands["lower"] is not None else None,
            "current": current_price,
            "position": bands["position"],
        }

    async def a_is_stressed_market(self, symbol: str) -> bool:
        """
        Enhanced market stress detection.
        Stressed market = price at or below lower Bollinger Band
        """
        bands = await self.a_calculate_bollinger_bands_realtime(symbol)

        # Simple implementation per spec
        if bands["current"] is not None and bands["lower"] is not None:
            is_below_lower_band = bands["current"] <= bands["lower"]
        else:
            is_below_lower_band = False

        return is_below_lower_band

    async def a_get_market_conditions(self, symbol: str) -> dict:
        """
        Get comprehensive market conditions for a symbol.
        Returns real data or None values - NEVER guesses or uses mock data.
        """
        from services.market_data.service import MarketDataService

        market_service = MarketDataService(self.user)

        # Get actual price data and market metrics concurrently
        prices, metrics = await asyncio.gather(
            self._get_historical_prices(symbol), market_service.get_market_metrics(symbol)
        )

        iv_rank = metrics.get("iv_rank") if metrics else None

        # Get current real-time price independently
        current_price = await self._get_current_quote(symbol)

        # Only calculate if we have real price data
        if prices and len(prices) > 0:
            # Use real-time Bollinger bands with current quote
            bollinger = await self.a_calculate_bollinger_bands_realtime(symbol)
            is_range_bound, range_days = self.detect_range_bound(prices)
            is_near_bollinger = self._is_near_bollinger_band(bollinger)
        else:
            bollinger = {
                "upper": None,
                "middle": None,
                "lower": None,
                "current_price": None,
                "position": "unknown",
            }
            is_range_bound = False
            range_days = 0
            is_near_bollinger = False
            logger.warning(f"No price data available for {symbol}")

        return {
            "symbol": symbol,
            "current_price": current_price,  # Direct real-time price
            "bollinger_bands": bollinger,
            "is_range_bound": is_range_bound,
            "range_bound_days": range_days,
            "near_bollinger_band": is_near_bollinger,
            "iv_rank": iv_rank,
            "data_available": prices is not None and len(prices) > 0,
            "analysis_time": timezone.now().isoformat(),
        }

    async def _get_historical_prices(self, symbol: str, days: int = 30) -> list[float] | None:
        """
        Get historical prices with Database → API fallback pattern.
        Returns real data or None - NEVER returns mock/random data.
        NO streaming cache dependency per REAL_DATA_IMPLEMENTATION_PLAN.md
        """
        try:
            # Use MarketDataService for Database → Stooq fallback
            if self.user:
                try:
                    from services.market_data.service import MarketDataService

                    market_service = MarketDataService(self.user)

                    # Get historical data using Database → Stooq fallback
                    historical_data = await market_service.get_historical_prices(symbol, days)

                    if historical_data:
                        # Extract closing prices from historical data
                        prices = [
                            float(item["close"]) for item in historical_data if "close" in item
                        ]
                        if prices:
                            source = historical_data[0].get("source", "unknown")
                            logger.info(
                                f"Retrieved {len(prices)} historical prices for {symbol} "
                                f"from {source}"
                            )
                            return prices

                except Exception as api_error:
                    logger.error(f"Error fetching historical prices for {symbol}: {api_error}")
            else:
                logger.warning(f"No user context available for historical data: {symbol}")

            logger.warning(f"No historical price data available for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Error retrieving historical prices for {symbol}: {e}", exc_info=True)
            return None

    async def _get_current_quote(self, symbol: str) -> float | None:
        """
        Get current real-time quote price using MarketDataService.
        Returns real data or None - NEVER returns mock data.
        NO streaming cache dependency per REAL_DATA_IMPLEMENTATION_PLAN.md
        """
        try:
            # Use MarketDataService for real-time quotes (Cache → API fallback)
            if self.user:
                try:
                    from services.market_data.service import MarketDataService

                    market_service = MarketDataService(self.user)

                    # Get quote data using Cache → TastyTrade API fallback
                    quote_data = await market_service.get_quote(symbol)

                    if quote_data:
                        # Try bid/ask average first for most accurate price
                        bid = quote_data.get("bid")
                        ask = quote_data.get("ask")

                        if bid is not None and ask is not None:
                            return (float(bid) + float(ask)) / 2

                        # Fall back to last trade price
                        last = quote_data.get("last")
                        if last is not None:
                            source = quote_data.get("source", "unknown")
                            logger.info(f"Retrieved quote for {symbol}: {last} from {source}")
                            return float(last)

                except Exception as api_error:
                    logger.error(f"Error fetching quote for {symbol}: {api_error}")
            else:
                logger.warning(f"No user context available for real-time quote: {symbol}")

            logger.debug(f"No real-time quote available for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Error getting current quote for {symbol}: {e}", exc_info=True)
            return None

    def _is_near_bollinger_band(self, bollinger: dict, threshold: float = 0.02) -> bool:
        """
        Check if current price is near a Bollinger band.
        Used to determine if call spread should be excluded.
        """
        if not bollinger or bollinger["position"] == "unknown":
            return False

        current = bollinger.get("current_price") or bollinger.get("current")
        lower = bollinger.get("lower")
        upper = bollinger.get("upper")

        if not current or not lower or not upper:
            return False

        # Use centralized utility function
        return check_near_band(current, upper, lower, threshold)

    def _check_data_quality(self, quote: dict[str, Any] | None) -> dict[str, Any]:
        """Check if market data is fresh and valid."""
        from datetime import timedelta

        from django.utils import timezone

        is_stale: bool = False
        last_update: datetime | None = None

        if not quote:
            is_stale = True
        else:
            # Check if data has timestamp
            timestamp_str: Any = quote.get("timestamp") or quote.get("fetched_at")
            if timestamp_str:
                try:
                    if isinstance(timestamp_str, str):
                        # Parse and make timezone-aware
                        last_update = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        # Ensure timezone-aware
                        if last_update.tzinfo is None:
                            last_update = timezone.make_aware(last_update)
                    else:
                        last_update = timestamp_str
                        # Ensure timezone-aware
                        if hasattr(last_update, "tzinfo") and last_update.tzinfo is None:
                            last_update = timezone.make_aware(last_update)

                    # Check if data is older than threshold
                    age: timedelta = timezone.now() - last_update
                    if age > timedelta(minutes=self.DATA_STALENESS_MINUTES):
                        is_stale = True
                except Exception as e:
                    logger.warning(f"Error parsing timestamp: {e}")
                    is_stale = True

        return {"is_stale": is_stale, "last_update": last_update}

    def _calculate_market_stress_level(
        self,
        iv_rank: float,
        recent_move_pct: float | None,
        current_price: float,
        support_level: float | None,
        resistance_level: float | None,
    ) -> float:
        """
        Calculate market stress level (0-100) based on multiple indicators.

        Epic 22 Task 023: Comprehensive stress calculation.

        Components:
        - IV Rank (40% weight): High IV Rank indicates elevated fear/stress
        - Recent Volatility (30% weight): Large price moves indicate instability
        - Technical Breaks (30% weight): Support/resistance breaks signal uncertainty

        Args:
            iv_rank: IV rank percentile (0-100)
            recent_move_pct: Recent price movement percentage (e.g., 5.0 = 5%)
            current_price: Current underlying price
            support_level: Support price level (optional)
            resistance_level: Resistance price level (optional)

        Returns:
            float: Stress score from 0 (calm) to 100 (extreme stress)
        """
        stress_score = 0.0

        # Component 1: IV Rank (40% weight) - Primary stress indicator
        if iv_rank > 70:
            # Very high IV = market stress (max 40 points)
            stress_score += 40 * (iv_rank / 100)
        elif iv_rank > 50:
            # Moderately high IV (max 20 points)
            stress_score += 20 * (iv_rank / 100)

        # Component 2: Recent Price Volatility (30% weight)
        # Note: recent_move_pct is in percentage points (5.0 = 5%), not decimal (0.05 = 5%)
        recent_move_abs = abs(recent_move_pct or 0.0)
        if recent_move_abs > 5.0:  # 5% move or more
            # Normalize to 0-30 scale (10% move = max contribution)
            volatility_contribution = min(recent_move_abs / 10.0, 1.0) * 30
            stress_score += volatility_contribution
        elif recent_move_abs > 3.0:  # 3-5% move
            stress_score += 15

        # Component 3: Technical Breaks (30% weight)
        if support_level and resistance_level and current_price > 0:
            # Check if price broke through key levels recently
            # Breaking support (2% below) indicates stress
            if current_price < support_level * 0.98:
                stress_score += 15

            # Breaking resistance (2% above) can also indicate volatility stress
            if current_price > resistance_level * 1.02:
                stress_score += 15

        # Cap at 100
        return min(stress_score, 100.0)

    async def a_analyze_market_conditions(
        self, user: AbstractBaseUser, symbol: str, market_snapshot: dict[str, Any] | None = None
    ) -> MarketConditionReport:
        """
        Analyze market conditions - returns DATA, not decisions.

        Steps:
        1. Get current price and market data
        2. Get IV metrics from TastyTrade API
        3. Calculate technical indicators
        4. Detect range-bound status
        5. Calculate market stress level
        6. Check data quality
        7. Identify hard no-trade conditions

        Returns:
            MarketConditionReport with comprehensive market data
        """
        # Get current price from MarketDataService
        quote: dict[str, Any] | None = await self.market_service.get_quote(symbol)
        current_price: float = 0.0
        open_price: float = 0.0

        if quote:
            # Try bid/ask average first
            bid = quote.get("bid")
            ask = quote.get("ask")
            if bid is not None and ask is not None:
                current_price = (float(bid) + float(ask)) / 2
            elif quote.get("last"):
                current_price = float(quote.get("last"))
            elif quote.get("close"):
                # Fallback to previous close if current quote unavailable
                current_price = float(quote.get("close"))
                logger.warning(
                    f"{symbol}: Using previous close ${current_price:.2f} "
                    f"(current quote unavailable)"
                )

            open_price = float(quote.get("open", current_price))

        # Get IV metrics from TastyTrade API (uses existing MarketDataService)
        metrics: dict[str, Any] | None = await self.market_service.get_market_metrics(symbol)
        iv_rank: float
        iv_percentile: float
        current_iv: float
        beta: float | None = None
        if metrics:
            iv_rank = float(metrics.get("iv_rank", 50.0))
            iv_percentile = float(metrics.get("iv_percentile", 50.0))
            current_iv = float(metrics.get("iv_30_day", 0.0))
            beta = metrics.get("beta")  # Epic 22 Task 018
        else:
            iv_rank = 50.0
            iv_percentile = 50.0
            current_iv = 0.0

        # Epic 22 Task 016: Get earnings information
        from services.market_data.earnings import EarningsCalendar

        earnings_calendar = EarningsCalendar()
        earnings_info = await earnings_calendar.get_earnings_info(symbol, metrics or {})

        # Epic 22 Task 017: Get dividend information
        from services.market_data.dividends import DividendSchedule

        dividend_schedule = DividendSchedule()
        dividend_info = await dividend_schedule.get_dividend_info(symbol, metrics or {})

        # Calculate technical indicators
        from services.market_data.indicators import TechnicalIndicatorCalculator

        technical_calculator = TechnicalIndicatorCalculator()
        technical_data: dict[str, Any] = await technical_calculator.a_calculate_indicators(
            user, symbol, market_snapshot or {}
        )

        # Extract range-bound status from market_snapshot (calculated by MarketAnalyzer)
        # Uses price-based detection: price range <= 2 points over 3 days
        is_range_bound: bool = (
            market_snapshot.get("is_range_bound", False) if market_snapshot else False
        )
        range_bound_days: int = market_snapshot.get("range_bound_days", 0) if market_snapshot else 0

        # Calculate market stress level (Epic 22, Task 023)
        # Use new comprehensive calculation instead of VIX-only method
        market_stress_level: float = self._calculate_market_stress_level(
            iv_rank=iv_rank,
            recent_move_pct=technical_data.get("recent_move_pct") or 0.0,
            current_price=current_price,
            support_level=technical_data.get("support_level"),
            resistance_level=technical_data.get("resistance_level"),
        )

        # Check data quality
        data_quality: dict[str, Any] = self._check_data_quality(quote)

        # Identify hard no-trade conditions
        no_trade_reasons: list[str] = []
        if data_quality["is_stale"]:
            no_trade_reasons.append("data_stale")

        # Epic 22 Task 016: Add earnings to no-trade reasons if within danger window
        if earnings_info.is_within_danger_window:
            no_trade_reasons.append(f"earnings_in_{earnings_info.days_until_earnings}_days")

        # Epic 22 Task 017: Add dividend to no-trade reasons if within risk window
        if dividend_info.is_within_risk_window:
            days = dividend_info.days_until_ex_div or dividend_info.days_until_next_div
            no_trade_reasons.append(f"dividend_in_{days}_days")

        return MarketConditionReport(
            # Symbol
            symbol=symbol,
            # Price information
            current_price=current_price,
            open_price=open_price,
            # Technical indicators - use OR to handle None values gracefully
            data_available=technical_data.get("data_available", False),
            rsi=technical_data.get("rsi") or 50.0,
            macd_signal=technical_data.get("macd_signal") or "neutral",
            bollinger_position=technical_data.get("bollinger_position") or "within_bands",
            sma_20=technical_data.get("sma_20") or 0.0,
            support_level=technical_data.get("support_level"),
            resistance_level=technical_data.get("resistance_level"),
            # Trend strength (Epic 05, Task 001)
            adx=technical_data.get("adx"),
            # Volatility analysis (Epic 05, Task 002)
            historical_volatility=technical_data.get("historical_volatility") or 0.0,
            # Range-bound detection (price-based from MarketAnalyzer)
            is_range_bound=is_range_bound,
            range_bound_days=range_bound_days,
            # IV metrics (from TastyTrade API via get_market_metrics)
            current_iv=current_iv,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            # Market stress
            market_stress_level=market_stress_level,
            recent_move_pct=technical_data.get("recent_move_pct") or 0.0,
            # Data quality
            is_data_stale=data_quality["is_stale"],
            last_update=data_quality["last_update"],
            # Hard no-trade flags
            no_trade_reasons=no_trade_reasons,
            # Epic 22 Task 016: Earnings information
            has_upcoming_earnings=earnings_info.has_upcoming_earnings,
            earnings_date=earnings_info.earnings_date,
            days_until_earnings=earnings_info.days_until_earnings,
            earnings_within_danger_window=earnings_info.is_within_danger_window,
            # Epic 22 Task 017: Dividend information
            has_upcoming_dividend=dividend_info.has_upcoming_dividend,
            dividend_ex_date=dividend_info.ex_dividend_date,
            dividend_next_date=dividend_info.dividend_next_date,
            days_until_dividend=(
                dividend_info.days_until_ex_div or dividend_info.days_until_next_div
            ),
            dividend_within_risk_window=dividend_info.is_within_risk_window,
            # Epic 22 Task 018: Beta
            beta=beta,
        )
