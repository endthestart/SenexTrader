"""
Centralized data access utilities to eliminate code duplication.
CRITICAL: Replaces 20+ instances of repetitive TradingAccount queries.

This module provides standardized utilities for:
- TradingAccount retrieval
- OAuth session management
- TastyTrade SDK API calls

Following DRY principle per REAL_DATA_IMPLEMENTATION_PLAN.md
"""

from services.core.logging import get_logger

logger = get_logger(__name__)


async def _validate_and_refresh_session(session, user) -> dict:
    """
    Validate session and auto-refresh if expired.

    Args:
        session: TastyTrade OAuthSession instance
        user: Django User instance

    Returns:
        Dict with validation status, session (possibly refreshed), and errors
        Format: {
            "success": bool,
            "session": OAuthSession or None,
            "error": str (optional)
        }
    """
    if not session:
        return {"success": False, "session": None, "error": "No session provided"}

    has_async_validate = hasattr(session, "a_validate")
    has_sync_validate = hasattr(session, "validate")

    if not has_async_validate and not has_sync_validate:
        logger.debug("Session has no validation method, assuming valid")
        return {"success": True, "session": session}

    try:
        if has_async_validate:
            is_valid = await session.a_validate()
        elif has_sync_validate:
            is_valid = session.validate()
        else:
            logger.warning("No validation method available, assuming valid")
            return {"success": True, "session": session}

        if is_valid:
            return {"success": True, "session": session}

        logger.info(f"Session validation failed for user {user.id}")
        return {
            "success": False,
            "session": None,
            "error": "Session validation failed - session expired or invalid",
        }

    except Exception as e:
        logger.error(f"Session validation error for user {user.id}: {e}")

        return {
            "success": False,
            "session": None,
            "error": f"Session validation exception: {e!s}",
        }


async def get_primary_tastytrade_account(user):
    """
    Single source of truth for primary TradingAccount queries.
    Replaces repetitive patterns across 20+ files.

    Args:
        user: Django User instance

    Returns:
        TradingAccount instance or None
    """
    from accounts.models import TradingAccount

    try:
        return (
            await TradingAccount.objects.select_related("user")
            .filter(user=user, connection_type="TASTYTRADE", is_primary=True)
            .afirst()
        )
    except Exception as e:
        logger.error(f"Error retrieving primary TastyTrade account for user {user.id}: {e}")
        return None


async def get_tastytrade_account_by_number(user, account_number: str):
    """
    Get TradingAccount by specific account number.
    Used when targeting specific accounts rather than primary.

    Args:
        user: Django User instance
        account_number: Specific account number string

    Returns:
        TradingAccount instance or None
    """
    from accounts.models import TradingAccount

    try:
        return await TradingAccount.objects.filter(
            user=user, account_number=account_number, connection_type="TASTYTRADE"
        ).afirst()
    except Exception as e:
        logger.error(
            f"Error retrieving TastyTrade account {account_number} for user {user.id}: {e}"
        )
        return None


async def get_oauth_session(user):
    """
    Standardized OAuth session retrieval using async TastyTradeSessionService.
    Eliminates repetitive session management code.

    This function now includes validation and auto-refresh:
    - Gets session from TastyTradeSessionService
    - Validates the session before returning
    - Auto-refreshes expired sessions
    - Logs refresh events appropriately

    Args:
        user: Django User instance

    Returns:
        TastyTrade OAuthSession instance or None
    """
    account = await get_primary_tastytrade_account(user)
    if not account:
        logger.warning(f"No primary TastyTrade account for user {user.id}")
        return None

    if not account.refresh_token:
        logger.warning(f"No refresh token available for user {user.id}")
        return None

    try:
        from services.brokers.tastytrade.session import TastyTradeSessionService

        session_result = await TastyTradeSessionService.get_session_for_user(
            user.id, account.refresh_token, is_test=account.is_test
        )
        if not session_result.get("success"):
            logger.error(f"Failed to get session: {session_result.get('error')}")
            return None

        session = session_result.get("session")

        validation_result = await _validate_and_refresh_session(session, user)

        if validation_result.get("success"):
            validated_session = validation_result.get("session")
            if validated_session != session:
                logger.info(f"Session auto-refreshed for user {user.id}")
            return validated_session

        logger.error(
            f"Session validation failed for user {user.id}: {validation_result.get('error')}"
        )
        return None

    except Exception as e:
        logger.error(f"Error getting OAuth session for user {user.id}: {e}")
        return None


