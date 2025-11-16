"""Unit tests for ErrorResponseBuilder utility.

Tests ensure consistent error handling across API endpoints with proper:
- Status codes
- Error message formatting
- Logging behavior
- Security (no internal details leaked)
"""

import json
from unittest.mock import patch

from django.http import JsonResponse

from services.api.error_responses import ErrorResponseBuilder


class TestErrorResponseBuilderFromException:
    """Test the from_exception() method with various exception types."""

    def test_known_exception_no_account_error(self):
        """Test error response for NoAccountError (400)."""
        from services.core.exceptions import NoAccountError

        exc = NoAccountError(user_id=123)

        response = ErrorResponseBuilder.from_exception(exc, context="test_operation user=123")

        assert isinstance(response, JsonResponse)
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        assert "User 123 has no primary trading account configured" in data["error"]

    def test_known_exception_oauth_session_error(self):
        """Test error response for OAuthSessionError (500)."""
        from services.core.exceptions import OAuthSessionError

        exc = OAuthSessionError(user_id=456, reason="Session expired")

        response = ErrorResponseBuilder.from_exception(exc, context="test_operation user=456")

        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["success"] is False
        # 500 errors should NOT expose details by default
        assert data["error"] == "Trading session unavailable"

    def test_known_exception_stale_pricing_error(self):
        """Test error response for StalePricingError (400)."""
        from services.core.exceptions import StalePricingError

        exc = StalePricingError(suggestion_id=1, age_seconds=30)

        response = ErrorResponseBuilder.from_exception(exc, context="pricing_check")

        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        # 400 errors should expose details
        assert "Pricing data for suggestion 1 is stale" in data["error"]

    def test_known_exception_invalid_price_effect_error(self):
        """Test error response for InvalidPriceEffectError (400)."""
        from decimal import Decimal

        from services.core.exceptions import InvalidPriceEffectError

        exc = InvalidPriceEffectError(
            expected_effect="credit", actual_effect="debit", amount=Decimal("1.00")
        )

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Invalid price effect for this strategy" in data["error"]

    def test_known_exception_order_build_error(self):
        """Test error response for OrderBuildError (400)."""
        from services.core.exceptions import OrderBuildError

        exc = OrderBuildError(suggestion_id=1, reason="Failed to build order legs")

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Failed to build order legs" in data["error"]

    def test_known_exception_order_placement_error(self):
        """Test error response for OrderPlacementError (400)."""
        from services.core.exceptions import OrderPlacementError

        exc = OrderPlacementError(reason="Broker rejected order")

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Broker rejected order" in data["error"]

    def test_unknown_exception_fallback(self):
        """Test error response for unknown exception type (fallback to 500)."""
        exc = RuntimeError("Something unexpected happened")

        response = ErrorResponseBuilder.from_exception(exc, context="unknown_operation")

        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["success"] is False
        # Unknown exceptions should use generic message
        assert data["error"] == "An error occurred"

    def test_json_decode_error(self):
        """Test error response for JSONDecodeError (400)."""
        exc = json.JSONDecodeError("Expecting value", "", 0)

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        # 400 errors expose details
        assert "Expecting value" in data["error"]

    def test_value_error(self):
        """Test error response for ValueError (400)."""
        exc = ValueError("Invalid integer format")

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Invalid integer format" in data["error"]

    def test_type_error(self):
        """Test error response for TypeError (400)."""
        exc = TypeError("Expected string, got int")

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Expected string, got int" in data["error"]

    @patch("services.api.error_responses.logger")
    def test_logging_error_level(self, mock_logger):
        """Test that errors are logged at error level by default."""
        exc = ValueError("Test error")

        ErrorResponseBuilder.from_exception(exc, context="test_op")

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "test_op" in call_args
        assert "ValueError" in call_args

    @patch("services.api.error_responses.logger")
    def test_logging_warning_level(self, mock_logger):
        """Test that log_level parameter controls logging level."""
        exc = ValueError("Test warning")

        ErrorResponseBuilder.from_exception(exc, context="test_op", log_level="warning")

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert "test_op" in call_args
        assert "ValueError" in call_args

    @patch("services.api.error_responses.logger")
    def test_logging_info_level(self, mock_logger):
        """Test logging at info level."""
        exc = ValueError("Test info")

        ErrorResponseBuilder.from_exception(exc, context="test_op", log_level="info")

        mock_logger.info.assert_called_once()

    def test_include_details_false_for_400(self):
        """Test that include_details=False hides exception details even for 4xx."""
        exc = ValueError("Sensitive validation error")

        response = ErrorResponseBuilder.from_exception(exc, include_details=False)

        assert response.status_code == 400
        data = json.loads(response.content)
        # Should use generic message, not exception details
        assert data["error"] == "Invalid value provided"
        assert "Sensitive" not in data["error"]

    def test_include_details_true_for_500(self):
        """Test that 5xx errors never expose details even with include_details=True."""
        exc = RuntimeError("Internal database error")

        response = ErrorResponseBuilder.from_exception(exc, include_details=True)

        assert response.status_code == 500
        data = json.loads(response.content)
        # Should still use generic message for 500
        assert data["error"] == "An error occurred"
        assert "database" not in data["error"]

    def test_exception_subclass_matching(self):
        """Test that exception subclasses are matched correctly via isinstance."""
        from django.core.exceptions import PermissionDenied

        class CustomPermissionDenied(PermissionDenied):
            """Custom subclass of PermissionDenied."""

            pass

        exc = CustomPermissionDenied("Access denied to resource X")

        response = ErrorResponseBuilder.from_exception(exc, include_details=False)

        assert response.status_code == 403
        data = json.loads(response.content)
        # Should match parent class PermissionDenied
        assert data["error"] == "Access denied"

    def test_exception_subclass_with_details(self):
        """Test that exception subclasses expose details when include_details=True."""
        from django.core.exceptions import ValidationError

        class CustomValidationError(ValidationError):
            """Custom subclass of ValidationError."""

            pass

        exc = CustomValidationError("Field X is required")

        response = ErrorResponseBuilder.from_exception(exc, include_details=True)

        assert response.status_code == 400
        data = json.loads(response.content)
        # Should expose details for 4xx
        assert "Field X is required" in data["error"]


