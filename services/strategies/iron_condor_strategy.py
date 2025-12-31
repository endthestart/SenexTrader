"""
Unified Iron Condor Strategy - Put spread + Call spread with direction parameter.

Supports both LONG and SHORT iron condors:
- SHORT: Sell put spread + sell call spread (credit, wants HIGH IV, range-bound)
- LONG: Buy put spread + buy call spread (debit, wants LOW IV, range-bound)

"""

from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.base import BaseStrategy
from services.strategies.core.types import Side
from services.strategies.utils.strike_utils import round_to_even_strike

if TYPE_CHECKING:
    from tastytrade.order import Leg

    from trading.models import Position

logger = get_logger(__name__)


class IronCondorStrategy(BaseStrategy):
    """
    Unified Iron Condor Strategy - Defined risk range-bound play.

    Direction determines behavior:
    - SHORT: Sell OTM put spread + sell OTM call spread (credit, wants HIGH IV > 50)
    - LONG: Buy OTM put spread + buy OTM call spread (debit, wants LOW IV < 40)

    Structure (SHORT):
    - Sell put at strike 1 (OTM)
    - Buy put at strike 2 (further OTM - protection)
    - Sell call at strike 3 (OTM)
    - Buy call at strike 4 (further OTM - protection)
    - Max profit: Credit received
    - Max loss: Wing width - Credit received

    Structure (LONG):
    - Buy put at strike 1 (OTM)
    - Sell put at strike 2 (further OTM)
    - Buy call at strike 3 (OTM)
    - Sell call at strike 4 (further OTM)
    - Max profit: Wing width - Debit paid
    - Max loss: Debit paid
    """

    # Shared constants
    TARGET_DTE = 45
    MIN_DTE = 30
    MAX_DTE = 60
    WING_WIDTH = 5  # $5 wings
    TARGET_DELTA = 0.16  # ~16 delta for short strikes

    # SHORT-specific constants (want HIGH IV)
    SHORT_MIN_IV_RANK = 45
    SHORT_OPTIMAL_IV_RANK = 60
    SHORT_MAX_ADX = 25
    SHORT_IDEAL_ADX_MAX = 20
    SHORT_PROFIT_TARGET_PCT = 50

    # LONG-specific constants (want LOW IV)
    LONG_MAX_IV_RANK = 50  # Hard stop above this
    LONG_OPTIMAL_IV_RANK = 25
    LONG_MAX_ADX = 25
    LONG_IDEAL_ADX_MAX = 20
    LONG_MIN_RISK_REWARD_RATIO = Decimal("1.5")

    def __init__(self, user, direction: Side = Side.SHORT):
        """
        Initialize IronCondorStrategy with direction.

        Args:
            user: User object
            direction: Side.SHORT (sell) or Side.LONG (buy)
        """
        super().__init__(user)
        self.direction = direction

    @property
    def strategy_name(self) -> str:
        """Return strategy name based on direction."""
        if self.direction == Side.SHORT:
            return "short_iron_condor"
        return "long_iron_condor"

    def automation_enabled_by_default(self) -> bool:
        """Both directions have automation disabled (needs active management)."""
        return False

    def should_place_profit_targets(self, position: "Position") -> bool:
        """Enable profit targets for both directions."""
        return True

    def get_dte_exit_threshold(self, position: "Position") -> int:
        """Exit at 21 DTE to avoid gamma risk."""
        return 21

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions based on direction.

        SHORT: Wants HIGH IV (sell premium), range-bound
        LONG: Wants LOW IV (buy cheap), range-bound
        """
        if self.direction == Side.SHORT:
            return await self._score_short_iron_condor(report)
        return await self._score_long_iron_condor(report)

    async def _score_short_iron_condor(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for SHORT iron condor - wants HIGH IV, range-bound."""
        score = 50.0
        reasons = []

        # IV Rank - WANT HIGH (sell expensive premium)
        if report.iv_rank > 70:
            score += 30
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} > 70% - exceptional premium for selling"
            )
        elif report.iv_rank > 60:
            score += 20
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} in optimal range (60-70%) - excellent for premium selling"
            )
        elif report.iv_rank > 45:
            score += 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} adequate (45-60%) - acceptable premium")
        elif report.iv_rank > 35:
            score -= 10
            reasons.append(f"IV Rank {report.iv_rank:.1f} - lower premium, monitor closely")
        else:
            score -= 20
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 35% - insufficient premium for iron condor"
            )

        # ADX - Want WEAK trend (range-bound)
        if report.adx is not None:
            if report.adx < 20:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound, ideal for iron condor"
                )
            elif report.adx < 25:
                score += 15
                reasons.append(f"ADX {report.adx:.1f} weak trend - favorable for iron condor")
            elif report.adx < 30:
                score += 5
                reasons.append(f"ADX {report.adx:.1f} moderate trend - acceptable")
            elif report.adx < 35:
                score -= 15
                reasons.append(f"ADX {report.adx:.1f} strong trend - risky for iron condor")
            else:
                score -= 25
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - very strong trend, avoid iron condor"
                )

        # HV/IV Ratio - Want IV overpriced (ratio < 1.0)
        if report.hv_iv_ratio < 0.8:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - IV very high, "
                "excellent for premium selling"
            )
        elif report.hv_iv_ratio < 0.9:
            score += 12
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - IV moderately elevated"
            )
        elif report.hv_iv_ratio < 1.0:
            score += 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - near fair value")
        elif report.hv_iv_ratio < 1.2:
            score -= 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - slightly underpriced")
        else:
            score -= 15
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.2 - IV underpriced, poor for selling"
            )

        # Market direction - neutral is ideal
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for iron condor, no directional bias")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 5
            reasons.append(
                f"{report.macd_signal.capitalize()} bias - manageable, watch threatened side"
            )
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 10
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - increased directional risk"
            )

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price within Bollinger Bands - ideal for range-bound trade")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 8
            reasons.append("Price at Bollinger extremes - risky for iron condor")

        # Market stress - want low
        if report.market_stress_level < 35:
            score += 5
            reasons.append(
                f"Low market stress ({report.market_stress_level:.0f}) - stable environment"
            )
        elif report.market_stress_level > 60:
            score -= 10
            reasons.append(
                f"Very high market stress ({report.market_stress_level:.0f}) - "
                "directional movement risk"
            )

        return (score, reasons)

    async def _score_long_iron_condor(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """Score for LONG iron condor - wants LOW IV, range-bound."""
        score = 50.0
        reasons = []

        # HARD STOP: If IV > 50, use SHORT iron condor instead
        if report.iv_rank > 50:
            score = 0.0
            reasons.append(
                f"⚠️ HARD STOP: IV Rank {report.iv_rank:.1f} > 50% - use SHORT Iron Condor instead. "
                "SELL premium when IV is high, don't BUY."
            )
            return (score, reasons)

        # IV Rank - WANT LOW (buy cheap options)
        if report.iv_rank < 20:
            score += 35
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} < 20% - exceptionally cheap options, ideal for long condor"
            )
        elif report.iv_rank < 30:
            score += 25
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} - excellent low IV for buying spreads"
            )
        elif report.iv_rank < 40:
            score += 15
            reasons.append(f"IV Rank {report.iv_rank:.1f} - acceptable for long iron condor")
        else:
            score -= 15
            reasons.append(
                f"IV Rank {report.iv_rank:.1f} elevated - consider short iron condor instead"
            )

        # ADX - Want WEAK trend (range-bound - same as short)
        if report.adx is not None:
            if report.adx < 20:
                score += 25
                reasons.append(
                    f"ADX {report.adx:.1f} < 20 - range-bound, ideal for long condor"
                )
            elif report.adx < 25:
                score += 15
                reasons.append(f"ADX {report.adx:.1f} weak trend - favorable for range play")
            elif report.adx < 30:
                score += 5
                reasons.append(f"ADX {report.adx:.1f} moderate trend - acceptable")
            elif report.adx < 35:
                score -= 20
                reasons.append(
                    f"ADX {report.adx:.1f} strong trend - risky, avoid (directional move likely)"
                )
            else:
                score -= 30
                reasons.append(
                    f"ADX {report.adx:.1f} > 35 - very strong trend, avoid iron condor"
                )

        # HV/IV Ratio - Want volatility contracting
        if report.hv_iv_ratio < 0.8:
            score += 20
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} < 0.8 - volatility contracting, excellent"
            )
        elif report.hv_iv_ratio < 1.0:
            score += 10
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} - moderate volatility environment"
            )
        elif report.hv_iv_ratio < 1.3:
            score -= 5
            reasons.append(f"HV/IV ratio {report.hv_iv_ratio:.2f} - slightly elevated realized vol")
        else:
            score -= 10
            reasons.append(
                f"HV/IV ratio {report.hv_iv_ratio:.2f} > 1.3 - high realized volatility, risky"
            )

        # Market direction - neutral is ideal
        if report.macd_signal == "neutral":
            score += 15
            reasons.append("Neutral market - ideal for iron condor, no directional bias")
        elif report.macd_signal in ["bullish", "bearish"]:
            score += 5
            reasons.append(f"{report.macd_signal.capitalize()} bias - acceptable")
        elif report.macd_signal in ["strong_bullish", "strong_bearish"]:
            score -= 20
            reasons.append(
                f"{report.macd_signal.replace('_', ' ').capitalize()} - reduces probability of success"
            )

        # Bollinger position
        if report.bollinger_position == "within_bands":
            score += 10
            reasons.append("Price centered in range - ideal for iron condor")
        elif report.bollinger_position in ["above_upper", "below_lower"]:
            score -= 5
            reasons.append("Price at extremes - potential for continued move")

        # Market stress - want low
        if report.market_stress_level < 35:
            score += 10
            reasons.append(
                f"Low market stress ({report.market_stress_level:.0f}) - stable environment"
            )
        elif report.market_stress_level > 60:
            score -= 15
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - increased risk of breakout"
            )

        # Recent movement - want minimal
        if hasattr(report, "recent_move_pct") and report.recent_move_pct is not None:
            if report.recent_move_pct < 2.5:
                score += 5
                reasons.append("Minimal recent movement - consolidating nicely")
            elif report.recent_move_pct > 5.0:
                score -= 10
                reasons.append("Large recent movement - may continue trending")

        return (score, reasons)

    def _calculate_short_strikes(
        self, current_price: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate short strike positions (16 delta targets).

        Returns:
            (put_short, call_short) tuple - the strikes to sell
        """
        # Put short: 8% below current price (~16 delta)
        put_target = current_price * Decimal("0.92")
        put_short = round_to_even_strike(put_target)

        # Call short: 8% above current price (~16 delta)
        call_target = current_price * Decimal("1.08")
        call_short = round_to_even_strike(call_target)

        return (put_short, call_short)

    def _calculate_long_strikes(
        self, put_short: Decimal, call_short: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate long strike positions (wings).

        Returns:
            (put_long, call_long) tuple - the protective wings
        """
        put_long = put_short - Decimal(str(self.WING_WIDTH))
        call_long = call_short + Decimal(str(self.WING_WIDTH))
        return (put_long, call_long)

    def _calculate_max_profit(
        self, credit_received: Decimal, quantity: int = 1
    ) -> Decimal:
        """Calculate max profit for SHORT iron condor."""
        return credit_received * Decimal("100") * Decimal(str(quantity))

    def _calculate_max_loss(
        self, wing_width: int, credit_received: Decimal, quantity: int = 1
    ) -> Decimal:
        """Calculate max loss for SHORT iron condor."""
        max_loss_per_spread = Decimal(str(wing_width)) - credit_received
        return max_loss_per_spread * Decimal("100") * Decimal(str(quantity))

    def _calculate_breakevens(
        self, put_short_strike: Decimal, call_short_strike: Decimal, premium: Decimal
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate breakeven points.

        Returns:
            (breakeven_down, breakeven_up) tuple
        """
        breakeven_down = put_short_strike - premium
        breakeven_up = call_short_strike + premium
        return (breakeven_down, breakeven_up)

    # Long iron condor specific methods
    def _select_strikes(
        self, current_price: Decimal, target_profit_zone_pct: float = 10.0
    ) -> dict:
        """
        Select strikes for long iron condor profit zone.

        Returns:
            Dict with outer_put, inner_put, inner_call, outer_call
        """
        half_zone = Decimal(str(target_profit_zone_pct / 2)) / Decimal("100")

        inner_put_target = current_price * (Decimal("1") - half_zone)
        inner_call_target = current_price * (Decimal("1") + half_zone)

        inner_put = round_to_even_strike(inner_put_target)
        inner_call = round_to_even_strike(inner_call_target)

        outer_put = inner_put - Decimal(str(self.WING_WIDTH))
        outer_call = inner_call + Decimal(str(self.WING_WIDTH))

        return {
            "outer_put": outer_put,
            "inner_put": inner_put,
            "inner_call": inner_call,
            "outer_call": outer_call,
        }

    def _calculate_profit_zone_width(self, strikes: dict) -> Decimal:
        """Calculate width of profit zone."""
        return strikes["inner_call"] - strikes["inner_put"]

    def _calculate_long_max_profit(
        self, put_spread_width: Decimal, call_spread_width: Decimal, debit_paid: Decimal
    ) -> Decimal:
        """Calculate max profit for LONG iron condor."""
        # Max profit when one spread maxes out
        return Decimal(str(self.WING_WIDTH)) - debit_paid

    def _calculate_long_max_loss(self, debit_paid: Decimal) -> Decimal:
        """Calculate max loss for LONG iron condor."""
        return debit_paid

    def _calculate_breakeven_points(
        self, strikes: dict, debit_paid: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Calculate breakeven points for LONG iron condor."""
        # Simplified: debit is split between spreads
        half_debit = debit_paid / Decimal("2")
        lower_be = strikes["inner_put"] + half_debit
        upper_be = strikes["inner_call"] - half_debit
        return (lower_be, upper_be)

    def _calculate_risk_reward_ratio(
        self, max_profit: Decimal, max_loss: Decimal
    ) -> Decimal:
        """Calculate risk-reward ratio."""
        if max_loss == 0:
            return Decimal("0")
        return max_profit / max_loss

    def _validate_risk_reward(
        self, strikes: dict, estimated_debit: Decimal
    ) -> tuple[bool, str]:
        """Validate risk-reward ratio meets minimum."""
        max_profit = self._calculate_long_max_profit(
            Decimal(str(self.WING_WIDTH)),
            Decimal(str(self.WING_WIDTH)),
            estimated_debit,
        )
        max_loss = estimated_debit
        ratio = self._calculate_risk_reward_ratio(max_profit, max_loss)

        if ratio >= self.LONG_MIN_RISK_REWARD_RATIO:
            return (True, f"Risk-reward {ratio:.2f}:1 acceptable (min {self.LONG_MIN_RISK_REWARD_RATIO}:1)")
        return (False, f"Risk-reward {ratio:.2f}:1 below minimum {self.LONG_MIN_RISK_REWARD_RATIO}:1")

    async def a_score_market_conditions(
        self, report: MarketConditionReport
    ) -> tuple[float, str]:
        """Score market conditions for iron condor entry."""
        score, reasons = await self._score_market_conditions_impl(report)
        score = max(0, score)
        explanation = "\n".join(reasons)
        return (score, explanation)

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: "MarketConditionReport | None" = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> dict | None:
        """
        Prepare iron condor suggestion context.

        Builds 4-leg iron condor: sell OTM put/call spreads (SHORT) or buy them (LONG).
        SHORT: Sell OTM put spread + sell OTM call spread (wants HIGH IV)
        LONG: Buy OTM put spread + buy OTM call spread (wants LOW IV)
        """
        config = await self.a_get_active_config()

        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        score, explanation = await self.a_score_market_conditions(report)
        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f}")

        min_threshold = 35 if self.direction == Side.SHORT else 40
        if score < min_threshold and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < min_threshold:
            logger.warning(
                f"Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        current_price = Decimal(str(report.current_price))
        put_short, call_short = self._calculate_short_strikes(current_price)
        put_long, call_long = self._calculate_long_strikes(put_short, call_short)

        target_criteria = {
            "long_put": put_long,
            "short_put": put_short,
            "short_call": call_short,
            "long_call": call_long,
        }

        from services.market_data.utils.expiration_utils import find_expiration_with_exact_strikes

        result = await find_expiration_with_exact_strikes(
            self.user,
            symbol,
            target_criteria,
            min_dte=self.MIN_DTE,
            max_dte=self.MAX_DTE,
        )

        if not result:
            logger.warning(f"No expiration with iron condor strikes for {symbol}")
            return None

        expiration, strikes, _validated_chain = result
        logger.info(
            f"User {self.user.id}: Using expiration {expiration} "
            f"with IC strikes: put wing ${strikes.get('long_put')}, "
            f"put short ${strikes.get('short_put')}, "
            f"call short ${strikes.get('short_call')}, "
            f"call wing ${strikes.get('long_call')}"
        )

        occ_bundle = await self.options_service.build_occ_bundle(symbol, expiration, strikes)
        if not occ_bundle:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundle")
            return None

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

        context = {
            "config_id": config.id if config else None,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "market_data": serializable_report,
            "strikes": {
                "long_put": float(strikes["long_put"]),
                "short_put": float(strikes["short_put"]),
                "short_call": float(strikes["short_call"]),
                "long_call": float(strikes["long_call"]),
                "wing_width": self.WING_WIDTH,
            },
            "occ_bundle": occ_bundle.to_dict(),
            "suggestion_mode": suggestion_mode,
            "force_generation": force_generation,
            "direction": "SHORT" if self.direction == Side.SHORT else "LONG",
        }

        logger.info(f"User {self.user.id}: Context prepared for {self.strategy_name}")
        return context

    async def a_request_suggestion_generation(
        self, report: "MarketConditionReport | None" = None, symbol: str = "QQQ"
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
        context = await self.a_prepare_suggestion_context(symbol, report)
        if not context:
            logger.info(f"{self.strategy_name}: Conditions not suitable for {symbol}")
            return

        await self.a_dispatch_to_stream_manager(context)

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """
        Calculate final suggestion using live pricing data from cache.
        Called by UserStreamManager after pricing data arrives.

        Args:
            context: Context dict from a_prepare_suggestion_context()

        Returns:
            TradingSuggestion object with real pricing, or None if failed
        """
        from datetime import date, timedelta

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
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
        wing_width = Decimal(str(strikes["wing_width"]))
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)
        force_generation = context.get("force_generation", False)
        direction = context.get("direction", "SHORT")

        # Extract pricing for 4 legs
        long_put_price = pricing_data.snapshots.get("long_put")
        short_put_price = pricing_data.snapshots.get("short_put")
        short_call_price = pricing_data.snapshots.get("short_call")
        long_call_price = pricing_data.snapshots.get("long_call")

        if not all([long_put_price, short_put_price, short_call_price, long_call_price]):
            logger.warning("Missing pricing data for iron condor legs")
            return None

        # Calculate mid prices from bid/ask for each leg
        long_put_mid = (
            Decimal(str(long_put_price["bid"])) + Decimal(str(long_put_price["ask"]))
        ) / Decimal("2")
        short_put_mid = (
            Decimal(str(short_put_price["bid"])) + Decimal(str(short_put_price["ask"]))
        ) / Decimal("2")
        short_call_mid = (
            Decimal(str(short_call_price["bid"])) + Decimal(str(short_call_price["ask"]))
        ) / Decimal("2")
        long_call_mid = (
            Decimal(str(long_call_price["bid"])) + Decimal(str(long_call_price["ask"]))
        ) / Decimal("2")

        if direction == "SHORT":
            # SHORT: Sell inner strikes, buy outer wings
            # Credit = (Short Put + Short Call) - (Long Put + Long Call)
            total_credit = (
                Decimal(str(short_put_price["bid"])) + Decimal(str(short_call_price["bid"]))
            ) - (Decimal(str(long_put_price["ask"])) + Decimal(str(long_call_price["ask"])))
            total_mid_credit = (short_put_mid + short_call_mid) - (long_put_mid + long_call_mid)

            # Max risk = wing width - credit received
            max_risk_per_contract = (wing_width - total_mid_credit) * Decimal("100")
            max_profit_total = total_mid_credit * Decimal("100")
            price_effect = PriceEffect.CREDIT.value
        else:
            # LONG: Buy inner strikes, sell outer wings
            # Debit = (Long Put + Long Call) - (Short Put + Short Call)
            total_debit = (
                Decimal(str(short_put_price["ask"])) + Decimal(str(short_call_price["ask"]))
            ) - (Decimal(str(long_put_price["bid"])) + Decimal(str(long_call_price["bid"])))
            total_mid_credit = -total_debit  # Negative for debit
            total_credit = -total_debit

            # Max risk = debit paid
            max_risk_per_contract = total_debit * Decimal("100")
            # Max profit = wing width - debit paid
            max_profit_total = (wing_width - total_debit) * Decimal("100")
            price_effect = PriceEffect.DEBIT.value

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
            "macd_signal": market_data.get("macd_signal"),
            "adx": market_data.get("adx"),
            "hv_iv_ratio": market_data.get("hv_iv_ratio"),
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
            # Strikes
            short_put_strike=Decimal(str(strikes["short_put"])),
            long_put_strike=Decimal(str(strikes["long_put"])),
            short_call_strike=Decimal(str(strikes["short_call"])),
            long_call_strike=Decimal(str(strikes["long_call"])),
            # Quantities (all 1 for iron condor)
            put_spread_quantity=1,
            call_spread_quantity=1,
            # Pricing
            put_spread_credit=short_put_mid - long_put_mid,
            call_spread_credit=short_call_mid - long_call_mid,
            total_credit=Decimal(str(total_credit)),
            total_mid_credit=Decimal(str(total_mid_credit)),
            max_risk=max_risk_per_contract,
            price_effect=price_effect,
            max_profit=max_profit_total,
            # Market conditions
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,
            generation_notes=notes,
            # Status
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: Iron Condor ({direction}) suggestion created with real pricing - "
            f"Credit: ${total_mid_credit:.2f}, Max Risk: ${max_risk_per_contract:.2f}"
        )

        return suggestion

    async def a_get_profit_target_specifications(self, position: "Position", *args) -> list:
        """
        Return profit target spec for iron condor based on direction.

        SHORT: Target 50% of credit received
        LONG: Target 50% of max profit potential
        """
        from trading.models import TradeOrder

        opening_order = await TradeOrder.objects.filter(
            position=position, order_type="opening"
        ).afirst()

        if not opening_order or not opening_order.price:
            logger.warning(f"No opening order found for position {position.id}")
            return []

        if self.direction == Side.SHORT:
            original_credit = abs(opening_order.price)
            target_price = original_credit * Decimal("0.50")
            return [
                {
                    "spread_type": "short_iron_condor",
                    "profit_percentage": 50,
                    "target_price": target_price,
                    "original_credit": original_credit,
                }
            ]
        original_debit = abs(opening_order.price)
        max_profit = Decimal(str(self.WING_WIDTH)) - original_debit
        target_profit = max_profit * Decimal("0.50")
        target_price = original_debit + target_profit
        return [
            {
                "spread_type": "long_iron_condor",
                "profit_percentage": 50,
                "target_price": target_price,
                "original_debit": original_debit,
                "max_profit": max_profit,
            }
        ]

    async def build_opening_legs(self, context: dict) -> list["Leg"]:
        """Build opening legs for iron condor."""
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type="iron_condor",
            strikes=context["strikes"],
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: "Position") -> list["Leg"]:
        """Build closing legs for iron condor."""
        from tastytrade.order import Leg

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(position.user)

        strikes = position.strikes
        legs = []

        # Build specs for all four options
        specs = [
            {"strike": strikes["put_long"], "option_type": "P"},
            {"strike": strikes["put_short"], "option_type": "P"},
            {"strike": strikes["call_short"], "option_type": "C"},
            {"strike": strikes["call_long"], "option_type": "C"},
        ]

        for spec in specs:
            instruments = await get_option_instruments_bulk(
                session,
                [
                    {
                        "underlying": position.underlying_symbol,
                        "expiration": position.expiration_date,
                        "strike": spec["strike"],
                        "option_type": spec["option_type"],
                    }
                ],
            )

            if not instruments:
                raise ValueError(f"No option found at strike {spec['strike']}")

            # Determine action based on direction and whether it's long/short
            if self.direction == Side.SHORT:
                # Short IC: bought wings, sold shorts
                if spec["strike"] in [strikes["put_long"], strikes["call_long"]]:
                    action = "Sell to Close"  # Close long wings
                else:
                    action = "Buy to Close"  # Close short strikes
            # Long IC: sold wings, bought shorts (inner)
            elif spec["strike"] in [strikes["put_long"], strikes["call_long"]]:
                action = "Buy to Close"  # Close short outer wings
            else:
                action = "Sell to Close"  # Close long inner strikes

            legs.append(
                Leg(
                    instrument_type=instruments[0].instrument_type,
                    symbol=instruments[0].symbol,
                    quantity=position.quantity,
                    action=action,
                )
            )

        return legs