async def get_oauth_session_for_account(user, account_number: str):
    """
    Get OAuth session for specific account number.
    Used when working with non-primary accounts.

    Args:
        user: Django User instance
        account_number: Specific account number string

    Returns:
        TastyTrade OAuthSession instance or None
    """
    account = await get_tastytrade_account_by_number(user, account_number)
    if not account:
        logger.warning(f"No TastyTrade account {account_number} for user {user.id}")
        return None

    if not account.refresh_token:
        logger.warning(f"No refresh token available for account {account_number}")
        return None

    try:
        from services.brokers.tastytrade.session import TastyTradeSessionService

        session_result = await TastyTradeSessionService.get_session_for_user(
            user.id, account.refresh_token, is_test=account.is_test
        )
        if session_result.get("success"):
            return session_result.get("session")
        logger.error(f"Failed to get session: {session_result.get('error')}")
        return None
    except Exception as e:
        logger.error(
            f"Error getting OAuth session for account {account_number}, user {user.id}: {e}"
        )
        return None


def get_oauth_session_sync(user):
    """
    Synchronous version of OAuth session retrieval for management commands.
    Uses synchronous TastyTrade session methods.

    Args:
        user: Django User instance

    Returns:
        TastyTrade OAuthSession instance or None
    """
    from accounts.models import TradingAccount

    account = TradingAccount.objects.filter(
        user=user, connection_type="TASTYTRADE", is_primary=True
    ).first()

    if not account:
        logger.warning(f"No primary TastyTrade account for user {user.id}")
        return None

    if not account.refresh_token:
        logger.warning(f"No refresh token available for user {user.id}")
        return None

    try:
        from asgiref.sync import async_to_sync

        from services.brokers.tastytrade.session import TastyTradeSessionService

        session_result = async_to_sync(TastyTradeSessionService.get_session_for_user)(
            user.id, account.refresh_token, is_test=account.is_test
        )

        if session_result.get("success"):
            return session_result.get("session")
        logger.error(f"Failed to get session: {session_result.get('error')}")
        return None
    except Exception as e:
        logger.error(f"Error getting OAuth session for user {user.id}: {e}")
        return None


async def get_account_numbers_for_user(user) -> list:
    """
    Get all TastyTrade account numbers for a user.
    Useful for multi-account operations.

    Args:
        user: Django User instance

    Returns:
        List of account number strings
    """
    from accounts.models import TradingAccount

    try:
        return [
            account_number
            async for account_number in TradingAccount.objects.filter(
                user=user, connection_type="TASTYTRADE"
            ).values_list("account_number", flat=True)
        ]
    except Exception as e:
        logger.error(f"Error retrieving account numbers for user {user.id}: {e}")
        return []


async def validate_user_has_tastytrade_access(user) -> bool:
    """
    Quick validation that user has at least one TastyTrade account.
    Used for early validation in views/services.

    Args:
        user: Django User instance

    Returns:
        Boolean indicating if user has TastyTrade access
    """
    account = await get_primary_tastytrade_account(user)
    return account is not None


async def has_configured_primary_account(user) -> bool:
    """
    Check if user has a configured primary trading account.

    A configured account means:
    - Account exists
    - Account is marked as primary
    - Account has account_number and access_token (is_configured=True)

    This is the standard check for features that require brokerage connectivity.
    Use this before calling risk manager, account state, or other brokerage-dependent features.

    Args:
        user: Django User instance

    Returns:
        Boolean indicating if user has a fully configured primary account
    """
    account = await get_primary_tastytrade_account(user)
    return account is not None and account.is_configured


def has_configured_primary_account_sync(user) -> bool:
    """
    Synchronous version of has_configured_primary_account.

    Use this in sync views, management commands, or other sync contexts.

    Args:
        user: Django User instance

    Returns:
        Boolean indicating if user has a fully configured primary account
    """
    from accounts.models import TradingAccount

    try:
        account = TradingAccount.objects.filter(
            user=user, connection_type="TASTYTRADE", is_primary=True
        ).first()
        return account is not None and account.is_configured
    except Exception as e:
        logger.error(f"Error checking configured account for user {user.id}: {e}")
        return False
