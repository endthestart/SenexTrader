"""
Celery tasks for the streaming application.
"""

from celery import shared_task

from services.core.logging import get_logger

logger = get_logger(__name__)


@shared_task
def cleanup_inactive_streamers():
    """
    Periodically cleans up inactive UserStreamManager instances to prevent memory leaks.
    """
    from services.core.utils.async_utils import run_async
    from streaming.services.stream_manager import GlobalStreamManager

    logger.info("Running cleanup of inactive streamers...")
    result = run_async(GlobalStreamManager.cleanup_inactive_managers())
    logger.info("Cleanup of inactive streamers complete.")
    return result
