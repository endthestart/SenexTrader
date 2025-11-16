"""
Task monitoring decorator for Celery tasks.

Tracks execution metrics, success rates, and durations for all background tasks.
"""

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from services.core.logging import get_logger

logger = get_logger(__name__)


def monitor_task(func: Callable) -> Callable:
    """
    Decorator to monitor Celery task execution.

    Tracks:
    - Task name
    - Execution duration
    - Success/failure status
    - Error details (if failed)

    Example:
        @shared_task
        @monitor_task
        def my_task():
            return "result"
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        task_name = func.__name__
        start_time = time.time()

        try:
            logger.info(f"Task started: {task_name}")
            result = func(*args, **kwargs)
            duration = time.time() - start_time

            logger.info(
                f"Task completed: {task_name}",
                extra={
                    "task_name": task_name,
                    "duration": duration,
                    "status": "success",
                },
            )

            return result

        except Exception as e:
            duration = time.time() - start_time

            logger.error(
                f"Task failed: {task_name}",
                extra={
                    "task_name": task_name,
                    "duration": duration,
                    "status": "failure",
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )

            raise

    return wrapper
