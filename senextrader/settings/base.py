"""
Base settings for Senex Trader application.

This contains common configuration shared between development and production.
"""

import os
from pathlib import Path

from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ================================================================================
# CORE APPLICATION SETTINGS
# ================================================================================

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

ROOT_URLCONF = "senextrader.urls"

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
                "senextrader.context_processors.dry_run_mode",
                "senextrader.context_processors.privacy_mode",
                "senextrader.context_processors.app_environment",
            ],
        },
    },
]

WSGI_APPLICATION = "senextrader.wsgi.application"
ASGI_APPLICATION = "senextrader.asgi.application"

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
# Market-hours aware scheduling: More frequent during market hours (9:30 AM - 4:00 PM ET),
# less frequent during off-hours to reduce API load while maintaining responsiveness.
CELERY_BEAT_SCHEDULE = {
    # =========================================================================
    # MARKET HOURS TASKS (9:30 AM - 4:00 PM ET, Mon-Fri)
    # =========================================================================
    # Monitor open orders - detect fills, rejections quickly during trading
    "monitor-open-orders-market": {
        "task": "trading.tasks.monitor_open_orders",
        "schedule": crontab(hour="9-15", minute="*/5", day_of_week="mon-fri"),  # Every 5 min
    },
    # Batch sync - position/order reconciliation during active trading
    "batch-sync-data-market": {
        "task": "trading.tasks.batch_sync_data_task",
        "schedule": crontab(hour="9-15", minute="*/10", day_of_week="mon-fri"),  # Every 10 min
    },
    # Monitor DTE positions - check for expiration closures
    "monitor-dte-positions-market": {
        "task": "trading.tasks.monitor_positions_for_dte_closure",
        "schedule": crontab(hour="9-15", minute="*/10", day_of_week="mon-fri"),  # Every 10 min
    },
    # Persist Greeks from streaming cache
    "persist-greeks-from-cache-market": {
        "task": "trading.tasks.persist_greeks_from_cache",
        "schedule": crontab(hour="9-15", minute="*/5", day_of_week="mon-fri"),  # Every 5 min
    },
    # =========================================================================
    # OFF-HOURS TASKS (4:00 PM - 9:30 AM ET, Mon-Fri)
    # =========================================================================
    # Monitor open orders - less frequent, catches GTC orders
    "monitor-open-orders-offhours": {
        "task": "trading.tasks.monitor_open_orders",
        "schedule": crontab(hour="0-8,16-23", minute="0,30", day_of_week="mon-fri"),  # Every 30 min
    },
    # Batch sync - hourly reconciliation off-hours
    "batch-sync-data-offhours": {
        "task": "trading.tasks.batch_sync_data_task",
        "schedule": crontab(hour="0-8,16-23", minute="0", day_of_week="mon-fri"),  # Hourly
    },
    # Monitor DTE positions - less urgent off-hours
    "monitor-dte-positions-offhours": {
        "task": "trading.tasks.monitor_positions_for_dte_closure",
        "schedule": crontab(hour="0-8,16-23", minute="0,30", day_of_week="mon-fri"),  # Every 30 min
    },
    # Persist Greeks - less frequent when market closed
    "persist-greeks-from-cache-offhours": {
        "task": "trading.tasks.persist_greeks_from_cache",
        "schedule": crontab(hour="0-8,16-23", minute="0,30", day_of_week="mon-fri"),  # Every 30 min
    },
    # =========================================================================
    # SCHEDULED TASKS (specific times)
    # =========================================================================
    "automated-daily-trade-cycle": {
        "task": "trading.tasks.automated_daily_trade_cycle",
        # Every 5 minutes from 10:00 AM to 2:55 PM ET on weekdays
        # Runs at: 10:00, 10:05, 10:10, ..., 14:50, 14:55 (60 times/day)
        # Each cycle: cancels stale orders, generates fresh suggestion, submits new order
        # Only opens ONE position per day (checks for existing open positions)
        "schedule": crontab(hour="10-14", minute="*/5", day_of_week="mon-fri"),
    },
    "generate-and-email-daily-suggestions": {
        "task": "trading.tasks.generate_and_email_daily_suggestions",
        "schedule": crontab(hour=10, minute=0, day_of_week="mon-fri"),  # 10:00 AM ET on weekdays
    },
    "generate-trading-summary": {
        "task": "trading.tasks.generate_trading_summary",
        "schedule": crontab(hour=16, minute=30, day_of_week="mon-fri"),  # 4:30 PM ET
    },
    "ensure-historical-data": {
        "task": "trading.tasks.ensure_historical_data",
        "schedule": crontab(hour=17, minute=30, day_of_week="mon-fri"),  # 5:30 PM ET weekdays
    },
    # =========================================================================
    # MAINTENANCE TASKS (daily/hourly, any time)
    # =========================================================================
    "cleanup-inactive-streamers": {
        "task": "streaming.tasks.cleanup_inactive_streamers",
        "schedule": 3600.0,  # Every hour
    },
    "cleanup-old-records": {
        "task": "trading.tasks.cleanup_old_records_task",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3:00 AM ET (trades + suggestions)
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
# Format: (symbol, description)
DEFAULT_WATCHLIST_SYMBOLS = [
    ("SPY", "SPDR S&P 500 ETF Trust"),
    ("QQQ", "Invesco QQQ Trust"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("NVDA", "NVIDIA Corporation"),
    ("GOOGL", "Alphabet Inc."),
    ("AMZN", "Amazon.com, Inc."),
    ("META", "Meta Platforms, Inc."),
    ("TSLA", "Tesla, Inc."),
    ("JPM", "JPMorgan Chase & Co."),
    ("V", "Visa Inc."),
    ("WMT", "Walmart Inc."),
    ("AMD", "Advanced Micro Devices, Inc."),
    ("NFLX", "Netflix, Inc."),
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
