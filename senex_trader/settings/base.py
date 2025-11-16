"""
Base settings for Senex Trader application.

This contains common configuration shared between development and production.
"""

import os
from pathlib import Path

from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ===============================================================================#
# CORE APPLICATION SETTINGS
# ===============================================================================#

APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://example.com")

# ================================================================================
# APPLICATION DEFINITION
# ================================================================================

INSTALLED_APPS = [
    "daphne",  # Must be FIRST for runserver ASGI integration
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third-party apps
    "channels",
    "encrypted_model_fields",
    # Local apps
    "accounts",
    "trading",
    "streaming",
    "services",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "senex_trader.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.broker_account_status",
                "senex_trader.context_processors.dry_run_mode",
                "senex_trader.context_processors.privacy_mode",
            ],
        },
    },
]

WSGI_APPLICATION = "senex_trader.wsgi.application"
ASGI_APPLICATION = "senex_trader.asgi.application"

# ================================================================================
# AUTHENTICATION AND AUTHORIZATION
# ================================================================================

AUTH_USER_MODEL = "accounts.User"
LOGIN_REDIRECT_URL = "trading:dashboard"
LOGOUT_REDIRECT_URL = "home"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": ("django.contrib.auth.password_validation.UserAttributeSimilarityValidator"),
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ================================================================================
# INTERNATIONALIZATION
# ================================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

# ================================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# ================================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ================================================================================
# STATIC FILES (CSS, JavaScript, Images)
# ================================================================================

STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# ================================================================================
# ENCRYPTED FIELDS CONFIGURATION
# ================================================================================

# This will be overridden in specific environments
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY")

# ================================================================================
# DEFAULT CELERY SETTINGS (will be overridden in production)
# ================================================================================

CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/New_York"
CELERY_ENABLE_UTC = True

# Beat scheduler for tasks
CELERY_BEAT_SCHEDULE = {
    "monitor-dte-positions": {
        "task": "trading.tasks.monitor_positions_for_dte_closure",
        "schedule": 900.0,  # Every 15 minutes (reduced from 5min to limit API calls)
    },
    "automated-daily-trade-cycle": {
        "task": "trading.tasks.automated_daily_trade_cycle",
        # Every 15 minutes from 10:00 AM to 2:45 PM ET on weekdays
        # Runs at: 10:00, 10:15, 10:30, ..., 14:30, 14:45 (20 times/day)
        # Task has built-in check to only trade once per day
        "schedule": crontab(hour="10-14", minute="0,15,30,45", day_of_week="mon-fri"),
    },
    "generate-and-email-daily-suggestions": {
        "task": "trading.tasks.generate_and_email_daily_suggestions",
        "schedule": crontab(hour=10, minute=0, day_of_week="mon-fri"),  # 10:00 AM ET on weekdays
    },
    "monitor-open-orders": {
        "task": "trading.tasks.monitor_open_orders",
        "schedule": 900.0,  # Every 15 minutes (reduced from 5min; AlertStreamer provides real-time updates)
    },
    "generate-trading-summary": {
        "task": "trading.tasks.generate_trading_summary",
        "schedule": crontab(hour=16, minute=30, day_of_week="mon-fri"),  # 4:30 PM ET
    },
    "cleanup-inactive-streamers": {
        "task": "streaming.tasks.cleanup_inactive_streamers",
        "schedule": 3600.0,  # Every hour
    },
    "cleanup-old-records": {
        "task": "trading.tasks.cleanup_old_records_task",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3:00 AM ET (trades + suggestions)
    },
    # BATCHED DATA SYNC - Combines position sync, order history, and trade reconciliation
    # to reduce API session overhead by sharing connection pool
    "batch-sync-data": {
        "task": "trading.tasks.batch_sync_data_task",
        "schedule": 1800.0,  # Every 30 minutes (batches 3 operations into 1)
    },
    # NOTE: Individual tasks below are now part of batch-sync-data task (disabled)
    # - reconcile-trades-with-tastytrade (was: every 30 min)
    # - sync-order-history (was: every 30 min)
    # - sync-positions (was: every 15 min)
    "ensure-historical-data": {
        "task": "trading.tasks.ensure_historical_data",
        "schedule": crontab(hour=17, minute=30, day_of_week="mon-fri"),  # 5:30 PM ET weekdays
    },
    "persist-greeks-from-cache": {
        "task": "trading.tasks.persist_greeks_from_cache",
        "schedule": 900.0,  # Every 15 minutes (reduced from 10min to limit API calls; Epic 05, Task 004)
    },
    "aggregate-historical-greeks": {
        "task": "trading.tasks.aggregate_historical_greeks",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3:00 AM ET (progressive aggregation)
    },
    "clear-expired-option-chains": {
        "task": "trading.tasks.clear_expired_option_chains",
        "schedule": crontab(hour=0, minute=5),  # Daily at 12:05 AM ET (Cache Bug 5 fix)
    },
}

