"""
Service for sending notifications to users.
"""

from django.utils import timezone

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from services.core.logging import get_logger
from services.notifications.email import EmailService

logger = get_logger(__name__)


class NotificationService:
    """
    Handles sending notifications to users via various channels (e.g., email, WebSocket).
    """

    def __init__(self, user) -> None:
        self.user = user
        self.channel_layer = get_channel_layer()
        self.email_service = EmailService()

    async def send_notification(
        self, message: str, details: dict, notification_type: str = "info"
    ) -> bool:
        """
        Send a notification to the user via multiple channels.

        Args:
            message: Human-readable notification message
            details: Additional context data
            notification_type: Type of notification (info, warning, error, success)

        Returns:
            bool: True if at least one channel succeeded
        """
        logger.info(f"User {self.user.id}: Sending {notification_type} notification: {message}")

        success = False

        # 1. Send email based on user preference
        email_sent = await self._send_email_notification(message, details, notification_type)
        if email_sent:
            success = True

        # 2. Send WebSocket notification for real-time updates
        websocket_sent = await self._send_websocket_notification(
            message, details, notification_type
        )
        if websocket_sent:
            success = True

        # 3. Store notification in database for persistence (future: Notification model)
        # await self._store_notification(message, details, notification_type)

        return success

    async def _send_email_notification(
        self, message: str, details: dict, notification_type: str
    ) -> bool:
        """Send email notification based on user preference."""
        try:
            # Check user email preference
            email_preference = await sync_to_async(lambda: self.user.email_preference)()

            if email_preference == "none":
                logger.debug(f"User {self.user.id}: Email disabled by preference")
                return False

            if email_preference == "summary":
                # Queue for daily summary (future implementation)
                logger.debug(f"User {self.user.id}: Notification queued for daily summary")
                return False

            # Send immediate email
            subject_prefix = {
                "info": "Notification",
                "warning": "⚠️ Warning",
                "error": "❌ Error",
                "success": "✅ Success",
            }.get(notification_type, "Notification")

            symbol = details.get("symbol", "")
            subject = (
                f"{subject_prefix}: {symbol} - Senex Trader"
                if symbol
                else f"{subject_prefix} - Senex Trader"
            )

            # Build email body
            body_lines = [message, ""]

            if details.get("position_id"):
                body_lines.append(f"Position ID: {details['position_id']}")
            if details.get("symbol"):
                body_lines.append(f"Symbol: {details['symbol']}")
            if details.get("reason"):
                body_lines.append(f"Reason: {details['reason']}")

            body_lines.extend(["", "View details in your dashboard: https://example.com"])

            email = await sync_to_async(lambda: self.user.email)()
            success = await self.email_service.asend_email(
                subject=subject,
                body="\n".join(body_lines),
                recipient=email,
                fail_silently=True,
            )

            if success:
                logger.info(f"User {self.user.id}: Email notification sent")
            return success

        except Exception as e:
            logger.error(f"User {self.user.id}: Failed to send email notification: {e}")
            return False

    async def _send_websocket_notification(
        self, message: str, details: dict, notification_type: str
    ) -> bool:
        """Send real-time WebSocket notification."""
        try:
            if not self.channel_layer:
                logger.warning(f"User {self.user.id}: No channel layer available for WebSocket")
                return False

            # Send to user's data group
            user_group = f"user_{self.user.id}_data"
            await self.channel_layer.group_send(
                user_group,
                {
                    "type": "notification",
                    "notification_type": notification_type,
                    "message": message,
                    "details": details,
                    "timestamp": timezone.now().isoformat(),
                },
            )

            logger.debug(f"User {self.user.id}: WebSocket notification sent to {user_group}")
            return True

        except Exception as e:
            logger.error(f"User {self.user.id}: Failed to send WebSocket notification: {e}")
            return False
