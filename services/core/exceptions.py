"""Custom exception hierarchy for Senex Trader application.

This module provides domain-specific exceptions that replace generic ValueError and
RuntimeError throughout the codebase. All exceptions include helpful attributes and
clear, user-friendly error messages.

Exception Hierarchy:
    SenexTraderError (base for all custom exceptions)
    ├── TradingError (base for trading-related errors)
    │   ├── SuggestionNotApprovedError
    │   ├── MissingPricingDataError
    │   ├── StalePricingError
    │   ├── NoAccountError
    │   ├── OAuthSessionError
    │   ├── OrderBuildError
    │   ├── InvalidPriceEffectError
    │   └── OrderPlacementError
    ├── RiskError (base for risk management errors)
    │   ├── InsufficientBuyingPowerError
    │   ├── MaxRiskExceededError
    │   └── AccountDataUnavailableError
    ├── OAuthError (base for OAuth/authentication errors)
    │   ├── TokenExpiredError
    │   ├── TokenRefreshError
    │   ├── MissingSecretError
    │   └── SessionCreationError
    ├── DataError (base for data-related errors)
    │   ├── NoHistoricalDataError
    │   ├── InvalidDataError
    │   └── CacheMissError
    └── ConfigurationError (base for configuration/setup errors)
        ├── EncryptionConfigError
        ├── InvalidEncryptionKeyError
        ├── InvalidSymbolFormatError
        └── InvalidOptionTypeError

Usage:
    from services.core.exceptions import InsufficientBuyingPowerError

    if required > available:
        raise InsufficientBuyingPowerError(required=required, available=available)
"""

from decimal import Decimal
from typing import Any

# =============================================================================
# Base Exception
# =============================================================================


class SenexTraderError(Exception):
    """Base exception for all Senex Trader custom exceptions.

    All custom exceptions in the application should inherit from this base class.
    This allows catching all application-specific exceptions with a single except clause.
    """

    pass


# =============================================================================
# Trading Exceptions
# =============================================================================


class TradingError(SenexTraderError):
    """Base exception for all trading-related errors.

    Raised when errors occur during trade suggestion, execution, or management.
    """

    pass


class SuggestionNotApprovedError(TradingError):
    """Raised when attempting to execute a suggestion that is not approved.

    Attributes:
        suggestion_id: ID of the suggestion that was not approved
        current_status: Current status of the suggestion (e.g., "pending", "rejected")
    """

    def __init__(self, suggestion_id: int, current_status: str) -> None:
        self.suggestion_id = suggestion_id
        self.current_status = current_status
        super().__init__(
            f"Suggestion {suggestion_id} is not approved for execution "
            f"(current status: {current_status}). "
            f"Please approve the suggestion before attempting to execute it."
        )


class MissingPricingDataError(TradingError):
    """Raised when a suggestion lacks required real-time pricing data.

    Attributes:
        suggestion_id: ID of the suggestion missing pricing data
    """

    def __init__(self, suggestion_id: int) -> None:
        self.suggestion_id = suggestion_id
        super().__init__(
            f"Suggestion {suggestion_id} lacks real pricing data. "
            f"Please regenerate the suggestion with current market prices."
        )


class StalePricingError(TradingError):
    """Raised when suggestion pricing data is too old to execute safely.

    Attributes:
        suggestion_id: ID of the suggestion with stale pricing
        age_seconds: Age of the pricing data in seconds
        max_age_seconds: Maximum acceptable age for pricing data
    """

    def __init__(self, suggestion_id: int, age_seconds: float, max_age_seconds: int = 600) -> None:
        self.suggestion_id = suggestion_id
        self.age_seconds = age_seconds
        self.max_age_seconds = max_age_seconds
        minutes_old = age_seconds / 60
        max_minutes = max_age_seconds / 60
        super().__init__(
            f"Pricing data for suggestion {suggestion_id} is stale "
            f"({minutes_old:.1f} minutes old, maximum {max_minutes:.0f} minutes). "
            f"Please generate a fresh suggestion with current market prices."
        )