class TestErrorResponseBuilderHelpers:
    """Test the helper methods for common error responses."""

    def test_validation_error_without_field(self):
        """Test validation_error() helper without field."""
        response = ErrorResponseBuilder.validation_error("Invalid credit format")

        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Invalid credit format"
        assert "field" not in data

    def test_validation_error_with_field(self):
        """Test validation_error() helper with field."""
        response = ErrorResponseBuilder.validation_error(
            "Invalid credit format", field="custom_credit"
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Invalid credit format"
        assert data["field"] == "custom_credit"

    def test_not_found_default(self):
        """Test not_found() helper with default resource name."""
        response = ErrorResponseBuilder.not_found()

        assert response.status_code == 404
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Resource not found"

    def test_not_found_custom_resource(self):
        """Test not_found() helper with custom resource name."""
        response = ErrorResponseBuilder.not_found("Position")

        assert response.status_code == 404
        data = json.loads(response.content)
        assert data["error"] == "Position not found"

    def test_not_found_suggestion(self):
        """Test not_found() helper for Suggestion."""
        response = ErrorResponseBuilder.not_found("Suggestion")

        assert response.status_code == 404
        data = json.loads(response.content)
        assert data["error"] == "Suggestion not found"

    def test_permission_denied_default(self):
        """Test permission_denied() helper with default message."""
        response = ErrorResponseBuilder.permission_denied()

        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Access denied"

    def test_permission_denied_custom_message(self):
        """Test permission_denied() helper with custom message."""
        response = ErrorResponseBuilder.permission_denied("Not authorized to view this position")

        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["error"] == "Not authorized to view this position"

    def test_service_unavailable_default(self):
        """Test service_unavailable() helper with default message."""
        response = ErrorResponseBuilder.service_unavailable()

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Service temporarily unavailable"

    def test_service_unavailable_custom_message(self):
        """Test service_unavailable() helper with custom message."""
        response = ErrorResponseBuilder.service_unavailable("Account data currently unavailable")

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["error"] == "Account data currently unavailable"

    def test_json_decode_error_helper(self):
        """Test json_decode_error() helper."""
        response = ErrorResponseBuilder.json_decode_error()

        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Invalid JSON in request body"

    def test_internal_error_default(self):
        """Test internal_error() helper with default message."""
        response = ErrorResponseBuilder.internal_error()

        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["success"] is False
        assert data["error"] == "Internal server error"

    def test_internal_error_custom_message(self):
        """Test internal_error() helper with custom message."""
        response = ErrorResponseBuilder.internal_error("Database connection failed")

        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["error"] == "Database connection failed"


class TestErrorResponseBuilderSecurity:
    """Test security aspects of error responses."""

    def test_500_error_never_exposes_details(self):
        """Test that 500 errors never expose internal details."""
        exc = RuntimeError("Database password: secret123")

        response = ErrorResponseBuilder.from_exception(exc, include_details=True)

        assert response.status_code == 500
        data = json.loads(response.content)
        # Should NOT contain sensitive info
        assert "password" not in data["error"].lower()
        assert "secret" not in data["error"].lower()

    def test_oauth_error_hides_tokens(self):
        """Test that OAuth errors don't expose tokens."""
        from services.core.exceptions import OAuthSessionError

        exc = OAuthSessionError(user_id=123, reason="Invalid token: abc123xyz456")

        response = ErrorResponseBuilder.from_exception(exc)

        assert response.status_code == 500
        data = json.loads(response.content)
        # Should use generic message
        assert "token" not in data["error"].lower()
        assert "abc123" not in data["error"]

    def test_response_structure_consistent(self):
        """Test that all responses have consistent structure."""
        test_cases = [
            ErrorResponseBuilder.validation_error("test"),
            ErrorResponseBuilder.not_found(),
            ErrorResponseBuilder.permission_denied(),
            ErrorResponseBuilder.service_unavailable(),
            ErrorResponseBuilder.json_decode_error(),
            ErrorResponseBuilder.internal_error(),
        ]

        for response in test_cases:
            data = json.loads(response.content)
            # All responses must have these fields
            assert "success" in data
            assert "error" in data
            assert data["success"] is False
            assert isinstance(data["error"], str)
            assert len(data["error"]) > 0
