import logging
import os
import sys

from django.conf import settings

from celery import Celery
from celery.signals import setup_logging


def _resolve_default_settings_module() -> str:
    """Return the default settings module respecting ENVIRONMENT."""
    env = os.environ.get("ENVIRONMENT")
    if env in ("production", "staging"):
        return f"senex_trader.settings.{env}"
    return "senex_trader.settings.development"


# Ensure Celery loads the same settings module as manage.py/asgi.py.
if (
    not os.environ.get("DJANGO_SETTINGS_MODULE")
    or os.environ["DJANGO_SETTINGS_MODULE"] == "senex_trader.settings"
):
    os.environ["DJANGO_SETTINGS_MODULE"] = _resolve_default_settings_module()

# Don't call django.setup() here - it causes circular imports when Django is
# already setting up. Celery workers handle their own Django setup.

app = Celery("senex_trader")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure Celery settings
app.conf.update(
    # Redis broker and result backend (separate databases from Django cache
    # and Channels)
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/2"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/3"),
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=False,  # CRITICAL: False so crontabs use America/New_York time, not UTC
    # Task routing for future trading automation
    task_routes={
        "accounts.tasks.*": {"queue": "accounts"},
        "trading.tasks.*": {"queue": "trading"},
    },
    # Worker configuration
    worker_prefetch_multiplier=4,  # Standard prefetch for trading tasks
    # Restart workers periodically to prevent memory leaks
    worker_max_tasks_per_child=100,
    # Results settings
    result_expires=3600,  # Results expire after 1 hour
    result_compression="gzip",
    # Trading-specific settings
    task_track_started=True,  # Track when tasks start
    task_acks_late=True,  # Acknowledge tasks only after completion
    # NOTE: Beat schedule is defined in settings/base.py as CELERY_BEAT_SCHEDULE
)

# Auto-discover tasks in all installed apps
# This will find all tasks.py modules in INSTALLED_APPS
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Configure Celery to log to console with our application's logging format."""
    # Get the root logger
    root_logger = logging.getLogger()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create formatter matching our application logs
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)-30s PID:%(process)d TID:%(thread)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)

    # Add handler to root logger if not already present
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(console_handler)

    # Set level for specific loggers
    logging.getLogger("trading").setLevel(logging.INFO)
    logging.getLogger("services").setLevel(logging.INFO)
    logging.getLogger("celery").setLevel(logging.INFO)


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery configuration."""
    print(f"Request: {self.request!r}")
