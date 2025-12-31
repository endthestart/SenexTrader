from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractBaseUser

from services.account.state import AccountStateService
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async

logger = get_logger(__name__)


class EnhancedRiskManager:
    """
    Enhanced risk manager for Senex Trident strategy.

    === UNIFIED RISK CALCULATION FORMULA (DRY) ===

    This class provides THE SINGLE SOURCE OF TRUTH for all risk calculations.
    All other parts of the application (settings page, strategy suggestion, etc.)
    should use these methods to ensure consistency.

    Formula Chain:
    1. Tradeable Capital = buying_power + app_managed_risk
       - buying_power: liquid funds available for new trades
       - app_managed_risk: risk from existing positions we manage
       - Total pool of capital available for options trading

    2. Strategy Power = tradeable_capital × risk_tolerance
       - Applies user's risk preference (40% conservative, 50% moderate, etc.)
       - Use stressed_risk_tolerance during high volatility periods

    3. Remaining Budget = strategy_power - current_risk
       - How much risk budget is available for new positions
       - current_risk = sum of risk from all active app-managed positions

    4. Position Approval = position_risk ≤ remaining_budget
       - Only approve positions that fit within remaining budget

    Example with $4,200 buying power, 40% conservative risk:
    - Tradeable Capital: $4,200 + $0 = $4,200
    - Strategy Power: $4,200 × 0.40 = $1,680
    - Remaining Budget: $1,680 - $0 = $1,680 available
    """

    def __init__(self, user: AbstractBaseUser) -> None:
        self.user = user
        self.account_state_service = AccountStateService()

    # --- Async Methods (Primary Logic) ---

    async def a_get_tradeable_capital(self) -> tuple[Decimal, bool]:
        """
        Get tradeable capital: total capital pool available for options trading.

        Formula: buying_power + app_managed_risk
        - buying_power: liquid funds available for new trades
        - app_managed_risk: risk from existing positions we manage (adds back to pool)

        NOTE: This does NOT apply risk tolerance - that's done in a_calculate_strategy_power()
        """
        try:
            account_state = await self.account_state_service.a_get(self.user)
            if not account_state.get("available"):
                logger.warning(f"Account state not available for user {self.user.id}")
                return Decimal("0"), False

            # Fail fast if buying_power is None - don't use default values
            buying_power_value = account_state.get("buying_power")
            if buying_power_value is None:
                logger.warning(
                    f"Buying power is None for user {self.user.id}, account state: {account_state}"
                )
                return Decimal("0"), False

            buying_power = Decimal(str(buying_power_value))
            app_managed_risk = await self._a_calculate_app_managed_risk()

            # Tradeable capital = liquid funds + risk from positions we manage
            # This represents the total capital pool we're working with
            tradeable_capital = buying_power + app_managed_risk

            logger.info(
                f"TRADEABLE CAPITAL - Buying Power: ${buying_power}, "
                f"App Managed Risk: ${app_managed_risk}, "
                f"Total Tradeable Capital: ${tradeable_capital}"
            )
            return tradeable_capital, True

        except Exception as e:
            logger.error(f"Error getting tradeable capital: {e}", exc_info=True)
            return Decimal("0"), False

    async def _a_calculate_app_managed_risk(self) -> Decimal:
        """Calculate risk from positions managed by our app"""
        from trading.models import Position

        positions = [
            pos
            async for pos in Position.objects.filter(
                user=self.user,
                is_app_managed=True,
                lifecycle_state__in=["open_full", "open_partial", "closing"],
            )
        ]

        total_risk = Decimal("0")
        for position in positions:
            total_risk += position.get_risk_amount()

        return total_risk

    async def a_calculate_strategy_power(self, is_stressed: bool = False) -> tuple[Decimal, bool]:
        """
        Calculate strategy power: how much risk we can take from our tradeable capital.

        Formula: tradeable_capital × risk_tolerance
        - tradeable_capital: total capital pool (buying_power + app_managed_risk)
        - risk_tolerance: percentage we're willing to risk (0.40 = 40%)
        - is_stressed: use stressed_risk_tolerance when market is volatile
        """
        from accounts.models import OptionsAllocation  # noqa: PLC0415

        tradeable_capital, is_available = await self.a_get_tradeable_capital()

        if not is_available:
            return Decimal("0"), False

        # Get allocation to determine risk tolerance
        # OptionsAllocation is created automatically via signals when user is created
        allocation = await OptionsAllocation.objects.aget(user=self.user)

        # Use appropriate risk tolerance based on market conditions
        if is_stressed:
            risk_tolerance = Decimal(str(allocation.stressed_risk_tolerance))
            tolerance_type = "stressed"
        else:
            risk_tolerance = Decimal(str(allocation.risk_tolerance))
            tolerance_type = "normal"

        # Apply risk tolerance to get strategy power
        strategy_power = tradeable_capital * risk_tolerance

        tolerance_pct = risk_tolerance * 100
        logger.info(
            f"STRATEGY POWER - Tradeable Capital: ${tradeable_capital}, "
            f"Risk Tolerance ({tolerance_type}): {risk_tolerance} ({tolerance_pct}%), "
            f"Strategy Power: ${strategy_power}"
        )
        return strategy_power, True

    async def a_get_remaining_budget(self, is_stressed: bool = False) -> tuple[Decimal, bool]:
        """Available Risk = Strategy Power - Used Risk"""
        strategy_power, is_available = await self.a_calculate_strategy_power(is_stressed)

        if not is_available:
            return Decimal("0"), False

        used_risk = await self._a_calculate_app_managed_risk()
        remaining_budget = strategy_power - used_risk

        logger.info(
            f"BUDGET CALC - Strategy Power: ${strategy_power}, "
            f"Used Risk: ${used_risk}, Remaining Budget: ${remaining_budget}"
        )
        return remaining_budget, True

    async def a_can_open_position(
        self, position_risk: Decimal, is_stressed: bool = False
    ) -> tuple[bool, str]:
        """Enhanced position validation with market stress awareness"""
        remaining_budget, is_available = await self.a_get_remaining_budget(is_stressed)

        if not is_available:
            return (
                False,
                "Cannot approve position: Account data unavailable. No guessing allowed.",
            )

        if position_risk > remaining_budget:
            return (
                False,
                f"Position risk ${position_risk:.2f} exceeds remaining budget "
                f"${remaining_budget:.2f}",
            )

        return (
            True,
            f"Position approved: ${position_risk:.2f} within budget ${remaining_budget:.2f}",
        )

    async def a_get_risk_budget_data(self, is_stressed: bool = False) -> dict[str, Any]:
        """
        Get complete risk budget data for async contexts.

        Consolidates all risk calculations into a single method following DRY principle.
        This method provides the same data structure as the get_risk_budget view
        but returns it as a dict instead of JsonResponse for service-layer use.

        Returns:
            Dict with risk budget data or error information:
            {
                "data_available": bool,
                "tradeable_capital": float,
                "strategy_power": float,
                "current_risk": float,
                "remaining_budget": float,
                "utilization_percent": float,
                "is_stressed": bool,
                "error": str (if data_available=False)
            }
        """
        try:
            # Get tradeable capital
            tradeable_capital, capital_available = await self.a_get_tradeable_capital()
            if not capital_available:
                logger.warning(f"Cannot calculate tradeable capital for user {self.user.id}")
                return {"data_available": False, "error": "Cannot calculate tradeable capital"}

            # Get strategy power
            strategy_power, strategy_available = await self.a_calculate_strategy_power(is_stressed)
            if not strategy_available:
                logger.warning(f"Cannot calculate strategy power for user {self.user.id}")
                return {"data_available": False, "error": "Cannot calculate strategy power"}

            # Get remaining budget
            remaining, budget_available = await self.a_get_remaining_budget(is_stressed)
            if not budget_available:
                remaining = Decimal("0")

            # Get current risk
            current_risk = await self.a_get_app_managed_risk()

            # Convert Decimals to float for JSON compatibility
            def to_float(x: Any) -> float:
                return float(x) if isinstance(x, Decimal) else float(Decimal(str(x)))

            # Calculate utilization percentage
            utilization = (
                (to_float(current_risk) / to_float(strategy_power) * 100)
                if to_float(strategy_power) > 0
                else 0.0
            )
            utilization = max(0.0, min(100.0, utilization))

            # Calculate spread width and max spreads using tradeable capital
            spread_width = None
            max_spreads = None
            from trading.models import StrategyConfiguration

            # StrategyConfiguration is created automatically via signals when broker is connected
            # If it doesn't exist, user hasn't connected broker yet - use defaults
            try:
                config = await StrategyConfiguration.objects.aget(
                    user=self.user,
                    strategy_id="senex_trident",
                    is_active=True,
                )
            except StrategyConfiguration.DoesNotExist:
                # No broker connected yet - use default spread width calculation
                # Formula: nearest_odd(sqrt(capital / 1000)), minimum 3
                # Thresholds: 3→16k, 5→36k, 7→64k, 9→100k, 11→144k
                if tradeable_capital < 16000:
                    spread_width = 3
                elif tradeable_capital < 36000:
                    spread_width = 5
                elif tradeable_capital < 64000:
                    spread_width = 7
                elif tradeable_capital < 100000:
                    spread_width = 9
                elif tradeable_capital < 144000:
                    spread_width = 11
                else:
                    spread_width = 13
            else:
                spread_width = config.get_spread_width(tradeable_capital)
            max_spreads = self.calculate_max_spreads(strategy_power, spread_width)

            logger.info(
                f"RISK BUDGET DATA - User {self.user.id}: "
                f"Strategy Power: ${strategy_power}, Current Risk: ${current_risk}, "
                f"Remaining: ${remaining}, Utilization: {utilization:.1f}%, "
                f"Spread Width: {spread_width}, Max Spreads: {max_spreads}"
            )

            return {
                "data_available": True,
                "tradeable_capital": to_float(tradeable_capital),
                "strategy_power": to_float(strategy_power),
                "current_risk": to_float(current_risk),
                "remaining_budget": to_float(remaining),
                "utilization_percent": round(utilization, 2),
                "is_stressed": is_stressed,
                "spread_width": spread_width,
                "max_spreads": max_spreads,
            }

        except Exception as e:
            logger.error(
                f"Error getting risk budget data for user {self.user.id}: {e}", exc_info=True
            )
            return {"data_available": False, "error": f"Risk calculation error: {e!s}"}

    # --- Sync Wrappers for Django Views/Sync Code ---

    def get_tradeable_capital(self) -> tuple[Decimal, bool]:
        return run_async(self.a_get_tradeable_capital())

    def calculate_strategy_power(self, is_stressed: bool = False) -> tuple[Decimal, bool]:
        """Synchronous wrapper for strategy power calculation."""
        return run_async(self.a_calculate_strategy_power(is_stressed))

    def get_remaining_budget(self, is_stressed: bool = False) -> tuple[Decimal, bool]:
        """Synchronous wrapper for getting remaining risk budget."""
        return run_async(self.a_get_remaining_budget(is_stressed))

    def can_open_position(
        self, position_risk: Decimal, is_stressed: bool = False
    ) -> tuple[bool, str]:
        """Synchronous wrapper for position approval check."""
        return run_async(self.a_can_open_position(position_risk, is_stressed))

    def get_risk_budget_data(self, is_stressed: bool = False) -> dict[str, Any]:
        """Synchronous wrapper for getting complete risk budget data."""
        return run_async(self.a_get_risk_budget_data(is_stressed))

    # --- Methods that do not require I/O ---

    def get_app_managed_risk(self) -> Decimal:
        """Synchronous wrapper for a_get_app_managed_risk."""
        return run_async(self.a_get_app_managed_risk())

    async def a_get_app_managed_risk(self) -> Decimal:
        """Public method to get the currently used risk for app-managed positions."""
        return await self._a_calculate_app_managed_risk()

    def calculate_max_spreads(self, strategy_power: Decimal, spread_width: int) -> int:
        """Calculate maximum number of spreads allowed."""
        if spread_width <= 0:
            return 0
        return int(strategy_power / (spread_width * 100))
