"""Validation utilities for trade execution."""

from decimal import Decimal, InvalidOperation
from typing import Any


class ExecutionValidator:
    """Validates trade execution parameters."""

    @staticmethod
    def validate_custom_credit(credit_raw: Any) -> tuple[Decimal | None, str | None]:
        """
        Validate custom credit parameter.

        Args:
            credit_raw: Raw credit value from request

        Returns:
            Tuple of (validated_decimal, error_message)
            - (Decimal, None) if valid
            - (None, error_string) if invalid
            - (None, None) if credit_raw is None
        """
        if credit_raw is None:
            return None, None

        # Validate format
        try:
            credit = Decimal(str(credit_raw))
        except (InvalidOperation, ValueError):
            return None, "Invalid credit format. Must be a valid number."

        # Validate positive
        if credit <= 0:
            return None, "Credit must be positive (greater than $0.00)."

        # Validate reasonable maximum
        if credit > Decimal("100.00"):
            return None, "Credit must not exceed $100.00."

        # Validate decimal precision
        if credit.as_tuple().exponent < -2:
            return None, "Credit must have at most 2 decimal places."

        return credit, None

    @staticmethod
    def validate_suggestion_access(suggestion, user) -> str | None:
        """
        Validate user has access to suggestion.

        Args:
            suggestion: TradingSuggestion instance or None
            user: User instance

        Returns:
            Error message string if invalid, None if valid
        """
        if not suggestion:
            return "Suggestion not found or not in pending status"

        if suggestion.user != user:
            return "Access denied to this suggestion"

        return None

    @staticmethod
    def validate_senex_trident_structure(suggestion) -> str | None:
        """
        Validate Senex Trident structure requirements.

        Senex Trident must have:
        - Exactly 2 put spreads
        - Exactly 1 call spread (when call spread is included)
        - Pricing that matches the structure

        Args:
            suggestion: TradingSuggestion instance

        Returns:
            Error message string if invalid, None if valid
        """
        strategy_id = suggestion.strategy_id

        # Only validate Senex Trident strategies
        if strategy_id != "senex_trident":
            return None

        # Validate put spread quantity
        if suggestion.put_spread_quantity != 2:
            return (
                f"Invalid Senex Trident structure: put_spread_quantity must be 2, "
                f"got {suggestion.put_spread_quantity}"
            )

        # Validate call spread quantity (if present)
        if suggestion.call_spread_quantity is not None and suggestion.call_spread_quantity > 0:
            if suggestion.call_spread_quantity != 1:
                return (
                    f"Invalid Senex Trident structure: call_spread_quantity must be 1, "
                    f"got {suggestion.call_spread_quantity}"
                )

        # Validate pricing exists
        if not suggestion.total_credit or suggestion.total_credit <= 0:
            return "Invalid pricing: total_credit must be positive"

        if not suggestion.put_spread_credit or suggestion.put_spread_credit <= 0:
            return "Invalid pricing: put_spread_credit must be positive"

        return None
