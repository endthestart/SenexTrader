from channels.layers import get_channel_layer

from services.core.logging import get_logger
from services.core.utils.async_utils import run_async

logger = get_logger(__name__)


class StreamingSubscriptionService:
    """
    A synchronous service to manage subscriptions for the live data streamer.

    This acts as a bridge from the synchronous world (Django Views) to the
    asynchronous world (Channels/StreamManager) to ensure the correct
    live data is being streamed for the page a user is on.
    """

    def ensure_subscriptions(
        self, user, symbols: list[str] | None = None, subscribe_to_account: bool = False
    ):
        """
        Sends a message to the user's stream manager to ensure the required
        subscriptions are active.
        """
        if not user or not user.is_authenticated:
            return

        if not symbols and not subscribe_to_account:
            return

        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                logger.warning("Channel layer not available, cannot manage subscriptions.")
                return

            group_name = f"stream_control_{user.id}"
            message = {
                "type": "ensure_subscriptions",
                "symbols": symbols or [],
                "account": subscribe_to_account,
            }

            # Use run_async to call the async group_send from this sync context
            run_async(channel_layer.group_send(group_name, message))
            logger.info(f"Sent subscription assurance request to {group_name}")

        except Exception as e:
            logger.error(f"Failed to send subscription assurance message: {e}", exc_info=True)
