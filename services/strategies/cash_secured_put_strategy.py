"""
Cash-Secured Put Strategy - Premium collection with stock acquisition intent.

Suitable when:
- IV Rank > 50% (high premium environment)
- Neutral to bullish outlook (ADX < 25 or bullish trend)
- Willing to own underlying stock at strike price
- Options overpriced (HV/IV ratio > 1.0)
- Range-bound market preferred (ADX < 20 ideal)

Part of Wheel Strategy:
Phase 1: Cash-Secured Put (this strategy)
Phase 2: Assignment → Own 100 shares
Phase 3: Covered Call on owned shares
Phase 4: Called away → Return to Phase 1
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


@register_strategy("cash_secured_put")
class CashSecuredPutStrategy(BaseStrategy):
    """
    Cash-Secured Put - Sell puts with full cash backing.

    TastyTrade Methodology:
    - 45 DTE entry
    - 0.30 delta target (~30% assignment probability)
    - 50% profit target (close at 50% of max profit)
    - IV Rank > 50% entry requirement
    """

    # Strategy-specific constants
    MIN_IV_RANK = 50  # HARD STOP - insufficient premium below this
    OPTIMAL_IV_RANK = 60  # Premium levels become excellent
    TARGET_DELTA = 0.30  # TastyTrade standard
    MIN_PREMIUM_YIELD = 1.5  # 1.5% of strike minimum
    OPTIMAL_PREMIUM_YIELD = 2.5  # 2.5%+ is excellent
    MAX_ADX_BEARISH = 40  # Avoid if ADX > 40 and bearish
    IDEAL_ADX_MAX = 20  # Range-bound ideal
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 50  # Standard for premium sellers

    @property
    def strategy_name(self) -> str:
        return "cash_secured_put"

    def automation_enabled_by_default(self) -> bool:
        """Cash-secured puts are manual only (requires stock purchase intent)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 50% of max profit."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid assignment risk."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for cash-secured put.

        Target: Close at 50% of original credit (standard for premium sellers)
        """
        from trading.models import TradeOrder

        # Get opening order to find original credit
        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        original_credit = abs(opening_order.price)  # Credit is negative, make positive
        target_price = original_credit * Decimal("0.50")  # Buy back at 50% of credit

        return [
            {
                "spread_type": "cash_secured_put",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_credit": original_credit,
            }
        ]

    async def a_score_market_conditions(self, report: MarketConditionReport) -> tuple[float, str]:
        """
        Score market conditions for cash-secured put.

        Returns:
            (score, explanation_string)
        """
        score, reasons = await self._score_market_conditions_impl(report)
        score = max(0, min(100, score))
        explanation = "\n".join(reasons)
        return (score, explanation)

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for cash-secured put.

        Multi-factor scoring (0-100):
        - IV Rank (30% weight): Primary premium driver
        - ADX/Trend (20% weight): Range-bound preferred
        - HV/IV Ratio (20% weight): Options pricing value
        - Premium Target (15% weight): Adequate compensation
        - Market Direction (10% weight): Neutral/bullish preferred
        - Technical Position (5% weight): Bollinger bands
        """
        score = 50.0  # Base score
        reasons = []

        # Factor 1: IV Rank (30% weight)
        if report.iv_rank < self.MIN_IV_RANK:
            # Severe penalty for insufficient IV - continue but warn strongly
            score -= 30
            reasons.append(
                f"⚠️ CRITICAL: IV Rank {report.iv_rank:.1f} below minimum {self.MIN_IV_RANK} - "
                f"insufficient premium environment. DO NOT EXECUTE. "
                f"Wait for IV Rank > {self.MIN_IV_RANK}% before selling premium."
            )
        elif report.iv_rank > 70:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 70% - exceptional premium collection opportunity"
            )
        elif report.iv_rank >= self.OPTIMAL_IV_RANK:
            score += 24
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (>60%) - excellent premiums"
            )
        elif report.iv_rank >= self.MIN_IV_RANK:
            score += 15
            reasons.append(f"IV Rank {report.iv_rank:.1f} adequate (>50%) - acceptable premiums")

        # Factor 2: ADX Trend Strength (20% weight) - Epic 22, Task 024
        # Prefer range-bound or weak bullish; avoid strong bearish
        if report.adx is not None:
            if report.adx < self.IDEAL_ADX_MAX:
                score += 20
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound market, IDEAL for premium collection"
                )
            elif report.adx < 25 and report.macd_signal in [
                "bullish",
                "neutral",
                "strong_bullish",
                "bullish_exhausted",
            ]:
                score += 16
                reasons.append(
                    f"ADX {report.adx:.1f} with {report.macd_signal.replace('_', ' ')} bias - weak trend, favorable"
                )
            elif report.adx < 30 and report.macd_signal in ["strong_bullish", "bullish"]:
                score += 12
                reasons.append(f"ADX {report.adx:.1f} moderate bullish trend - acceptable for CSP")
            elif report.adx > self.MAX_ADX_BEARISH and report.macd_signal in [
                "strong_bearish",
                "bearish",
            ]:
                score -= 40
                reasons.append(
                    f"ADX {report.adx:.1f} strong bearish trend - AVOID cash-secured puts, "
                    "high assignment risk with continued losses"
                )
            elif report.macd_signal in ["strong_bearish", "bearish"]:
                score -= 20
                reasons.append(f"Bearish trend (ADX {report.adx:.1f}) - increased assignment risk")

        # Factor 3: HV/IV Ratio (20% weight)
        # Higher IV relative to HV = overpriced options = good for sellers
        if report.hv_iv_ratio > 1.3:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.3 - options significantly overpriced, "
                "excellent value for sellers"
            )
        elif report.hv_iv_ratio > 1.15:
            score += 16
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.15 - options moderately overpriced"
            )
        elif report.hv_iv_ratio > 1.0:
            score += 12
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.0 - options fairly priced")
        elif report.hv_iv_ratio < 0.8:
            score -= 10
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - options underpriced, "
                "poor environment for sellers"
            )

        # Factor 4: Premium Collection Target (15% weight)
        # Estimate based on IV rank (higher IV = higher premium)
        estimated_premium_yield = (report.iv_rank / 100) * 3.0  # Rough estimate

        if estimated_premium_yield > self.OPTIMAL_PREMIUM_YIELD:
            score += 15
            reasons.append(
                f"Estimated premium yield ~{estimated_premium_yield:.1f}% - excellent compensation"
            )
        elif estimated_premium_yield > 2.0:
            score += 12
            reasons.append(
                f"Estimated premium yield ~{estimated_premium_yield:.1f}% - good compensation"
            )
        elif estimated_premium_yield > self.MIN_PREMIUM_YIELD:
            score += 8
            reasons.append(f"Estimated premium yield ~{estimated_premium_yield:.1f}% - acceptable")
        else:
            score += 4
            reasons.append(
                f"Estimated premium yield ~{estimated_premium_yield:.1f}% - minimal compensation"
            )

        # Factor 5: Market Direction (10% weight) - Epic 22, Task 024
        if report.macd_signal == "bullish":
            score += 20
            reasons.append("Bullish direction - favorable for CSP (lower assignment risk)")
        elif report.macd_signal == "strong_bullish":
            score += 15
            reasons.append("Strong bullish trend - good but might not get assigned")
        elif report.macd_signal == "bullish_exhausted":
            score += 15
            reasons.append("Bullish exhausted - potential bounce favorable for CSP entry")
        elif report.macd_signal == "neutral":
            score += 10
            reasons.append("Neutral market - ideal for cash-secured puts")
        elif report.macd_signal == "bearish_exhausted":
            score += 5
            reasons.append("Bearish exhausted - might reverse, marginal for CSP")
        elif report.macd_signal == "bearish":
            score -= 15
            reasons.append("Bearish direction - increased assignment risk")
        elif report.macd_signal == "strong_bearish":
            score -= 25
            reasons.append("Strong bearish trend - very unfavorable for CSP")

        # Factor 6: Position relative to Bollinger Bands (5% weight)
        if report.bollinger_position == "below_lower":
            score += 5
            reasons.append("Price at lower Bollinger - potential bounce, good entry")
        elif report.bollinger_position == "above_upper":
            score -= 3
            reasons.append("Price at upper Bollinger - extended, wait for pullback")

        # Market stress consideration
        if report.market_stress_level < 40:
            score += 5
            reasons.append("Low market stress - stable environment for CSP")
        elif report.market_stress_level > 60:
            score -= 8
            reasons.append(
                f"Elevated market stress ({report.market_stress_level:.0f}) - "
                "increased volatility risk"
            )

        return (score, reasons)

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: MarketConditionReport | None = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> dict | None:
        """
        Prepare suggestion context WITHOUT creating TradingSuggestion.

        This method validates conditions, calculates strike, and builds
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
        # Get active config first to access all parameters
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

        # Calculate strike (0.30 delta, ~7% OTM)
        current_price = Decimal(str(report.current_price))
        put_strike = self._select_strike(current_price, self.TARGET_DELTA)

        logger.info(
            f"User {self.user.id}: Selected strike ${put_strike} "
            f"(~{self.TARGET_DELTA} delta, 7% OTM from ${current_price})"
        )

        # Find expiration in DTE range
        from services.market_data.utils.expiration_finder import a_fetch_and_find_expiration

        params = config.get_strategy_parameters() if config else {}
        min_dte = params.get("min_dte", self.MIN_DTE)
        max_dte = params.get("max_dte", self.MAX_DTE)
        target_dte = params.get("target_dte", self.TARGET_DTE)

        expiration = await a_fetch_and_find_expiration(
            self.user, symbol, target_dte, min_dte, max_dte
        )
        if not expiration:
            logger.warning(f"No expiration found between {min_dte} and {max_dte} DTE for {symbol}")
            return None

        logger.info(f"User {self.user.id}: Using expiration {expiration}")

        # Build OCC bundle (single put)
        logger.info(f"User {self.user.id}: Building OCC bundle for {symbol} {expiration}")
        occ_bundle_strikes = {"put_strike": put_strike}
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

        # Build context
        context = {
            "config_id": config.id if config else None,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "market_data": serializable_report,
            "strikes": {"put_strike": float(put_strike)},
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,  # Pass through for risk bypass
            "force_generation": force_generation,  # Pass through to know if manual/forced mode
            # NOTE: is_automated will be set by caller
        }

        logger.info(f"User {self.user.id}: ✅ Context prepared for {self.strategy_name}")
        return context

    async def a_request_suggestion_generation(
        self, report: "Optional[MarketConditionReport]" = None, symbol: str = "QQQ"
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
        """Calculate suggestion from cached pricing data (single-leg PUT sale)."""
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found for {self.strategy_name}")
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
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)
        force_generation = context.get("force_generation", False)

        # Extract pricing for single put leg
        put_strike = Decimal(str(strikes["put_strike"]))
        put_payload = pricing_data.snapshots.get("put_strike")
        if not put_payload:
            logger.warning(f"Missing pricing data for put strike {put_strike}")
            return None

        # Premium received (credit) - calculate mid from bid/ask
        bid = put_payload.get("bid")
        ask = put_payload.get("ask")
        if bid is None or ask is None:
            logger.warning(f"Missing bid/ask for put strike {put_strike}")
            return None
        premium = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")

        # Max profit = premium received * 100
        max_profit_total = premium * Decimal("100")

        # Max risk = (strike - premium) * 100 (if assigned)
        max_risk_per_contract = (put_strike - premium) * Decimal("100")

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

        # Build market_conditions with risk warning if applicable
        market_conditions_dict = {
            "macd_signal": market_data.get("macd_signal"),
            "adx": market_data.get("adx"),
            "score": market_data["score"],
            "explanation": market_data["explanation"],
        }
        if risk_warning:
            market_conditions_dict["risk_budget_exceeded"] = True
            market_conditions_dict["risk_warning"] = risk_warning

        # Build generation notes if risk warning
        notes = ""
        if risk_warning:
            notes = f"⚠️ RISK BUDGET EXCEEDED: {risk_warning}"

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            short_put_strike=put_strike,
            put_spread_quantity=1,
            put_spread_credit=premium,
            total_credit=premium,
            total_mid_credit=premium,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,  # Includes risk warning if applicable
            generation_notes=notes,  # Risk warning if applicable
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: ✅ Cash-Secured Put suggestion - "
            f"Premium: ${premium:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )
        return suggestion

    def _calculate_cash_requirement(self, strike_price: Decimal) -> Decimal:
        """
        Calculate cash required for cash-secured put.

        Formula: Strike Price × 100 shares

        Example: $50 strike = $5,000 required
        """
        return strike_price * Decimal("100")

    def _calculate_net_cash_outlay(
        self, strike_price: Decimal, premium_received: Decimal
    ) -> Decimal:
        """
        Calculate net cash if assigned.

        Formula: (Strike × 100) - Premium Received

        Example: $100 strike, $3 premium = $10,000 - $300 = $9,700 net
        """
        gross_requirement = self._calculate_cash_requirement(strike_price)
        return gross_requirement - (premium_received * Decimal("100"))

    def _calculate_breakeven(self, strike_price: Decimal, premium_received: Decimal) -> Decimal:
        """
        Calculate breakeven price.

        Formula: Strike Price - Premium

        Example: $100 strike - $3 premium = $97 breakeven
        """
        return strike_price - premium_received

    def _select_strike(self, current_price: Decimal, target_delta: float = None) -> Decimal:
        """
        Select strike for cash-secured put.

        TastyTrade Guidelines:
        - Target 0.30 delta (~30% assignment probability, 70% success rate)
        - Strike typically 5-10% below current price
        - Only select strikes where willing to own stock

        Returns:
            Strike price (rounded to nearest standard strike)
        """
        if target_delta is None:
            target_delta = self.TARGET_DELTA

        # Approximate: 0.30 delta put typically 7-10% OTM
        # Use conservative 7% for safety
        strike_target = current_price * Decimal("0.93")

        # Round to nearest standard strike
        strike = round_to_even_strike(strike_target)

        return strike

    def _calculate_assignment_probability(self, delta: float) -> float:
        """
        Calculate approximate assignment probability from delta.

        Delta approximates probability of expiring ITM.

        Returns:
            Probability as percentage (0-100)
        """
        return abs(delta) * 100

    def _calculate_annualized_return(self, premium: Decimal, strike: Decimal, dte: int) -> Decimal:
        """
        Calculate annualized return as percentage.

        Formula: (Premium / Strike) × (365 / DTE) × 100

        Example: $3 premium, $100 strike, 45 DTE
                 = (3/100) × (365/45) × 100 = 3% × 8.11 × 100 = 24.3% annualized
        """
        return (premium / strike) * (Decimal("365") / Decimal(str(dte))) * Decimal("100")

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for cash-secured put.

        Single leg: Sell put at target strike

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - strike: Put strike to sell
                - quantity: Number of contracts

        Returns:
            List with single Leg (sell put)
        """
        from tastytrade.order import Leg

        from services.sdk.instruments import get_option_instruments_bulk

        # Build spec dictionary for the put option
        specs = [
            {
                "underlying": context["underlying_symbol"],
                "expiration": context["expiration_date"],
                "strike": context["strike"],
                "option_type": "P",
            }
        ]

        # Get put instrument
        instruments = await get_option_instruments_bulk(context["session"], specs)

        if not instruments:
            raise ValueError(f"No put found at strike {context['strike']}")

        put_instrument = instruments[0]

        # Sell to open the put
        return [
            Leg(
                instrument_type=put_instrument.instrument_type,
                symbol=put_instrument.symbol,
                quantity=context["quantity"],
                action="Sell to Open",
            )
        ]

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for cash-secured put.

        Single leg: Buy to close the short put

        Args:
            position: Position with:
                - strikes: {"put_strike": Decimal}
                - expiration_date
                - underlying_symbol
                - quantity

        Returns:
            List with single Leg (buy to close put)
        """
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        # Get session using correct pattern
        account = await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        # Build spec dictionary for the put option
        specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["put_strike"],
                "option_type": "P",
            }
        ]

        # Get put instrument
        instruments = await get_option_instruments_bulk(session, specs)

        if not instruments:
            raise ValueError(f"No put found at strike {position.strikes['put_strike']}")

        put_instrument = instruments[0]

        # Buy to close the put (opposite of opening)
        return [
            Leg(
                instrument_type=put_instrument.instrument_type,
                symbol=put_instrument.symbol,
                quantity=position.quantity,
                action="Buy to Close",
            )
        ]
