import os

from django.apps import AppConfig


class TradingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trading"

    def ready(self):
        """
        Application startup hook - triggers async historical data backfill.

        Runs once on server startup (not during migrations or shell commands).
        Delegates data validation to Celery task to avoid database access during initialization.
        Non-blocking - queues task and continues.
        """
        # Import strategy modules to trigger @register_strategy decorators
        # Only run during server startup, skip for migrations/management commands
        import sys

        import services.strategies.calendar_spread_strategy
        import services.strategies.call_backspread_strategy
        import services.strategies.cash_secured_put_strategy
        import services.strategies.covered_call_strategy
        import services.strategies.credit_spread_strategy
        import services.strategies.debit_spread_strategy
        import services.strategies.iron_butterfly_strategy
        import services.strategies.long_iron_condor_strategy
        import services.strategies.long_straddle_strategy
        import services.strategies.long_strangle_strategy
        import services.strategies.senex_trident_strategy
        import services.strategies.short_iron_condor_strategy  # noqa: F401

        management_commands = ["check", "migrate", "makemigrations", "shell", "test"]
        if os.environ.get("RUN_MAIN") != "true" or any(
            cmd in sys.argv for cmd in management_commands
        ):
            return

        from services.core.logging import get_logger

        logger = get_logger(__name__)

        try:
            from trading.tasks import ensure_historical_data

            ensure_historical_data.delay()
            logger.info("[OK] Historical data backfill task queued for async execution")

        except Exception as e:
            logger.debug(f"Could not queue historical data task: {e}")
