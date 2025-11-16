from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        """Import system checks and signals when Django starts up."""
        # Import Django system checks for TastyTrade OAuth URL validation
        # This ensures checks run at startup to prevent wrong URLs
        # Import must be in ready() to avoid circular imports
        from senex_trader import checks  # noqa: PLC0415

        _ = checks  # Mark as intentionally used for side effects

        # Import signals to register them
        import accounts.signals  # noqa: PLC0415, F401
