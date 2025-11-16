"""Standardized error response builder for API views.

Consolidates duplicate error response patterns across API endpoints.
Ensures consistent error handling, logging, and user-facing messages.
"""

from typing import ClassVar

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse

from services.core.logging import get_logger

logger = get_logger(__name__)


def _get_exception_mapping():
    """Lazy-load exception classes to avoid circular imports."""
    from json import JSONDecodeError

    from django.core.exceptions import ObjectDoesNotExist

    from services.core.exceptions import (
        InvalidPriceEffectError,
        NoAccountError,
        OAuthSessionError,
        OrderBuildError,
        OrderPlacementError,
        StalePricingError,
    )

    return {
        # Django exceptions
        ObjectDoesNotExist: (404, "Resource not found"),
        ValidationError: (400, "Invalid request data"),
        PermissionDenied: (403, "Access denied"),
        # Order service exceptions
        NoAccountError: (400, "No trading account configured"),
        OAuthSessionError: (500, "Trading session unavailable"),
        InvalidPriceEffectError: (400, "Invalid price calculation"),
        StalePricingError: (400, "Pricing data outdated"),
        OrderBuildError: (400, "Order build failed"),
        OrderPlacementError: (400, "Order placement failed"),
        # Generic exceptions
        JSONDecodeError: (400, "Invalid JSON in request body"),
        ValueError: (400, "Invalid value provided"),
        TypeError: (400, "Invalid type provided"),
    }


class ErrorResponseBuilder:
    """Build consistent error responses for API endpoints.

    Centralizes exception-to-response mapping, logging, and error message formatting.
    All error responses follow the pattern: {"success": False, "error": "..."}
    """

    _exception_map: ClassVar[dict | None] = None

    @classmethod
    def _get_map(cls):
        """Get or initialize exception map with lazy loading."""
        if cls._exception_map is None:
            cls._exception_map = _get_exception_mapping()
        return cls._exception_map

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        context: str | None = None,
        log_level: str = "error",
        include_details: bool = True,
    ) -> JsonResponse:
        """Build error response from exception.

        Args:
            exc: Exception that occurred
            context: Additional context for logging (e.g., user_id, action)
            log_level: 'error', 'warning', or 'info' (default: 'error')
            include_details: Whether to include exception details in response for 4xx errors.
                Default is True, which exposes the actual exception message for client errors.
                Set to False when the exception message might contain sensitive information:
                - Internal system paths or database schema details
                - User-specific data from other users (privacy concern)
                - Detailed authorization logic that could aid attackers

        Returns:
            JsonResponse with appropriate status code and user-safe message

        Examples:
            # Default behavior - expose client error details:
            try:
                service.execute()
            except (NoAccountError, OAuthSessionError) as e:
                return ErrorResponseBuilder.from_exception(
                    e, context=f"execute_suggestion user={user_id}"
                )

            # Hide sensitive permission logic:
            try:
                validate_user_access(user, resource)
            except PermissionDenied as e:
                return ErrorResponseBuilder.from_exception(
                    e, include_details=False  # Don't reveal why access was denied
                )
        """
        exc_name = exc.__class__.__name__

        # Log full details server-side
        log_msg = f"Exception in {context}: {exc_name}: {exc}" if context else f"{exc_name}: {exc}"

        if log_level == "error":
            logger.error(log_msg, exc_info=True)
        elif log_level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # Check exception class hierarchy for mapping
        exception_map = cls._get_map()
        status_code, base_message = None, None

        for exc_class, (code, msg) in exception_map.items():
            if isinstance(exc, exc_class):
                status_code, base_message = code, msg
                break

        # Default for unknown exceptions
        if status_code is None:
            status_code, base_message = 500, "An error occurred"

        # Build user-safe response
        response_data = {"success": False, "error": base_message}

        # Add specific error details if safe to expose (4xx errors only)
        if include_details and 400 <= status_code < 500:
            response_data["error"] = str(exc)

        return JsonResponse(response_data, status=status_code)

    @classmethod
    def validation_error(cls, message: str, field: str | None = None) -> JsonResponse:
        """Quick validation error response (400).

        Args:
            message: Error message to display
            field: Optional field name that failed validation

        Returns:
            JsonResponse with status 400

        Example:
            if not custom_credit:
                return ErrorResponseBuilder.validation_error(
                    "Invalid credit format", field="custom_credit"
                )
        """
        data = {"success": False, "error": message}
        if field:
            data["field"] = field
        return JsonResponse(data, status=400)

    @classmethod
    def not_found(cls, resource: str = "Resource") -> JsonResponse:
        """Quick 404 response.

        Args:
            resource: Name of the resource that wasn't found

        Returns:
            JsonResponse with status 404

        Example:
            return ErrorResponseBuilder.not_found("Suggestion")
        """
        return JsonResponse({"success": False, "error": f"{resource} not found"}, status=404)

    @classmethod
    def permission_denied(cls, message: str = "Access denied") -> JsonResponse:
        """Quick 403 response.

        Args:
            message: Permission error message

        Returns:
            JsonResponse with status 403

        Example:
            return ErrorResponseBuilder.permission_denied("Not authorized to view this position")
        """
        return JsonResponse({"success": False, "error": message}, status=403)

    @classmethod
    def service_unavailable(cls, message: str = "Service temporarily unavailable") -> JsonResponse:
        """Quick 503 response for service unavailability.

        Args:
            message: Service unavailability message

        Returns:
            JsonResponse with status 503

        Example:
            return ErrorResponseBuilder.service_unavailable("Account data currently unavailable")
        """
        return JsonResponse({"success": False, "error": message}, status=503)

    @classmethod
    def json_decode_error(cls) -> JsonResponse:
        """Quick response for JSON decode errors (400).

        Returns:
            JsonResponse with status 400

        Example:
            except json.JSONDecodeError:
                return ErrorResponseBuilder.json_decode_error()
        """
        return JsonResponse({"success": False, "error": "Invalid JSON in request body"}, status=400)

    @classmethod
    def internal_error(cls, message: str = "Internal server error") -> JsonResponse:
        """Quick 500 response for internal errors.

        Args:
            message: Error message (should be user-safe, no internal details)

        Returns:
            JsonResponse with status 500

        Example:
            return ErrorResponseBuilder.internal_error()
        """
        return JsonResponse({"success": False, "error": message}, status=500)
