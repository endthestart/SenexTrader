"""
Credit Spread Strategy - Unified strategy for both bullish and bearish credit spreads.

This strategy consolidates Bull Put Spread and Bear Call Spread into a single
parameterized strategy that uses direction to determine behavior.

Strategy Characteristics:
- Bullish direction: Profits if price stays flat or rises (Bull Put Spread)
- Bearish direction: Profits if price stays flat or falls (Bear Call Spread)
- Theta-positive: Time decay increases profit
- Max profit: Credit received
- Max loss: Spread width - credit received

When to Use:
- Bullish: Bullish/neutral conditions with moderate to high IV
- Bearish: Bearish/neutral conditions with moderate to high IV
- Price away from support (bullish) or resistance (bearish)

This strategy consolidates ~240 duplicate lines from separate Bull Put/Bear Call classes.
"""

from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport, RegimeType
from services.strategies.core.types import Direction
from services.strategies.credit_spread_base import BaseCreditSpreadStrategy

logger = get_logger(__name__)


class CreditSpreadStrategy(BaseCreditSpreadStrategy):
    """
    Unified Credit Spread - Bullish (put) or Bearish (call) premium collection.

    Suitable for directional/neutral conditions with decent IV.
    """

    MIN_IV_RANK = 35
    SUPPORT_BUFFER_PCT = 2.0
    RESISTANCE_BUFFER_PCT = 2.0

    def __init__(self, user, direction: str | Direction, strategy_name: str):
        super().__init__(user)
        if isinstance(direction, str):
            self._direction = (
                Direction.BULLISH
                if direction.lower() == "bullish"
                else Direction.BEARISH
            )
        else:
            self._direction = direction
        self._strategy_name = strategy_name

    @property
    def spread_direction(self) -> Direction:
        return self._direction

    @property
    def strategy_name(self) -> str:
        return self._strategy_name

    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions for credit spread (direction-aware).

        Favorable conditions depend on direction:
        - Bullish: Bullish/neutral regime, NOT overbought with exhaustion
        - Bearish: Bearish/neutral regime, NOT oversold with exhaustion

        Returns:
            (score adjustment from baseline, list of reason strings)
        """
        score_adjustment = 0.0
        reasons = []

        is_bullish = self._direction == Direction.BULLISH

        if report.regime_primary == RegimeType.BULL:
            if is_bullish:
                score_adjustment += 30
                reasons.append(
                    f"Bull regime (confidence {report.regime_confidence:.0f}%) - very favorable for bull put spread"
                )
            else:
                score_adjustment -= 30
                reasons.append(
                    f"Bull regime (confidence {report.regime_confidence:.0f}%) - very unfavorable for bear call spread"
                )
        elif report.regime_primary == RegimeType.BEAR:
            if is_bullish:
                score_adjustment -= 30
                reasons.append(
                    f"Bear regime (confidence {report.regime_confidence:.0f}%) - very unfavorable for bull put spread"
                )
            else:
                score_adjustment += 30
                reasons.append(
                    f"Bear regime (confidence {report.regime_confidence:.0f}%) - very favorable for bear call spread"
                )
        else:
            score_adjustment += 15
            reasons.append(
                f"Neutral/range regime (confidence {report.regime_confidence:.0f}%) - favorable for credit spreads"
            )

        if report.iv_rank >= 70:
            score_adjustment += 20
            reasons.append(f"Very high IV rank {report.iv_rank:.0f} - premium collection ideal")
        elif report.iv_rank >= self.MIN_IV_RANK:
            boost = (report.iv_rank - self.MIN_IV_RANK) / 2
            score_adjustment += boost
            reasons.append(f"IV rank {report.iv_rank:.0f} adequate (+{boost:.1f})")
        else:
            penalty = (self.MIN_IV_RANK - report.iv_rank) * 2
            score_adjustment -= penalty
            reasons.append(f"IV rank {report.iv_rank:.0f} too low (-{penalty:.1f})")

        if report.macd_signal == "bullish":
            if is_bullish:
                score_adjustment += 10
                reasons.append("Bullish MACD - favorable for bull put spread")
            else:
                score_adjustment -= 10
                reasons.append("Bullish MACD - unfavorable for bear call spread")
        elif report.macd_signal == "bearish":
            if is_bullish:
                score_adjustment -= 10
                reasons.append("Bearish MACD - unfavorable for bull put spread")
            else:
                score_adjustment += 10
                reasons.append("Bearish MACD - favorable for bear call spread")

        if report.is_range_bound:
            score_adjustment += 10
            reasons.append("Range-bound market - favorable for credit spreads")

        if report.rsi > 70:
            if is_bullish:
                score_adjustment -= 15
                reasons.append(f"Overbought RSI {report.rsi:.0f} - risky for bull put spread")
            else:
                score_adjustment += 5
                reasons.append(
                    f"Overbought RSI {report.rsi:.0f} - potential reversal for bear call spread"
                )
        elif report.rsi < 30:
            if is_bullish:
                score_adjustment += 5
                reasons.append(
                    f"Oversold RSI {report.rsi:.0f} - potential bounce for bull put spread"
                )
            else:
                score_adjustment -= 15
                reasons.append(f"Oversold RSI {report.rsi:.0f} - risky for bear call spread")

        stress = report.market_stress_level
        if stress > 60:
            score_adjustment -= 20
            reasons.append(f"High market stress {stress:.0f} - risky for credit spreads")
        elif stress > 40:
            score_adjustment -= 10
            reasons.append(f"Moderate stress {stress:.0f} - caution for credit spreads")
        elif stress < 20:
            score_adjustment += 10
            reasons.append(f"Low stress {stress:.0f} - favorable for credit spreads")

        return (score_adjustment, reasons)

    def _get_target_criteria(
        self, current_price: Decimal, spread_width: int, report: MarketConditionReport
    ) -> dict:
        """
        Get target criteria for strike optimization.

        Returns target criteria (not calculated strikes) so the optimizer
        can find the best available strikes from the option chain.

        Strategy:
        - Bull Put: ~3% OTM (below current price, above support)
        - Bear Call: ~3% OTM (above current price, below resistance)
        """
        if self._direction == Direction.BULLISH:
            return {
                "spread_type": "bull_put",
                "otm_pct": 0.03,
                "spread_width": spread_width,
                "current_price": current_price,
                "support_level": (
                    Decimal(str(report.support_level)) if report.support_level else None
                ),
                "resistance_level": None,
            }
        return {
            "spread_type": "bear_call",
            "otm_pct": 0.03,
            "spread_width": spread_width,
            "current_price": current_price,
            "support_level": None,
            "resistance_level": (
                Decimal(str(report.resistance_level)) if report.resistance_level else None
            ),
        }

    def _get_strike_field_mapping(self, strikes: dict) -> dict:
        """
        Map strike types to TradingSuggestion field names based on direction.

        Returns dict with TradingSuggestion field names as keys and strike values.
        """
        if self._direction == Direction.BULLISH:
            # Bull Put Spread: uses put strikes
            return {
                "short_put_strike": strikes["short_put"],
                "long_put_strike": strikes["long_put"],
                "short_call_strike": None,
                "long_call_strike": None,
            }
        # Bear Call Spread: uses call strikes
        return {
            "short_call_strike": strikes["short_call"],
            "long_call_strike": strikes["long_call"],
            "short_put_strike": None,
            "long_put_strike": None,
        }

    def _validate_strikes_direction(
        self, short_strike: Decimal, long_strike: Decimal, current_price: Decimal
    ) -> bool:
        """
        Validate strike relationship based on direction.
        """
        if self._direction == Direction.BULLISH:
            return short_strike < current_price and long_strike < short_strike
        return short_strike > current_price and long_strike > short_strike

    def _extract_pricing_from_data(self, pricing_data):
        """Extract credit values from pricing data based on direction."""
        if self._direction == Direction.BULLISH:
            return (pricing_data.put_credit, pricing_data.put_mid_credit)
        return (pricing_data.call_credit, pricing_data.call_mid_credit)

    def _get_occ_bundle_strikes(self, strikes: dict) -> dict:
        """Get strikes for OCC bundle creation based on direction."""
        if self._direction == Direction.BULLISH:
            return {"short_put": strikes["short_put"], "long_put": strikes["long_put"]}
        return {"short_call": strikes["short_call"], "long_call": strikes["long_call"]}

    def _get_credit_field_mapping(self, credit: Decimal, mid_credit: Decimal) -> dict:
        """Map credit values to TradingSuggestion fields based on direction."""
        if self._direction == Direction.BULLISH:
            return {
                "put_spread_credit": credit,
                "put_spread_mid_credit": mid_credit,
                "call_spread_credit": None,
                "call_spread_mid_credit": None,
            }
        return {
            "put_spread_credit": None,
            "put_spread_mid_credit": None,
            "call_spread_credit": credit,
            "call_spread_mid_credit": mid_credit,
        }

    def _get_spread_quantity_fields(self) -> dict:
        """Get quantity fields based on direction."""
        if self._direction == Direction.BULLISH:
            return {
                "put_spread_quantity": 1,
                "call_spread_quantity": 0,
            }
        return {
            "put_spread_quantity": 0,
            "call_spread_quantity": 1,
        }

    async def build_opening_legs(self, context: dict):
        """Build opening legs for credit spread based on direction."""
        from services.orders.utils.order_builder_utils import build_opening_spread_legs

        spread_type = "put_spread" if self._direction == Direction.BULLISH else "call_spread"

        return await build_opening_spread_legs(
            session=context["session"],
            underlying_symbol=context["underlying_symbol"],
            expiration_date=context["expiration_date"],
            spread_type=spread_type,
            strikes=context["strikes"],
            quantity=context.get("quantity", 1),
        )

    async def build_closing_legs(self, position):
        """Build closing legs for credit spread based on direction."""
        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        underlying = position.underlying_symbol
        expiration = position.expiration_date
        strikes = position.strikes
        quantity = position.quantity

        account = await get_primary_tastytrade_account(position.user)
        session = await TastyTradeSessionService.get_session_for_user(
            position.user, account.account_number
        )

        option_type = "P" if self._direction == Direction.BULLISH else "C"
        short_strike_key = (
            "short_put" if self._direction == Direction.BULLISH else "short_call"
        )
        long_strike_key = "long_put" if self._direction == Direction.BULLISH else "long_call"

        specs = [
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes[short_strike_key],
                "option_type": option_type,
            },
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strikes[long_strike_key],
                "option_type": option_type,
            },
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        return [
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=quantity,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.SELL_TO_CLOSE,
                quantity=quantity,
            ),
        ]