# ================================================================================
# DEFAULT STREAMING CONFIGURATION
# ================================================================================

STREAMING_CONFIG = {
    "IDLE_TIMEOUT_MINUTES": 5,
    "MAX_SESSION_HOURS": 1,
    "HEARTBEAT_INTERVAL": 15,
    "LEASE_TTL_SECONDS": 90,
    "CLEANUP_INTERVAL": 60,
}

# ================================================================================
# DEFAULT RATE LIMITING SETTINGS
# ================================================================================

ACCOUNT_API_RATE_LIMIT_MAX = 1
ACCOUNT_API_RATE_LIMIT_WINDOW = 60

OPTIONS_API_RATE_LIMIT_MAX = 10
OPTIONS_API_RATE_LIMIT_WINDOW = 60

DXFEED_API_RATE_LIMIT_MAX = 5
DXFEED_API_RATE_LIMIT_WINDOW = 60

STRATEGY_GENERATION_RATE_LIMIT_MAX = 20
STRATEGY_GENERATION_RATE_LIMIT_WINDOW = 300

ORDER_EXECUTION_RATE_LIMIT_MAX = 10
ORDER_EXECUTION_RATE_LIMIT_WINDOW = 60

# ================================================================================
# DEFAULT CIRCUIT BREAKER SETTINGS
# ================================================================================

CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60
CIRCUIT_BREAKER_SUCCESS_THRESHOLD = 3

# ================================================================================
# DEFAULT METRICS SETTINGS
# ================================================================================

STREAMING_METRICS_TTL = 3600
STREAMING_METRICS_WINDOW = 300

# ================================================================================
# ACCOUNT STATE SETTINGS
# ================================================================================

ACCOUNT_STATE_CACHE_TTL = 120
ACCOUNT_SNAPSHOT_WINDOW = 300
ACCOUNT_SNAPSHOT_FRESH_THRESHOLD = 120

# ================================================================================
# OPTIONS DATA SETTINGS
# ================================================================================

OPTION_CHAIN_CACHE_TTL = 600  # 10 minutes

# ================================================================================
# HISTORICAL DATA SETTINGS
# ================================================================================

# Default watchlist symbols for new users
# Top high-volume equities commonly used for options trading
DEFAULT_WATCHLIST_SYMBOLS = [
    "SPY",  # S&P 500 ETF
    "QQQ",  # Nasdaq 100 ETF
    "IWM",  # Russell 2000 ETF
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "NVDA",  # NVIDIA
    "GOOGL",  # Alphabet
    "AMZN",  # Amazon
    "META",  # Meta
    "TSLA",  # Tesla
    "JPM",  # JPMorgan Chase
    "V",  # Visa
    "WMT",  # Walmart
    "AMD",  # AMD
    "NFLX",  # Netflix
]

# Minimum days of historical data required for technical analysis
MINIMUM_HISTORICAL_DAYS = 90

# ================================================================================
# DEFAULT CHANNEL LAYERS (will be overridden in production)
# ================================================================================


# ================================================================================
# TASTYTRADE OAUTH CONFIGURATION
# ================================================================================

# Individual TastyTrade settings
TASTYTRADE_CLIENT_ID = os.environ.get("TASTYTRADE_CLIENT_ID")
TASTYTRADE_CLIENT_SECRET = os.environ.get("TASTYTRADE_CLIENT_SECRET")

# Consolidated OAuth configuration
TASTYTRADE_OAUTH_CONFIG = {
    "CLIENT_ID": TASTYTRADE_CLIENT_ID or "",
    "CLIENT_SECRET": TASTYTRADE_CLIENT_SECRET or "",
    "AUTHORIZATION_URL": os.environ.get(
        "TASTYTRADE_AUTHORIZATION_URL", "https://my.tastytrade.com/auth.html"
    ),
    "TOKEN_URL": os.environ.get("TASTYTRADE_TOKEN_URL", "https://api.tastyworks.com/oauth/token"),
    "SCOPES": os.environ.get("TASTYTRADE_SCOPES", "read trade openid"),
}

# Dry-run mode: validate orders without database writes. See planning/33-dry-run-support/
TASTYTRADE_DRY_RUN = os.environ.get("TASTYTRADE_DRY_RUN", "False").lower() in (
    "true",
    "1",
    "yes",
    "on",
)
