"""Utility helpers for computing realized and unrealized P&L across trades.

This module delegates to PnLCalculator for actual calculations.
Kept for backward compatibility with existing code.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from services.core.utils.decimal_utils import to_decimal
from services.positions.lifecycle.pnl_calculator import PnLCalculator
from services.sdk.trading_utils import PriceEffect
from trading.models import Position, Trade

_DECIMAL_PLACES = Decimal("0.01")


@dataclass
class ProfitBreakdown:
    realized: Decimal
    unrealized: Decimal


class ProfitCalculator:
    """Centralised P&L helper used by lifecycle services.

    This class wraps PnLCalculator for trade-based P&L calculations.
    """

    def __init__(self, contract_multiplier: Decimal = Decimal("100")) -> None:
        self.contract_multiplier = contract_multiplier

    def calculate_trade_pnl(self, trade: Trade) -> Decimal:
        """Return realised P&L for a single trade."""
        executed_price = to_decimal(trade.executed_price or trade.fill_price)
        quantity = abs(trade.quantity or 0)
        if executed_price is None or quantity == 0:
            return Decimal("0")

        position = trade.position
        entry_price = to_decimal(position.avg_price)
        if entry_price is None:
            return Decimal("0")

        is_credit = position.opening_price_effect == PriceEffect.CREDIT.value
        return PnLCalculator.calculate_realized_pnl(
            opening_price=entry_price,
            closing_price=executed_price,
            quantity=quantity,
            is_credit=is_credit,
            multiplier=self.contract_multiplier,
        )

    def calculate_position_realized(
        self, position: Position, trades: Iterable[Trade] | None = None
    ) -> Decimal:
        """Aggregate realised P&L across filled lifecycle trades for a position."""
        relevant_trades = trades if trades is not None else position.trades.all()
        realised_total = Decimal("0")

        for trade in relevant_trades:
            if trade.trade_type not in {"close", "adjustment"}:
                continue
            if trade.status != "filled":
                continue

            trade_pnl = self.calculate_trade_pnl(trade)
            realised_total += trade_pnl

        return realised_total.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    def calculate_position_unrealized(self, position: Position) -> Decimal:
        """Return the stored unrealised P&L or zero if not available."""
        if position.unrealized_pnl is None:
            return Decimal("0")
        return Decimal(str(position.unrealized_pnl)).quantize(
            _DECIMAL_PLACES, rounding=ROUND_HALF_UP
        )

    def calculate_position_breakdown(self, position: Position) -> ProfitBreakdown:
        """Convenience helper returning both realised and unrealised totals."""
        realised = self.calculate_position_realized(position)
        unrealised = self.calculate_position_unrealized(position)
        return ProfitBreakdown(realized=realised, unrealized=unrealised)

    def calculate_profit_target_pnl(
        self,
        position: Position,
        close_price: Decimal | None,
        quantity: int,
        opening_price: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate realized P&L for a profit target fill.

        Delegates to PnLCalculator.calculate_profit_target_pnl.

        Args:
            position: Position being closed
            close_price: Price at which profit target filled
            quantity: Number of contracts closed
            opening_price: Spread-specific opening price (e.g., original_credit).
                If provided, uses this instead of position.avg_price.

        Returns:
            Realized P&L for this profit target fill
        """
        return PnLCalculator.calculate_profit_target_pnl(
            position=position,
            close_price=close_price,
            quantity=quantity,
            multiplier=self.contract_multiplier,
            opening_price=opening_price,
        )
