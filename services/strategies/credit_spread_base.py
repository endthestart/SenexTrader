"""
Base Credit Spread Strategy - Shared logic for Bull Put and Bear Call spreads.

This module provides the common foundation for credit spread strategies:
- Bull Put Spread: Bullish bias, sell put spread below current price
- Bear Call Spread: Bearish bias, sell call spread above current price

Both strategies share ~97% of their code - only differing in:
1. Strike selection (0.97x vs 1.03x multipliers)
2. Scoring logic (bullish vs bearish indicators)
3. Market stress preferences
4. TradingSuggestion field mapping
"""

from abc import abstractmethod
from datetime import date
from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.sdk.trading_utils import PriceEffect
from services.strategies.base import BaseStrategy
from services.strategies.core.types import Direction
from services.strategies.utils.strike_utils import calculate_max_profit_credit_spread

logger = get_logger(__name__)


class BaseCreditSpreadStrategy(BaseStrategy):
    """
    Base class for credit spread strategies (Bull Put and Bear Call).

    Credit spreads are theta-positive strategies that:
    - Collect premium by selling options
    - Define risk by buying further OTM options
    - Profit from time decay and favorable price movement
    - Target 50% profit (standard)

    Subclasses must implement:
    - spread_direction: Direction enum
    - strategy_name: Human-readable name
    - _score_market_conditions_impl: Strategy-specific scoring
    - _select_strikes: Strike selection logic
    - _get_strike_field_mapping: Map to TradingSuggestion fields
    """

    # Common configuration constants
    MIN_IV_RANK = 25  # Lower threshold than Trident
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 45
    PROFIT_TARGET_PCT = 50  # Standard for credit spreads
    MIN_SCORE_THRESHOLD = 35  # Minimum score to generate suggestion

    def __init__(self, user):
        super().__init__(user)

    @property
    @abstractmethod
    def spread_direction(self) -> Direction:
        """Return the spread direction (BULLISH or BEARISH)."""
        pass

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Return the strategy identifier (e.g., 'short_put_vertical')."""
        pass

    @abstractmethod
    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Strategy-specific scoring logic.

        Args:
            report: Market condition report

        Returns:
            (score adjustment from 50.0 baseline, list of reason strings)
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

        Args:
            current_price: Current price of underlying
            spread_width: Width of spread in points
            report: Market condition report

        Returns:
            Dict with optimization criteria:
            - spread_type: "bull_put" | "bear_call"
            - otm_pct: Target out-of-the-money percentage (e.g., 0.03 for 3%)
            - spread_width: Width of spread in points
            - current_price: Current underlying price
            - support_level: Support level (optional, for bull put)
            - resistance_level: Resistance level (optional, for bear call)

        Example:
            >>> return {
            ...     "spread_type": "bull_put",
            ...     "otm_pct": 0.03,
            ...     "spread_width": 5,
            ...     "current_price": current_price,
            ...     "support_level": report.support_level,
            ...     "resistance_level": None,
            ... }
        """
        pass

    @abstractmethod
    def _get_strike_field_mapping(self, strikes: dict) -> dict:
        """
        Map strike dict to TradingSuggestion field names.

        Args:
            strikes: Strike dict from _select_strikes()

        Returns:
            Dict with TradingSuggestion field names as keys
        """
        pass

    @abstractmethod
    def _get_occ_bundle_strikes(self, strikes: dict) -> dict:
        """
        Get strikes dict formatted for OCC bundle creation.

        Args:
            strikes: Strike dict from _select_strikes()

        Returns:
            Dict with keys matching OptionsService.build_occ_bundle expectations
        """
        pass

    @abstractmethod
    def _extract_pricing_from_data(self, pricing_data):
        """
        Extract credit values from pricing data.

        Args:
            pricing_data: Pricing data from OptionsService

        Returns:
            (credit, mid_credit) tuple
        """
        pass

    @abstractmethod
    def _get_credit_field_mapping(self, credit: Decimal, mid_credit: Decimal) -> dict:
        """
        Map credit values to TradingSuggestion field names.

        Args:
            credit: Conservative credit value
            mid_credit: Mid-market credit value

        Returns:
            Dict with TradingSuggestion field names as keys
        """
        pass

    @abstractmethod
    def _get_spread_quantity_fields(self) -> dict:
        """
        Get spread quantity field mapping.

        Returns:
            Dict with put_spread_quantity and call_spread_quantity
        """
        pass

    # Shared implementation methods

    def _score_rsi_levels(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score RSI levels for credit spreads.

        Credit spreads sell premium, so:
        - Extreme RSI increases mean reversion risk
        - Moderate RSI is favorable

        Returns:
            (score adjustment, list of reason strings)
        """
        score = 0.0
        reasons = []

        if report.rsi > 70:
            score = -15.0
            reasons.append(f"Overbought (RSI {report.rsi:.1f}) - mean reversion risk")
        elif report.rsi > 60:
            score = -5.0
            reasons.append(f"Slightly overbought (RSI {report.rsi:.1f})")
        elif report.rsi < 30:
            score = -15.0
            reasons.append(f"Oversold (RSI {report.rsi:.1f}) - mean reversion risk")
        elif report.rsi < 40:
            score = -5.0
            reasons.append(f"Slightly oversold (RSI {report.rsi:.1f})")
        elif 45 <= report.rsi <= 55:
            score = +5.0
            reasons.append(f"Neutral RSI ({report.rsi:.1f}) - balanced market")

        return (score, reasons)

    def get_profit_target_config(self, position) -> list:
        return [
            {
                "percentage": self.PROFIT_TARGET_PCT,
                "description": f"{self.PROFIT_TARGET_PCT}% Profit Target",
            }
        ]

    def should_place_profit_targets(self, position) -> bool:
        return True

    def get_dte_exit_threshold(self, position) -> int:
        config = self.get_active_config()
        params = config.get_strategy_parameters() if config else {}
        return params.get("dte_close", 7)

    async def a_score_market_conditions(self, report: MarketConditionReport) -> tuple[float, str]:
        """
        Score market conditions for credit spread.

        Combines base checks with strategy-specific scoring.

        Returns:
            (score 0-100, explanation)
        """
        score = 50.0
        reasons = []

        # Hard stops
        if not report.can_trade():
            return (0.0, report.get_no_trade_explanation())

        # CRITICAL: Verify technical indicator data is available
        if not report.data_available:
            return (0.0, "Insufficient historical data for technical analysis")

        # Strategy-specific scoring
        score_adjustment, strategy_reasons = await self._score_market_conditions_impl(report)
        score += score_adjustment
        reasons.extend(strategy_reasons)

        # RSI scoring
        if report.rsi is not None:
            rsi_score, rsi_reasons = self._score_rsi_levels(report)
            score += rsi_score
            reasons.extend(rsi_reasons)

        # Common IV rank scoring (graduated penalty)
        if report.iv_rank >= self.MIN_IV_RANK:
            bonus = min(20, (report.iv_rank - self.MIN_IV_RANK) * 0.3)
            score += bonus
            reasons.append(f"Good premium collection (IV rank {report.iv_rank:.1f}%)")
        else:
            # Graduated penalty based on distance from threshold
            iv_deficit = self.MIN_IV_RANK - report.iv_rank
            if iv_deficit <= 5:  # Within 5% of threshold (20-25%)
                penalty = 5
                reasons.append(
                    f"Slightly low premium (IV rank {report.iv_rank:.1f}%, "
                    f"{iv_deficit:.1f}% below {self.MIN_IV_RANK}%)"
                )
            elif iv_deficit <= 10:  # 5-10% below threshold (15-20%)
                penalty = 10
                reasons.append(
                    f"Low premium (IV rank {report.iv_rank:.1f}%, "
                    f"{iv_deficit:.1f}% below {self.MIN_IV_RANK}%)"
                )
            else:  # >10% below threshold (<15%)
                penalty = 15
                reasons.append(
                    f"Very low premium (IV rank {report.iv_rank:.1f}%, "
                    f"{iv_deficit:.1f}% below {self.MIN_IV_RANK}%)"
                )
            score -= penalty

        score = max(0, min(100, score))

        explanation = " | ".join(reasons) if reasons else "Base scoring"
        return (score, explanation)

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
        config = await self.a_get_active_config()

        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)

        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f} - {explanation}")

        if score < self.MIN_SCORE_THRESHOLD and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < self.MIN_SCORE_THRESHOLD:
            logger.warning(
                f"Force generating {self.strategy_name} despite low score ({score:.1f}) - "
                f"user explicitly requested"
            )

        tradeable_capital, is_available = await self.risk_manager.a_get_tradeable_capital()
        spread_width = (
            config.get_spread_width(tradeable_capital) if (config and is_available) else 3
        )

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
            "force_generation": force_generation,  # Pass through to know if manual/forced mode
            # NOTE: is_automated will be set by caller
        }

        logger.info(f"User {self.user.id}: Context prepared for {self.strategy_name}")
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
            f"User {self.user.id}: Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """
        Calculate final suggestion using live pricing data from cache.
        Called by UserStreamManager after pricing data arrives.

        Args:
            context: Context dict from a_prepare_suggestion_context()

        Returns:
            TradingSuggestion object with real pricing, or None if failed
        """
        from datetime import timedelta

        from django.utils import timezone

        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        # Reconstruct OCC bundle
        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])

        # Read pricing from cache (populated by streaming)
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found in cache for {self.strategy_name}")
            return None

        # Extract context data
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
        force_generation = context.get("force_generation", False)

        # Extract pricing (strategy-specific)
        credit, mid_credit = self._extract_pricing_from_data(pricing_data)

        # Calculate max risk
        # Max risk = (spread width - credit received) * 100 * quantity
        # Using mid credit for realistic calculation
        max_risk_per_contract = (Decimal(str(spread_width)) - mid_credit) * Decimal("100")

        # Calculate max profit for credit spread
        max_profit_total = calculate_max_profit_credit_spread(mid_credit, quantity=1)

        # Risk budget checking with different behavior for manual vs auto mode
        risk_warning = None
        if not suggestion_mode:
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk_per_contract, is_stressed=market_data.get("is_stressed", False)
            )
            if not can_open:
                if force_generation:
                    # Manual mode: Create suggestion with warning
                    logger.warning(
                        f"User {self.user.id}: Generating {self.strategy_name} despite insufficient risk budget "
                        f"(max risk: ${max_risk_per_contract:.2f}) - manual request"
                    )
                    risk_warning = reason
                else:
                    # Auto mode: Block generation entirely
                    logger.info(
                        f"User {self.user.id}: Risk budget insufficient for {self.strategy_name} "
                        f"(max risk: ${max_risk_per_contract:.2f})"
                    )
                    return {
                        "error": True,
                        "error_type": "risk_budget_exceeded",
                        "message": reason,
                        "max_risk": float(max_risk_per_contract),
                        "strategy": self.strategy_name,
                    }
        else:
            logger.info(
                f"User {self.user.id}: Suggestion mode enabled - skipping risk validation "
                f"for {self.strategy_name}"
            )

        # Map strikes to TradingSuggestion fields
        strike_fields = self._get_strike_field_mapping(strikes)

        # Map credits to TradingSuggestion fields
        credit_fields = self._get_credit_field_mapping(credit, mid_credit)

        # Get quantity fields
        quantity_fields = self._get_spread_quantity_fields()

        # Build market_conditions with risk warning if applicable
        market_conditions_dict = {
            "macd_signal": market_data["macd_signal"],
            "bollinger_position": market_data["bollinger_position"],
            "score": market_data["score"],
            "explanation": market_data["explanation"],
        }
        if risk_warning:
            market_conditions_dict["risk_budget_exceeded"] = True
            market_conditions_dict["risk_warning"] = risk_warning

        # Build generation notes if risk warning
        notes = ""
        if risk_warning:
            notes = f"RISK BUDGET EXCEEDED: {risk_warning}"

        # Create TradingSuggestion with REAL pricing
        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            # Strikes (strategy-specific)
            **strike_fields,
            # Quantities (strategy-specific)
            **quantity_fields,
            # REAL pricing from streaming (strategy-specific)
            **credit_fields,
            total_credit=credit,  # Conservative total
            total_mid_credit=mid_credit,  # Realistic total
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value,  # All credit spreads receive credit
            max_profit=max_profit_total,  # Calculated max profit
            # Market conditions (including risk warning if applicable)
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data["is_range_bound"],
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,
            # Generation notes (risk warning if applicable)
            generation_notes=notes,
            # Status
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,  # We have real pricing!
            pricing_source="streaming",
            # Mark as automated if from Celery
            is_automated=is_automated,
        )

        logger.info(
            f"Created {self.strategy_name} suggestion {suggestion.id} for {symbol} "
            f"with credit ${mid_credit:.2f}"
        )

        # Always return TradingSuggestion object
        # Stream manager handles serialization for WebSocket broadcast
        return suggestion

    async def a_get_profit_target_specifications(
        self, position, *args, target_pct: int | None = None
    ) -> list:
        """
        Generate profit target for credit spread.

        Default target: 50% profit (buy back at 50% of credit received).
        User can configure 40%, 50%, or 60% via target_pct parameter.

        For credit spreads:
        - Entry: Receive credit (e.g., $1.25 per spread)
        - Target: Buy back at (100 - target_pct)% of credit
        - Example: 50% profit target = buy back at 50% of original credit

        Args:
            position: Position object with metadata['suggestion_id']
            target_pct: Optional profit target percentage (40, 50, or 60). Defaults to 50.

        Returns:
            List of profit target specifications
        """
        from trading.models import TradingSuggestion

        profit_targets = []

        # Use provided target_pct or default to PROFIT_TARGET_PCT (50)
        actual_target_pct = target_pct if target_pct is not None else self.PROFIT_TARGET_PCT

        # Get original suggestion
        try:
            suggestion = await TradingSuggestion.objects.aget(id=position.metadata["suggestion_id"])
        except Exception as e:
            logger.error(f"Error fetching suggestion for profit target: {e}")
            return profit_targets

        # Calculate profit target based on spread type
        mid_credit = None
        spread_type = ""

        if self.spread_direction == Direction.BULLISH:
            mid_credit = suggestion.put_spread_mid_credit
            spread_type = "Bull Put Spread"
        elif self.spread_direction == Direction.BEARISH:
            mid_credit = suggestion.call_spread_mid_credit
            spread_type = "Bear Call Spread"

        if mid_credit:
            # For credit spreads: target_price = credit * (1 - target_pct/100)
            # E.g., 50% profit target = buy back at 50% of credit
            multiplier = Decimal(str(1 - actual_target_pct / 100))
            target_price = mid_credit * multiplier

            profit_targets.append(
                {
                    "percentage": actual_target_pct,
                    "target_price": target_price,
                    "description": f"{spread_type} - {actual_target_pct}% Profit Target",
                }
            )

            logger.info(
                f"{spread_type} profit target: Buy back at ${target_price:.2f} "
                f"({actual_target_pct}% profit of ${mid_credit:.2f} credit)"
            )

        return profit_targets
