"""
Production settings for Senex Trader application.

This configuration is optimized for production deployment with security,
performance, and reliability considerations.

Secrets Management:
    Secrets can be loaded from HashiCorp Vault (recommended) or environment variables.

    To use Vault, set these environment variables:
        VAULT_ADDR: Vault server URL (e.g., https://vault.example.com)
        VAULT_TOKEN: Authentication token (simple setup)
        OR
        VAULT_ROLE_ID + VAULT_SECRET_ID: AppRole credentials (production)

    If Vault is not configured, secrets fall back to environment variables.
"""

import copy
import os
from pathlib import Path

from services.core.logging import LOGGING as BASE_LOGGING  # noqa: E402

from .base import *  # noqa: F403

# ================================================================================
# SECRETS MANAGEMENT (Vault or Environment Variables)
# ================================================================================

# Check if Vault is configured
VAULT_ENABLED = bool(os.environ.get("VAULT_ADDR"))

if VAULT_ENABLED:
    from services.core.vault import VaultError, get_secret

    print("Vault configured - loading secrets from HashiCorp Vault")
    try:
        # Load all secrets from Vault (cached after first call)
        SECRET_KEY = get_secret("secret_key")
        FIELD_ENCRYPTION_KEY = get_secret("field_encryption_key")
        _db_password = get_secret("db_password")
        _db_user = get_secret("db_user", default=os.environ.get("DB_USER", "senex_user"))
        _tastytrade_client_id = get_secret("tastytrade_client_id")
        _tastytrade_client_secret = get_secret("tastytrade_client_secret")
        _email_host_user = get_secret("email_host_user", default="")
        _email_host_password = get_secret("email_host_password", default="")
        print("Secrets loaded from Vault successfully")
    except VaultError as e:
        raise ValueError(f"Failed to load secrets from Vault: {e}") from e
else:
    print("Vault not configured - using environment variables for secrets")
    # Fall back to environment variables
    SECRET_KEY = os.environ.get("SECRET_KEY")
    _db_password = os.environ.get("DB_PASSWORD")
    _db_user = os.environ.get("DB_USER", "senex_user")
    _tastytrade_client_id = os.environ.get("TASTYTRADE_CLIENT_ID")
    _tastytrade_client_secret = os.environ.get("TASTYTRADE_CLIENT_SECRET")
    _email_host_user = os.environ.get("EMAIL_HOST_USER", "")
    _email_host_password = os.environ.get("EMAIL_HOST_PASSWORD", "")

# ================================================================================
# PRODUCTION SECURITY SETTINGS
# ================================================================================

# Validate required secrets
if not SECRET_KEY:
    raise ValueError("SECRET_KEY must be set (via Vault or SECRET_KEY env var)")

# Encryption key check (FIELD_ENCRYPTION_KEY loaded in base.py if not from Vault)
if not FIELD_ENCRYPTION_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "FIELD_ENCRYPTION_KEY must be set in production. "
        "Configure Vault or set FIELD_ENCRYPTION_KEY env var. "
        "Generate with: python -c 'from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())'"
    )

# Security settings
DEBUG = False
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()
] + [
    "localhost",
    "127.0.0.1",
]  # Add localhost for health checks
# Django will reject requests if ALLOWED_HOSTS is empty - no need for import-time validation

# CSRF trusted origins for HTTPS
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS if host and host not in ["localhost", "127.0.0.1"]
]

# WebSocket origin validation
WS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("WS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# CSRF and session security
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# Proxy SSL header (required for reverse proxy setups)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() == "true"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# ================================================================================
# CONTAINER CONFIGURATION
# ================================================================================

# Detect if running in containerized environment
CONTAINER_MODE = os.environ.get("CONTAINER_MODE", "false").lower() == "true"

# ================================================================================
# DATABASE CONFIGURATION
# ================================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "senextrader"),
        "USER": _db_user if VAULT_ENABLED else os.environ.get("DB_USER", "senex_user"),
        "PASSWORD": _db_password if VAULT_ENABLED else os.environ.get("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "OPTIONS": {
            "sslmode": "disable" if CONTAINER_MODE else "require",
            "connect_timeout": 10,  # Fail fast on connection issues
            "options": "-c statement_timeout=30000",  # 30s query timeout
        },
        "CONN_MAX_AGE": 60,  # Reduced from 600 to prevent connection exhaustion
    }
}

