"""
Debit Spread Strategy - Unified strategy for both bullish and bearish debit spreads.

This strategy consolidates Bull Call Spread and Bear Put Spread into a single
parameterized strategy that uses direction to determine behavior.

Strategy Characteristics:
- Bullish direction: Profits from upward price movement (Bull Call Spread)
- Bearish direction: Profits from downward price movement (Bear Put Spread)
- Theta-negative: Time decay reduces profit (long options)
- Max profit: Spread width - debit paid
- Max loss: Debit paid (limited risk)

When to Use:
- Bullish: Bullish market conditions with strong trend
- Bearish: Bearish market conditions with strong downtrend
- Low to moderate IV rank (affordable options)
- HV/IV ratio > 1.0 (options fairly priced)
- Strong ADX for directional momentum

Epic 29 Phase 3:
This strategy consolidates duplicate lines from separate Bull Call/Bear Put classes.
"""

from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.strategies.debit_spread_base import BaseDebitSpreadStrategy, SpreadDirection
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import round_to_even_strike
from trading.models import Position

logger = get_logger(__name__)


class DebitSpreadStrategy(BaseDebitSpreadStrategy):
    """
    Unified Debit Spread - Bullish (call) or Bearish (put) directional play.

    Suitable for trending markets with low-moderate IV.
    """

    MIN_IV_RANK = 10
    MAX_IV_RANK = 60
    OPTIMAL_IV_RANGE = (30, 50)
    MIN_DTE = 30
    MAX_DTE = 45

    def __init__(self, user, direction: str | SpreadDirection, strategy_name: str):
        super().__init__(user)
        if isinstance(direction, str):
            self._direction = (
                SpreadDirection.BULLISH
                if direction.lower() == "bullish"
                else SpreadDirection.BEARISH
            )
        else:
            self._direction = direction
        self._strategy_name = strategy_name

        if self._direction == SpreadDirection.BULLISH:
            self.LONG_OTM_PCT = Decimal("0.05")
        else:
            self.LONG_OTM_PCT = Decimal("0.03")

    @property
    def spread_direction(self) -> SpreadDirection:
        return self._direction

    @property
    def strategy_name(self) -> str:
        return self._strategy_name

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for debit spread (direction-aware).

        Favorable conditions depend on direction:
        - Bullish: Bullish trend, price above SMA, NOT bullish_exhausted
        - Bearish: Bearish trend, price below SMA, NOT bearish_exhausted

        Returns:
            (score adjustment from baseline, list of reason strings)
        """
        score_adjustment = 0.0
        reasons = []

        is_bullish = self._direction == SpreadDirection.BULLISH

        if is_bullish:
            if report.macd_signal == "strong_bullish":
                score_adjustment += 35
                reasons.append("Strong bullish trend - maximum favorable for bull call spread")
            elif report.macd_signal == "bullish":
                score_adjustment += 30
                reasons.append("Bullish direction - strong buy signal for bull call spread")
            elif report.macd_signal == "bullish_exhausted":
                score_adjustment -= 20
                reasons.append("Bullish exhausted - buying at top NOT suitable for debit spread")
            elif report.macd_signal == "neutral":
                score_adjustment += 5
                reasons.append("Neutral market - marginal for bull call spread")
            elif report.macd_signal == "bearish_exhausted":
                score_adjustment -= 10
                reasons.append("Bearish exhausted - still not favorable for bull call spread")
            elif report.macd_signal == "bearish":
                score_adjustment -= 40
                reasons.append("Bearish direction - bull call spread NOT suitable")
            elif report.macd_signal == "strong_bearish":
                score_adjustment -= 50
                reasons.append("Strong bearish trend - extremely unfavorable for bull call spread")
        elif report.macd_signal == "strong_bearish":
            score_adjustment += 35
            reasons.append("Strong bearish trend - maximum favorable for bear put spread")
        elif report.macd_signal == "bearish":
            score_adjustment += 30
            reasons.append("Bearish direction - strong signal for bear put spread")
        elif report.macd_signal == "bearish_exhausted":
            score_adjustment -= 20
            reasons.append("Bearish exhausted - selling at bottom NOT suitable for debit spread")
        elif report.macd_signal == "neutral":
            score_adjustment += 5
            reasons.append("Neutral market - marginal for bear put spread")
        elif report.macd_signal == "bullish_exhausted":
            score_adjustment -= 10
            reasons.append("Bullish exhausted - still not favorable for bear put spread")
        elif report.macd_signal == "bullish":
            score_adjustment -= 40
            reasons.append("Bullish direction - bear put spread NOT suitable")
        elif report.macd_signal == "strong_bullish":
            score_adjustment -= 50
            reasons.append("Strong bullish trend - extremely unfavorable for bear put spread")

        if is_bullish:
            if report.current_price > report.sma_20:
                # Defensive check: prevent division by zero if SMA is 0
                if report.sma_20 and report.sma_20 > 0:
                    price_above_pct = ((report.current_price - report.sma_20) / report.sma_20) * 100
                    score_adjustment += 15
                    reasons.append(
                        f"Price ${report.current_price:.2f} above 20-day SMA "
                        f"(${report.sma_20:.2f}, +{price_above_pct:.1f}%) - confirmed uptrend"
                    )
                else:
                    # SMA missing or zero - can't calculate percentage
                    score_adjustment += 10
                    reasons.append(
                        f"Price ${report.current_price:.2f} above 20-day SMA - uptrend likely, "
                        "but insufficient data for percentage calculation"
                    )
            else:
                score_adjustment -= 20
                reasons.append("Price below 20-day SMA - uptrend not confirmed, risk of reversal")
        elif report.current_price < report.sma_20:
            # Defensive check: prevent division by zero if SMA is 0
            if report.sma_20 and report.sma_20 > 0:
                price_below_pct = ((report.sma_20 - report.current_price) / report.sma_20) * 100
                score_adjustment += 20
                reasons.append(
                    f"Price ${report.current_price:.2f} below 20-day SMA "
                    f"(${report.sma_20:.2f}, -{price_below_pct:.1f}%) - downtrend confirmed"
                )
            else:
                # SMA missing or zero - can't calculate percentage
                score_adjustment += 15
                reasons.append(
                    f"Price ${report.current_price:.2f} below 20-day SMA - downtrend likely, "
                    "but insufficient data for percentage calculation"
                )
        # Defensive check: prevent division by zero if SMA is 0
        elif report.sma_20 and report.sma_20 > 0:
            price_above_pct = ((report.current_price - report.sma_20) / report.sma_20) * 100
            score_adjustment -= 25
            reasons.append(
                f"Price ${report.current_price:.2f} above 20-day SMA "
                f"(${report.sma_20:.2f}, +{price_above_pct:.1f}%) - uptrend risk, "
                "not favorable for bear put spread"
            )
        else:
            # SMA missing or zero - can't calculate percentage
            score_adjustment -= 20
            reasons.append(
                f"Price ${report.current_price:.2f} above 20-day SMA - uptrend risk, "
                "not favorable for bear put spread (insufficient data for percentage)"
            )

        if is_bullish:
            if report.bollinger_position == "below_lower":
                score_adjustment += 5
                reasons.append(
                    "Price at lower Bollinger band - potential bounce entry, "
                    "oversold conditions favor bullish play"
                )
            elif report.bollinger_position == "above_upper":
                score_adjustment -= 5
                reasons.append(
                    "Price at upper Bollinger band - extended move, "
                    "caution warranted (may be overbought)"
                )
            elif report.bollinger_position == "within_bands":
                score_adjustment += 3
                reasons.append("Price within Bollinger range - neutral positioning")
        elif report.bollinger_position == "above_upper":
            score_adjustment += 10
            reasons.append(
                "Price at upper Bollinger band - potential reversal down, "
                "good setup for bear put spread"
            )
        elif report.bollinger_position == "below_lower":
            score_adjustment += 5
            reasons.append(
                "Price at lower Bollinger - already oversold, "
                "be cautious of bounce (limited downside)"
            )
        elif report.bollinger_position == "within_bands":
            score_adjustment += 5
            reasons.append("Price within range - neutral setup")

        if not is_bullish:
            if report.market_stress_level > 50:
                score_adjustment += 10
                reasons.append(
                    f"Elevated market stress ({report.market_stress_level:.0f}) - "
                    "fear supports downside moves"
                )
            elif report.market_stress_level < 25:
                score_adjustment -= 5
                reasons.append(
                    "Low market stress - complacency may limit downside, "
                    "prefer higher fear for put spreads"
                )

        return (score_adjustment, reasons)

    def _get_target_criteria(
        self, current_price: Decimal, spread_width: int, report: MarketConditionReport
    ) -> dict:
        """
        Get target criteria for debit spread strike optimization.

        Returns target criteria (not calculated strikes) so the optimizer
        can find the best available strikes from the option chain.

        Returns:
            Dict with optimization criteria for finding optimal strikes
        """
        if self._direction == SpreadDirection.BULLISH:
            return {
                "spread_type": "bull_call",
                "otm_pct": 0.05,
                "spread_width": spread_width,
                "current_price": current_price,
                "support_level": None,
                "resistance_level": (
                    Decimal(str(report.resistance_level)) if report.resistance_level else None
                ),
            }
        return {
            "spread_type": "bear_put",
            "otm_pct": 0.03,
            "spread_width": spread_width,
            "current_price": current_price,
            "support_level": (Decimal(str(report.support_level)) if report.support_level else None),
            "resistance_level": None,
        }

    def _get_occ_bundle_strikes(self, strikes: dict) -> dict:
        """Get strikes for OCC bundle creation (direction-based)."""
        if self._direction == SpreadDirection.BULLISH:
            return {"long_call": strikes["long_call"], "short_call": strikes["short_call"]}
        return {"long_put": strikes["long_put"], "short_put": strikes["short_put"]}

    def _extract_pricing_from_data(self, pricing_data):
        """Extract debit values from pricing data (direction-based)."""
        if self._direction == SpreadDirection.BULLISH:
            return (abs(pricing_data.call_credit), abs(pricing_data.call_mid_credit))
        return (abs(pricing_data.put_credit), abs(pricing_data.put_mid_credit))

    def _get_strike_field_mapping(self, strikes: dict) -> dict:
        """Map strikes to TradingSuggestion fields (direction-based)."""
        if self._direction == SpreadDirection.BULLISH:
            return {
                "long_call_strike": strikes["long_call"],
                "short_call_strike": strikes["short_call"],
                "long_put_strike": None,
                "short_put_strike": None,
            }
        return {
            "long_put_strike": strikes["long_put"],
            "short_put_strike": strikes["short_put"],
            "long_call_strike": None,
            "short_call_strike": None,
        }

    def _get_debit_field_mapping(self, debit: Decimal, mid_debit: Decimal) -> dict:
        """Map debit values to TradingSuggestion fields (negative credit)."""
        if self._direction == SpreadDirection.BULLISH:
            return {
                "call_spread_credit": -debit,
                "call_spread_mid_credit": -mid_debit,
                "put_spread_credit": None,
                "put_spread_mid_credit": None,
            }
        return {
            "put_spread_credit": -debit,
            "put_spread_mid_credit": -mid_debit,
            "call_spread_credit": None,
            "call_spread_mid_credit": None,
        }

    def _get_spread_quantity_fields(self) -> dict:
        """Get quantity fields for appropriate spread type."""
        if self._direction == SpreadDirection.BULLISH:
            return {
                "call_spread_quantity": 1,
                "put_spread_quantity": 0,
            }
        return {
            "put_spread_quantity": 1,
            "call_spread_quantity": 0,
        }

    async def a_select_strikes(
        self, report: MarketConditionReport, spread_width: int = 5
    ) -> dict[str, Decimal]:
        """
        Select strikes for debit spread (direction-based).

        Args:
            report: Market condition report with current price
            spread_width: Distance between strikes in dollars (default $5)

        Returns:
            Dict with strike keys based on direction
        """
        current_price = report.current_price

        if self._direction == SpreadDirection.BULLISH:
            long_strike_target = Decimal(str(current_price)) * (Decimal("1") + self.LONG_OTM_PCT)
            long_strike = round_to_even_strike(long_strike_target)
            short_strike = long_strike + Decimal(str(spread_width))

            logger.info(
                f"Bull Call Spread strikes: "
                f"Long Call ${long_strike} (5% OTM), "
                f"Short Call ${short_strike}, "
                f"Spread Width ${spread_width}"
            )

            return {
                "long_call": long_strike,
                "short_call": short_strike,
                "spread_width": Decimal(str(spread_width)),
            }
        long_put_target = Decimal(str(current_price)) * (Decimal("1") - self.LONG_OTM_PCT)
        long_put = round_to_even_strike(long_put_target)
        short_put = long_put - Decimal(str(spread_width))

        logger.info(
            f"Bear Put Spread strikes: "
            f"Long Put ${long_put} (~3% below current), "
            f"Short Put ${short_put}, "
            f"Spread Width ${spread_width}"
        )

        return {
            "long_put": long_put,
            "short_put": short_put,
            "spread_width": Decimal(str(spread_width)),
        }

    async def build_opening_legs(self, context: dict) -> list:
        """Build opening legs for debit spread based on direction."""
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        spread_type = "call_spread" if self._direction == SpreadDirection.BULLISH else "put_spread"

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type=spread_type,
            strikes=context["strikes"],
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position: Position) -> list:
        """Build closing legs for debit spread based on direction."""
        from decimal import Decimal as D

        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        metadata = position.metadata or {}
        expiration_date = metadata.get("expiration_date")
        quantity = int(metadata.get("quantity", 1))

        account = await get_primary_tastytrade_account(self.user)
        if not account:
            raise ValueError(f"No TastyTrade account found for user {self.user.id}")

        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=self.user.id, refresh_token=account.refresh_token, is_test=account.is_test
        )

        if not session_result.get("success"):
            raise ValueError(f"Failed to get session: {session_result.get('error')}")

        session = session_result["session"]

        if self._direction == SpreadDirection.BULLISH:
            long_strike = D(str(metadata.get("long_call_strike")))
            short_strike = D(str(metadata.get("short_call_strike")))

            specs = [
                {
                    "underlying": position.symbol,
                    "expiration": expiration_date,
                    "strike": long_strike,
                    "option_type": "C",
                },
                {
                    "underlying": position.symbol,
                    "expiration": expiration_date,
                    "strike": short_strike,
                    "option_type": "C",
                },
            ]

            instruments = await get_option_instruments_bulk(session, specs)

            return [
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=instruments[0].symbol,
                    action=OrderAction.SELL_TO_CLOSE,
                    quantity=D(str(quantity)),
                ),
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=instruments[1].symbol,
                    action=OrderAction.BUY_TO_CLOSE,
                    quantity=D(str(quantity)),
                ),
            ]
        long_strike = D(str(metadata.get("long_put_strike")))
        short_strike = D(str(metadata.get("short_put_strike")))

        specs = [
            {
                "underlying": position.symbol,
                "expiration": expiration_date,
                "strike": long_strike,
                "option_type": "P",
            },
            {
                "underlying": position.symbol,
                "expiration": expiration_date,
                "strike": short_strike,
                "option_type": "P",
            },
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        return [
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.SELL_TO_CLOSE,
                quantity=D(str(quantity)),
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=D(str(quantity)),
            ),
        ]

    def calculate_greeks_requirements(self) -> dict[str, tuple[float, float]]:
        """Define Greeks requirements for debit spread."""
        if self._direction == SpreadDirection.BULLISH:
            return {
                "long_delta": (0.40, 0.60),
                "net_theta": (-5.0, -0.5),
                "net_vega": (0.0, 15.0),
            }
        return {
            "net_delta": (-60, -30),
            "net_theta": (-5.0, -0.5),
            "net_vega": (5.0, 15.0),
        }

    def should_place_profit_targets(self, position: Position) -> bool:
        """Enable profit targets at 50% of max profit for debit spreads."""
        return True

    def get_dte_exit_threshold(self, position: Position) -> int:
        """Close at 21 DTE to preserve remaining time value."""
        return 21

    async def a_get_profit_target_specifications(
        self, position: Position, *args, target_pct: int | None = None
    ) -> list:
        """
        Return profit target spec for debit spread.

        Debit Spread Target: Close at target_pct% of max profit (default 50%)
        Max profit = (width - debit) × 100
        Target = debit + (max_profit × target_pct/100)

        Args:
            position: Position object with metadata['opening_price']
            target_pct: Optional profit target percentage (40, 50, or 60). Defaults to 50.

        Returns:
            List of profit target specifications
        """
        # Use provided target_pct or default to 50
        actual_target_pct = target_pct if target_pct is not None else 50

        metadata = position.metadata or {}
        debit_paid = abs(Decimal(str(metadata.get("opening_price", 0))))

        if not debit_paid:
            logger.warning(f"No opening price in metadata for debit spread position {position.pk}")
            return []

        spread_width = Decimal("5.00")
        max_profit = spread_width - debit_paid

        # Calculate target price based on profit percentage
        profit_multiplier = Decimal(str(actual_target_pct / 100))
        profit_target_price = debit_paid + (max_profit * profit_multiplier)

        spread_type = (
            "long_call_vertical"
            if self._direction == SpreadDirection.BULLISH
            else "long_put_vertical"
        )

        return [
            {
                "spread_type": spread_type,
                "profit_percentage": actual_target_pct,
                "target_price": profit_target_price,
                "original_debit": debit_paid,
            }
        ]


@register_strategy("long_call_vertical")
class LongCallVerticalStrategy(DebitSpreadStrategy):
    """Long Call Vertical - Debit spread for bullish outlook."""

    def __init__(self, user):
        super().__init__(user, SpreadDirection.BULLISH, "long_call_vertical")


@register_strategy("long_put_vertical")
class LongPutVerticalStrategy(DebitSpreadStrategy):
    """Long Put Vertical - Debit spread for bearish outlook."""

    def __init__(self, user):
        super().__init__(user, SpreadDirection.BEARISH, "long_put_vertical")
