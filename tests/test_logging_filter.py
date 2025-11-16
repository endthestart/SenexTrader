"""
Tests for the SensitiveDataFilter logging filter.

This module tests that sensitive data is properly redacted from log messages
while preserving safe content unchanged.
"""

import logging
from unittest.mock import Mock

import pytest

from services.core.logging import SensitiveDataFilter


class TestSensitiveDataFilter:
    """Test suite for the SensitiveDataFilter class."""

    @pytest.fixture
    def filter(self):
        """Create a SensitiveDataFilter instance for testing."""
        return SensitiveDataFilter()

    @pytest.fixture
    def mock_record(self):
        """Create a mock LogRecord for testing."""
        record = Mock(spec=logging.LogRecord)
        record.msg = ""
        record.args = None
        return record

    def test_tokens_are_redacted(self, filter, mock_record):
        """Test that OAuth tokens and access tokens are properly redacted."""
        # Test Bearer token
        mock_record.msg = "Authorization header: Bearer abc123def456ghi789"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "Authorization header: Bearer [REDACTED_TOKEN]"

        # Test access token
        mock_record.msg = "Got response with access_token: xyz789secret123token"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "Got response with access_token: [REDACTED_TOKEN]"

        # Test access token with quotes
        mock_record.msg = 'Config: {"access_token": "super_secret_token_12345"}'
        assert filter.filter(mock_record) is True
        assert mock_record.msg == 'Config: {"access_token": "[REDACTED_TOKEN]"}'

        # Test case insensitive
        mock_record.msg = "ACCESS_TOKEN=my_secret_token_value"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "ACCESS_TOKEN=[REDACTED_TOKEN]"

    def test_passwords_are_redacted(self, filter, mock_record):
        """Test that passwords in various formats are properly redacted."""
        # Test password field
        mock_record.msg = "User login with password: MySecretPass123!"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "User login with password: [REDACTED_PASSWORD]"

        # Test pwd abbreviation
        mock_record.msg = "Database connection: pwd=admin123"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "Database connection: pwd=[REDACTED_PASSWORD]"

        # Test pass abbreviation
        mock_record.msg = "Auth failed for user with pass: wrongpass"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "Auth failed for user with pass: [REDACTED_PASSWORD]"

        # Test with quotes
        mock_record.msg = 'Login attempt {"username": "john", "password": "secret123"}'
        assert filter.filter(mock_record) is True
        assert (
            mock_record.msg
            == 'Login attempt {"username": "john", "password": "[REDACTED_PASSWORD]"}'
        )

        # Test case insensitive
        mock_record.msg = "PASSWORD=SuperSecret123"
        assert filter.filter(mock_record) is True
        assert mock_record.msg == "PASSWORD=[REDACTED_PASSWORD]"

    def test_multiple_patterns_are_redacted_in_one_message(self, filter, mock_record):
        """Test that multiple sensitive patterns in a single message are all redacted."""
        mock_record.msg = (
            "API call with api_key: abc123xyz789 and password: secret123 "
            "using Bearer token456 for SSN 123-45-6789"
        )
        assert filter.filter(mock_record) is True

        # Check that all patterns were redacted
        assert "api_key: [REDACTED_API_KEY]" in mock_record.msg
        assert "password: [REDACTED_PASSWORD]" in mock_record.msg
        assert "Bearer [REDACTED_TOKEN]" in mock_record.msg
        assert "[REDACTED_SSN]" in mock_record.msg
        assert "abc123xyz789" not in mock_record.msg
        assert "secret123" not in mock_record.msg
        assert "token456" not in mock_record.msg
        assert "123-45-6789" not in mock_record.msg

        # Test with credit card number
        mock_record.msg = (
            "Payment processed: card=4111-1111-1111-1111, "
            "client_secret: sk_test_abc123, api_key=key_xyz789"
        )
        assert filter.filter(mock_record) is True
        assert "[REDACTED_CREDIT_CARD]" in mock_record.msg
        assert "client_secret: [REDACTED_SECRET]" in mock_record.msg
        assert "api_key=[REDACTED_API_KEY]" in mock_record.msg
        assert "4111-1111-1111-1111" not in mock_record.msg
        assert "sk_test_abc123" not in mock_record.msg
        assert "key_xyz789" not in mock_record.msg

    def test_safe_content_is_preserved_unchanged(self, filter, mock_record):
        """Test that non-sensitive content passes through unchanged."""
        # Test normal log message
        original_msg = "User john.doe logged in from IP 192.168.1.1"
        mock_record.msg = original_msg
        assert filter.filter(mock_record) is True
        assert mock_record.msg == original_msg

        # Test with numbers that aren't SSN or credit cards
        original_msg = "Order #12345 processed with amount $1234.56"
        mock_record.msg = original_msg
        assert filter.filter(mock_record) is True
        assert mock_record.msg == original_msg

        # Test technical logs
        original_msg = "Database query took 123ms, returned 45 rows"
        mock_record.msg = original_msg
        assert filter.filter(mock_record) is True
        assert mock_record.msg == original_msg

        # Test with partial matches that shouldn't trigger
        original_msg = "Password policy requires 8 characters"
        mock_record.msg = original_msg
        assert filter.filter(mock_record) is True
        # Should not redact because "password" is not followed by : or =
        assert "Password policy requires 8 characters" in mock_record.msg

        # Test URLs and paths
        original_msg = "Loading configuration from /etc/app/config.json"
        mock_record.msg = original_msg
        assert filter.filter(mock_record) is True
        assert mock_record.msg == original_msg

    def test_args_are_filtered(self, filter, mock_record):
        """Test that arguments in log records are also filtered."""
        # Test with dictionary args
        mock_record.msg = "User authentication"
        mock_record.args = {
            "username": "john",
            "password": "password: secret123",
            "api_key": "api_key: key_abc123",
        }
        assert filter.filter(mock_record) is True
        assert mock_record.args["username"] == "john"
        assert mock_record.args["password"] == "password: [REDACTED_PASSWORD]"
        assert mock_record.args["api_key"] == "api_key: [REDACTED_API_KEY]"

        # Test with tuple args
        mock_record.msg = "Processing payment"
        mock_record.args = ("user123", "password: mysecret", "4111-1111-1111-1111")
        assert filter.filter(mock_record) is True
        assert mock_record.args[0] == "user123"
        assert mock_record.args[1] == "password: [REDACTED_PASSWORD]"
        assert mock_record.args[2] == "[REDACTED_CREDIT_CARD]"

    def test_filter_always_returns_true(self, filter, mock_record):
        """Test that the filter always returns True to allow messages through."""
        # Even with sensitive data, the filter returns True (just redacts content)
        mock_record.msg = "password: secret123"
        assert filter.filter(mock_record) is True

        # Even with no sensitive data
        mock_record.msg = "Normal log message"
        assert filter.filter(mock_record) is True

        # Even with empty message
        mock_record.msg = ""
        assert filter.filter(mock_record) is True

    def test_preserves_non_string_types_in_args(self, filter, mock_record):
        """Test that non-string types (floats, ints) are preserved unchanged."""
        mock_record.msg = "HTTP %(method)s %(path)s %(status)s [%(time_taken).2f, %(client)s]"
        mock_record.args = {
            "method": "GET",
            "path": "/api/test",
            "status": 200,
            "time_taken": 0.07,  # Float value
            "client": "192.168.13.7:62341",
        }

        assert filter.filter(mock_record) is True

        # Verify float is still a float, not converted to string
        assert isinstance(mock_record.args["time_taken"], float)
        assert mock_record.args["time_taken"] == 0.07
        # Verify int is still an int
        assert isinstance(mock_record.args["status"], int)
        assert mock_record.args["status"] == 200
        # Verify strings are still strings and IP is preserved
        assert isinstance(mock_record.args["method"], str)
        assert mock_record.args["client"] == "192.168.13.7:62341"
