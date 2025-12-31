"""
Call Backspread (Ratio Call Backspread) - Advanced bullish strategy with unlimited profit.

Suitable when:
- IV Rank < 40 (cheap to buy calls)
- Strong bullish trend expected (ADX > 25)
- HV/IV ratio > 1.2 (options underpriced)
- Expecting large upside move (>10%)

Structure:
- Sell 1 ATM/ITM call (collect high premium)
- Buy 2 OTM calls (pay lower premium each)
- Ratio: 2:1 (buy 2, sell 1)
- Net result: Small credit or minimal debit

Example: SPY @ $550
- Sell 1x $550 call @ $15 = +$1,500
- Buy 2x $565 calls @ $7 = -$1,400
- Net credit: $100

Risk Profile:
- Max loss occurs at long call strikes ("danger zone")
- Unlimited profit on large rally
- Small profit if price drops significantly
- Probability of danger zone: ~20-25%

TastyTrade Methodology:
- Entry: IV rank < 40 (cheap options) + strong bullish trend
- DTE: 45 days
- Short call: ATM (delta ~0.50)
- Long calls: 5-10% OTM (delta ~0.30 each)
- Profit target: 50-100% on rally
- Management: Close if approaching danger zone
- Win rate: ~40-50%
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


class LongCallRatioBackspreadStrategy(BaseStrategy):
    """
    Long Call Ratio Backspread - Advanced bullish strategy with unlimited profit potential.

    WARNING: Has "danger zone" where max loss occurs.
    Requires understanding of complex risk profile.

    TastyTrade Methodology:
    - 45 DTE entry
    - ATM short call (delta ~0.50)
    - 5% OTM long calls (delta ~0.30 each)
    - 2:1 ratio (buy 2, sell 1)
    - Win rate: 40-50%
    """

    # Ratio configuration
    SELL_QUANTITY = 1
    BUY_QUANTITY = 2
    RATIO = BUY_QUANTITY / SELL_QUANTITY  # 2:1

    # Strike spacing
    OTM_DISTANCE_PCT = 5.0  # 5% OTM for long calls

    # Strategy-specific constants
    MAX_IV_RANK = 40  # Above this, options too expensive to buy
    OPTIMAL_IV_RANK = 25  # Sweet spot for cheap calls
    MIN_ADX_BULLISH = 25  # Need strong trend
    MIN_HV_IV_RATIO = 1.2  # Want options underpriced
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    PROFIT_TARGET_PCT = 75  # Close at 75% profit

    # Position sizing (smaller due to complexity)
    MAX_POSITION_SIZE_PCT = 0.03  # Max 3% of capital per backspread

    @property
    def strategy_name(self) -> str:
        return "long_call_ratio_backspread"

    def automation_enabled_by_default(self) -> bool:
        """Call backspreads are manual only (complex risk profile)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets at 75% profit."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Close at 21 DTE to avoid gamma risk."""
        return 21

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for call backspread.

        Target: Close when position value increases by 75%
        """
        from trading.models import TradeOrder

        # Get opening order
        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        original_price = abs(opening_order.price)
        # Target: 75% profit
        target_price = original_price * Decimal("1.75")

        return [
            {
                "spread_type": "long_call_ratio_backspread",
                "profit_percentage": 75,
                "target_price": target_price,
                "original_price": original_price,
            }
        ]

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for call backspread.

        Multi-factor scoring (0-100):
        - Bullish Bias (30% weight): MUST be bullish
        - Trend Strength (25% weight): Need strong trend (ADX > 25)
        - IV Environment (20% weight): Want LOW IV (cheap to buy)
        - HV/IV Ratio (15% weight): Want underpriced options
        - Volatility Expansion Potential (10% weight): Room for vol spike
        """
        score = 30.0  # Lower base (advanced strategy)
        reasons = []

        # CRITICAL: Must be bullish
        # Backspread penalizes exhaustion (buying at top is bad)
        if report.macd_signal == "strong_bullish":
            score += 30
            reasons.append("Strong bullish signal - excellent for call backspread")
        elif report.macd_signal == "bullish":
            score += 25
            reasons.append("Bullish signal - favorable for call backspread")
        elif report.macd_signal == "bullish_exhausted":
            return (0.0, ["Bullish exhausted - buying at top NOT suitable for backspread"])
        else:  # neutral, bearish_exhausted, bearish, strong_bearish
            return (
                0.0,
                [
                    f"Market not bullish ({report.macd_signal.replace('_', ' ')}) - "
                    "call backspread requires strong bullish outlook"
                ],
            )

        # Factor 2: Trend Strength (25% weight)
        # Need strong trend for large move
        if report.adx is not None:
            if report.adx > 35:
                score += 25
                reasons.append(
                    f"Very strong trend (ADX {report.adx:.1f}) - high probability of large move"
                )
            elif report.adx >= self.MIN_ADX_BULLISH:
                score += 20
                reasons.append(f"Strong trend (ADX {report.adx:.1f}) - favorable for backspread")
            elif report.adx > 20:
                score += 10
                reasons.append(f"Moderate trend (ADX {report.adx:.1f}) - marginal for backspread")
            else:
                score -= 20
                reasons.append(
                    f"Weak trend (ADX {report.adx:.1f}) - insufficient momentum for backspread"
                )

        # Factor 3: IV Environment (20% weight)
        # Lower IV = cheaper to buy calls
        if report.iv_rank < 25:
            score += 20
            reasons.append(f"Low IV rank {report.iv_rank:.1f} < 25 - options cheap to buy, ideal")
        elif report.iv_rank < self.MAX_IV_RANK:
            score += 15
            reasons.append(f"IV rank {report.iv_rank:.1f} < 40 - acceptable for buying calls")
        elif report.iv_rank < 50:
            score += 5
            reasons.append(f"IV rank {report.iv_rank:.1f} moderate - options getting expensive")
        else:
            score -= 15
            reasons.append(f"IV rank {report.iv_rank:.1f} > 50 - too expensive to buy calls")

        # Factor 4: HV/IV Ratio (15% weight)
        # Want HV > IV (options underpriced)
        if report.hv_iv_ratio > 1.3:
            score += 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.3 - options severely underpriced"
            )
        elif report.hv_iv_ratio >= self.MIN_HV_IV_RATIO:
            score += 12
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.2 - options underpriced vs realized"
            )
        elif report.hv_iv_ratio > 1.0:
            score += 7
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - options slightly underpriced")
        else:
            score -= 10
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - options not underpriced")

        # Factor 5: Volatility Expansion Potential (10% weight)
        # Want potential for vol expansion on rally
        if report.iv_rank < 30:
            score += 10
            reasons.append("Low IV with room for expansion on rally - enhances profit potential")
        elif report.iv_rank > 60:
            score -= 5
            reasons.append("High IV may contract - reduces profit potential")

        # Factor 6: Recent Move (risk assessment)
        if report.recent_move_pct is not None:
            if 2 < report.recent_move_pct < 5:
                score += 5
                reasons.append(
                    f"Moderate bullish momentum ({report.recent_move_pct:+.1f}%) - trend developing"
                )
            elif report.recent_move_pct > 10:
                score -= 10
                reasons.append(
                    f"Large recent move ({report.recent_move_pct:+.1f}%) - "
                    "may be exhausted, risky for backspread"
                )

        # Factor 7: Market Stress
        if report.market_stress_level < 40:
            score += 5
            reasons.append("Low market stress - stable environment for risk-taking")
        elif report.market_stress_level > 70:
            score -= 10
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - "
                "risky for complex strategy"
            )

        # Add warning about danger zone
        reasons.append(
            "Advanced strategy: Max loss occurs in danger zone at long call strikes (~20-25% probability)"
        )

        return (score, reasons)

    def _select_strikes(self, current_price: Decimal) -> dict[str, Decimal]:
        """
        Select strikes for call backspread.

        Strategy:
        - Short call: ATM (highest premium)
        - Long calls: 5% OTM (buy 2)

        Args:
            current_price: Current stock price

        Returns:
            Dict with short_call, long_calls, quantities
        """
        # Short call: ATM
        short_strike = round_to_even_strike(current_price)

        # Long calls: 5% OTM
        long_strike_target = current_price * (
            Decimal("1.0") + Decimal(str(self.OTM_DISTANCE_PCT / 100))
        )
        long_strike = round_to_even_strike(long_strike_target)

        return {
            "short_call": short_strike,
            "long_calls": long_strike,
            "quantity_short": self.SELL_QUANTITY,
            "quantity_long": self.BUY_QUANTITY,
        }

    def _calculate_danger_zone(
        self, short_strike: Decimal, long_strike: Decimal, credit_or_debit: Decimal
    ) -> dict:
        """
        Calculate the danger zone where max loss occurs.

        Args:
            short_strike: ATM short call strike
            long_strike: OTM long call strike
            credit_or_debit: Net credit (positive) or debit (negative)

        Returns:
            Dict with danger zone analysis
        """
        # Max loss occurs at long call strikes
        danger_price = long_strike

        # Calculate max loss
        # At long strike: short call fully ITM, long calls worthless
        intrinsic_short = long_strike - short_strike
        max_loss_per_spread = intrinsic_short - credit_or_debit  # Subtract credit or add debit

        # Probability based on delta (long calls ~0.30 delta = 30% ITM probability)
        probability = 0.25  # ~25% probability based on delta

        return {
            "danger_zone_price": danger_price,
            "max_loss_per_spread": max_loss_per_spread,
            "max_loss_total": max_loss_per_spread * Decimal("100"),  # Per contract
            "probability": probability,
            "warning": f"Max loss ${max_loss_per_spread * 100:.0f} occurs if price at ${danger_price} at expiration",
        }

    def _calculate_breakevens(
        self, short_strike: Decimal, long_strike: Decimal, credit_or_debit: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven points for call backspread.

        Lower BE: Short strike + (Long strike - Short strike - Net credit)
        Upper BE: Long strike + (Long strike - Short strike - Net credit)

        Args:
            short_strike: ATM short call strike
            long_strike: OTM long call strike
            credit_or_debit: Net credit (positive) or debit (negative)

        Returns:
            (lower_breakeven, upper_breakeven)
        """
        spread_width = long_strike - short_strike

        # Adjust for credit/debit
        adjustment = spread_width - credit_or_debit

        lower_be = short_strike + adjustment
        upper_be = long_strike + adjustment

        return (lower_be, upper_be)

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """
        Build opening legs for call backspread.

        Three legs:
        1. Sell 1 ATM call (collect premium)
        2. Buy 2 OTM calls (define risk and unlimited profit)

        Args:
            context: Dict with:
                - session: OAuth session
                - underlying_symbol: Ticker
                - expiration_date: Expiration
                - short_call: Short call strike
                - long_calls: Long call strike
                - quantity_short: Short call quantity (1)
                - quantity_long: Long call quantity (2)

        Returns:
            List with three Legs (1 sell, 2 buy)
        """
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="long_call_ratio_backspread",
            strikes={
                "short_call": context["short_call"],
                "long_call": context["long_calls"],
            },
            quantity=context.get("quantity_short", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """
        Build closing legs for call backspread.

        Three legs (opposite of opening):
        1. Buy to close ATM short call
        2. Sell to close OTM long calls (2x)

        Args:
            position: Position with:
                - strikes: {
                    "short_call": Decimal,
                    "long_calls": Decimal,
                    "quantity_short": int,
                    "quantity_long": int
                  }
                - expiration_date
                - underlying_symbol

        Returns:
            List with three Legs (closing all positions)
        """
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        # Get session
        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        # Build spec dictionaries for bulk fetch
        specs = [
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["short_call"],
                "option_type": "C",
            },
            {
                "underlying": position.underlying_symbol,
                "expiration": position.expiration_date,
                "strike": position.strikes["long_calls"],
                "option_type": "C",
            },
        ]

        # Get call instruments
        call_instruments = await get_option_instruments_bulk(session, specs)

        if len(call_instruments) != 2:
            raise ValueError("Could not find both call strikes")

        # Map strikes to instruments
        call_short = next(
            i for i in call_instruments if str(position.strikes["short_call"]) in i.symbol
        )
        call_long = next(
            i for i in call_instruments if str(position.strikes["long_calls"]) in i.symbol
        )

        # Build 3-leg closing order (opposite of opening)
        return [
            # Close short call
            Leg(
                instrument_type=call_short.instrument_type,
                symbol=call_short.symbol,
                quantity=position.strikes["quantity_short"],
                action="Buy to Close",
            ),
            # Close long calls
            Leg(
                instrument_type=call_long.instrument_type,
                symbol=call_long.symbol,
                quantity=position.strikes["quantity_long"],
                action="Sell to Close",
            ),
        ]

    async def a_score_market_conditions(self, report: "MarketConditionReport") -> tuple[float, str]:
        """
        Score market conditions for call backspread (0-100).

        Evaluates bullish environment with cheap options.
        Ideal: Low IV (<40), strong bullish trend (ADX>25), underpriced options.
        WARNING: Complex strategy with "danger zone" risk.
        """
        score, reasons = await self._score_market_conditions_impl(report)

        # Ensure score doesn't go below zero (no upper limit)
        score = max(0, score)

        explanation = "\n".join(reasons)
        return (score, explanation)

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: "Optional[MarketConditionReport]" = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> "Optional[dict]":
        """
        Prepare call backspread suggestion context.

        Builds 2:1 ratio spread: sell 1 ATM call, buy 2 OTM calls.
        Creates unlimited profit potential with "danger zone" risk at long strike.
        """
        # Get active config
        config = await self.a_get_active_config()

        # Get market report if not provided
        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)
        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f}")

        # Check threshold (allow bypass in force mode)
        if score < 35 and not force_generation:  # MIN_SCORE_THRESHOLD
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < 35:
            logger.warning(
                f"Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Calculate strikes for backspread
        current_price = Decimal(str(report.current_price))

        # Short call: ATM (delta ~0.50)
        short_call = round_to_even_strike(current_price)

        # Long calls: 5% OTM (delta ~0.30 each)
        long_call_target = current_price * Decimal("1.05")
        long_call = round_to_even_strike(long_call_target)

        # Find expiration with both strikes (use exact strike matching)
        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        required_strikes = {
            "short_call": short_call,
            "long_call": long_call,
        }

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            required_strikes,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(f"No expiration with backspread strikes for {symbol}")
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} "
            f"with Backspread strikes: short ${strikes.get('short_call')}, "
            f"long ${strikes.get('long_call')} (2:1 ratio)"
        )

        # Build OCC bundle for both strikes
        occ_bundle = await self.options_service.build_occ_bundle(symbol, expiration, strikes)
        if not occ_bundle:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundle")
            return None

        # Prepare serializable market data
        serializable_report = {
            "current_price": float(report.current_price),
            "iv_rank": float(report.iv_rank),
            "hv_iv_ratio": float(report.hv_iv_ratio),
            "adx": float(report.adx) if report.adx else None,
            "macd_signal": report.macd_signal,
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
            "strikes": {
                "short_call": float(strikes["short_call"]),
                "long_call": float(strikes["long_call"]),
            },
            "ratio": self.RATIO,  # 2:1
            "sell_quantity": self.SELL_QUANTITY,
            "buy_quantity": self.BUY_QUANTITY,
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,
            "force_generation": force_generation,
        }

        logger.info(f"User {self.user.id}: Context prepared for {self.strategy_name}")
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
            f"User {self.user.id}: Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """Calculate suggestion from cached pricing data (1:2 call backspread = sell 1 ATM, buy 2 OTM)."""
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

        # Extract pricing (1 short ATM, 2 long OTM)
        short_call_strike = Decimal(str(strikes["short_call"]))
        long_call_strike = Decimal(str(strikes["long_call"]))

        # Extract pricing using leg names as keys
        short_call_payload = pricing_data.snapshots.get("short_call")
        long_call_payload = pricing_data.snapshots.get("long_call")

        if not short_call_payload or not long_call_payload:
            logger.warning("Missing pricing data for call backspread")
            return None

        # Calculate mid prices
        short_call_mid = (
            Decimal(str(short_call_payload["bid"])) + Decimal(str(short_call_payload["ask"]))
        ) / Decimal("2")
        long_call_mid = (
            Decimal(str(long_call_payload["bid"])) + Decimal(str(long_call_payload["ask"]))
        ) / Decimal("2")

        # Net = sell 1 short - buy 2 longs
        # Usually a small credit or small debit
        net_credit = short_call_mid - (long_call_mid * Decimal("2"))

        # Max risk = if price stays at short strike
        # Risk = difference between strikes * 100 - net credit received
        strike_diff = long_call_strike - short_call_strike
        max_risk_per_contract = (strike_diff * Decimal("100")) - (net_credit * Decimal("100"))

        # Max profit = unlimited above long strike
        # Set to None to indicate unlimited profit potential
        max_profit_total = None

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

        # Build market_conditions with risk warning if applicable
        market_conditions_dict = {
            "hv_iv_ratio": market_data.get("hv_iv_ratio"),
            "macd_signal": market_data.get("macd_signal"),
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

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=expiration,
            short_call_strike=short_call_strike,
            long_call_strike=long_call_strike,
            call_spread_quantity=2,  # 2 long calls
            call_spread_credit=net_credit,
            total_credit=net_credit,
            total_mid_credit=net_credit,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value if net_credit > 0 else PriceEffect.DEBIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,
            generation_notes=notes,
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: Long Call Ratio Backspread suggestion - "
            f"Net: ${net_credit:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )
        return suggestion