if not DATABASES["default"]["PASSWORD"]:
    raise ValueError("DB_PASSWORD must be set (via Vault or DB_PASSWORD env var)")

# Database Connection Pool Configuration
DATABASE_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "2"))
DATABASE_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "20"))

# Note: For production, consider using PgBouncer for connection pooling
# PgBouncer configuration in deployment:
#   pool_mode = transaction
#   max_client_conn = 200
#   default_pool_size = 20

# ================================================================================
# CACHE CONFIGURATION (REDIS)
# ================================================================================

REDIS_URL = os.environ.get("REDIS_URL")
if not REDIS_URL:
    raise ValueError("REDIS_URL environment variable must be set in production")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "senex_cache",
        "VERSION": 1,
        "TIMEOUT": 300,  # 5 minutes default timeout
    }
}

# ================================================================================
# CELERY CONFIGURATION (PRODUCTION)
# ================================================================================

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND")

if not CELERY_BROKER_URL or not CELERY_RESULT_BACKEND:
    raise ValueError("CELERY_BROKER_URL and CELERY_RESULT_BACKEND must be set in production")

# Production Celery settings
CELERY_TASK_ALWAYS_EAGER = False
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 100
CELERY_WORKER_DISABLE_RATE_LIMITS = False

# Task time limits for production
# P1.2: Reduced from 30min/1hr to 5min/10min to prevent hung tasks blocking workers
# Long-running tasks (position sync, etc) have per-task overrides in tasks.py
CELERY_TASK_SOFT_TIME_LIMIT = 300  # 5 minutes (default)
CELERY_TASK_TIME_LIMIT = 600  # 10 minutes (hard limit)

# Task routing for production automation
CELERY_TASK_ROUTES = {
    "accounts.tasks.*": {"queue": "accounts"},
    "trading.tasks.*": {"queue": "trading"},
    "services.tasks.*": {"queue": "services"},
}

# ================================================================================
# CHANNELS CONFIGURATION (WEBSOCKETS)
# ================================================================================

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("CHANNELS_REDIS_URL", "redis://redis:6379/1")],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# Production WebSocket settings
ASGI_APPLICATION = "senextrader.asgi.application"

# ================================================================================
# STATIC AND MEDIA FILES
# ================================================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Use WhiteNoise for static files in production
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ================================================================================
# LOGGING CONFIGURATION (PRODUCTION)
# ================================================================================

LOGGING = copy.deepcopy(BASE_LOGGING)

