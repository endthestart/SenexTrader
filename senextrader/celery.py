import logging
import os
import sys

from celery import Celery
from celery.signals import setup_logging


def _resolve_default_settings_module() -> str:
    """Return the default settings module respecting ENVIRONMENT."""
    env = os.environ.get("ENVIRONMENT")
    if env in ("production", "staging"):
        return f"senextrader.settings.{env}"
    return "senextrader.settings.development"


# Ensure Celery loads the correct settings module BEFORE importing Django settings
if (
    not os.environ.get("DJANGO_SETTINGS_MODULE")
    or os.environ["DJANGO_SETTINGS_MODULE"] == "senextrader.settings"
):
    os.environ["DJANGO_SETTINGS_MODULE"] = _resolve_default_settings_module()

# Import Django settings AFTER setting DJANGO_SETTINGS_MODULE
from django.conf import settings  # noqa: E402

app = Celery("senextrader")
app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/2"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/3"),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=False,  # Required for crontabs to use America/New_York time
    task_routes={
        "accounts.tasks.*": {"queue": "accounts"},
        "trading.tasks.*": {"queue": "trading"},
    },
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=100,
    result_expires=3600,
    result_compression="gzip",
    task_track_started=True,
    task_acks_late=True,
)

app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Configure Celery logging to match application format."""
    root_logger = logging.getLogger()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)-30s "
        "PID:%(process)d TID:%(thread)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(console_handler)

    logging.getLogger("trading").setLevel(logging.INFO)
    logging.getLogger("services").setLevel(logging.INFO)
    logging.getLogger("celery").setLevel(logging.INFO)


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery configuration."""
    print(f"Request: {self.request!r}")
