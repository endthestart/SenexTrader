"""
Email sending service with retry logic and connection pooling.

Centralizes email sending logic to replace duplicate code across tasks and services.
"""

import time

from django.conf import settings
from django.core.mail import send_mail as django_send_mail

from asgiref.sync import sync_to_async

from services.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """
    Centralized email sending service with retry logic.

    Features:
    - Automatic retry on transient failures
    - Configurable sender (from settings)
    - Support for both sync and async contexts
    - Structured logging for monitoring

    Example:
        service = EmailService()
        service.send_email(
            subject="Test",
            body="Hello",
            recipient="user@example.com"
        )
    """

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # seconds (initial delay)
    RETRY_BACKOFF = 2.0  # exponential backoff multiplier
    MAX_DELAY = 10.0  # seconds (cap on exponential backoff)

    def __init__(self, default_from_email: str | None = None):
        """
        Initialize email service.

        Args:
            default_from_email: Default sender email (defaults to settings.DEFAULT_FROM_EMAIL)
        """
        self.default_from_email = default_from_email or getattr(
            settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"
        )

    def send_email(
        self,
        subject: str,
        body: str,
        recipient: str,
        from_email: str | None = None,
        fail_silently: bool = True,
    ) -> bool:
        """
        Send email with retry logic.

        Args:
            subject: Email subject
            body: Email body (plain text)
            recipient: Recipient email address
            from_email: Sender email (defaults to default_from_email)
            fail_silently: If True, suppress exceptions (default: True)

        Returns:
            True if email sent successfully, False otherwise
        """
        from_email = from_email or self.default_from_email

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    f"Sending email to {recipient}",
                    extra={
                        "recipient": recipient,
                        "subject": subject,
                        "attempt": attempt,
                    },
                )

                django_send_mail(
                    subject=subject,
                    message=body,
                    from_email=from_email,
                    recipient_list=[recipient],
                    fail_silently=False,  # We handle errors ourselves
                )

                logger.info(
                    f"Email sent successfully to {recipient}",
                    extra={
                        "recipient": recipient,
                        "subject": subject,
                        "attempt": attempt,
                    },
                )

                return True

            except Exception as e:
                logger.warning(
                    f"Email send attempt {attempt}/{self.MAX_RETRIES} failed to {recipient}: {e}",
                    extra={
                        "recipient": recipient,
                        "subject": subject,
                        "attempt": attempt,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

                if attempt < self.MAX_RETRIES:
                    delay = min(
                        self.RETRY_DELAY * (self.RETRY_BACKOFF ** (attempt - 1)), self.MAX_DELAY
                    )
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Failed to send email to {recipient} after {self.MAX_RETRIES} attempts",
                        extra={
                            "recipient": recipient,
                            "subject": subject,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                        exc_info=not fail_silently,
                    )

                    if not fail_silently:
                        raise

                    return False

        return False

    async def asend_email(
        self,
        subject: str,
        body: str,
        recipient: str,
        from_email: str | None = None,
        fail_silently: bool = True,
    ) -> bool:
        """
        Async version of send_email.

        Args:
            subject: Email subject
            body: Email body (plain text)
            recipient: Recipient email address
            from_email: Sender email (defaults to default_from_email)
            fail_silently: If True, suppress exceptions (default: True)

        Returns:
            True if email sent successfully, False otherwise
        """
        return await sync_to_async(self.send_email)(
            subject=subject,
            body=body,
            recipient=recipient,
            from_email=from_email,
            fail_silently=fail_silently,
        )

    def send_batch(
        self,
        emails: list[dict],
        fail_silently: bool = True,
    ) -> dict:
        """
        Send multiple emails.

        Args:
            emails: List of dicts with keys: subject, body, recipient, from_email (optional)
            fail_silently: If True, continue on errors

        Returns:
            Dict with 'sent' and 'failed' counts
        """
        results = {"sent": 0, "failed": 0}

        for email_data in emails:
            success = self.send_email(
                subject=email_data["subject"],
                body=email_data["body"],
                recipient=email_data["recipient"],
                from_email=email_data.get("from_email"),
                fail_silently=fail_silently,
            )

            if success:
                results["sent"] += 1
            else:
                results["failed"] += 1

        return results

    async def asend_batch(
        self,
        emails: list[dict],
        fail_silently: bool = True,
    ) -> dict:
        """
        Async version of send_batch.

        Args:
            emails: List of dicts with keys: subject, body, recipient, from_email (optional)
            fail_silently: If True, continue on errors

        Returns:
            Dict with 'sent' and 'failed' counts
        """
        return await sync_to_async(self.send_batch)(
            emails=emails,
            fail_silently=fail_silently,
        )
