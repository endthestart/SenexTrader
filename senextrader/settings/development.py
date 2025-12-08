"""
Development settings for Senex Trader application.

This configuration is optimized for local development with debugging enabled
and relaxed security for easier development.
"""

import contextlib
import logging.config
import os
import sys

# Ensure encrypted fields work in local/test environments even if developers
# forget to provision a FIELD_ENCRYPTION_KEY. Production/staging must still set
# this explicitly via environment variables.
if "FIELD_ENCRYPTION_KEY" not in os.environ:
    DEFAULT_DEV_FIELD_ENCRYPTION_KEY = os.environ.get(
        "DEFAULT_DEV_FIELD_ENCRYPTION_KEY",
        "6mWFB6OGHm-9siUMz2CxRV-nWZnoki5qt7Ya0sTT82o=",
    )
    os.environ["FIELD_ENCRYPTION_KEY"] = DEFAULT_DEV_FIELD_ENCRYPTION_KEY

from .base import *  # noqa: F403

# ================================================================================
# DEVELOPMENT SETTINGS
# ================================================================================

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "SECRET_KEY", "django-insecure-5x6aa=dy*)!lf1n+spvwzkmu*321$5dg=4+#=p@7=p!0bt@4w%"
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes", "on")

# Hosts and CSRF trusted origins (configurable via env)
_default_hosts = "127.0.0.1,localhost,testserver"
_allowed_hosts_raw = os.environ.get("ALLOWED_HOSTS")
if _allowed_hosts_raw and _allowed_hosts_raw.strip():
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
else:
    ALLOWED_HOSTS = [h.strip() for h in _default_hosts.split(",") if h.strip()]

# ================================================================================
# DATABASE CONFIGURATION (DEVELOPMENT)
# ================================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ================================================================================
# CACHE CONFIGURATION (DEVELOPMENT)
# ================================================================================

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "senex_cache",
        "VERSION": 1,
        "TIMEOUT": 300,
    }
}

# ================================================================================
# CELERY CONFIGURATION (DEVELOPMENT)
# ================================================================================

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/2")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/3")

# Development Celery settings
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50

# Task time limits (more generous for development)
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 600

# Task routing for future trading automation
CELERY_TASK_ROUTES = {
    "accounts.tasks.*": {"queue": "accounts"},
    "trading.tasks.*": {"queue": "trading"},
}

# ================================================================================
# CHANNELS CONFIGURATION (DEVELOPMENT)
# ================================================================================

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# ================================================================================
# DEVELOPMENT LOGGING
# ================================================================================

from services.core.logging import get_development_logging  # noqa: E402

LOGGING = get_development_logging()
logging.config.dictConfig(LOGGING)

# ================================================================================
# EMAIL BACKEND (DEVELOPMENT)
# ================================================================================

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ================================================================================
# STATIC FILES (DEVELOPMENT)
# ================================================================================

STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ================================================================================
# THIRD-PARTY API CONFIGURATION (DEVELOPMENT)
# ================================================================================

# TastyTrade API (sandbox/development)
TASTYTRADE_CLIENT_ID = os.environ.get("TASTYTRADE_CLIENT_ID")
TASTYTRADE_CLIENT_SECRET = os.environ.get("TASTYTRADE_CLIENT_SECRET")

# Default True: prevents accidental real trades in development
TASTYTRADE_DRY_RUN = os.environ.get("TASTYTRADE_DRY_RUN", "True").lower() in (
    "true",
    "1",
    "yes",
    "on",
)


# ================================================================================
# RATE LIMITING (DEVELOPMENT)
# ================================================================================

# Relaxed rate limits for development to prevent blocking during testing
ACCOUNT_API_RATE_LIMIT_MAX = 10  # 10 requests per window (vs 1 in production)
ACCOUNT_API_RATE_LIMIT_WINDOW = 60  # 60 seconds

OPTIONS_API_RATE_LIMIT_MAX = 20  # 20 requests per window
OPTIONS_API_RATE_LIMIT_WINDOW = 60  # 60 seconds

DXFEED_API_RATE_LIMIT_MAX = 15  # 15 requests per window
DXFEED_API_RATE_LIMIT_WINDOW = 60  # 60 seconds

STRATEGY_GENERATION_RATE_LIMIT_MAX = 50  # 50 requests per window
STRATEGY_GENERATION_RATE_LIMIT_WINDOW = 300  # 5 minutes

# ================================================================================
# DEVELOPMENT TOOLS
# ================================================================================

# Add django-extensions if available
with contextlib.suppress(ImportError):
    INSTALLED_APPS.append("django_extensions")

# Django Debug Toolbar (if available)
if DEBUG:
    try:
        import debug_toolbar  # noqa: F401

        INSTALLED_APPS.append("debug_toolbar")
        MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
        INTERNAL_IPS = ["127.0.0.1", "localhost"]
    except ImportError:
        # Debug toolbar not installed, skip it
        pass

# ================================================================================
# WEBSOCKET CONFIGURATION (DEVELOPMENT)
# ================================================================================

# Production WebSocket origin validation
WS_ALLOWED_ORIGINS = os.environ.get("WS_ALLOWED_ORIGINS", "localhost:8000,127.0.0.1:8000").split(
    ","
)

# Print settings info only when running the actual server process, not the reloader
if ("runserver" in sys.argv or "test" in sys.argv) and os.environ.get("RUN_MAIN") == "true":
    print("Development settings loaded")
    print(f"Database: SQLite at {DATABASES['default']['NAME']}")
    print(f"Redis: {REDIS_URL}")
    print(f"Debug mode: {DEBUG}")
    print(f"Allowed hosts: {', '.join(ALLOWED_HOSTS)}")
