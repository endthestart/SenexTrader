"""
TastyTrade Session Management Service

Provides SDK-based session management for TastyTrade OAuth connections.
Uses tastytrade SDK's OAuthSession for proper authentication context.
"""

import asyncio
from dataclasses import dataclass

from django.conf import settings

from tastytrade import Session

from services.core.data_access import get_primary_tastytrade_account
from services.core.exceptions import MissingSecretError
from services.core.logging import get_logger

from .session_helpers import SessionErrorType, categorize_error

logger = get_logger(__name__)


@dataclass
class TastyTradeSessionConfig:
    """Configuration for TastyTrade session management."""

    client_secret: str
    is_test: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0


class TastyTradeSessionService:
    """
    Service for managing TastyTrade SDK sessions with session-per-task pattern.

    Handles:
    - Fresh session creation for each task (no caching)
    - OAuth authentication with TastyTrade API
    - Session validation and error handling
    - Enhanced logging for debugging event loop issues

    NOTE: This service previously used ClassVar caching which caused "Event loop is closed"
    errors in production when Celery workers recycled. The session-per-task approach
    eliminates this issue by creating fresh sessions for each task execution.
    """

    # NOTE: Session caching removed to fix "Event loop is closed" production bug
    # See docs/patterns/REALTIME_DATA_FLOW_PATTERN.md for session management patterns
    #
    # Previous implementation cached sessions in ClassVar, which caused event loop
    # issues when Celery workers recycled (--max-tasks-per-child=100).
    #
    # New approach: Create fresh session for each task (session-per-task pattern).
    # Performance impact is minimal (~200-500ms per task) given task frequency (10-min intervals).

    def __init__(self, config: TastyTradeSessionConfig | None = None, is_test: bool | None = None):
        if config is None:
            config = self._get_default_config()
            # Override is_test if explicitly provided
            if is_test is not None:
                config.is_test = is_test
        self.config = config
        self.session = None

    def _get_default_config(self) -> TastyTradeSessionConfig:
        """Get configuration from Django settings."""
        oauth_config = getattr(settings, "TASTYTRADE_OAUTH_CONFIG", {})
        client_secret = oauth_config.get("CLIENT_SECRET", "")

        if not client_secret:
            raise MissingSecretError("TASTYTRADE_CLIENT_SECRET")

        return TastyTradeSessionConfig(
            client_secret=client_secret,
            is_test=getattr(settings, "TASTYTRADE_IS_TEST", False),
            max_retries=oauth_config.get("MAX_RETRIES", 3),
            retry_delay=oauth_config.get("RETRY_DELAY", 1.0),
            retry_backoff=oauth_config.get("RETRY_BACKOFF", 2.0),
        )

    async def create_session(self, refresh_token: str) -> dict:
        """
        Create OAuthSession from refresh token with retry logic and detailed
        error handling.

        Args:
            refresh_token: OAuth2 refresh token

        Returns:
            Dict with success status, session, error details, and error type
        """
        if not refresh_token:
            return {
                "success": False,
                "error": "Refresh token is required",
                "error_type": SessionErrorType.CONFIGURATION_ERROR.value,
                "retry_recommended": False,
            }

        if not refresh_token.strip():
            return {
                "success": False,
                "error": "Refresh token cannot be empty",
                "error_type": SessionErrorType.CONFIGURATION_ERROR.value,
                "retry_recommended": False,
            }

        # Retry logic for session creation
        last_error = None
        last_error_type = SessionErrorType.UNKNOWN_ERROR
        retry_delay = self.config.retry_delay
        actual_attempts = 0

        for attempt in range(self.config.max_retries + 1):
            actual_attempts = attempt + 1
            try:
                if attempt > 0:
                    logger.info(
                        f"Creating TastyTrade OAuth session (attempt "
                        f"{attempt + 1}/{self.config.max_retries + 1})"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= self.config.retry_backoff
                else:
                    logger.info("Creating TastyTrade OAuth session")

                self.session = Session(
                    provider_secret=self.config.client_secret,
                    refresh_token=refresh_token,
                    is_test=self.config.is_test,
                )

                # CRITICAL: Call refresh() immediately per documentation
                # This generates a fresh session_token (15-minute lifetime)
                # See: WORKING_STREAMING_IMPLEMENTATION.md and implementation_plan.md
                try:
                    async with asyncio.timeout(10):  # 10 second timeout
                        await self.session.a_refresh()
                    logger.debug("OAuth session refreshed - fresh session_token generated")
                except TimeoutError:
                    logger.error(
                        "Session refresh timeout after 10s", extra={"attempt": attempt + 1}
                    )
                    last_error = "Session refresh timeout after 10 seconds"
                    last_error_type = SessionErrorType.TIMEOUT_ERROR
                    continue  # Try next attempt if available

                # Enhanced validation
                validation_result = await self._validate_session_with_details()
                if validation_result["success"]:
                    logger.info(
                        f"TastyTrade OAuth session created and validated "
                        f"successfully (attempt {attempt + 1})"
                    )
                    return {"success": True, "session": self.session}
                last_error = validation_result["error"]
                last_error_type = SessionErrorType.VALIDATION_ERROR
                logger.warning(f"Session validation failed on attempt {attempt + 1}: {last_error}")
                if not validation_result.get("retry_recommended", True):
                    break

            except ImportError as e:
                last_error = "TastyTrade SDK not installed or not accessible"
                last_error_type = SessionErrorType.SDK_ERROR
                logger.error(f"Import error on attempt {attempt + 1}: {e}", exc_info=True)
                break  # Don't retry import errors

            except Exception as e:
                last_error = str(e)
                last_error_type = self._categorize_error(e)
                logger.error(
                    f"Session creation failed on attempt {attempt + 1}: {e}", exc_info=True
                )

                # Don't retry certain error types
                if last_error_type in [
                    SessionErrorType.AUTHENTICATION_ERROR,
                    SessionErrorType.EXPIRED_TOKEN,
                ]:
                    break

        # All attempts failed
        retry_recommended = last_error_type in [
            SessionErrorType.NETWORK_ERROR,
            SessionErrorType.TEMPORARY_ERROR,
            SessionErrorType.RATE_LIMIT,
        ]

        return {
            "success": False,
            "error": (f"Session creation failed after {actual_attempts} attempt(s): {last_error}"),
            "error_type": last_error_type.value,
            "retry_recommended": retry_recommended,
            "attempts_made": actual_attempts,
        }

    async def fetch_accounts(self, refresh_token: str) -> dict:
        """
        Fetch accounts using TastyTrade SDK.

        Args:
            refresh_token: OAuth2 refresh token

        Returns:
            Dict with success status and account data or error details
        """
        # Create session if not already created
        if not self.session:
            session_result = await self.create_session(refresh_token)
            if not session_result.get("success"):
                return session_result

        try:
            from tastytrade import Account as TTAccount

            logger.info("Fetching TastyTrade accounts via SDK")

            # Use SDK to fetch accounts
            if hasattr(TTAccount, "a_get"):
                accounts_result = await TTAccount.a_get(self.session)
            else:
                accounts_result = TTAccount.get(self.session)

            # Ensure it's always a list
            if isinstance(accounts_result, list):
                accounts = accounts_result
            else:
                accounts = [accounts_result] if accounts_result else []

            if not accounts:
                logger.warning("No accounts returned from TastyTrade API")
                return {"success": False, "error": "No accounts found"}

            # Convert account objects to dict format for consistency
            account_data = []
            for account in accounts:
                if hasattr(account, "account_number"):
                    account_data.append(
                        {
                            "account_number": account.account_number,
                            "nickname": getattr(account, "nickname", ""),
                            "account_type": getattr(account, "account_type", ""),
                            "is_closed": getattr(account, "is_closed", False),
                        }
                    )
                else:
                    # Fallback for unexpected account object structure
                    account_data.append(str(account))

            logger.info(f"Successfully fetched {len(account_data)} TastyTrade accounts")
            return {"success": True, "data": account_data}

        except ImportError:
            logger.error("tastytrade SDK not available")
            return {"success": False, "error": "TastyTrade SDK not installed"}
        except Exception as e:
            logger.error(f"Failed to fetch TastyTrade accounts: {e}", exc_info=True)
            return {"success": False, "error": f"Account fetch failed: {e!s}"}

    async def _validate_session(self) -> bool:
        """Validate current session internally."""
        result = await self._validate_session_with_details()
        return result["success"]

    async def _validate_session_with_details(self) -> dict:
        """
        Validate current session with detailed error information.

        Returns:
            Dict with success status and detailed error information
        """
        if not self.session:
            return {
                "success": False,
                "error": "No session available for validation",
                "error_type": SessionErrorType.CONFIGURATION_ERROR.value,
                "retry_recommended": False,
            }

        try:
            if hasattr(self.session, "a_validate"):
                try:
                    async with asyncio.timeout(5):  # 5 second timeout for validation
                        is_valid = await self.session.a_validate()
                except TimeoutError:
                    logger.warning("Session validation timeout after 5s")
                    return {
                        "success": False,
                        "error": "Session validation timeout after 5 seconds",
                        "error_type": SessionErrorType.TIMEOUT_ERROR.value,
                        "retry_recommended": True,
                    }
                if is_valid:
                    return {"success": True}
                return {
                    "success": False,
                    "error": ("Session validation returned False - likely expired or invalid"),
                    "error_type": SessionErrorType.EXPIRED_TOKEN.value,
                    "retry_recommended": True,
                }
            if hasattr(self.session, "validate"):
                is_valid = self.session.validate()
                if is_valid:
                    return {"success": True}
                return {
                    "success": False,
                    "error": ("Session validation returned False - likely expired or invalid"),
                    "error_type": SessionErrorType.EXPIRED_TOKEN.value,
                    "retry_recommended": True,
                }
            # If validation method not available, try basic health check
            return self._basic_session_health_check()

        except Exception as e:
            error_type = self._categorize_error(e)
            retry_recommended = error_type in [
                SessionErrorType.NETWORK_ERROR,
                SessionErrorType.TEMPORARY_ERROR,
            ]

            return {
                "success": False,
                "error": f"Session validation failed: {e!s}",
                "error_type": error_type.value,
                "retry_recommended": retry_recommended,
            }

    def _basic_session_health_check(self) -> dict:
        """Basic health check for sessions without validate method."""
        try:
            # Check if session has required attributes
            if not hasattr(self.session, "session_token"):
                return {
                    "success": False,
                    "error": "Session missing required attributes",
                    "error_type": SessionErrorType.VALIDATION_ERROR.value,
                    "retry_recommended": True,
                }

            # Session appears healthy
            logger.debug("Session passed basic health check (validation method not available)")
            return {"success": True}

        except Exception as e:
            return {
                "success": False,
                "error": f"Basic session health check failed: {e!s}",
                "error_type": SessionErrorType.VALIDATION_ERROR.value,
                "retry_recommended": True,
            }

    def _categorize_error(self, error: Exception) -> SessionErrorType:
        """Categorize errors for better handling and retry logic."""
        return categorize_error(error)

    def close_session(self):
        """Close and cleanup session resources."""
        if self.session:
            # Cleanup session if needed
            self.session = None
            logger.debug("TastyTrade session closed")

    @classmethod
    async def get_session_for_user(
        cls, user_id: int, refresh_token: str, is_test: bool = False
    ) -> dict:
        """
        Create fresh session for user (session-per-task pattern).

        This is the main entry point for getting TastyTrade sessions.
        Creates a new session for each call - NO CACHING.

        Args:
            user_id: User ID for logging/tracking
            refresh_token: OAuth2 refresh token
            is_test: Whether to use test/cert environment (default: False for production)

        Returns:
            Dict with success status, session, and error details if applicable
        """
        import os

        # Enhanced logging for debugging session lifecycle
        try:
            current_loop = asyncio.get_running_loop()
            loop_id = id(current_loop)
        except RuntimeError:
            loop_id = None

        logger.info(
            f"Creating fresh session for user {user_id}",
            extra={
                "user_id": user_id,
                "is_test": is_test,
                "worker_pid": os.getpid(),
                "event_loop_id": loop_id,
                "task_id": getattr(
                    getattr(asyncio, "current_task", lambda: None)(), "get_name", lambda: "unknown"
                )(),
            },
        )

        # Create new session (no caching)
        service = cls(is_test=is_test)
        result = await service.create_session(refresh_token)

        if result.get("success"):
            logger.info(
                f"Session created successfully for user {user_id}",
                extra={"user_id": user_id, "worker_pid": os.getpid()},
            )
            return {"success": True, "session": result.get("session")}

        # Handle persistent authentication failures
        error_type = result.get("error_type")
        if error_type in [
            SessionErrorType.EXPIRED_TOKEN.value,
            SessionErrorType.AUTHENTICATION_ERROR.value,
        ]:
            logger.error(
                f"Authentication failure for user {user_id} - marking token as invalid. "
                f"User must re-authenticate via OAuth.",
                extra={"user_id": user_id, "error_type": error_type},
            )
            await cls._mark_account_token_invalid(user_id)
        else:
            logger.error(
                f"Failed to create session for user {user_id}: {result.get('error')}",
                extra={"user_id": user_id, "error_type": error_type, "error": result.get("error")},
            )

        return result

    # NOTE: Caching-related methods removed (_needs_refresh, _refresh_session,
    # _store_session, _clear_session) - no longer needed with session-per-task pattern

    @classmethod
    async def _mark_account_token_invalid(cls, user_id: int) -> None:
        """
        Mark user's TradingAccount token as invalid in database.
        This prevents Celery tasks from repeatedly attempting to use bad tokens.

        Args:
            user_id: User ID whose token should be marked invalid
        """
        from accounts.models import TradingAccount

        try:
            # Update all TastyTrade accounts for this user
            updated = await TradingAccount.objects.filter(
                user_id=user_id, connection_type="TASTYTRADE"
            ).aupdate(is_token_valid=False)

            if updated > 0:
                logger.warning(
                    f"Marked {updated} TastyTrade account(s) for user {user_id} as having invalid tokens. "
                    f"User must reconnect via OAuth to restore functionality."
                )
        except Exception as e:
            logger.error(f"Failed to mark account token invalid for user {user_id}: {e}")

    # NOTE: Session monitoring methods removed (get_session_info, force_refresh_session,
    # clear_user_session, record_activity, get_all_active_sessions)
    # - no longer applicable with session-per-task pattern (no cached sessions to monitor)

    async def get_session_for_account(self, user, account_number: str | None = None):
        """
        Get or create an async session for the specified account.

        Args:
            user: Django user object
            account_number: Optional specific account number

        Returns:
            OAuthSession instance or None
        """
        try:
            # Get the primary account if none specified
            if not account_number:
                trading_account = await get_primary_tastytrade_account(user)
            else:
                trading_account = await self._get_account_async(user, account_number)

            if not trading_account or not trading_account.refresh_token:
                logger.warning(f"No valid TradingAccount or refresh token for user {user.id}")
                return None

            # Use singleton pattern with automatic refresh
            session_result = await self.get_session_for_user(
                user.id, trading_account.refresh_token, is_test=trading_account.is_test
            )
            if not session_result.get("success"):
                logger.error(f"Failed to get session: {session_result.get('error')}")
                return None

            return session_result.get("session")

        except Exception as e:
            logger.error(f"Error getting session for account: {e}", exc_info=True)
            return None

    async def _get_account_async(self, user, account_number: str):
        """Get specific trading account asynchronously."""
        from asgiref.sync import sync_to_async

        from accounts.models import TradingAccount

        return await sync_to_async(
            lambda: TradingAccount.objects.filter(
                user=user, account_number=account_number, connection_type="TASTYTRADE"
            ).first()
        )()

    # NOTE: Background refresh methods removed (start_background_refresh, stop_background_refresh,
    # _background_refresh_loop, _check_and_refresh_sessions, is_background_refresh_running)
    # - no longer needed with session-per-task pattern

    @classmethod
    async def get_fresh_session_async(cls, user_id: int) -> object | None:
        """Async wrapper for streaming consumers"""
        from asgiref.sync import sync_to_async

        from accounts.models import TradingAccount

        # Get user's primary account
        account = await sync_to_async(
            lambda: TradingAccount.objects.filter(
                user_id=user_id, connection_type="TASTYTRADE", is_primary=True
            ).first()
        )()

        if not account or not account.refresh_token:
            return None

        # Use existing session management
        result = await cls.get_session_for_user(
            user_id, account.refresh_token, is_test=account.is_test
        )
        return result.get("session") if result.get("success") else None
