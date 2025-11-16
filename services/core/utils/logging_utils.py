"""
Centralized logging utilities for DRY code
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_error_with_context(
    operation: str, exception: Exception, context: dict[str, Any] | None = None
):
    """Log an exception with context."""
    error_msg = f"Error in {operation}: {exception!s}"
    logger.error(
        error_msg,
        extra={
            **(context or {}),
            "operation": operation,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
        },
    )
