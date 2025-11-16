"""
Greeks aggregation utilities for single-table time-series data compression.

Single table approach (KISS principle):
- All resolutions stored in HistoricalGreeks table
- Timestamp precision indicates resolution (1s, 1min, 5min)
- Aggregation replaces high-res data with low-res summaries
- Never delete old data (indefinite retention with progressive compression)

Strategy:
- 0-30 days: 1-second resolution (raw streaming data)
- 30 days - 1 year: 1-minute resolution (aggregated)
- 1+ years: 5-minute resolution (aggregated)
"""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from services.core.logging import get_logger
from trading.models import HistoricalGreeks

logger = get_logger(__name__)


def aggregate_greeks_to_1min() -> dict[str, Any]:
    """
    Aggregate HistoricalGreeks older than 30 days to 1-minute resolution.

    Process:
    1. Find records 30+ days old
    2. Group by (option_symbol, minute)
    3. Take last value in each minute (representative sample)
    4. Replace with 1-minute aggregated records
    5. Delete original 1-second records

    Returns:
        Dict with status and statistics
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=30)

        # Get distinct option symbols that need aggregation
        symbols_to_aggregate = list(
            HistoricalGreeks.objects.filter(timestamp__lt=cutoff_date)
            .values_list("option_symbol", flat=True)
            .distinct()
        )

        total_aggregated = 0
        total_deleted = 0

        for option_symbol in symbols_to_aggregate:
            with transaction.atomic():
                # Get all records for this symbol older than 30 days
                old_records = HistoricalGreeks.objects.filter(
                    option_symbol=option_symbol, timestamp__lt=cutoff_date
                ).order_by("timestamp")

                # Group by minute and take the last record in each minute
                minute_records = {}
                for record in old_records.iterator():
                    # Truncate to minute
                    record_minute = record.timestamp.replace(second=0, microsecond=0)
                    # Keep last record for each minute (overwrites previous)
                    minute_records[record_minute] = record

                # Create new 1-minute resolution records
                for minute_ts, last_record in minute_records.items():
                    HistoricalGreeks.objects.update_or_create(
                        option_symbol=last_record.option_symbol,
                        timestamp=minute_ts,
                        defaults={
                            "underlying_symbol": last_record.underlying_symbol,
                            "delta": last_record.delta,
                            "gamma": last_record.gamma,
                            "theta": last_record.theta,
                            "vega": last_record.vega,
                            "rho": last_record.rho,
                            "implied_volatility": last_record.implied_volatility,
                            "strike": last_record.strike,
                            "expiration_date": last_record.expiration_date,
                            "option_type": last_record.option_type,
                        },
                    )
                    total_aggregated += 1

                # Delete original 1-second records
                deleted_count, _ = old_records.delete()
                total_deleted += deleted_count

        logger.info(
            f"Aggregated to 1-min: {total_aggregated} minutes from {total_deleted} second-level records",
            extra={
                "aggregated_count": total_aggregated,
                "deleted_count": total_deleted,
                "symbols_processed": len(symbols_to_aggregate),
            },
        )

        return {
            "status": "success",
            "aggregated": total_aggregated,
            "deleted": total_deleted,
            "symbols_processed": len(symbols_to_aggregate),
        }

    except Exception as e:
        logger.error(f"Error aggregating Greeks to 1min: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


def aggregate_greeks_to_5min() -> dict[str, Any]:
    """
    Aggregate HistoricalGreeks older than 1 year to 5-minute resolution.

    Process:
    1. Find 1-min records 1+ years old
    2. Group by (option_symbol, 5-minute interval)
    3. Take last value in each 5-minute interval
    4. Replace with 5-minute aggregated records
    5. Delete original 1-minute records

    Returns:
        Dict with status and statistics
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=365)

        # Get distinct option symbols that need aggregation
        symbols_to_aggregate = list(
            HistoricalGreeks.objects.filter(timestamp__lt=cutoff_date)
            .values_list("option_symbol", flat=True)
            .distinct()
        )

        total_aggregated = 0
        total_deleted = 0

        for option_symbol in symbols_to_aggregate:
            with transaction.atomic():
                # Get all 1-min records for this symbol older than 1 year
                # (identified by having second=0, microsecond=0)
                old_records = HistoricalGreeks.objects.filter(
                    option_symbol=option_symbol, timestamp__lt=cutoff_date
                ).order_by("timestamp")

                # Group by 5-minute intervals and take the last record in each
                interval_records = {}
                for record in old_records.iterator():
                    # Truncate to 5-minute intervals (0, 5, 10, 15, ...)
                    minute = record.timestamp.minute
                    interval_minute = (minute // 5) * 5
                    record_interval = record.timestamp.replace(
                        minute=interval_minute, second=0, microsecond=0
                    )
                    # Keep last record for each interval (overwrites previous)
                    interval_records[record_interval] = record

                # Create new 5-minute resolution records
                for interval_ts, last_record in interval_records.items():
                    HistoricalGreeks.objects.update_or_create(
                        option_symbol=last_record.option_symbol,
                        timestamp=interval_ts,
                        defaults={
                            "underlying_symbol": last_record.underlying_symbol,
                            "delta": last_record.delta,
                            "gamma": last_record.gamma,
                            "theta": last_record.theta,
                            "vega": last_record.vega,
                            "rho": last_record.rho,
                            "implied_volatility": last_record.implied_volatility,
                            "strike": last_record.strike,
                            "expiration_date": last_record.expiration_date,
                            "option_type": last_record.option_type,
                        },
                    )
                    total_aggregated += 1

                # Delete original 1-minute records
                deleted_count, _ = old_records.delete()
                total_deleted += deleted_count

        logger.info(
            f"Aggregated to 5-min: {total_aggregated} intervals from {total_deleted} 1-min records",
            extra={
                "aggregated_count": total_aggregated,
                "deleted_count": total_deleted,
                "symbols_processed": len(symbols_to_aggregate),
            },
        )

        return {
            "status": "success",
            "aggregated": total_aggregated,
            "deleted": total_deleted,
            "symbols_processed": len(symbols_to_aggregate),
        }

    except Exception as e:
        logger.error(f"Error aggregating Greeks to 5min: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