if CONTAINER_MODE:
    # Container mode: Log to stdout/stderr only (Docker/Kubernetes best practice)
    LOGGING["handlers"]["console"]["formatter"] = "console_journald"

    LOGGING["handlers"]["mail_admins"] = {
        "level": "ERROR",
        "class": "django.utils.log.AdminEmailHandler",
        "include_html": True,
        "filters": ["sensitive_data"],
    }

    LOGGING["loggers"]["django"]["handlers"] = ["console", "mail_admins"]
    LOGGING["loggers"]["django.request"] = {
        "handlers": ["console", "mail_admins"],
        "level": "ERROR",
        "propagate": False,
    }
    LOGGING["loggers"]["services"]["handlers"] = ["console", "mail_admins"]
    LOGGING["loggers"]["streaming"]["handlers"] = ["console", "mail_admins"]
    LOGGING["loggers"]["trading"] = {
        "handlers": ["console", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["accounts"] = {
        "handlers": ["console", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["celery"] = {
        "handlers": ["console", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["celery.task"] = {
        "handlers": ["console", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    # Silence noisy third-party libraries
    LOGGING["loggers"]["tastytrade"] = {
        "handlers": ["console"],
        "level": "WARNING",
        "propagate": False,
    }
    LOGGING["loggers"]["websockets"] = {
        "handlers": ["console"],
        "level": "WARNING",
        "propagate": False,
    }
    LOGGING["loggers"]["websockets.client"] = {
        "handlers": ["console"],
        "level": "ERROR",
        "propagate": False,
    }
    LOGGING["root"]["handlers"] = ["console", "mail_admins"]
    LOGGING["root"]["level"] = "INFO"
else:
    # Bare-metal mode: Log to files in /var/log/senextrader
    PRODUCTION_LOG_DIR = Path("/var/log/senextrader")
    PRODUCTION_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Override file paths for production
    LOGGING["handlers"]["file_structured"]["filename"] = "/var/log/senextrader/application.log"
    LOGGING["handlers"]["file_structured"]["maxBytes"] = 50 * 1024 * 1024
    LOGGING["handlers"]["file_structured"]["backupCount"] = 10

    LOGGING["handlers"]["error_file"]["filename"] = "/var/log/senextrader/errors.log"
    LOGGING["handlers"]["error_file"]["maxBytes"] = 50 * 1024 * 1024
    LOGGING["handlers"]["error_file"]["backupCount"] = 10

    LOGGING["handlers"]["trading_file"]["filename"] = "/var/log/senextrader/trading.log"
    LOGGING["handlers"]["trading_file"]["maxBytes"] = 100 * 1024 * 1024
    LOGGING["handlers"]["trading_file"]["backupCount"] = 20

    LOGGING["handlers"]["security_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": "/var/log/senextrader/security.log",
        "maxBytes": 50 * 1024 * 1024,
        "backupCount": 10,
        "formatter": "structured",
        "level": "WARNING",
        "filters": ["sensitive_data"],
    }

    LOGGING["handlers"]["mail_admins"] = {
        "level": "ERROR",
        "class": "django.utils.log.AdminEmailHandler",
        "include_html": True,
        "filters": ["sensitive_data"],
    }

    LOGGING["loggers"]["django.security"] = {
        "handlers": ["security_file", "error_file", "mail_admins"],
        "level": "WARNING",
        "propagate": False,
    }

    LOGGING["loggers"]["django"]["handlers"] = ["file_structured", "error_file", "mail_admins"]
    LOGGING["loggers"]["django.request"] = {
        "handlers": ["file_structured", "error_file", "mail_admins"],
        "level": "ERROR",
        "propagate": False,
    }
    LOGGING["loggers"]["services"]["handlers"] = ["file_structured", "error_file", "mail_admins"]
    LOGGING["loggers"]["streaming"]["handlers"] = ["file_structured", "error_file", "mail_admins"]
    LOGGING["loggers"]["trading"] = {
        "handlers": ["file_structured", "trading_file", "error_file", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["accounts"] = {
        "handlers": ["file_structured", "error_file", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }

    LOGGING["loggers"]["celery"] = {
        "handlers": ["file_structured", "error_file", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["celery.task"] = {
        "handlers": ["file_structured", "error_file", "mail_admins"],
        "level": "INFO",
        "propagate": False,
    }

    LOGGING["root"]["handlers"] = ["file_structured", "error_file", "mail_admins"]
    LOGGING["root"]["level"] = "WARNING"

# ================================================================================
# PERFORMANCE OPTIMIZATIONS
# ================================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email backend for production (configure based on your email service)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = _email_host_user if VAULT_ENABLED else os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = _email_host_password if VAULT_ENABLED else os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.com")

# ================================================================================
# ADMIN ERROR NOTIFICATIONS
# ================================================================================

# Admins who receive error emails (500s, exceptions, critical errors)
ADMINS = [
    ("Michael Anderson", os.environ.get("ADMIN_EMAIL", "admin@example.com")),
]

# Email address for server error emails
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", "errors@example.com")

# ================================================================================
# RATE LIMITING CONFIGURATION
# ================================================================================

# Production rate limits (more restrictive)
ACCOUNT_API_RATE_LIMIT_MAX = int(os.environ.get("ACCOUNT_API_RATE_LIMIT_MAX", "5"))
ACCOUNT_API_RATE_LIMIT_WINDOW = int(
    os.environ.get("ACCOUNT_API_RATE_LIMIT_WINDOW", "300")
)  # 5 minutes

OPTIONS_API_RATE_LIMIT_MAX = int(os.environ.get("OPTIONS_API_RATE_LIMIT_MAX", "50"))
OPTIONS_API_RATE_LIMIT_WINDOW = int(os.environ.get("OPTIONS_API_RATE_LIMIT_WINDOW", "300"))

STRATEGY_GENERATION_RATE_LIMIT_MAX = int(
    os.environ.get("STRATEGY_GENERATION_RATE_LIMIT_MAX", "100")
)
STRATEGY_GENERATION_RATE_LIMIT_WINDOW = int(
    os.environ.get("STRATEGY_GENERATION_RATE_LIMIT_WINDOW", "3600")
)  # 1 hour

ORDER_EXECUTION_RATE_LIMIT_MAX = int(os.environ.get("ORDER_EXECUTION_RATE_LIMIT_MAX", "50"))
ORDER_EXECUTION_RATE_LIMIT_WINDOW = int(os.environ.get("ORDER_EXECUTION_RATE_LIMIT_WINDOW", "300"))

# ================================================================================
# CIRCUIT BREAKER CONFIGURATION
# ================================================================================

CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.environ.get("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "10"))
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = int(os.environ.get("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "120"))
CIRCUIT_BREAKER_SUCCESS_THRESHOLD = int(os.environ.get("CIRCUIT_BREAKER_SUCCESS_THRESHOLD", "5"))

# ================================================================================
# MONITORING AND METRICS
# ================================================================================

STREAMING_METRICS_TTL = int(os.environ.get("STREAMING_METRICS_TTL", "7200"))  # 2 hours
STREAMING_METRICS_WINDOW = int(os.environ.get("STREAMING_METRICS_WINDOW", "600"))  # 10 minutes

# ================================================================================
# STREAMING CONFIGURATION (PRODUCTION)
# ================================================================================

STREAMING_CONFIG = {
    "IDLE_TIMEOUT_MINUTES": int(os.environ.get("STREAMING_IDLE_TIMEOUT_MINUTES", "10")),
    "MAX_SESSION_HOURS": int(os.environ.get("STREAMING_MAX_SESSION_HOURS", "4")),
    "HEARTBEAT_INTERVAL": int(os.environ.get("STREAMING_HEARTBEAT_INTERVAL", "30")),
    "LEASE_TTL_SECONDS": int(os.environ.get("STREAMING_LEASE_TTL_SECONDS", "180")),
    "CLEANUP_INTERVAL": int(os.environ.get("STREAMING_CLEANUP_INTERVAL", "60")),
}

# ================================================================================
# THIRD-PARTY API CONFIGURATION
# ================================================================================

# Validate OAuth configuration (use Vault secrets if available)
if VAULT_ENABLED:
    TASTYTRADE_OAUTH_CONFIG["CLIENT_ID"] = _tastytrade_client_id
    TASTYTRADE_OAUTH_CONFIG["CLIENT_SECRET"] = _tastytrade_client_secret

if not TASTYTRADE_OAUTH_CONFIG["CLIENT_ID"] or not TASTYTRADE_OAUTH_CONFIG["CLIENT_SECRET"]:
    raise ValueError("TastyTrade OAuth configuration incomplete in production")

TASTYTRADE_DRY_RUN = False
if os.environ.get("TASTYTRADE_DRY_RUN", "False").lower() in ("true", "1", "yes", "on"):
    raise ValueError("TASTYTRADE_DRY_RUN cannot be enabled in production")

# ================================================================================
# ERROR REPORTING (Optional - configure based on your monitoring service)
# ================================================================================

# Example: Sentry configuration
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(auto_enabling=True),
            CeleryIntegration(auto_enabling=True),
        ],
        traces_sample_rate=0.1,  # Adjust based on traffic
        send_default_pii=False,
        environment="production",
    )

# ================================================================================
# BACKUP AND RECOVERY
# ================================================================================

# Database backup settings (implement with your backup strategy)
DATABASE_BACKUP_RETENTION_DAYS = int(os.environ.get("DATABASE_BACKUP_RETENTION_DAYS", "30"))
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))

# ================================================================================
# HEALTH CHECK CONFIGURATION
# ================================================================================

# Health check endpoints for load balancer
HEALTH_CHECK_BASIC_TIMEOUT = int(os.environ.get("HEALTH_CHECK_BASIC_TIMEOUT", "5"))
HEALTH_CHECK_DETAILED_TIMEOUT = int(os.environ.get("HEALTH_CHECK_DETAILED_TIMEOUT", "30"))

print("Production settings loaded successfully")
print(f"Secrets: {'Vault' if VAULT_ENABLED else 'Environment variables'}")
print(f"Configured for hosts: {', '.join(ALLOWED_HOSTS)}")
print(f"Security: SSL redirect={SECURE_SSL_REDIRECT}, HSTS={SECURE_HSTS_SECONDS}s")
print(f"Database: {DATABASES['default']['HOST']}:{DATABASES['default']['PORT']}")
print(f"Redis: {REDIS_URL}")
print(f"Celery: {len(CELERY_TASK_ROUTES)} task routes configured")
