"""
Utilities for Django management commands.

Provides reusable base classes and utilities to reduce code duplication
and standardize patterns across management commands.
"""

import asyncio
import logging
from argparse import ArgumentParser

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class AsyncCommand(BaseCommand):
    """
    Base class for async management commands.

    Subclasses should override async_handle() instead of handle().
    The event loop is automatically managed.

    Example:
        class Command(AsyncCommand):
            def add_arguments(self, parser):
                parser.add_argument('--symbol', type=str, required=True)

            async def async_handle(self, *args, **options):
                symbol = options['symbol']
                data = await some_async_function(symbol)
                self.stdout.write(f"Result: {data}")
    """

    async def async_handle(self, *args, **options):
        """
        Override this method in subclass to implement async logic.

        This method is automatically called within an event loop by handle().
        Use async/await as normal.

        Args:
            *args: Positional arguments from handle()
            **options: Keyword arguments from argparse

        Returns:
            Any value to be returned from the command

        Raises:
            NotImplementedError: If subclass doesn't override this method
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement async_handle()")

    def handle(self, *args, **options):
        """
        Standard Django handle() method.

        Automatically creates event loop and runs async_handle().
        Handles KeyboardInterrupt gracefully.

        Do not override this method - override async_handle() instead.
        """
        try:
            return asyncio.run(self.async_handle(*args, **options))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nOperation cancelled by user."))
            return None


def add_user_arguments(
    parser: ArgumentParser, required: bool = False, allow_superuser_fallback: bool = True
) -> None:
    """
    Add standard user selection arguments to command parser.

    Adds --user (email) and --user-id arguments to support multiple
    ways of specifying which user the command should operate on.

    Args:
        parser: ArgumentParser instance from add_arguments()
        required: If True, user must be specified (no defaults)
        allow_superuser_fallback: If True, adds help text about superuser fallback

    Example:
        class Command(BaseCommand):
            def add_arguments(self, parser):
                add_user_arguments(parser, required=False)
                parser.add_argument('--symbol', type=str, default='SPY')
    """
    help_text = "Email address of user"
    if allow_superuser_fallback and not required:
        help_text += " (defaults to first superuser if not specified)"

    parser.add_argument(
        "--user",
        type=str,
        required=required,
        help=help_text,
    )

    parser.add_argument(
        "--user-id",
        type=int,
        help="User ID (alternative to --user email)",
    )


def get_user_from_options(
    options: dict, require_user: bool = False, allow_superuser_fallback: bool = True
) -> User | None:
    """
    Get user from command options with consistent fallback behavior.

    Tries multiple methods to find a user:
    1. --user email if provided
    2. --user-id if provided
    3. First superuser if allow_superuser_fallback=True
    4. None or raise CommandError based on require_user

    Args:
        options: Command options dict from handle()
        require_user: If True, raises CommandError if no user found
        allow_superuser_fallback: If True, falls back to first superuser

    Returns:
        User instance or None

    Raises:
        CommandError: If require_user=True and no user found

    Example:
        def handle(self, *args, **options):
            user = get_user_from_options(options, require_user=True)
            self.stdout.write(f"Processing for user: {user.email}")
    """
    # Try email first
    if options.get("user"):
        user = User.objects.filter(email=options["user"]).first()
        if user:
            return user
        if require_user:
            raise CommandError(f"User '{options['user']}' not found")
        return None

    # Try user ID
    if options.get("user_id"):
        user = User.objects.filter(id=options["user_id"]).first()
        if user:
            return user
        if require_user:
            raise CommandError(f"User ID {options['user_id']} not found")
        return None

    # Fallback to superuser
    if allow_superuser_fallback:
        user = User.objects.filter(is_superuser=True).first()
        if user:
            return user

    # No user found
    if require_user:
        raise CommandError("No user specified. Use --user EMAIL or --user-id ID")

    return None


async def aget_user_from_options(
    options: dict, require_user: bool = False, allow_superuser_fallback: bool = True
) -> User | None:
    """
    Async version of get_user_from_options().

    Same interface but uses async queries for use in async commands.

    Args:
        options: Command options dict from async_handle()
        require_user: If True, raises CommandError if no user found
        allow_superuser_fallback: If True, falls back to first superuser

    Returns:
        User instance or None

    Raises:
        CommandError: If require_user=True and no user found

    Example:
        async def async_handle(self, *args, **options):
            user = await aget_user_from_options(options, require_user=True)
            self.stdout.write(f"Processing for user: {user.email}")
    """
    # Try email first
    if options.get("user"):
        user = await User.objects.filter(email=options["user"]).afirst()
        if user:
            return user
        if require_user:
            raise CommandError(f"User '{options['user']}' not found")
        return None

    # Try user ID
    if options.get("user_id"):
        user = await User.objects.filter(id=options["user_id"]).afirst()
        if user:
            return user
        if require_user:
            raise CommandError(f"User ID {options['user_id']} not found")
        return None

    # Fallback to superuser
    if allow_superuser_fallback:
        user = await User.objects.filter(is_superuser=True).afirst()
        if user:
            return user

    # No user found
    if require_user:
        raise CommandError("No user specified. Use --user EMAIL or --user-id ID")

    return None


def add_verbose_argument(parser):
    """
    Add standard --verbose argument to command parser.

    Adds a verbose flag that can be used with configure_command_logging()
    to enable detailed logging output.

    Args:
        parser: ArgumentParser instance from add_arguments()

    Example:
        class Command(BaseCommand):
            def add_arguments(self, parser):
                add_verbose_argument(parser)
    """
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output (DEBUG level for all loggers)",
    )


def configure_command_logging(options: dict, custom_suppressions: dict | None = None) -> None:
    """
    Configure logging levels for management commands.

    By default, suppresses verbose logging from common noisy modules
    (services, streaming, tastytrade, httpx, httpcore, asyncio).
    Can be overridden with verbose=True or custom suppressions.

    Args:
        options: Command options dict from handle() (checks for 'verbose' key)
        custom_suppressions: Dict mapping logger names to logging levels
                           Overrides default suppressions

    Example:
        def handle(self, *args, **options):
            configure_command_logging(options)
            # ... rest of command logic

        # Or with custom suppressions:
        configure_command_logging(
            options,
            custom_suppressions={
                "services": logging.INFO,
                "streaming": logging.WARNING,
            }
        )
    """
    verbose = options.get("verbose", False)
    if verbose:
        # Enable verbose logging for everything
        logging.getLogger().setLevel(logging.DEBUG)
        return

    # Default suppressions for common noisy modules
    default_suppressions = {
        "services": logging.WARNING,
        "streaming": logging.WARNING,
        "tastytrade": logging.ERROR,
        "httpx": logging.ERROR,
        "httpcore": logging.ERROR,
        "asyncio": logging.WARNING,
    }

    # Use custom suppressions if provided, otherwise use defaults
    suppressions = custom_suppressions if custom_suppressions is not None else default_suppressions

    # Apply suppressions
    for logger_name, level in suppressions.items():
        logging.getLogger(logger_name).setLevel(level)
