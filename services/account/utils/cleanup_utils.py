"""
Utilities for database cleanup tasks.

Provides reusable cleanup logic to prevent code duplication across Celery tasks.
"""

from datetime import timedelta
from typing import Any, Literal, TypeVar

from django.db.models import Model
from django.utils import timezone

from services.core.logging import get_logger

logger = get_logger(__name__)

# TypeVar for Django Model subclasses to satisfy MyPy
TModel = TypeVar("TModel", bound=Model)


def cleanup_old_records[TModel: Model](
    model: type[TModel],
    days: int,
    statuses: list[str],
    date_field: Literal["created_at", "updated_at"] = "created_at",
    record_type: str = "records",
) -> dict[str, Any]:
    """
    Delete old records matching criteria to prevent database bloat.

    Args:
        model: Django model class to clean up
        days: Number of days old before deletion
        statuses: List of status values to match
        date_field: Which date field to use for age comparison
        record_type: Human-readable name for logging (e.g., "trades", "suggestions")

    Returns:
        Dict with status and deleted count: {"status": "success", "deleted": 123}

    Example:
        cleanup_old_records(
            model=Trade,
            days=90,
            statuses=["cancelled", "rejected", "expired"],
            date_field="updated_at",
            record_type="trades"
        )
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=days)

        # Build queryset with dynamic date field
        filter_kwargs = {
            "status__in": statuses,
            f"{date_field}__lt": cutoff_date,
        }
        old_records = model.objects.filter(**filter_kwargs)

        count = old_records.count()

        if count > 0:
            old_records.delete()
            logger.info(
                f"Deleted {count} old {record_type}",
                extra={
                    "record_type": record_type,
                    "deleted_count": count,
                    "days": days,
                    "statuses": statuses,
                },
            )
        else:
            logger.debug(f"No old {record_type} to delete")

        return {"status": "success", "deleted": count}

    except Exception as e:
        logger.error(
            f"Error cleaning up {record_type}: {e}",
            extra={
                "record_type": record_type,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return {"status": "error", "message": str(e)}
