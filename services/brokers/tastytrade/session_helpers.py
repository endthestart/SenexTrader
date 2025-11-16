"""
TastyTrade Session Helper Utilities

Extracted common utilities from TastyTradeSessionService for better organization
and code reuse. Contains error categorization, cache management, and session validation helpers.
"""

from enum import Enum

from django.core.cache import cache

from services.core.logging import get_logger

logger = get_logger(__name__)


class SessionErrorType(Enum):
    """Categorizes different types of session errors for better handling."""

    CONFIGURATION_ERROR = "configuration_error"
    NETWORK_ERROR = "network_error"
    AUTHENTICATION_ERROR = "authentication_error"
    VALIDATION_ERROR = "validation_error"
    SDK_ERROR = "sdk_error"
    REFRESH_ERROR = "refresh_error"
    EXPIRED_TOKEN = "expired_token"
    RATE_LIMIT = "rate_limit"
    TEMPORARY_ERROR = "temporary_error"
    TIMEOUT_ERROR = "timeout_error"
    UNKNOWN_ERROR = "unknown_error"


def categorize_error(error: Exception) -> SessionErrorType:
    """Static version of error categorization for class methods."""
    error_str = str(error).lower()

    # Network-related errors
    if any(
        keyword in error_str
        for keyword in [
            "connection",
            "network",
            "timeout",
            "unreachable",
            "dns",
            "socket",
        ]
    ):
        return SessionErrorType.NETWORK_ERROR

    # Authentication/authorization errors
    if any(
        keyword in error_str
        for keyword in [
            "unauthorized",
            "invalid jwt",
            "expired",
            "forbidden",
            "auth",
        ]
    ):
        if "expired" in error_str or "invalid jwt" in error_str:
            return SessionErrorType.EXPIRED_TOKEN
        return SessionErrorType.AUTHENTICATION_ERROR

    # Rate limiting
    if any(keyword in error_str for keyword in ["rate limit", "too many requests", "429"]):
        return SessionErrorType.RATE_LIMIT

    # Temporary server errors
    if any(
        keyword in error_str
        for keyword in ["5xx", "server error", "service unavailable", "temporary"]
    ):
        return SessionErrorType.TEMPORARY_ERROR

    # SDK-specific errors
    if any(keyword in error_str for keyword in ["tastytrade", "sdk", "import", "module"]):
        return SessionErrorType.SDK_ERROR

    return SessionErrorType.UNKNOWN_ERROR


def categorize_refresh_error(error: Exception) -> SessionErrorType:
    """Categorize refresh-specific errors."""
    error_str = str(error).lower()

    # Check for refresh-specific patterns first
    if any(keyword in error_str for keyword in ["refresh token", "invalid_grant", "token expired"]):
        return SessionErrorType.EXPIRED_TOKEN

    if "refresh" in error_str and any(
        keyword in error_str for keyword in ["not supported", "not available", "method"]
    ):
        return SessionErrorType.SDK_ERROR

    # Fall back to general error categorization
    return categorize_error(error)


def get_session_cache_key(user_id: int) -> str:
    """Generate cache key for user session."""
    return f"tastytrade_session:{user_id}"


def clear_session_cache(user_id: int) -> None:
    """Clear session from cache."""
    cache_key = get_session_cache_key(user_id)
    cache.delete(cache_key)
    logger.debug(f"Cleared session cache for user {user_id}")


def store_session_in_cache(user_id: int, serialized_session: str, timeout: int) -> None:
    """Store serialized session in cache."""
    cache_key = get_session_cache_key(user_id)
    cache.set(cache_key, serialized_session, timeout=timeout)
    logger.debug(f"Session cached for user {user_id}")
