"""
Risk validation service - business logic extracted from JavaScript.
Implements centralized risk validation for trading operations.

Following CLAUDE.md principles:
- Simple, direct implementation
- Business logic in service layer, not frontend
- DRY principle for risk calculations
"""

from typing import Any

from django.utils import timezone

from services.core.logging import get_logger

logger = get_logger(__name__)


class RiskValidationService:
    """Centralized risk validation for trading operations."""

    @staticmethod
    async def validate_trade_risk(
        user, suggestion_id: str, suggestion_data: dict | None = None
    ) -> dict[str, Any]:
        """
        Validate trade risk against available budget and current utilization.

        This replaces the 92-line JavaScript validateRiskBudget method with
        proper server-side business logic.

        Args:
            user: Django User instance
            suggestion_id: ID of the trade suggestion to validate
            suggestion_data: Optional pre-loaded suggestion data to avoid API calls

        Returns:
            Dict with validation result:
            {
                "valid": bool,
                "message": str (if invalid),
                "warning": str (optional warning),
                "current_utilization": float,
                "new_utilization": float,
                "position_risk": float,
                "remaining_budget": float
            }
        """
        try:
            # Get current risk budget
            risk_data = await RiskValidationService._get_risk_budget(user)
            if not risk_data or not risk_data.get("data_available"):
                return {
                    "valid": False,
                    "message": (
                        "Cannot validate risk: Account data unavailable. "
                        "Trade execution blocked for safety."
                    ),
                }

            # Get suggestion details if not provided
            if not suggestion_data:
                suggestion_data = await RiskValidationService._get_suggestion_data(
                    user, suggestion_id
                )
                if not suggestion_data:
                    return {
                        "valid": False,
                        "message": "Cannot validate risk: Suggestion not found.",
                    }

            # Extract risk calculation data
            position_risk = float(suggestion_data.get("max_risk", 0))
            remaining_budget = float(risk_data.get("remaining_budget", 0))
            current_risk = float(risk_data.get("current_risk", 0))
            strategy_power = float(risk_data.get("strategy_power", 0))
            current_utilization = float(risk_data.get("utilization_percent", 0))

            # Validate position fits within remaining budget
            if position_risk > remaining_budget:
                return {
                    "valid": False,
                    "message": (
                        f"Trade risk (${position_risk:.2f}) exceeds remaining budget "
                        f"(${remaining_budget:.2f}). Cannot execute trade."
                    ),
                }

            # Calculate new utilization after this trade
            new_utilization = 0.0
            if strategy_power > 0:
                new_utilization = ((current_risk + position_risk) / strategy_power) * 100

            # Get user's risk warning thresholds from allocation settings
            try:
                allocation = user.options_allocation
                high_threshold = allocation.warning_threshold_high * 100
                medium_threshold = allocation.warning_threshold_medium * 100
            except Exception:
                # Fallback to conservative defaults if allocation not configured
                high_threshold = 80.0
                medium_threshold = 65.0

            # Generate warnings based on configured thresholds
            warning = None
            if new_utilization > high_threshold:
                remaining_pct = 100 - new_utilization
                warning = (
                    f"⚠️ WARNING: This trade will push risk utilization to "
                    f"{new_utilization:.1f}% ({remaining_pct:.1f}% remaining)."
                )
            elif new_utilization > medium_threshold:
                warning = (
                    f"CAUTION: This trade will increase risk utilization to "
                    f"{new_utilization:.1f}%. Consider position sizing."
                )

            return {
                "valid": True,
                "warning": warning,
                "current_utilization": current_utilization,
                "new_utilization": new_utilization,
                "position_risk": position_risk,
                "remaining_budget": remaining_budget,
            }

        except Exception as e:
            logger.error(
                f"Risk validation error for user {user.id}, suggestion {suggestion_id}: {e}"
            )
            return {
                "valid": False,
                "message": f"Risk validation failed: {e!s}. Trade execution blocked for safety.",
            }

    @staticmethod
    async def _get_risk_budget(user) -> dict | None:
        """Get current risk budget data for user."""
        try:
            # Use the new consolidated async method from EnhancedRiskManager
            from services.risk.manager import EnhancedRiskManager

            risk_manager = EnhancedRiskManager(user)
            return await risk_manager.a_get_risk_budget_data()
        except Exception as e:
            logger.error(f"Error getting risk budget for user: {e}")
            return None

    @staticmethod
    async def _get_suggestion_data(user, suggestion_id: str) -> dict | None:
        """Get suggestion details for risk calculation."""
        try:
            # Import here to avoid circular dependencies
            from asgiref.sync import sync_to_async

            from trading.models import TradingSuggestion

            # Get the suggestion directly from the database
            suggestion = await sync_to_async(
                TradingSuggestion.objects.filter(
                    user=user, id=suggestion_id, expires_at__gt=timezone.now()
                ).first
            )()

            if suggestion:
                # Return the suggestion data as dict
                return {
                    "id": suggestion.id,
                    "max_risk": float(suggestion.max_risk),
                    "total_credit": float(suggestion.total_credit),
                    "underlying_symbol": suggestion.underlying_symbol,
                    "expiration_date": suggestion.expiration_date.isoformat(),
                }

            logger.warning(f"Suggestion {suggestion_id} not found for user {user.id}")
            return None

        except Exception as e:
            logger.error(f"Error getting suggestion {suggestion_id} for user {user.id}: {e}")
            return None