class NoAccountError(TradingError):
    """Raised when user has no primary trading account configured.

    Attributes:
        user_id: ID of the user missing an account
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has no primary trading account configured. "
            f"Please connect a trading account in Settings before executing trades."
        )


class OAuthSessionError(TradingError):
    """Raised when unable to obtain OAuth session for broker API.

    Attributes:
        user_id: ID of the user for whom session creation failed
        message: Optional custom user-friendly error message
        reason: Optional reason for session creation failure
    """

    def __init__(self, user_id: int, message: str | None = None, reason: str | None = None) -> None:
        self.user_id = user_id
        self.reason = reason
        if message:
            # Use custom message if provided
            error_message = message
        else:
            # Default message
            error_message = f"Unable to authenticate with broker for user {user_id}. "
            if reason:
                error_message += f"Reason: {reason}. "
            error_message += "Please reconnect your trading account in Settings."
        super().__init__(error_message)


class OrderBuildError(TradingError):
    """Raised when unable to build order legs from suggestion.

    Attributes:
        suggestion_id: ID of the suggestion for which order building failed
        reason: Optional reason for build failure
    """

    def __init__(self, suggestion_id: int | None = None, reason: str | None = None) -> None:
        self.suggestion_id = suggestion_id
        self.reason = reason
        message = "Unable to construct order from suggestion data. "
        if reason:
            message += f"Reason: {reason}. "
        message += "This may indicate a system error - please contact support."
        super().__init__(message)


class InvalidPriceEffectError(TradingError):
    """Raised when calculated price effect is invalid for strategy.

    Attributes:
        expected_effect: Expected price effect (e.g., "credit")
        actual_effect: Actual calculated price effect (e.g., "debit")
        amount: The price amount that led to the invalid effect
    """

    def __init__(self, expected_effect: str, actual_effect: str, amount: Decimal) -> None:
        self.expected_effect = expected_effect
        self.actual_effect = actual_effect
        self.amount = amount
        super().__init__(
            f"Invalid price effect for this strategy. Expected {expected_effect}, "
            f"but calculated {actual_effect} (amount: ${amount}). "
            f"This may indicate incorrect pricing data."
        )


class OrderPlacementError(TradingError):
    """Raised when order submission to broker fails.

    Attributes:
        reason: Optional reason for order placement failure
        order_details: Optional dict containing order details for debugging
    """

    def __init__(self, reason: str | None = None, order_details: dict | None = None) -> None:
        self.reason = reason
        self.order_details = order_details
        message = "Failed to submit order to broker. "
        if reason:
            message += f"Reason: {reason}. "
        message += "Please verify your account connection and try again."
        super().__init__(message)


class MarketClosedError(TradingError):
    """Raised when attempting to submit orders while market is closed.

    Attributes:
        market_hours: Description of market hours for reference
    """

    def __init__(self, market_hours: str = "9:30 AM - 4:00 PM ET, Monday-Friday") -> None:
        self.market_hours = market_hours
        super().__init__(
            f"Cannot submit orders when market is closed. Market hours are {market_hours}."
        )


# =============================================================================
# Risk Management Exceptions
# =============================================================================


class RiskError(SenexTraderError):
    """Base exception for risk management errors.

    Raised when risk limits or constraints are violated.
    """

    pass


class InsufficientBuyingPowerError(RiskError):
    """Raised when account lacks sufficient buying power for a trade.

    Attributes:
        required: Amount of buying power required
        available: Amount of buying power currently available
    """

    def __init__(self, required: Decimal, available: Decimal) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient buying power. Required: ${required:.2f}, "
            f"Available: ${available:.2f}. "
            f"Please deposit additional funds or reduce position size."
        )


class MaxRiskExceededError(RiskError):
    """Raised when a trade would exceed maximum allowed risk.

    Attributes:
        trade_risk: Risk amount of the proposed trade
        max_risk: Maximum allowed risk based on risk tolerance
        remaining_budget: Remaining risk budget available
    """

    def __init__(
        self, trade_risk: Decimal, max_risk: Decimal, remaining_budget: Decimal | None = None
    ) -> None:
        self.trade_risk = trade_risk
        self.max_risk = max_risk
        self.remaining_budget = remaining_budget
        message = f"Trade risk ${trade_risk:.2f} exceeds maximum allowed risk ${max_risk:.2f}. "
        if remaining_budget is not None:
            message += f"Remaining budget: ${remaining_budget:.2f}. "
        message += "Please reduce position size or adjust risk tolerance in Settings."
        super().__init__(message)


class AccountDataUnavailableError(RiskError):
    """Raised when account data is unavailable for risk calculations.

    Attributes:
        user_id: ID of the user for whom account data is unavailable
        reason: Optional reason why data is unavailable
    """

    def __init__(self, user_id: int, reason: str | None = None) -> None:
        self.user_id = user_id
        self.reason = reason
        message = f"Account data unavailable for user {user_id}. "
        if reason:
            message += f"Reason: {reason}. "
        message += "Cannot approve position without account data."
        super().__init__(message)


# =============================================================================
# OAuth & Authentication Exceptions
# =============================================================================


class OAuthError(SenexTraderError):
    """Base exception for OAuth and authentication errors."""

    pass


class TokenExpiredError(OAuthError):
    """Raised when OAuth token has expired and refresh is needed.

    Attributes:
        user_id: ID of the user whose token expired
    """

    def __init__(self, user_id: int | None = None) -> None:
        self.user_id = user_id
        message = "OAuth token has expired. "
        if user_id:
            message = f"OAuth token for user {user_id} has expired. "
        message += "Please reconnect your trading account in Settings."
        super().__init__(message)


class TokenRefreshError(OAuthError):
    """Raised when OAuth token refresh fails.

    Attributes:
        user_id: ID of the user whose token refresh failed
        reason: Optional reason for refresh failure
    """

    def __init__(self, user_id: int | None = None, reason: str | None = None) -> None:
        self.user_id = user_id
        self.reason = reason
        message = "Failed to refresh OAuth token. "
        if reason:
            message += f"Reason: {reason}. "
        message += "Please reconnect your trading account in Settings."
        super().__init__(message)


class MissingSecretError(OAuthError):
    """Raised when OAuth client secret is not configured.

    Attributes:
        setting_name: Name of the missing setting/environment variable
    """

    def __init__(self, setting_name: str = "TASTYTRADE_CLIENT_SECRET") -> None:
        self.setting_name = setting_name
        super().__init__(
            f"{setting_name} not configured in settings. "
            f"Please set the {setting_name} environment variable."
        )


class SessionCreationError(OAuthError):
    """Raised when unable to create TastyTrade session.

    Attributes:
        reason: Reason for session creation failure
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Unable to create TastyTrade session: {reason}")


