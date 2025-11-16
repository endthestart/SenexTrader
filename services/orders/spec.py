"""
Order specification data structures for strategy-agnostic order execution.
"""

from dataclasses import dataclass
from decimal import Decimal

from services.sdk.trading_utils import PriceEffect


@dataclass
class OrderLeg:
    """Represents a single leg of an order."""

    instrument_type: str  # e.g., "equity_option"
    symbol: str  # OCC symbol
    action: str  # "buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"
    quantity: int


@dataclass
class OrderSpec:
    """
    Generic order specification that can be executed by OrderExecutionService.
    Contains all information needed to place an order without strategy-specific knowledge.
    """

    legs: list[OrderLeg]
    limit_price: Decimal
    time_in_force: str = "GTC"  # "DAY", "GTC", etc.
    description: str = ""  # Human-readable description of the order
    order_type: str = "LIMIT"  # "LIMIT", "MARKET", etc.
    price_effect: str = (
        PriceEffect.CREDIT.value
    )  # "Credit" or "Debit" - determines how limit_price is interpreted

    def to_dict(self) -> dict:
        """Convert to dictionary format expected by TastyTrade API."""
        return {
            "legs": [
                {
                    "instrument_type": leg.instrument_type,
                    "symbol": leg.symbol,
                    "action": leg.action,
                    "quantity": leg.quantity,
                }
                for leg in self.legs
            ],
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force,
            "order_type": self.order_type,
            "description": self.description,
            "price_effect": self.price_effect,
        }


@dataclass
class ProfitTargetSpec:
    """Specification for a profit target order with strategy context."""

    order_spec: OrderSpec
    spread_type: str  # "put_spread_1", "put_spread_2", "call_spread"
    profit_percentage: int  # 40, 50, 60, etc.
    original_credit: Decimal  # Credit received when opening
