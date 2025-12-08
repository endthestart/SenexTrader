"""Tests for email sending service."""

from unittest.mock import patch

import pytest

from services.notifications.email.email_service import EmailService


class TestEmailService:
    """Test EmailService class."""

    @pytest.fixture
    def email_service(self):
        """Create email service for testing."""
        return EmailService(default_from_email="test@example.com")

    def test_init_default_from_email(self):
        """Test initialization with default from email."""
        service = EmailService(default_from_email="custom@example.com")
        assert service.default_from_email == "custom@example.com"

    def test_init_uses_settings_default(self):
        """Test initialization uses settings if no default provided."""
        with patch("services.notifications.email.email_service.settings") as mock_settings:
            mock_settings.DEFAULT_FROM_EMAIL = "settings@example.com"
            service = EmailService()
            assert service.default_from_email == "settings@example.com"

    def test_send_email_success(self, email_service):
        """Test successful email send."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            result = email_service.send_email(
                subject="Test Subject",
                body="Test Body",
                recipient="recipient@example.com",
            )

            assert result is True
            mock_send.assert_called_once_with(
                subject="Test Subject",
                message="Test Body",
                from_email="test@example.com",
                recipient_list=["recipient@example.com"],
                fail_silently=False,
            )

    def test_send_email_custom_from_email(self, email_service):
        """Test email send with custom from_email."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            email_service.send_email(
                subject="Test",
                body="Body",
                recipient="user@example.com",
                from_email="custom@example.com",
            )

            assert mock_send.call_args[1]["from_email"] == "custom@example.com"

    def test_send_email_retry_on_failure(self, email_service):
        """Test email send retries on transient failure."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            with patch("services.notifications.email.email_service.time.sleep"):
                # Fail twice, succeed on third attempt
                mock_send.side_effect = [
                    Exception("Temp failure"),
                    Exception("Temp failure"),
                    None,
                ]

                result = email_service.send_email(
                    subject="Test",
                    body="Body",
                    recipient="user@example.com",
                    fail_silently=True,
                )

                assert result is True
                assert mock_send.call_count == 3

    def test_send_email_max_retries_exceeded(self, email_service):
        """Test email send fails after max retries."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            with patch("services.notifications.email.email_service.time.sleep"):
                mock_send.side_effect = Exception("Permanent failure")

                result = email_service.send_email(
                    subject="Test",
                    body="Body",
                    recipient="user@example.com",
                    fail_silently=True,
                )

                assert result is False
                assert mock_send.call_count == 3  # MAX_RETRIES

    def test_send_email_raises_on_fail_silently_false(self, email_service):
        """Test email send raises exception when fail_silently=False."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            with patch("services.notifications.email.email_service.time.sleep"):
                mock_send.side_effect = Exception("Fatal error")

                with pytest.raises(Exception, match="Fatal error"):
                    email_service.send_email(
                        subject="Test",
                        body="Body",
                        recipient="user@example.com",
                        fail_silently=False,
                    )

    @pytest.mark.asyncio
    async def test_asend_email_success(self, email_service):
        """Test async email send."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            result = await email_service.asend_email(
                subject="Async Test",
                body="Async Body",
                recipient="async@example.com",
            )

            assert result is True
            mock_send.assert_called_once()

    def test_send_batch_success(self, email_service):
        """Test batch email sending."""
        emails = [
            {"subject": "Email 1", "body": "Body 1", "recipient": "user1@example.com"},
            {"subject": "Email 2", "body": "Body 2", "recipient": "user2@example.com"},
            {"subject": "Email 3", "body": "Body 3", "recipient": "user3@example.com"},
        ]

        with patch("services.notifications.email.email_service.django_send_mail"):
            results = email_service.send_batch(emails)

            assert results["sent"] == 3
            assert results["failed"] == 0

    def test_send_batch_partial_failure(self, email_service):
        """Test batch sending with some failures."""
        emails = [
            {"subject": "Email 1", "body": "Body 1", "recipient": "user1@example.com"},
            {"subject": "Email 2", "body": "Body 2", "recipient": "user2@example.com"},
        ]

        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            with patch("services.notifications.email.email_service.time.sleep"):
                # First email fails all retries, second succeeds
                mock_send.side_effect = [
                    Exception("Fail"),
                    Exception("Fail"),
                    Exception("Fail"),
                    None,
                ]

                results = email_service.send_batch(emails, fail_silently=True)

                assert results["sent"] == 1
                assert results["failed"] == 1

    @pytest.mark.asyncio
    async def test_asend_batch_success(self, email_service):
        """Test async batch email sending."""
        emails = [
            {"subject": "Email 1", "body": "Body 1", "recipient": "user1@example.com"},
            {"subject": "Email 2", "body": "Body 2", "recipient": "user2@example.com"},
        ]

        with patch("services.notifications.email.email_service.django_send_mail"):
            results = await email_service.asend_batch(emails)

            assert results["sent"] == 2
            assert results["failed"] == 0

    def test_logging_on_success(self, email_service):
        """Test structured logging on successful send."""
        with patch("services.notifications.email.email_service.django_send_mail"):
            with patch("services.notifications.email.email_service.logger") as mock_logger:
                email_service.send_email(
                    subject="Test",
                    body="Body",
                    recipient="user@example.com",
                )

                # Check that success log was called
                success_calls = [
                    call for call in mock_logger.info.call_args_list if "successfully" in str(call)
                ]
                assert len(success_calls) == 1

    def test_logging_on_failure(self, email_service):
        """Test structured logging on failure."""
        with patch("services.notifications.email.email_service.django_send_mail") as mock_send:
            with patch("services.notifications.email.email_service.time.sleep"):
                with patch("services.notifications.email.email_service.logger") as mock_logger:
                    mock_send.side_effect = Exception("Test error")

                    email_service.send_email(
                        subject="Test",
                        body="Body",
                        recipient="user@example.com",
                        fail_silently=True,
                    )

                    # Check that error log was called
                    error_calls = [
                        call
                        for call in mock_logger.error.call_args_list
                        if "Failed to send email" in str(call)
                    ]
                    assert len(error_calls) == 1
