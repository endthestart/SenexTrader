"""
Base classes for trading strategies.

Each strategy owns its leg construction logic (SRP).
"""

from abc import ABC, abstractmethod
from typing import Any

from tastytrade.order import Leg

from trading.models import Position


class BaseStrategy(ABC):
    """
    Lifecycle-aware strategy contract used by automation services.

    All strategies automatically get:
    - user: Django User instance
    - risk_manager: EnhancedRiskManager for risk validation
    - market_analyzer: MarketAnalyzer for market data
    - options_service: StreamingOptionsDataService for option data

    Example:
        class MyStrategy(BaseStrategy):
            def __init__(self, user):
                super().__init__(user)
                # Add strategy-specific dependencies here
    """

    # Default score threshold (strategies can override)
    # Industry-aligned threshold from TastyTrade methodology
    MIN_SCORE_THRESHOLD = 35

    def __init__(self, user):
        """
        Initialize common strategy dependencies.

        Args:
            user: Django User instance for strategy execution context
        """
        from services.market_data.analysis import MarketAnalyzer
        from services.risk.manager import EnhancedRiskManager
        from services.streaming.options_service import StreamingOptionsDataService

        self.user = user
        self.risk_manager = EnhancedRiskManager(user)
        self.market_analyzer = MarketAnalyzer(user)
        self.options_service = StreamingOptionsDataService(user)

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        Return strategy identifier (snake_case).

        This property must be implemented by all strategies and should return
        a unique snake_case identifier for the strategy type.

        Examples:
            - "short_put_vertical"
            - "iron_condor"
            - "covered_call"
        """
        raise NotImplementedError

    @abstractmethod
    async def a_get_profit_target_specifications(self, position: Position, *args) -> list[Any]:
        """
        Return ordered profit target specifications for a position.

        Args:
            position: Position object with metadata
            *args: Additional strategy-specific arguments (e.g., trade for Senex Trident)

        Returns:
            List of profit target specification objects with:
            - spread_type: Identifier for which spread this targets
            - profit_percentage: Target profit percentage
            - order_spec: Order specification for execution
            - original_credit: Original credit received
        """
        raise NotImplementedError

    @abstractmethod
    def should_place_profit_targets(self, position: Position) -> bool:
        """Gate profit target creation for strategies that opt out."""
        raise NotImplementedError

    @abstractmethod
    def get_dte_exit_threshold(self, position: Position) -> int:
        """Return the DTE level where automation should trigger closure."""
        raise NotImplementedError

    def automation_enabled_by_default(self) -> bool:
        """Optional hook if a strategy wants automation opt-in behaviour."""
        return False

    def get_active_config(self):
        """Get active trading configuration for this specific strategy."""
        from trading.models import StrategyConfiguration

        return StrategyConfiguration.objects.filter(
            user=self.user, strategy_id=self.strategy_name, is_active=True
        ).first()

    async def a_get_active_config(self):
        """Get active trading configuration for this specific strategy (async version)."""
        from trading.models import StrategyConfiguration

        return await StrategyConfiguration.objects.filter(
            user=self.user, strategy_id=self.strategy_name, is_active=True
        ).afirst()

    async def a_dispatch_to_stream_manager(self, context: dict):
        """
        Dispatch suggestion generation context to stream manager via channel layer.

        Args:
            context: Suggestion context dict prepared by strategy
        """
        from decimal import Decimal

        from channels.layers import get_channel_layer

        # Serialize Decimals to floats for WebSocket transmission
        def serialize_decimals(obj):
            """Recursively convert Decimal objects to floats for serialization."""
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, dict):
                return {k: serialize_decimals(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [serialize_decimals(item) for item in obj]
            if isinstance(obj, tuple):
                return tuple(serialize_decimals(item) for item in obj)
            return obj

        serialized_context = serialize_decimals(context)

        channel_layer = get_channel_layer()
        group_name = f"stream_control_{self.user.id}"

        await channel_layer.group_send(
            group_name,
            {
                "type": "generate_suggestion",
                "context": serialized_context,
            },
        )

    async def a_validate_risk_budget(self, max_risk, is_stressed: bool = False) -> tuple[bool, str]:
        """
        Validate if position can be opened within risk budget.

        Args:
            max_risk: Maximum risk amount for the position
            is_stressed: Whether market is in stressed condition

        Returns:
            Tuple of (can_open, reason) where can_open is True if position is allowed
        """
        return await self.risk_manager.a_can_open_position(max_risk, is_stressed)

    @abstractmethod
    async def build_opening_legs(self, context: dict) -> list[Leg]:
        """
        Build opening order legs for this strategy.


        Args:
            context: Strategy-specific context containing:
                - session: OAuth session for API calls
                - underlying_symbol: Ticker symbol
                - expiration_date: Option expiration
                - strikes: Strategy-specific strike dict
                - quantity: Number of contracts

        Returns:
            List of tastytrade.order.Leg objects

        Example (Bull Call Spread):
            [
                Leg(buy call at 100 strike),
                Leg(sell call at 105 strike)
            ]

        Example (Long Straddle):
            [
                Leg(buy call at 100 strike),
                Leg(buy put at 100 strike)
            ]

        Note:
            Use services.utils.sdk_instruments.get_option_instruments_bulk()
            for efficient bulk instrument lookups.
        """
        raise NotImplementedError

    @abstractmethod
    async def build_closing_legs(self, position: Position) -> list[Leg]:
        """
        Build closing order legs for this strategy.


        Args:
            position: Position object containing:
                - strategy_id: Strategy identifier
                - underlying_symbol: Ticker symbol
                - expiration_date: Option expiration
                - strikes: Stored strike prices (JSON field)
                - quantity: Number of contracts
                - user: User object for session access

        Returns:
            List of tastytrade.order.Leg objects for closing

        Example (Bull Call Spread):
            [
                Leg(sell to close long call at 100),
                Leg(buy to close short call at 105)
            ]

        Note:
            Closing legs are OPPOSITE of opening:
            - Opening: buy → Closing: sell to close
            - Opening: sell → Closing: buy to close

            Use TastytradeService to get session from position.user.
        """
        raise NotImplementedError
