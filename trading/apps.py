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
        # Strategy modules are now instantiated via StrategyFactory
        # No decorator-based registration needed - factory uses explicit definitions
        import os
        import sys

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
