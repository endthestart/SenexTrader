"""
Centralized authentication service for streaming infrastructure.

This service eliminates code duplication by providing a single point for
TastyTrade authentication across all streaming components.
"""

from typing import Any

from accounts.models import TradingAccount
from services.core.logging import get_logger
from streaming.constants import STREAMING_AUTH_MAX_RETRIES

logger = get_logger(__name__)


class StreamingAuthService:
    """Centralized authentication service for streaming operations."""

    def __init__(self):
        """Initialize the authentication service."""
        pass

    async def authenticate_account(self, trading_account: TradingAccount) -> Any | None:
        """
        Authenticate with TastyTrade using stored tokens.

        Args:
            trading_account: TradingAccount with refresh_token

        Returns:
            TastyTrade session object if successful, None if failed
        """
        try:
            from services.core.data_access import get_oauth_session_for_account

            session = await get_oauth_session_for_account(
                trading_account.user, trading_account.account_number
            )

            if session:
                logger.info(
                    f"Successfully authenticated for account " f"{trading_account.account_number}"
                )
                return session
            logger.error(f"Authentication failed for account {trading_account.account_number}")
            return None

        except Exception as e:
            logger.error(
                f"Authentication error for account " f"{trading_account.account_number}: {e}"
            )
            return None

    async def authenticate_with_retry(
        self,
        trading_account: TradingAccount,
        max_retries: int = STREAMING_AUTH_MAX_RETRIES,
    ) -> Any | None:
        """
        Authenticate with retry logic for improved reliability.

        Args:
            trading_account: TradingAccount with refresh_token
            max_retries: Maximum number of retry attempts

        Returns:
            TastyTrade session object if successful, None if failed
        """
        for attempt in range(max_retries + 1):
            session = await self.authenticate_account(trading_account)
            if session:
                return session

            if attempt < max_retries:
                logger.warning(
                    f"Authentication attempt {attempt + 1} failed for "
                    f"account {trading_account.account_number}, retrying..."
                )
            else:
                logger.error(
                    f"Authentication failed after {max_retries + 1} "
                    f"attempts for account {trading_account.account_number}"
                )

        return None


# Shared instance for use across streaming components
streaming_auth = StreamingAuthService()
