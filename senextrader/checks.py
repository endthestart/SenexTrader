"""
Django system checks for Senex Trader application.

Critical validation checks that run at startup to prevent configuration errors.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register()
def check_tastytrade_oauth_urls(app_configs, **kwargs):
    """
    System check to prevent wrong TastyTrade OAuth URLs from being used.

    This check validates that OAuth URLs are correctly configured and raises
    a critical error if any wrong URL patterns are detected.

    Wrong URL patterns that are detected and blocked:
    - signin.tastytrade.com (WRONG domain)
    - signin.tastyworks.com (WRONG domain)
    - /oauth2/authorization (WRONG path)
    - /oauth2/token (WRONG path)

    Correct URLs should be:
    - Production: https://my.tastytrade.com/auth.html
    - Production: https://api.tastyworks.com/oauth/token
    - Sandbox: https://cert-my.staging-tasty.works/auth.html
    - Sandbox: https://api.cert.tastyworks.com/oauth/token
    """
    errors = []

    # Get OAuth configuration from settings
    oauth_config = getattr(settings, "TASTYTRADE_OAUTH_CONFIG", {})
    auth_url = oauth_config.get("AUTHORIZATION_URL", "")
    token_url = oauth_config.get("TOKEN_URL", "")

    # Define wrong URL patterns that should NEVER be used
    wrong_patterns = [
        "signin.tastytrade.com",
        "signin.tastyworks.com",
        "/oauth2/authorization",
        "/oauth2/token",
    ]

    # Check for wrong patterns in URLs
    for pattern in wrong_patterns:
        if pattern in auth_url:
            errors.append(
                Error(
                    f"Invalid TastyTrade OAuth Authorization URL contains '{pattern}'",
                    hint=(
                        "Use correct URLs: "
                        "'https://my.tastytrade.com/auth.html' (production) or "
                        "'https://cert-my.staging-tasty.works/auth.html' (sandbox). "
                        f"Current URL: '{auth_url}'"
                    ),
                    obj=settings,
                    id="senextrader.E001",
                )
            )

        if pattern in token_url:
            errors.append(
                Error(
                    f"Invalid TastyTrade OAuth Token URL contains '{pattern}'",
                    hint=(
                        "Use correct URLs: 'https://api.tastyworks.com/oauth/token' "
                        "(production) or 'https://api.cert.tastyworks.com/oauth/token' "
                        f"(sandbox). Current URL: '{token_url}'"
                    ),
                    obj=settings,
                    id="senextrader.E002",
                )
            )

    # Also validate that URLs are not empty (which could indicate missing configuration)
    if not auth_url:
        errors.append(
            Error(
                "TastyTrade OAuth Authorization URL is not configured",
                hint=(
                    "Set TASTYTRADE_AUTHORIZATION_URL environment variable or check "
                    "TASTYTRADE_OAUTH_CONFIG in settings"
                ),
                obj=settings,
                id="senextrader.E003",
            )
        )

    if not token_url:
        errors.append(
            Error(
                "TastyTrade OAuth Token URL is not configured",
                hint=(
                    "Set TASTYTRADE_TOKEN_URL environment variable or check "
                    "TASTYTRADE_OAUTH_CONFIG in settings"
                ),
                obj=settings,
                id="senextrader.E004",
            )
        )

    return errors


@register()
def check_tastytrade_configuration(app_configs, **kwargs):
    """
    System check to validate overall TastyTrade configuration.

    Ensures that required TastyTrade configuration is present and valid.
    """
    errors = []

    # Check that OAuth configuration exists
    oauth_config = getattr(settings, "TASTYTRADE_OAUTH_CONFIG", None)
    if not oauth_config:
        errors.append(
            Error(
                "TastyTrade OAuth configuration is missing",
                hint="Ensure TASTYTRADE_OAUTH_CONFIG is defined in settings",
                obj=settings,
                id="senextrader.E005",
            )
        )
        # Return early if no config exists
        return errors

    # Validate required fields exist
    required_fields = ["CLIENT_ID", "CLIENT_SECRET", "AUTHORIZATION_URL", "TOKEN_URL"]
    for field in required_fields:
        if field not in oauth_config:
            errors.append(
                Error(
                    f"TastyTrade OAuth configuration missing required field: {field}",
                    hint=f"Add '{field}' to TASTYTRADE_OAUTH_CONFIG in settings",
                    obj=settings,
                    id=f"senextrader.E00{6 + required_fields.index(field)}",
                )
            )

    return errors


@register(Tags.database)
def check_database_connections(app_configs, **kwargs):
    """
    Check database connection pool health.
    
    This system check validates PostgreSQL connection pool usage at startup.
    For production monitoring, use services/monitoring/ for continuous health checks.
    """
    from django.db import connection

    errors = []

    # Only run this check for PostgreSQL databases
    if connection.vendor != "postgresql":
        return errors

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            active_connections = cursor.fetchone()[0]

            max_connections = getattr(settings, "DATABASE_POOL_MAX_SIZE", 20)
            if active_connections > max_connections * 0.8:
                errors.append(
                    Warning(
                        f"High database connection usage: {active_connections}/{max_connections}",
                        hint="Consider increasing DB_POOL_MAX_SIZE or investigating connection leaks",
                        id="database.W001",
                    )
                )
    except Exception as e:
        errors.append(
            Error(
                f"Unable to check database connections: {e}",
                id="database.E001",
            )
        )

    return errors
