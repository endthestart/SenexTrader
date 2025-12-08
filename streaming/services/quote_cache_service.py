"""Helpers for building cache payloads from streaming events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.utils import timezone as dj_timezone

from .stream_helpers import format_timestamp, safe_float


def _copy(existing: dict[str, Any] | None) -> dict[str, Any]:
    return dict(existing) if existing else {}


def _apply_daily_change(payload: dict[str, Any]) -> None:
    last_price = payload.get("last")
    previous_close = payload.get("previous_close")
    if last_price is None or previous_close in (None, 0):
        return

    daily_change = float(last_price) - float(previous_close)
    daily_change_percent = (daily_change / float(previous_close)) * 100
    payload.update(
        {
            "change": daily_change,
            "change_percent": round(daily_change_percent, 2),
        }
    )


def build_quote_payload(quote, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge quote event data with an existing cache payload."""

    payload = _copy(existing)
    bid_price = safe_float(getattr(quote, "bid_price", None))
    ask_price = safe_float(getattr(quote, "ask_price", None))
    midpoint = None
    if bid_price is not None and ask_price is not None:
        midpoint = (bid_price + ask_price) / 2.0

    payload.update(
        {
            "symbol": quote.event_symbol,
            "bid": bid_price,
            "ask": ask_price,
            "last": midpoint,
            "updated_at": format_timestamp(getattr(quote, "event_time", None)),
            "source": "consolidated_streaming",
        }
    )

    _apply_daily_change(payload)
    return payload


def build_trade_payload(trade, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge trade event data with an existing cache payload."""

    payload = _copy(existing)
    payload.update(
        {
            "symbol": trade.event_symbol,
            "last": safe_float(getattr(trade, "price", None)),
            "volume": getattr(trade, "day_volume", None),
            "trade_change": safe_float(getattr(trade, "change", None)),
            "trade_size": getattr(trade, "size", None),
            "updated_at": format_timestamp(getattr(trade, "time", None)),
        }
    )

    return payload


def build_summary_payload(
    summary,
    existing: dict[str, Any] | None = None,
    *,
    now_provider: Callable[[], datetime | str] | None = None,
) -> dict[str, Any]:
    """Merge summary event data with an existing cache payload."""

    payload = _copy(existing)
    timestamp_source = now_provider or dj_timezone.now
    timestamp_value = timestamp_source()
    if hasattr(timestamp_value, "isoformat"):
        timestamp_str = timestamp_value.isoformat()
    else:
        timestamp_str = str(timestamp_value)

    payload.update(
        {
            "symbol": summary.event_symbol,
            "previous_close": safe_float(getattr(summary, "prev_day_close_price", None)),
            "day_open": safe_float(getattr(summary, "day_open_price", None)),
            "day_high": safe_float(getattr(summary, "day_high_price", None)),
            "day_low": safe_float(getattr(summary, "day_low_price", None)),
            "updated_at": timestamp_str,
        }
    )

    _apply_daily_change(payload)
    return payload
