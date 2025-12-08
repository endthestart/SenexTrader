"""Tests for management command utilities."""

import asyncio
import logging
from io import StringIO

from django.core.management.base import CommandError

import pytest

from services.management.utils import (
    AsyncCommand,
    add_user_arguments,
    add_verbose_argument,
    aget_user_from_options,
    get_user_from_options,
)


class TestAsyncCommand:
    """Test AsyncCommand base class."""

    def test_requires_async_handle_implementation(self):
        """Test that subclass must implement async_handle()."""

        class BadCommand(AsyncCommand):
            pass

        cmd = BadCommand()
        with pytest.raises(NotImplementedError) as exc_info:
            cmd.handle()

        assert "must implement async_handle()" in str(exc_info.value)

    def test_async_handle_called_in_event_loop(self):
        """Test that async_handle() runs in event loop."""

        class GoodCommand(AsyncCommand):
            async def async_handle(self, *args, **options):
                # Verify we're in an event loop
                loop = asyncio.get_running_loop()
                assert loop is not None
                return "success"

        cmd = GoodCommand()
        result = cmd.handle()
        assert result == "success"

    def test_keyboard_interrupt_handled_gracefully(self):
        """Test that KeyboardInterrupt shows user-friendly message."""

        class InterruptCommand(AsyncCommand):
            async def async_handle(self, *args, **options):
                raise KeyboardInterrupt()

        cmd = InterruptCommand()
        cmd.stdout = StringIO()
        result = cmd.handle()

        assert result is None
        output = cmd.stdout.getvalue()
        assert "cancelled by user" in output.lower()

    def test_exceptions_propagate(self):
        """Test that other exceptions propagate normally."""

        class FailCommand(AsyncCommand):
            async def async_handle(self, *args, **options):
                raise ValueError("test error")

        cmd = FailCommand()
        with pytest.raises(ValueError, match="test error"):
            cmd.handle()

    def test_arguments_passed_correctly(self):
        """Test that arguments are passed to async_handle()."""

        class ArgsCommand(AsyncCommand):
            async def async_handle(self, *args, **options):
                return options.get("test_arg")

        cmd = ArgsCommand()
        result = cmd.handle(test_arg="value")
        assert result == "value"


@pytest.fixture
def regular_user(db):
    """Create a regular user for testing."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="testuser", email="test@example.com", password="testpass123"
    )


@pytest.fixture
def superuser(db):
    """Create a superuser for testing."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser(
        username="admin", email="admin@example.com", password="adminpass123"
    )


class TestAddUserArguments:
    """Test add_user_arguments function."""

    def test_adds_user_and_user_id_arguments(self):
        """Test that both --user and --user-id are added."""
        from argparse import ArgumentParser

        parser = ArgumentParser()
        add_user_arguments(parser)

        # Parse with --user
        args = parser.parse_args(["--user", "test@example.com"])
        assert args.user == "test@example.com"

        # Parse with --user-id
        args = parser.parse_args(["--user-id", "123"])
        assert args.user_id == 123

    def test_required_flag_works(self):
        """Test that required=True makes --user required."""
        from argparse import ArgumentParser

        parser = ArgumentParser()
        add_user_arguments(parser, required=True)

        with pytest.raises(SystemExit):
            parser.parse_args([])  # Should fail without --user


class TestGetUserFromOptions:
    """Test get_user_from_options function."""

    def test_finds_user_by_email(self, regular_user):
        """Test finding user by email."""
        options = {"user": "test@example.com"}
        user = get_user_from_options(options)
        assert user == regular_user

    def test_finds_user_by_id(self, regular_user):
        """Test finding user by ID."""
        options = {"user_id": regular_user.id}
        user = get_user_from_options(options)
        assert user == regular_user

    def test_prefers_email_over_id(self, regular_user, superuser):
        """Test that email is tried before ID."""
        options = {
            "user": "test@example.com",
            "user_id": superuser.id,  # Different user
        }
        user = get_user_from_options(options)
        assert user == regular_user  # Should get email user, not ID user

    def test_falls_back_to_superuser(self, superuser):
        """Test fallback to first superuser."""
        options = {}
        user = get_user_from_options(options, allow_superuser_fallback=True)
        assert user == superuser

    def test_returns_none_without_superuser_fallback(self):
        """Test returns None when no user and no fallback."""
        options = {}
        user = get_user_from_options(options, allow_superuser_fallback=False)
        assert user is None

    @pytest.mark.django_db
    def test_raises_when_required_and_not_found(self):
        """Test raises CommandError when require_user=True."""
        options = {"user": "nonexistent@example.com"}

        with pytest.raises(CommandError, match="not found"):
            get_user_from_options(options, require_user=True)

    def test_raises_when_required_and_no_options(self):
        """Test raises CommandError when require_user=True and no options."""
        options = {}

        with pytest.raises(CommandError, match="No user specified"):
            get_user_from_options(options, require_user=True, allow_superuser_fallback=False)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAgetUserFromOptions:
    """Test aget_user_from_options async function."""

    async def test_async_finds_user_by_email(self, regular_user):
        """Test async version finds user by email."""
        options = {"user": "test@example.com"}
        user = await aget_user_from_options(options)
        assert user == regular_user

    async def test_async_finds_user_by_id(self, regular_user):
        """Test async version finds user by ID."""
        options = {"user_id": regular_user.id}
        user = await aget_user_from_options(options)
        assert user == regular_user

    async def test_async_raises_when_required(self):
        """Test async version raises when required."""
        options = {"user": "nonexistent@example.com"}

        with pytest.raises(CommandError, match="not found"):
            await aget_user_from_options(options, require_user=True)


class TestAddVerboseArgument:
    """Test add_verbose_argument function."""

    def test_adds_verbose_flag(self):
        """Test that --verbose flag is added."""
        from argparse import ArgumentParser

        parser = ArgumentParser()
        add_verbose_argument(parser)

        # Parse with --verbose
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

        # Parse without --verbose
        args = parser.parse_args([])
        assert args.verbose is False


class TestConfigureCommandLogging:
    """Test configure_command_logging function."""

    def test_verbose_enables_debug_logging(self):
        """Test that verbose=True enables DEBUG logging."""
        from services.management.utils import configure_command_logging

        configure_command_logging({"verbose": True})

        # Root logger should be at DEBUG level
        assert logging.getLogger().level == logging.DEBUG

    def test_default_suppressions_applied(self):
        """Test that default suppressions are applied when verbose=False."""
        from services.management.utils import configure_command_logging

        configure_command_logging({"verbose": False})

        # Check default suppressions
        assert logging.getLogger("services").level == logging.WARNING
        assert logging.getLogger("streaming").level == logging.WARNING
        assert logging.getLogger("tastytrade").level == logging.ERROR
        assert logging.getLogger("httpx").level == logging.ERROR
        assert logging.getLogger("httpcore").level == logging.ERROR
        assert logging.getLogger("asyncio").level == logging.WARNING

    def test_custom_suppressions_override_defaults(self):
        """Test that custom suppressions override defaults."""
        from services.management.utils import configure_command_logging

        custom = {
            "services": logging.INFO,
            "custom_logger": logging.DEBUG,
        }
        configure_command_logging({}, custom_suppressions=custom)

        # Custom suppressions should be applied
        assert logging.getLogger("services").level == logging.INFO
        assert logging.getLogger("custom_logger").level == logging.DEBUG

        # Default suppressions should NOT be applied
        # (httpx won't be set to ERROR because we provided custom suppressions)
