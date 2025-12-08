"""
Technical Indicator Calculator - Pure calculation service

Calculates technical indicators for market analysis without blocking event loop.
Pure calculation service - no strategy decisions.

Phase 4.1: Added caching layer (memory + database) for 80% CPU reduction.
"""

import asyncio

from django.core.cache import cache

from services.core.logging import get_logger
from services.market_data.utils.indicator_utils import (
    calculate_bollinger_bands,
    calculate_bollinger_bands_pandas,
    determine_bollinger_position,
)

logger = get_logger(__name__)


class TechnicalIndicatorCalculator:
    """
    Calculate technical indicators for market analysis.

    Pure calculation service - no strategy decisions.

    Phase 4.1: Implements two-tier caching:
    - Memory cache (5 min TTL) for hot data
    - Database persistence for historical reference
    """

    CACHE_TTL = 300  # 5 minutes

    async def a_calculate_indicators(self, user, symbol: str, market_snapshot: dict) -> dict:
        """
        Calculate all technical indicators without blocking event loop.

        PERFORMANCE FIX: Wraps CPU-bound pandas calculations in asyncio.to_thread()
        to prevent blocking the async event loop.

        Returns:
            dict with:
            - rsi: float (0-100)
            - macd_signal: str ('bullish', 'bearish', 'neutral')
            - bollinger_position: str
            - sma_20: float
            - support_level: Optional[float]
            - resistance_level: Optional[float]
            - recent_move_pct: float
            - current_price: float
            - open_price: float
        """
        # Get historical data using MarketDataService
        market_data = await self._get_market_data(user, symbol, days_back=60)

        if market_data is None or len(market_data) < 20:
            return self._get_default_indicators()

        try:
            import pandas as pd

            df = pd.DataFrame(market_data)

            if "close" not in df.columns:
                logger.warning(f"No close prices for {symbol}")
                return self._get_default_indicators()

            rsi = await self._get_cached_rsi(symbol, df["close"], 14)

            _macd_line, _signal_line, histogram = await self._get_cached_macd(symbol, df["close"])

            upper, _middle, lower = await self._get_cached_bollinger_bands(
                symbol, df["close"], 20, 2.0
            )

            adx = await self._get_cached_adx(symbol, df, 14)

            hv_30 = await self._get_cached_hv(symbol, df["close"], 30)

            current_price = float(df["close"].iloc[-1])
            open_price = float(df["open"].iloc[-1]) if "open" in df.columns else current_price

            bollinger_position = determine_bollinger_position(current_price, upper, lower)

            sma_20 = float(df["close"].rolling(window=20).mean().iloc[-1])

            support_level = (
                float(df["low"].rolling(window=20).min().iloc[-1]) if "low" in df.columns else None
            )
            resistance_level = (
                float(df["high"].rolling(window=20).max().iloc[-1])
                if "high" in df.columns
                else None
            )

            if "high" in df.columns and "low" in df.columns:
                recent_high = float(df["high"].tail(5).max())
                recent_low = float(df["low"].tail(5).min())
                recent_move_pct = abs((recent_high - recent_low) / current_price) * 100
            else:
                recent_move_pct = 0.0

            macd_signal = self._calculate_composite_direction(
                current_price=current_price,
                sma_20=sma_20,
                macd_histogram=histogram,
                rsi=rsi,
                adx=adx,
                bollinger_position=bollinger_position,
                recent_move_pct=recent_move_pct,
            )

            return {
                "data_available": True,
                "rsi": rsi,
                "macd_signal": macd_signal,
                "bollinger_position": bollinger_position,
                "sma_20": sma_20,
                "support_level": support_level,
                "resistance_level": resistance_level,
                "recent_move_pct": recent_move_pct,
                "current_price": current_price,
                "open_price": open_price,
                "adx": adx,
                "historical_volatility": hv_30,
            }

        except ImportError:
            logger.warning("pandas not available, using simplified calculations")
            return await self._calculate_indicators_simple(market_data)
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}", exc_info=True)
            return self._get_default_indicators()

    async def _get_cached_bollinger_bands(
        self, symbol: str, prices, period: int = 20, std_dev: float = 2.0
    ) -> tuple:
        """
        Get Bollinger Bands with caching (Phase 4.1).

        Returns: (upper, middle, lower) tuple
        """
        cache_key = f"bollinger_{symbol}_1D_{period}_{std_dev}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Bollinger Bands cache HIT for {symbol}")
            return (cached["upper"], cached["middle"], cached["lower"])

        upper, middle, lower = await asyncio.to_thread(
            calculate_bollinger_bands_pandas, prices, period, std_dev
        )

        bands_data = {"upper": upper, "middle": middle, "lower": lower}
        cache.set(cache_key, bands_data, self.CACHE_TTL)

        try:
            from trading.models import TechnicalIndicatorCache

            await TechnicalIndicatorCache.objects.aupdate_or_create(
                symbol=symbol,
                indicator_type="bollinger",
                timeframe="1D",
                defaults={"data": bands_data},
            )
        except Exception as e:
            logger.warning(f"Failed to cache Bollinger Bands in DB: {e}")

        logger.debug(f"Bollinger Bands calculated and cached for {symbol}")
        return (upper, middle, lower)

    async def _get_cached_rsi(self, symbol: str, prices, period: int = 14) -> float:
        """
        Get RSI with caching (Phase 4.1).

        Returns: RSI value (0-100)
        """
        cache_key = f"rsi_{symbol}_1D_{period}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"RSI cache HIT for {symbol}")
            return cached["value"]

        rsi_value = await asyncio.to_thread(self._calculate_rsi, prices, period)

        rsi_data = {"value": rsi_value}
        cache.set(cache_key, rsi_data, self.CACHE_TTL)

        try:
            from trading.models import TechnicalIndicatorCache

            await TechnicalIndicatorCache.objects.aupdate_or_create(
                symbol=symbol,
                indicator_type="rsi",
                timeframe="1D",
                defaults={"data": rsi_data},
            )
        except Exception as e:
            logger.warning(f"Failed to cache RSI in DB: {e}")

        logger.debug(f"RSI calculated and cached for {symbol}")
        return rsi_value

    async def _get_cached_macd(
        self, symbol: str, prices, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple:
        """
        Get MACD with caching (Phase 4.1).

        Returns: (macd_line, signal_line, histogram) tuple
        """
        cache_key = f"macd_{symbol}_1D_{fast}_{slow}_{signal}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"MACD cache HIT for {symbol}")
            return (cached["macd_line"], cached["signal_line"], cached["histogram"])

        macd_line, signal_line, histogram = await asyncio.to_thread(
            self._calculate_macd, prices, fast, slow, signal
        )

        macd_data = {"macd_line": macd_line, "signal_line": signal_line, "histogram": histogram}
        cache.set(cache_key, macd_data, self.CACHE_TTL)

        try:
            from trading.models import TechnicalIndicatorCache

            await TechnicalIndicatorCache.objects.aupdate_or_create(
                symbol=symbol,
                indicator_type="macd",
                timeframe="1D",
                defaults={"data": macd_data},
            )
        except Exception as e:
            logger.warning(f"Failed to cache MACD in DB: {e}")

        logger.debug(f"MACD calculated and cached for {symbol}")
        return (macd_line, signal_line, histogram)

    async def _get_cached_adx(self, symbol: str, df, period: int = 14) -> float:
        """
        Get ADX with caching (Epic 05, Task 001).

        Returns: ADX value (0-100)
        """
        cache_key = f"adx_{symbol}_1D_{period}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"ADX cache HIT for {symbol}")
            return cached["value"]

        # Calculate (requires OHLC data)
        adx_value = await asyncio.to_thread(self._calculate_adx, df, period)

        adx_data = {"value": adx_value}
        cache.set(cache_key, adx_data, self.CACHE_TTL)

        try:
            from trading.models import TechnicalIndicatorCache

            await TechnicalIndicatorCache.objects.aupdate_or_create(
                symbol=symbol,
                indicator_type="adx",
                timeframe="1D",
                defaults={"data": adx_data},
            )
        except Exception as e:
            logger.warning(f"Failed to cache ADX in DB: {e}")

        logger.debug(f"ADX calculated and cached for {symbol}")
        return adx_value

    async def _get_cached_hv(self, symbol: str, prices, period: int = 30) -> float:
        """
        Get Historical Volatility with caching (Epic 05, Task 002).

        Returns: Annualized volatility percentage (e.g., 25.5 = 25.5%)
        """
        cache_key = f"hv_{symbol}_1D_{period}"

        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"HV cache HIT for {symbol}")
            return cached["value"]

        hv_value = await asyncio.to_thread(self._calculate_historical_volatility, prices, period)

        hv_data = {"value": hv_value}
        cache.set(cache_key, hv_data, self.CACHE_TTL)

        try:
            from trading.models import TechnicalIndicatorCache

            await TechnicalIndicatorCache.objects.aupdate_or_create(
                symbol=symbol,
                indicator_type="historical_volatility",
                timeframe="1D",
                defaults={"data": hv_data},
            )
        except Exception as e:
            logger.warning(f"Failed to cache HV in DB: {e}")

        logger.debug(f"HV calculated and cached for {symbol}")
        return hv_value

    def _calculate_rsi(self, prices, period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""

        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        # Avoid division by zero
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        return float(rsi.iloc[-1])

    def _calculate_macd(self, prices, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line

        return (float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1]))

    def _calculate_composite_direction(
        self,
        current_price: float,
        sma_20: float,
        macd_histogram: float,
        rsi: float,
        adx: float,
        bollinger_position: str,
        recent_move_pct: float,
    ) -> str:
        """
        Calculate market direction using composite signal.

        Combines multiple indicators with adaptive weighting based on trend strength (ADX).
        Detects exhaustion at extremes (RSI + Bollinger) while respecting strong trends.

        Signal States:
        - "strong_bullish": Uptrend with momentum (ADX > 25, price > SMA, RSI < 70)
        - "bullish": Uptrend (price > SMA, positive momentum)
        - "bullish_exhausted": Uptrend BUT overbought (RSI > 70, upper Bollinger)
        - "neutral": Sideways/mixed signals
        - "bearish_exhausted": Downtrend BUT oversold (RSI < 30, lower Bollinger)
        - "bearish": Downtrend (price < SMA, negative momentum)
        - "strong_bearish": Downtrend with momentum (ADX > 25, price < SMA, RSI > 30)

        Weighting Logic:
        - Strong trend (ADX > 25): Trust price (60%) > MACD (20%) > momentum (20%)
        - Moderate trend (ADX 15-25): Balance price (40%) = MACD (40%), momentum (20%)
        - Weak trend (ADX < 15): Trust MACD (50%) > price (30%), momentum (20%)

        Args:
            current_price: Current price
            sma_20: 20-day simple moving average
            macd_histogram: MACD histogram value
            rsi: RSI value (0-100)
            adx: ADX trend strength (0-100)
            bollinger_position: "above_upper", "within_bands", or "below_lower"
            recent_move_pct: Recent 5-day price movement %

        Returns:
            str: Composite direction signal
        """
        # Step 1: Calculate component signals
        price_signal = 1.0 if current_price > sma_20 else -1.0
        macd_signal = 1.0 if macd_histogram > 0 else -1.0 if macd_histogram < 0 else 0.0

        # Momentum signal from recent 5-day move
        # Positive if recent high > recent low significantly
        momentum_signal = 0.0
        if recent_move_pct > 3.0:  # Significant move
            # Determine direction from price vs SMA
            if current_price > sma_20:
                momentum_signal = 1.0
            elif current_price < sma_20:
                momentum_signal = -1.0

        # Step 2: Weight by ADX strength (adaptive)
        adx = adx or 0.0  # Handle None
        if adx > 25:  # Strong trend - trust price action
            direction_score = (price_signal * 0.6) + (macd_signal * 0.2) + (momentum_signal * 0.2)
        elif adx > 15:  # Moderate trend - balance
            direction_score = (price_signal * 0.4) + (macd_signal * 0.4) + (momentum_signal * 0.2)
        else:  # Weak trend - trust MACD
            direction_score = (price_signal * 0.3) + (macd_signal * 0.5) + (momentum_signal * 0.2)

        # Step 3: Determine base direction from score
        if direction_score > 0.6 and adx > 25:
            base_signal = "strong_bullish"
        elif direction_score > 0.3:
            base_signal = "bullish"
        elif direction_score < -0.6 and adx > 25:
            base_signal = "strong_bearish"
        elif direction_score < -0.3:
            base_signal = "bearish"
        else:
            base_signal = "neutral"

        # Step 4: Check for exhaustion (only in weak/moderate trends)
        # Don't fight strong trends (ADX > 25)
        if adx < 25:
            # Bullish exhaustion: RSI > 70 AND at upper Bollinger
            if base_signal in ["strong_bullish", "bullish"]:
                if rsi > 70 and bollinger_position == "above_upper":
                    return "bullish_exhausted"

            # Bearish exhaustion: RSI < 30 AND at lower Bollinger
            elif base_signal in ["strong_bearish", "bearish"]:
                if rsi < 30 and bollinger_position == "below_lower":
                    return "bearish_exhausted"

        return base_signal

    def _calculate_adx(self, df, period: int = 14) -> float:
        """
        Calculate ADX (Average Directional Index) from OHLC data.

        ADX measures trend strength on a 0-100 scale:
        - ADX > 30: Strong trend (directional strategies preferred)
        - ADX 20-30: Moderate trend
        - ADX < 20: Weak trend/range-bound (credit spreads like Senex Trident preferred)

        Steps:
        1. Calculate True Range (TR)
        2. Calculate Directional Movement (+DM, -DM)
        3. Smooth TR and DM using Wilder's smoothing (EWM)
        4. Calculate Directional Indicators (+DI, -DI)
        5. Calculate ADX from DI values

        Args:
            df: DataFrame with columns: high, low, close
            period: Lookback period (default 14)

        Returns:
            float: ADX value (0-100)
        """
        import pandas as pd

        high = df["high"]
        low = df["low"]
        close = df["close"]

        # Step 1: True Range - maximum of three values
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Step 2: Directional Movement
        up_move = high - high.shift()
        down_move = low.shift() - low

        # +DM when up_move > down_move and up_move > 0
        plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
        # -DM when down_move > up_move and down_move > 0
        minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

        # Step 3: Wilder's smoothing (exponential weighted moving average)
        # Note: Wilder's smoothing uses alpha = 1/period
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di_raw = plus_dm.ewm(span=period, adjust=False).mean()
        minus_di_raw = minus_dm.ewm(span=period, adjust=False).mean()

        # Step 4: Calculate Directional Indicators (as percentages)
        # Avoid division by zero
        plus_di = 100 * (plus_di_raw / atr.replace(0, 1e-10))
        minus_di = 100 * (minus_di_raw / atr.replace(0, 1e-10))

        # Step 5: Calculate DX (Directional Index)
        # DX = 100 * |+DI - -DI| / (+DI + -DI)
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum.replace(0, 1e-10)

        # ADX is the smoothed average of DX
        adx = dx.ewm(span=period, adjust=False).mean()

        return float(adx.iloc[-1])

    def _calculate_historical_volatility(self, prices, period: int = 30) -> float:
        """
        Calculate annualized historical volatility from daily returns.

        Historical volatility measures realized price movement, providing context
        for implied volatility (IV) comparisons. Used in HV/IV ratio analysis.

        Formula:
        1. Calculate daily returns: (price[i] / price[i-1]) - 1
        2. Calculate standard deviation of returns
        3. Annualize: std_dev * sqrt(252) * 100

        Args:
            prices: Series of close prices
            period: Lookback period for volatility calculation (default 30)

        Returns:
            float: Annualized volatility as percentage (e.g., 25.5 = 25.5%)

        Epic 05, Task 002: Historical Volatility
        """
        import math

        import numpy as np

        # Use last 'period' prices
        price_data = prices.tail(period + 1)

        if len(price_data) < 2:
            return 0.0

        # Calculate daily returns
        returns = price_data.pct_change().dropna()

        if len(returns) < 2:
            return 0.0

        # Calculate standard deviation
        std_dev = float(np.std(returns, ddof=1))  # Sample std dev

        # Annualize (252 trading days per year)
        return std_dev * math.sqrt(252) * 100

    async def _get_market_data(self, user, symbol: str, days_back: int) -> list | None:
        """Get market data from MarketDataService"""
        try:
            from services.market_data.service import MarketDataService

            market_service = MarketDataService(user)
            return await market_service.get_historical_prices(symbol, days=days_back)

        except Exception as e:
            logger.error(f"Error fetching market data: {e}", exc_info=True)
            return None

    async def _calculate_indicators_simple(self, market_data: list) -> dict:
        """
        Simplified indicator calculation without pandas.
        Used as fallback when pandas is not available.
        """
        if not market_data or len(market_data) < 20:
            return self._get_default_indicators()

        try:
            # Extract close prices
            closes = [float(d["close"]) for d in market_data if "close" in d]

            if len(closes) < 20:
                return self._get_default_indicators()

            current_price = closes[-1]

            # Simple SMA
            sma_20 = sum(closes[-20:]) / 20

            # Simple RSI (14 period)
            rsi = self._calculate_rsi_simple(closes[-15:])

            # Use centralized Bollinger Bands calculation
            bands = calculate_bollinger_bands(closes, period=20, std_dev=2.0)
            float(bands["upper"]) if bands["upper"] is not None else current_price
            float(bands["lower"]) if bands["lower"] is not None else current_price

            bollinger_position = bands["position"]

            return {
                "data_available": True,
                "rsi": rsi,
                "macd_signal": "neutral",  # Simplified
                "bollinger_position": bollinger_position,
                "sma_20": sma_20,
                "support_level": min(closes[-20:]),
                "resistance_level": max(closes[-20:]),
                "recent_move_pct": 0.0,
                "current_price": current_price,
                "open_price": current_price,
            }

        except Exception as e:
            logger.error(f"Error in simple calculation: {e}", exc_info=True)
            return self._get_default_indicators()

    def _calculate_rsi_simple(self, prices: list, period: int = 14) -> float:
        """Simple RSI calculation without pandas"""
        if len(prices) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_default_indicators(self) -> dict:
        """
        Return indicator structure when data is unavailable.

        CRITICAL: This signals data unavailability - strategies MUST check
        data_available flag before using any indicator values.
        """
        return {
            "data_available": False,
            "rsi": None,
            "macd_signal": None,
            "bollinger_position": None,
            "sma_20": None,
            "support_level": None,
            "resistance_level": None,
            "recent_move_pct": None,
            "current_price": None,
            "open_price": None,
            "adx": None,
            "historical_volatility": None,
        }
