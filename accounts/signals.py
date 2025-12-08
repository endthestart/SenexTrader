"""
Django signals for automatic creation of user-related objects.

Ensures UserPreferences, OptionsAllocation, StrategyConfiguration, and Watchlist
are created at the appropriate times with proper defaults.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import TradingAccount, User, UserPreferences
from trading.models import SENEX_TRIDENT_DEFAULTS, StrategyConfiguration, Watchlist


@receiver(post_save, sender=User)
def create_user_preferences(sender, instance, created, **kwargs):
    """
    Create UserPreferences when a User is created.

    This ensures user.preferences is always available without lazy creation.
    """
    if created:
        UserPreferences.objects.get_or_create(
            user=instance,
            defaults={
                "email_preference": "summary",
                "email_daily_trade_suggestion": False,
                "privacy_mode": False,
            },
        )


@receiver(post_save, sender=User)
def create_options_allocation(sender, instance, created, **kwargs):
    """
    Create OptionsAllocation when a User is created.

    This ensures user.options_allocation is always available with conservative defaults.
    """
    if created:
        from accounts.models import OptionsAllocation

        OptionsAllocation.objects.get_or_create(
            user=instance,
            defaults={
                "allocation_method": "conservative",
                "risk_tolerance": 0.40,
                "stressed_risk_tolerance": 0.60,
                "warning_threshold_high": 0.80,
                "warning_threshold_medium": 0.65,
            },
        )


@receiver(post_save, sender=User)
def create_default_watchlist(sender, instance, created, **kwargs):
    """
    Create default watchlist with DEFAULT_WATCHLIST_SYMBOLS when a User is created.

    This ensures users have a populated watchlist from the start with popular
    high-volume equities commonly used for options trading.
    """
    if created:
        # Get default watchlist symbols from settings
        # Format: list of (symbol, description) tuples
        default_symbols = getattr(settings, "DEFAULT_WATCHLIST_SYMBOLS", [])

        # Create watchlist items for each symbol
        for order, (symbol, description) in enumerate(default_symbols, start=1):
            Watchlist.objects.get_or_create(
                user=instance,
                symbol=symbol,
                defaults={
                    "order": order,
                    "description": description,
                },
            )


@receiver(post_save, sender=TradingAccount)
def create_trading_account_preferences(sender, instance, created, **kwargs):
    """
    Create TradingAccountPreferences when a TradingAccount is created.

    This ensures account.trading_preferences is always available without lazy creation.
    """
    if created:
        from accounts.models import TradingAccountPreferences

        TradingAccountPreferences.objects.get_or_create(
            account=instance,
            defaults={
                "is_automated_trading_enabled": False,
                "automated_entry_offset_cents": 0,
            },
        )


@receiver(post_save, sender=TradingAccount)
def create_strategy_configuration_on_broker_connect(sender, instance, created, **kwargs):
    """
    Create StrategyConfiguration for senex_trident when a broker account is connected.

    Only creates if account is configured (has account_number and access_token)
    and is marked as primary. This ensures the strategy config exists when broker is connected.
    """
    # Check if account is configured and is primary
    is_configured = bool(instance.account_number and instance.access_token)

    if is_configured and instance.is_primary:
        # Account is configured and primary - ensure strategy config exists
        StrategyConfiguration.objects.get_or_create(
            user=instance.user,
            strategy_id="senex_trident",
            defaults={
                "parameters": SENEX_TRIDENT_DEFAULTS.copy(),
                "is_active": True,
            },
        )
