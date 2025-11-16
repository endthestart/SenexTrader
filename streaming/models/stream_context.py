"""User streaming context to encapsulate all streaming state for a single user."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone as dj_timezone

from services.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UserStreamContext:
    """Encapsulates all streaming state for a single user.

    This replaces the complex multi-layer orchestration with a simple
    in-memory state container that manages both data and account streamers.
    """

    user_id: int
    data_streamer: object | None = None  # DXLinkStreamer
    account_streamer: object | None = None  # AlertStreamer
    subscribed_symbols: set[str] = field(default_factory=set)
    reference_count: int = 0
    last_activity: datetime = field(default_factory=lambda: dj_timezone.now())

    # Channel tracking for WebSocket connections
    connected_channels: set[str] = field(default_factory=set)

    async def close(self) -> None:
        """Properly close both streamers and cancel any running tasks."""
        # Cancel account tasks if any
        if hasattr(self, "_account_tasks"):
            for task in list(self._account_tasks):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except Exception:
                        pass  # Task cancellation exceptions are expected
            self._account_tasks.clear()

        if self.data_streamer:
            try:
                # Check if it's an async close method
                close_method = getattr(self.data_streamer, "close", None)
                if close_method:
                    await close_method()
                    logger.info(f"Closed data streamer for user {self.user_id}")
            except Exception as e:
                logger.error(f"Error closing data streamer for user {self.user_id}: {e}")
            finally:
                self.data_streamer = None

        if self.account_streamer:
            try:
                # Check if it's an async close method
                close_method = getattr(self.account_streamer, "close", None)
                if close_method:
                    await close_method()
                    logger.info(f"Closed account streamer for user {self.user_id}")
            except Exception as e:
                logger.error(f"Error closing account streamer for user {self.user_id}: {e}")
            finally:
                self.account_streamer = None

        self.subscribed_symbols.clear()
        self.connected_channels.clear()

    def add_channel(self, channel_name: str) -> None:
        """Add a WebSocket channel to this context."""
        self.connected_channels.add(channel_name)
        self.reference_count += 1
        self.last_activity = dj_timezone.now()
        logger.debug(
            f"Added channel {channel_name} to user {self.user_id} "
            f"context (ref_count={self.reference_count})"
        )

    def remove_channel(self, channel_name: str) -> None:
        """Remove a WebSocket channel from this context."""
        if channel_name in self.connected_channels:
            self.connected_channels.discard(channel_name)
            self.reference_count = max(0, self.reference_count - 1)
            self.last_activity = dj_timezone.now()
            logger.debug(
                f"Removed channel {channel_name} from user {self.user_id} "
                f"context (ref_count={self.reference_count})"
            )

    @property
    def is_active(self) -> bool:
        """Check if this context has active connections."""
        return self.reference_count > 0

    @property
    def has_data_stream(self) -> bool:
        """Check if data streamer is active."""
        if not self.data_streamer:
            return False
        # Check if streamer has a 'closed' attribute
        closed = getattr(self.data_streamer, "closed", None)
        if closed is not None:
            return not closed
        return True

    @property
    def has_account_stream(self) -> bool:
        """Check if account streamer is active."""
        if not self.account_streamer:
            return False
        # Check if streamer has a 'closed' attribute
        closed = getattr(self.account_streamer, "closed", None)
        if closed is not None:
            return not closed
        return True
