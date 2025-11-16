"""
Base Debit Spread Strategy - Shared logic for Bull Call and Bear Put spreads.

Debit spreads:
- Buy option closer to ATM (higher cost)
- Sell option further OTM (lower cost, cap profits)
- Pay net debit upfront (max risk = debit)
- Profit from directional price movement

Epic 22 Task 014: Infrastructure base class for debit spreads.
"""

from abc import abstractmethod
from decimal import Decimal
from enum import Enum

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy

logger = get_logger(__name__)


class SpreadDirection(Enum):
    """Direction of debit spread."""

    BULLISH = "bullish"  # Bull Call Spread
    BEARISH = "bearish"  # Bear Put Spread


class BaseDebitSpreadStrategy(BaseStrategy):
    """
    Base class for debit spread strategies.

    Common logic for:
    - Bull Call Spread (bullish, buy calls)
    - Bear Put Spread (bearish, buy puts)
    """

    def __init__(self, user):
        super().__init__(user)  # Get common dependencies from BaseStrategy

    # Strategy-specific constants
    MIN_IV_RANK = 10  # Minimum IV (avoid dead markets)
    MAX_IV_RANK = 70  # Maximum IV (too expensive above this)
    OPTIMAL_IV_RANGE = (30, 50)  # Sweet spot for debit spreads
    MIN_ADX_TREND = 20  # Minimum trend strength for directional play
    OPTIMAL_ADX = 30  # Strong trend confirmation
    TARGET_RISK_REWARD = 2.0  # Target 2:1 reward:risk ratio
    MIN_RISK_REWARD = 1.5  # Minimum acceptable ratio

    @property
    @abstractmethod
    def spread_direction(self) -> SpreadDirection:
        """Return the direction of the spread (bullish/bearish)."""
        pass

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Return strategy name for logging/tracking."""
        pass

    async def a_score_market_conditions(self, report: MarketConditionReport) -> tuple[float, str]:
        """
        Score market conditions for debit spread.

        Base scoring (50 points) + strategy-specific adjustments.
        """
        base_score = 50.0
        reasons = []

        # Hard stops
        if not report.can_trade():
            return (0.0, report.get_no_trade_explanation())

        # CRITICAL: Verify technical indicator data is available
        # Debit spreads require SMA, MACD, ADX, etc. for trend analysis
        if not report.data_available:
            return (0.0, "Insufficient historical data for technical analysis")

        # IV environment scoring (debit spreads prefer moderate IV)
        iv_adjustment, iv_reasons = self._score_iv_environment(report)
        base_score += iv_adjustment
        reasons.extend(iv_reasons)

        # Trend strength scoring (directional plays need momentum)
        trend_adjustment, trend_reasons = self._score_trend_strength(report)
        base_score += trend_adjustment
        reasons.extend(trend_reasons)

        # Strategy-specific scoring (direction alignment, etc.)
        strategy_adjustment, strategy_reasons = await self._score_market_conditions_impl(report)
        base_score += strategy_adjustment
        reasons.extend(strategy_reasons)

        # Risk management filters
        risk_adjustment, risk_reasons = self._score_risk_factors(report)
        base_score += risk_adjustment
        reasons.extend(risk_reasons)

        # Build explanation
        explanation = "\n".join(reasons)

        return (max(0, min(100, base_score)), explanation)

    def _score_iv_environment(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score IV environment for debit spreads.

        Debit spreads require MODERATE IV:
        - Too low: insufficient premium to capture
        - Too high: too expensive to buy options
        """
        score = 0.0
        reasons = []

        # IV Rank optimal range check
        if self.OPTIMAL_IV_RANGE[0] <= report.iv_rank <= self.OPTIMAL_IV_RANGE[1]:
            score += 25
            reasons.append(
                f"IV rank {report.iv_rank:.1f} in optimal range "
                f"({self.OPTIMAL_IV_RANGE[0]}-{self.OPTIMAL_IV_RANGE[1]}) - "
                "excellent entry price for debit spread"
            )
        elif report.iv_rank > self.MAX_IV_RANK:
            score -= 25
            reasons.append(
                f"IV rank {report.iv_rank:.1f} too high (>{self.MAX_IV_RANK}) - "
                "options too expensive to buy, wait for IV to settle"
            )
        elif report.iv_rank < self.MIN_IV_RANK:
            score -= 15
            reasons.append(
                f"IV rank {report.iv_rank:.1f} very low (<{self.MIN_IV_RANK}) - "
                "minimal premium available"
            )
        elif report.iv_rank > self.OPTIMAL_IV_RANGE[1]:
            score += 10
            reasons.append(
                f"IV rank {report.iv_rank:.1f} moderately elevated - acceptable but monitor cost"
            )
        else:
            score += 15
            reasons.append(f"IV rank {report.iv_rank:.1f} below optimal but acceptable")

        # HV/IV Ratio (Epic 05, Task 003)
        # Debit strategies prefer HV > IV (options cheap relative to realized)
        if report.hv_iv_ratio > 1.3:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.3 - "
                "options significantly underpriced, excellent value for buying"
            )
        elif report.hv_iv_ratio > 1.15:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.15 - options moderately underpriced"
            )
        elif report.hv_iv_ratio > 1.0:
            score += 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.0 - options fairly priced")
        elif report.hv_iv_ratio < 0.8:
            score -= 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - "
                "options expensive relative to realized volatility, poor value for buying"
            )

        return (score, reasons)

    def _score_trend_strength(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score trend strength for debit spreads with directional alignment gating.

        Directional plays require strong trending markets with momentum IN THE CORRECT DIRECTION.

        CRITICAL LOGIC: ADX bonus is ONLY awarded when trend direction aligns with spread direction.
        This prevents rewarding "wrong-way" momentum:
        - Bull Call Spread: High ADX in bearish trend = no bonus (strength working against us)
        - Bear Put Spread: High ADX in bullish trend = no bonus (strength working against us)

        This directional gating is a key risk management feature that distinguishes debit spreads
        from non-directional strategies (which can reward high ADX regardless of direction).
        """
        score = 0.0
        reasons = []

        # Check if trend direction aligns with spread direction
        # Bull Call needs bullish trend, Bear Put needs bearish trend
        is_bullish_trend = report.macd_signal in ["bullish", "strong_bullish"]
        is_bearish_trend = report.macd_signal in ["bearish", "strong_bearish"]
        direction_aligned = (
            self.spread_direction == SpreadDirection.BULLISH and is_bullish_trend
        ) or (self.spread_direction == SpreadDirection.BEARISH and is_bearish_trend)

        # ADX trend strength scoring (Epic 05, Task 001)
        # ONLY award bonus if trend direction matches spread direction (directional gating)
        if report.adx is not None:
            if report.adx > self.OPTIMAL_ADX:
                if direction_aligned:
                    score += 20
                    reasons.append(
                        f"Strong trend (ADX {report.adx:.1f} > {self.OPTIMAL_ADX}) in correct direction - "
                        "excellent momentum for directional play"
                    )
                else:
                    reasons.append(
                        f"Strong trend (ADX {report.adx:.1f}) but wrong direction - "
                        "no ADX bonus awarded"
                    )
            elif report.adx >= self.MIN_ADX_TREND:
                if direction_aligned:
                    score += 12
                    reasons.append(
                        f"Moderate trend (ADX {report.adx:.1f}) in correct direction - "
                        "acceptable momentum for debit spread"
                    )
                else:
                    reasons.append(
                        f"Moderate trend (ADX {report.adx:.1f}) but wrong direction - "
                        "no ADX bonus awarded"
                    )
            else:
                score -= 20
                reasons.append(
                    f"Weak trend (ADX {report.adx:.1f} < {self.MIN_ADX_TREND}) - "
                    "insufficient momentum for directional play, wait for trend confirmation"
                )

        return (score, reasons)

    @abstractmethod
    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Strategy-specific market condition scoring.

        Implemented by Bull Call Spread, Bear Put Spread, etc.
        Must check:
        - Direction alignment (bullish/bearish MACD)
        - Price vs SMA position
        - Bollinger Band position
        """
        pass

    @abstractmethod
    def _get_target_criteria(
        self, current_price: Decimal, spread_width: int, report: MarketConditionReport
    ) -> dict:
        """
        Strategy-specific target criteria for strike optimization.

        This method returns TARGET criteria (not calculated strikes).
        The actual strikes will be selected from available strikes in
        the option chain using the StrikeOptimizer.

        Implemented by Bull Call Spread, Bear Put Spread, etc.

        Args:
            current_price: Current price of underlying
            spread_width: Width of spread in points
            report: Market condition report

        Returns:
            Dict with optimization criteria:
            - spread_type: "bull_call" | "bear_put"
            - otm_pct: Target out-of-the-money percentage (e.g., 0.05 for 5%)
            - spread_width: Width of spread in points
            - current_price: Current underlying price
            - support_level: Support level (optional)
            - resistance_level: Resistance level (optional)
        """
        pass

    def _score_risk_factors(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score risk factors common to all debit spreads.
        """
        score = 0.0
        reasons = []

        # Market stress (prefer low for directional plays)
        if report.market_stress_level < 40:
            score += 10
            reasons.append("Low market stress - stable conditions for directional position")
        elif 40 <= report.market_stress_level <= 60:
            score += 3
            reasons.append("Moderate market stress - acceptable risk level")
        elif report.market_stress_level > 70:
            score -= 15
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - "
                "elevated risk for directional plays, unpredictable volatility"
            )

        return (score, reasons)

    def _validate_debit_spread(
        self, debit_paid: Decimal, spread_width: Decimal, strikes: dict
    ) -> tuple[bool, str]:
        """
        Validate debit spread meets minimum requirements.

        Returns:
            (is_valid, reason)
        """
        # Max profit calculation
        max_profit = spread_width - debit_paid

        if max_profit <= 0:
            return (False, f"Max profit ${max_profit:.2f} non-positive - spread too expensive")

        # Risk/reward ratio
        risk_reward = max_profit / debit_paid

        if risk_reward < self.MIN_RISK_REWARD:
            return (
                False,
                f"Risk/reward ratio {risk_reward:.2f}:1 below minimum {self.MIN_RISK_REWARD:.2f}:1",
            )

        # Debit should be < 70% of spread width (otherwise poor value)
        debit_ratio = debit_paid / spread_width
        if debit_ratio > 0.7:
            return (
                False,
                f"Debit ratio {debit_ratio:.2%} too high (>70% of spread width) - poor risk/reward",
            )

        logger.info(
            f"Debit spread validated: "
            f"Debit ${debit_paid}, "
            f"Spread ${spread_width}, "
            f"Max Profit ${max_profit}, "
            f"R/R {risk_reward:.2f}:1"
        )

        return (True, f"Debit spread meets requirements (R/R {risk_reward:.2f}:1)")

    def _calculate_breakeven(
        self, long_strike: Decimal, short_strike: Decimal, debit_paid: Decimal
    ) -> Decimal:
        """
        Calculate breakeven price for debit spread.

        Bull Call: Long strike + debit
        Bear Put: Long strike - debit
        """
        if self.spread_direction == SpreadDirection.BULLISH:
            # Bull Call: Need price above long strike + debit
            return long_strike + debit_paid
        # Bear Put: Need price below long strike - debit
        return long_strike - debit_paid

    def _calculate_max_profit(self, spread_width: Decimal, debit_paid: Decimal) -> Decimal:
        """
        Calculate max profit for debit spread.

        Formula: (Spread Width - Debit Paid) × 100
        """
        return (spread_width - debit_paid) * Decimal("100")

    def _calculate_max_loss(self, debit_paid: Decimal) -> Decimal:
        """
        Calculate max loss for debit spread.

        Formula: Debit Paid × 100
        """
        return debit_paid * Decimal("100")

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: MarketConditionReport | None = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> dict | None:
        """
        Prepare suggestion context WITHOUT creating TradingSuggestion.

        This method validates conditions, calculates strikes, and builds
        the OCC bundle. The actual suggestion creation happens later
        after pricing data arrives via streaming.

        Args:
            symbol: Underlying symbol
            report: Optional pre-computed market report
            suggestion_mode: If True, skip risk validation (for email suggestions)
            force_generation: If True, bypass score threshold checks (for manual mode)

        Returns:
            Optional[dict]: Context dict ready for stream manager, or None if unsuitable
        """
        # Get active config if available (optional for simple strategies)
        config = await self.a_get_active_config()

        # Get market report if not provided
        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)

        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f} - {explanation}")

        # Check threshold (allow bypass in force mode)
        if score < self.MIN_SCORE_THRESHOLD and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < self.MIN_SCORE_THRESHOLD:
            logger.warning(
                f"⚠️ Force generating {self.strategy_name} despite low score ({score:.1f}) - "
                f"user explicitly requested"
            )

        # Calculate spread width
        tradeable_capital, is_available = await self.risk_manager.a_get_tradeable_capital()
        spread_width = (
            config.get_spread_width(tradeable_capital) if (config and is_available) else 5
        )

        # Get target criteria (NEW PATTERN: criteria instead of calculated strikes)
        target_criteria = self._get_target_criteria(
            Decimal(str(report.current_price)), spread_width, report
        )

        # Find expiration with optimal strikes from available strikes
        from services.market_data.utils.expiration_utils import find_expiration_with_optimal_strikes

        params = config.get_strategy_parameters() if config else {}
        result = await find_expiration_with_optimal_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=params.get("min_dte", self.MIN_DTE),
            max_dte=params.get("max_dte", self.MAX_DTE),
            relaxed_quality=force_generation,  # Use 15% threshold in force mode
        )
        if not result:
            threshold = "15%" if force_generation else "5%"
            logger.warning(
                f"No expiration with optimal strikes for {symbol} "
                f"(no strikes passed {threshold} deviation quality gate)"
            )
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} with optimal strikes: {strikes}"
        )

        # Build OCC bundle (strikes already validated)
        logger.info(f"User {self.user.id}: Building OCC bundle for {symbol} {expiration}")
        occ_bundle_strikes = self._get_occ_bundle_strikes(strikes)
        occ_bundle = await self.options_service.build_occ_bundle(
            symbol, expiration, occ_bundle_strikes
        )
        if not occ_bundle:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundle")
            return None

        # Prepare serializable market data
        serializable_report = {
            "current_price": float(report.current_price),
            "iv_rank": float(report.iv_rank),
            "macd_signal": report.macd_signal,
            "bollinger_position": report.bollinger_position,
            "is_range_bound": report.is_range_bound,
            "market_stress_level": float(report.market_stress_level),
            "score": score,
            "explanation": explanation,
        }

        # Build context (convert strikes to float for JSON serialization)
        context = {
            "config_id": config.id if config else None,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "market_data": serializable_report,
            "spread_width": spread_width,
            "strikes": {k: float(v) for k, v in strikes.items()},
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,  # Pass through for risk bypass
            # NOTE: is_automated will be set by caller
        }

        logger.info(f"User {self.user.id}: ✅ Context prepared for {self.strategy_name}")
        return context

    async def a_request_suggestion_generation(
        self, report: MarketConditionReport | None = None, symbol: str = "QQQ"
    ) -> None:
        """
        Request suggestion generation via channel layer (manual flow).

        This method prepares the context and sends it to the stream manager.
        The actual suggestion will be created after pricing data arrives and
        will be broadcast to the user via WebSocket.

        Args:
            report: Pre-calculated market condition report
            symbol: Underlying symbol (default QQQ)
        """
        # Prepare context using new method
        context = await self.a_prepare_suggestion_context(symbol, report)
        if not context:
            logger.info(f"{self.strategy_name}: Conditions not suitable for {symbol}")
            return

        # Mark as manual (not automated)
        context["is_automated"] = False

        # Dispatch to stream manager
        await self.a_dispatch_to_stream_manager(context)
        logger.info(
            f"User {self.user.id}: 🚀 Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """Calculate final suggestion from cached pricing data (DEBIT spreads)."""
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.strategies.utils.strike_utils import calculate_max_profit_debit_spread
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found in cache for {self.strategy_name}")
            return None

        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        symbol = context["symbol"]
        expiration = date.fromisoformat(context["expiration"])
        strikes = context["strikes"]
        market_data = context["market_data"]
        spread_width = context["spread_width"]
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)

        # Extract pricing (debit = BUY long strike, SELL short strike)
        debit, mid_debit = self._extract_pricing_from_data(pricing_data)

        # Max risk = debit paid * 100
        max_risk_per_contract = mid_debit * Decimal("100")
        # Max profit = (spread width - debit) * 100
        max_profit_total = calculate_max_profit_debit_spread(
            mid_debit, Decimal(str(spread_width)), quantity=1
        )

        if not suggestion_mode:
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk_per_contract, is_stressed=market_data.get("is_stressed", False)
            )
            if not can_open:
                return {
                    "error": True,
                    "error_type": "risk_budget_exceeded",
                    "message": reason,
                    "max_risk": float(max_risk_per_contract),
                    "strategy": self.strategy_name,
                }

        strike_fields = self._get_strike_field_mapping(strikes)
        debit_fields = self._get_debit_field_mapping(debit, mid_debit)
        quantity_fields = self._get_spread_quantity_fields()

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            **strike_fields,
            **quantity_fields,
            **debit_fields,
            total_credit=-mid_debit,  # Negative for debit
            total_mid_credit=-mid_debit,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.DEBIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data["is_range_bound"],
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions={
                "macd_signal": market_data["macd_signal"],
                "bollinger_position": market_data["bollinger_position"],
                "score": market_data["score"],
                "explanation": market_data["explanation"],
            },
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: ✅ {self.strategy_name} suggestion - "
            f"Debit: ${mid_debit:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )
        return suggestion

    @abstractmethod
    def _get_occ_bundle_strikes(self, strikes: dict) -> dict:
        """
        Get strikes dict formatted for OCC bundle creation.

        Implemented by child classes (Bull Call, Bear Put).

        Args:
            strikes: Strike dict from optimizer

        Returns:
            Dict with keys matching OptionsService.build_occ_bundle expectations
        """
        pass

    def calculate_greeks_requirements(self) -> dict[str, tuple[float, float]]:
        """
        Define Greeks requirements for debit spreads.

        Returns:
            {
                "long_delta": (min, max),  # Delta of long option
                "net_theta": (min, max),   # Net time decay (negative - we lose value)
                "net_vega": (min, max),    # Net vega (positive - benefit from IV increase)
            }
        """
        if self.spread_direction == SpreadDirection.BULLISH:
            # Bull Call Spread: Long calls (positive delta)
            return {
                "long_delta": (0.40, 0.60),  # Long call ~50 delta
                "net_theta": (-5.0, -0.5),  # Negative theta (lose time value)
                "net_vega": (0.0, 15.0),  # Positive vega (benefit from IV increase)
            }
        # Bear Put Spread: Long puts (negative delta)
        return {
            "long_delta": (-0.60, -0.40),  # Long put ~-50 delta
            "net_theta": (-5.0, -0.5),  # Negative theta (lose time value)
            "net_vega": (0.0, 15.0),  # Positive vega (benefit from IV increase)
        }
