"""Senex Trader package initialization."""

from .celery import app as celery_app

__all__ = ("celery_app",)


def validate_redis_connection():
    """
    Validate Redis connection at startup.

    Only runs in production environments to avoid disrupting development.
    """
    import os
    import sys

    if not os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith("production"):
        return

    try:
        from django.core.cache import cache
        from django.core.exceptions import ImproperlyConfigured

        test_key = "startup_health_check"
        test_value = "ok"

        cache.set(test_key, test_value, timeout=10)
        result = cache.get(test_key)

        if result != test_value:
            raise ImproperlyConfigured("Redis write/read test failed")

        cache.delete(test_key)

        print("[OK] Redis connection validated successfully")

    except Exception as e:
        print(
            f"FATAL: Redis connection failed: {e}\n"
            f"Please check REDIS_URL environment variable and Redis server status.",
            file=sys.stderr,
        )
        sys.exit(1)


validate_redis_connection()
