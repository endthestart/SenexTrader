"""
Tests for OAuth token validation and auto-refresh functionality.

Tests the P0.4: OAuth Token Validation Before Orders feature:
- Valid sessions pass through unchanged
- Expired sessions are auto-refreshed
- Refresh failures return errors
- get_oauth_session handles expired tokens gracefully
"""

from unittest.mock import AsyncMock, Mock, patch

from django.contrib.auth import get_user_model

import pytest

from accounts.models import TradingAccount
from services.core.data_access import _validate_and_refresh_session, get_oauth_session

User = get_user_model()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_valid_session_passes_through_unchanged():
    """Test that valid sessions pass through validation without changes."""
    # Create a mock user
    user = await User.objects.acreate(username="testuser", email="test@example.com")

    # Create a mock session with a_validate method that returns True
    mock_session = Mock()
    mock_session.a_validate = AsyncMock(return_value=True)

    # Validate the session
    result = await _validate_and_refresh_session(mock_session, user)

    # Assert session is valid and unchanged
    assert result["success"] is True
    assert result["session"] is mock_session
    assert "error" not in result

    # Verify validate was called
    mock_session.a_validate.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expired_session_auto_refreshes():
    """Test that expired sessions return error (session-per-task pattern)."""
    # Create a mock user and account
    user = await User.objects.acreate(username="testuser", email="test@example.com")
    await TradingAccount.objects.acreate(
        user=user,
        account_number="TEST12345",
        connection_type="TASTYTRADE",
        is_primary=True,
        refresh_token="test_refresh_token",
        is_test=False,
    )

    # Create a mock expired session
    expired_session = Mock()
    expired_session.a_validate = AsyncMock(return_value=False)

    # With session-per-task pattern, _validate_and_refresh_session doesn't refresh
    # It just validates and returns error if invalid
    result = await _validate_and_refresh_session(expired_session, user)

    # Assert validation failed (no auto-refresh in this function)
    assert result["success"] is False
    assert result["session"] is None
    assert "error" in result
    assert "expired or invalid" in result["error"].lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_refresh_failure_returns_error():
    """Test that validation errors are returned when session.a_validate raises exception."""
    # Create a mock user
    user = await User.objects.acreate(username="testuser", email="test@example.com")

    # Create a mock session that raises exception during validation
    error_session = Mock()
    error_session.a_validate = AsyncMock(side_effect=Exception("Token validation failed"))

    # Validate the session that raises error
    result = await _validate_and_refresh_session(error_session, user)

    # Assert validation failed with appropriate error
    assert result["success"] is False
    assert result["session"] is None
    assert "error" in result
    assert "validation exception" in result["error"].lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_oauth_session_handles_expired_tokens():
    """Test that get_oauth_session returns None when session is expired."""
    # Create a mock user and account
    user = await User.objects.acreate(username="testuser", email="test@example.com")
    await TradingAccount.objects.acreate(
        user=user,
        account_number="TEST12345",
        connection_type="TASTYTRADE",
        is_primary=True,
        refresh_token="test_refresh_token",
        is_test=False,
    )

    # Create mock expired session
    expired_session = Mock()
    expired_session.a_validate = AsyncMock(return_value=False)

    # Mock the TastyTradeSessionService at the import location
    with patch(
        "services.brokers.tastytrade.session.TastyTradeSessionService.get_session_for_user"
    ) as mock_get_session:
        # Mock returns expired session
        mock_get_session.return_value = {"success": True, "session": expired_session}

        # Get OAuth session - should return None because validation fails
        result_session = await get_oauth_session(user)

        # Assert we got None (validation failed)
        assert result_session is None

        # Verify session service was called
        mock_get_session.assert_called_once_with(user.id, "test_refresh_token", is_test=False)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_session_without_validate_method_passes():
    """Test that sessions without validate methods are assumed valid."""
    # Create a mock user
    user = await User.objects.acreate(username="testuser", email="test@example.com")

    # Create a mock session without validate methods
    mock_session = Mock(spec=[])  # Empty spec means no methods

    # Validate the session
    result = await _validate_and_refresh_session(mock_session, user)

    # Assert session is assumed valid
    assert result["success"] is True
    assert result["session"] is mock_session
    assert "error" not in result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_oauth_session_returns_none_for_missing_account():
    """Test that get_oauth_session returns None when no account exists."""
    # Create a user without a trading account
    user = await User.objects.acreate(username="testuser", email="test@example.com")

    # Get OAuth session
    result_session = await get_oauth_session(user)

    # Assert None is returned
    assert result_session is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_oauth_session_returns_none_for_missing_refresh_token():
    """Test that get_oauth_session returns None when refresh token is missing."""
    # Create a user with account but no refresh token
    user = await User.objects.acreate(username="testuser", email="test@example.com")
    await TradingAccount.objects.acreate(
        user=user,
        account_number="TEST12345",
        connection_type="TASTYTRADE",
        is_primary=True,
        refresh_token="",  # Empty refresh token
        is_test=False,
    )

    # Get OAuth session
    result_session = await get_oauth_session(user)

    # Assert None is returned
    assert result_session is None
