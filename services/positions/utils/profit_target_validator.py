"""Profit target details validation (Security - CODE_REVIEW.md Issues #7, #11)."""

from typing import Any


class ProfitTargetValidationError(Exception):
    """Raised when profit_target_details validation fails."""

    pass


def validate_profit_target_details(details: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and sanitize profit_target_details dictionary.

    This function prevents malicious data injection into Position.profit_target_details
    by enforcing strict type checking and allowed field validation.

    Expected structure:
    {
        "put_spread_1_40": {
            "order_id": "abc123",
            "percent": 40.0,
            "original_credit": 1.50,  # optional
            "target_price": 0.90,
            "status": "filled",  # optional, added after fill
            "filled_at": "2025-10-06T12:00:00Z",  # optional
            "fill_price": 0.85,  # optional
            "realized_pnl": 65.00  # optional
        }
    }

    Args:
        details: Dictionary to validate

    Returns:
        Sanitized dictionary with validated fields

    Raises:
        ProfitTargetValidationError: If validation fails

    References:
        - CODE_REVIEW.md Issue #7 (Input validation)
        - CODE_REVIEW.md Issue #11 (Notification content sanitization)
    """
    if not isinstance(details, dict):
        raise ProfitTargetValidationError(
            f"profit_target_details must be a dict, got {type(details).__name__}"
        )

    # Empty dict is valid (no profit targets created yet)
    if not details:
        return {}

    # Maximum number of profit targets per position (safety limit)
    MAX_TARGETS = 10
    if len(details) > MAX_TARGETS:
        raise ProfitTargetValidationError(
            f"Too many profit targets: {len(details)} (max {MAX_TARGETS})"
        )

    sanitized = {}

    # Allowed fields and their types
    REQUIRED_FIELDS = {
        "order_id": str,
        "percent": (int, float),
        "target_price": (int, float),
    }

    OPTIONAL_FIELDS = {
        "original_credit": (int, float),
        "status": str,
        "filled_at": str,
        "fill_price": (int, float),
        "realized_pnl": (int, float),
    }

    ALLOWED_STATUSES = {"filled", "cancelled", "rejected"}

    for spread_type, target_info in details.items():
        # Validate spread_type key
        if not isinstance(spread_type, str):
            raise ProfitTargetValidationError(
                f"spread_type key must be string, got {type(spread_type).__name__}"
            )

        # Validate key format (basic alphanumeric + underscore check)
        if not spread_type.replace("_", "").replace("-", "").isalnum():
            raise ProfitTargetValidationError(f"Invalid spread_type key format: {spread_type}")

        # Max key length (prevent memory exhaustion)
        if len(spread_type) > 100:
            raise ProfitTargetValidationError(
                f"spread_type key too long: {len(spread_type)} chars (max 100)"
            )

        # Validate target_info is dict
        if not isinstance(target_info, dict):
            raise ProfitTargetValidationError(
                f"Target info for {spread_type} must be dict, got {type(target_info).__name__}"
            )

        # Check required fields
        for field, field_type in REQUIRED_FIELDS.items():
            if field not in target_info:
                raise ProfitTargetValidationError(
                    f"Missing required field '{field}' in {spread_type}"
                )

            value = target_info[field]
            if not isinstance(value, field_type):
                actual_type = type(value).__name__
                raise ProfitTargetValidationError(
                    f"Field '{field}' in {spread_type} must be {field_type}, " f"got {actual_type}"
                )

        # Validate all fields (no extra fields allowed)
        all_allowed = set(REQUIRED_FIELDS.keys()) | set(OPTIONAL_FIELDS.keys())
        for field in target_info:
            if field not in all_allowed:
                raise ProfitTargetValidationError(
                    f"Unknown field '{field}' in {spread_type} (allowed: {all_allowed})"
                )

        # Validate optional fields if present
        for field, field_type in OPTIONAL_FIELDS.items():
            if field in target_info:
                value = target_info[field]
                if not isinstance(value, field_type):
                    actual_type = type(value).__name__
                    raise ProfitTargetValidationError(
                        f"Optional field '{field}' in {spread_type} must be {field_type}, "
                        f"got {actual_type}"
                    )

        # Validate specific field constraints
        percent = target_info["percent"]
        if not (0 < percent <= 100):
            raise ProfitTargetValidationError(
                f"Invalid percent in {spread_type}: {percent} (must be 0 < percent <= 100)"
            )

        target_price = target_info["target_price"]
        if target_price < 0:
            raise ProfitTargetValidationError(
                f"Invalid target_price in {spread_type}: {target_price} (must be >= 0)"
            )

        # Validate order_id format (basic alphanumeric check)
        order_id = target_info["order_id"]
        if order_id and not order_id.replace("-", "").replace("_", "").isalnum():
            raise ProfitTargetValidationError(
                f"Invalid order_id format in {spread_type}: {order_id}"
            )

        # Max order_id length
        if len(order_id) > 200:
            raise ProfitTargetValidationError(
                f"order_id too long in {spread_type}: {len(order_id)} chars (max 200)"
            )

        # Validate status if present
        if "status" in target_info:
            status = target_info["status"]
            if status not in ALLOWED_STATUSES:
                raise ProfitTargetValidationError(
                    f"Invalid status in {spread_type}: {status} (allowed: {ALLOWED_STATUSES})"
                )

        # Validate filled_at format if present (basic ISO 8601 check)
        if "filled_at" in target_info:
            filled_at = target_info["filled_at"]
            if len(filled_at) > 50:
                raise ProfitTargetValidationError(
                    f"filled_at too long in {spread_type}: {len(filled_at)} chars (max 50)"
                )

        # Validate numeric ranges for optional fields
        if "original_credit" in target_info and target_info["original_credit"] < 0:
            raise ProfitTargetValidationError(
                f"Invalid original_credit in {spread_type}: must be >= 0"
            )

        if "fill_price" in target_info and target_info["fill_price"] < 0:
            raise ProfitTargetValidationError(f"Invalid fill_price in {spread_type}: must be >= 0")

        # realized_pnl can be negative (losses)
        if "realized_pnl" in target_info:
            # Sanity check: P&L should be within reasonable bounds
            pnl = target_info["realized_pnl"]
            if abs(pnl) > 1_000_000:
                raise ProfitTargetValidationError(
                    f"Unrealistic realized_pnl in {spread_type}: {pnl} (abs must be < 1M)"
                )

        # Copy sanitized data
        sanitized[spread_type] = target_info.copy()

    return sanitized


def sanitize_for_notification(details: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize profit_target_details for inclusion in notifications.

    Removes sensitive fields and validates remaining data before sending
    to notification channels (email, WebSocket, etc.).

    Args:
        details: profit_target_details dictionary

    Returns:
        Sanitized dictionary safe for notifications

    References:
        - CODE_REVIEW.md Issue #11 (Notification content sanitization)
    """
    if not details:
        return {}

    # First validate structure
    validated = validate_profit_target_details(details)

    # Remove or truncate sensitive fields
    sanitized = {}
    for spread_type, target_info in validated.items():
        # Truncate order_id for security - extract suffix after "order_" if present
        order_id = target_info["order_id"]
        if order_id:
            # Find "order_" substring and extract everything after it
            if "order_" in order_id:
                idx = order_id.find("order_")
                # Extract everything after "order_" (6 chars), which gives us "_id_..." or "id_..."
                suffix = order_id[idx + 6 :]
                # Remove leading underscore if present
                if suffix.startswith("_"):
                    truncated_id = suffix[1:]  # Remove leading underscore
                else:
                    truncated_id = suffix
            else:
                # No "order_" found, just take last 8 characters
                truncated_id = order_id[-8:]
        else:
            truncated_id = None

        sanitized[spread_type] = {
            "percent": target_info["percent"],
            "status": target_info.get("status", "active"),
            "order_id": truncated_id,
        }

        # Include fill information if present (useful for notifications)
        if "filled_at" in target_info:
            sanitized[spread_type]["filled_at"] = target_info["filled_at"]
        if "realized_pnl" in target_info:
            # Round to 2 decimal places
            sanitized[spread_type]["realized_pnl"] = round(target_info["realized_pnl"], 2)

    return sanitized