# =============================================================================
# Data Exceptions
# =============================================================================


class DataError(SenexTraderError):
    """Base exception for data-related errors."""

    pass


class NoHistoricalDataError(DataError):
    """Raised when no historical data is available for a symbol.

    Attributes:
        symbol: Symbol for which no data is available
        data_type: Type of data that was requested (e.g., "price", "volume")
    """

    def __init__(self, symbol: str, data_type: str = "historical data") -> None:
        self.symbol = symbol
        self.data_type = data_type
        super().__init__(
            f"No {data_type} available for symbol {symbol}. "
            f"Please verify the symbol is correct and try again."
        )


class InvalidDataError(DataError):
    """Raised when data validation fails.

    Attributes:
        field_name: Name of the field with invalid data
        value: The invalid value
        reason: Reason why the data is invalid
    """

    def __init__(self, field_name: str, value: Any, reason: str) -> None:
        self.field_name = field_name
        self.value = value
        self.reason = reason
        super().__init__(f"Invalid data for field '{field_name}': {value}. Reason: {reason}")


class CacheMissError(DataError):
    """Raised when requested data is not found in cache.

    Attributes:
        cache_key: The cache key that was not found
        cache_type: Type of cache (e.g., "options", "pricing")
    """

    def __init__(self, cache_key: str, cache_type: str = "cache") -> None:
        self.cache_key = cache_key
        self.cache_type = cache_type
        super().__init__(
            f"Data not found in {cache_type} for key: {cache_key}. "
            f"Please refresh the data and try again."
        )


# =============================================================================
# Configuration Exceptions
# =============================================================================


class ConfigurationError(SenexTraderError):
    """Base exception for configuration and setup errors."""

    pass


class EncryptionConfigError(ConfigurationError):
    """Raised when encryption configuration is invalid or missing.

    Attributes:
        reason: Reason for configuration error
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Encryption configuration error: {reason}")


class InvalidEncryptionKeyError(ConfigurationError):
    """Raised when encryption key is invalid or malformed.

    Attributes:
        reason: Reason why the key is invalid
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Invalid encryption key: {reason}")


class InvalidSymbolFormatError(ConfigurationError):
    """Raised when OCC symbol format is invalid.

    Attributes:
        symbol: The invalid symbol
        expected_length: Expected length of the symbol
        actual_length: Actual length of the symbol
    """

    def __init__(
        self, symbol: str, expected_length: int = 21, actual_length: int | None = None
    ) -> None:
        self.symbol = symbol
        self.expected_length = expected_length
        self.actual_length = actual_length or len(symbol)
        super().__init__(
            f"Invalid OCC symbol format: '{symbol}'. "
            f"Expected length {expected_length}, got {self.actual_length}."
        )


class InvalidOptionTypeError(ConfigurationError):
    """Raised when option type is not 'C' (call) or 'P' (put).

    Attributes:
        option_type: The invalid option type provided
        valid_types: List of valid option types
    """

    def __init__(self, option_type: str, valid_types: list[str] | None = None) -> None:
        self.option_type = option_type
        self.valid_types = valid_types or ["C", "P"]
        super().__init__(
            f"Invalid option type: '{option_type}'. Must be one of: {', '.join(self.valid_types)}."
        )


class TestModeError(ConfigurationError):
    """Raised when test mode is used inappropriately.

    Attributes:
        reason: Reason why test mode cannot be used
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Test mode error: {reason}")
