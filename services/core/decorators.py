"""
Service layer decorators for common patterns.

Reduces duplication of error handling and session setup across services.
"""

import functools
from collections.abc import Callable
from typing import TypeVar

from services.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def handle_errors(
    error_message: str = "Operation failed", return_value=None, log_traceback: bool = True
):
    """
    Decorator for standardized error handling in service methods.

    Args:
        error_message: Custom error message prefix (default: "Operation failed")
        return_value: Value to return on error (default: None)
        log_traceback: Whether to log full traceback (default: True)

    Usage:
        @handle_errors("Failed to fetch data")
        async def fetch_data(self):
            ...

        @handle_errors("Failed to process", return_value={})
        def process_data(self):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if log_traceback:
                    logger.error(f"{error_message}: {e}", exc_info=True)
                else:
                    logger.error(f"{error_message}: {e}")
                return return_value

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_traceback:
                    logger.error(f"{error_message}: {e}", exc_info=True)
                else:
                    logger.error(f"{error_message}: {e}")
                return return_value

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def require_session(error_return=None):
    """
    Decorator for methods that need TastyTrade OAuth session.

    Automatically:
    1. Gets primary trading account for user
    2. Fetches OAuth session
    3. Returns error_return if session unavailable

    Expects first parameter to be 'self' with self.user attribute.

    Args:
        error_return: Value to return if session setup fails (default: None)

    Usage:
        @require_session(error_return={"error": "Session required"})
        async def fetch_data(self):
            # self.session and self.account available here
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Check if user exists
            if not hasattr(self, "user") or not self.user:
                logger.error(f"{func.__name__}: No user attribute found")
                return error_return

            # Get primary account
            from accounts.models import TradingAccount

            account = await TradingAccount.objects.filter(user=self.user, is_primary=True).afirst()

            if not account:
                logger.error(f"{func.__name__}: No primary trading account for user {self.user.id}")
                return error_return

            # Get OAuth session
            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(self.user)
            if not session:
                logger.error(
                    f"{func.__name__}: Failed to get OAuth session for user {self.user.id}"
                )
                return error_return

            # Set session and account on instance for method to use
            self.session = session
            self.account = account

            # Call original method
            return await func(self, *args, **kwargs)

        return wrapper

    return decorator


def require_session_sync(error_return=None):
    """
    Synchronous version of require_session decorator.

    Use for synchronous methods that need TastyTrade session.
    Note: Still requires async for database and session operations.

    Args:
        error_return: Value to return if session setup fails (default: None)

    Usage:
        @require_session_sync(error_return={})
        def sync_method(self):
            # self.session and self.account available here
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Import sync_to_async for database operations
            from asgiref.sync import async_to_sync

            @async_to_sync
            async def setup_session():
                # Check if user exists
                if not hasattr(self, "user") or not self.user:
                    logger.error(f"{func.__name__}: No user attribute found")
                    return None, None

                # Get primary account
                from accounts.models import TradingAccount

                account = await TradingAccount.objects.filter(
                    user=self.user, is_primary=True
                ).afirst()

                if not account:
                    logger.error(
                        f"{func.__name__}: No primary trading account for user {self.user.id}"
                    )
                    return None, None

                # Get OAuth session
                from services.core.data_access import get_oauth_session

                session = await get_oauth_session(self.user)
                if not session:
                    logger.error(
                        f"{func.__name__}: Failed to get OAuth session for user {self.user.id}"
                    )
                    return None, None

                return session, account

            session, account = setup_session()

            if not session or not account:
                return error_return

            # Set session and account on instance
            self.session = session
            self.account = account

            # Call original method
            return func(self, *args, **kwargs)

        return wrapper

    return decorator
