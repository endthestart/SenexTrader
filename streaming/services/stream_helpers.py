"""
Stream Helper Utilities

Extracted common utilities from StreamManager for better organization
and code reuse. Contains data formatting, symbol validation, and utility functions.
"""

from datetime import UTC, datetime

from django.utils import timezone as dj_timezone

from services.core.logging import get_logger

logger = get_logger(__name__)


def safe_float(value) -> float | None:
    """Convert value to float safely"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_timestamp(event_time: int | None) -> str:
    """Convert event time to ISO 8601 string safely"""
    if event_time in (None, 0):
        return dj_timezone.now().isoformat()
    try:
        return datetime.fromtimestamp(event_time / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError):
        return dj_timezone.now().isoformat()


def validate_symbols(symbols: list[str]) -> list[str]:
    """Validate and clean symbol list."""
    if not symbols:
        return []

    cleaned_symbols = []
    for symbol in symbols:
        if symbol and isinstance(symbol, str):
            cleaned = symbol.upper().strip()
            if cleaned:
                cleaned_symbols.append(cleaned)

    return cleaned_symbols


def format_quote_data(raw_quote: dict, symbol: str) -> dict:
    """Format quote data for consistency."""
    return {
        "symbol": symbol,
        "bid": safe_float(raw_quote.get("bidPrice", 0)),
        "ask": safe_float(raw_quote.get("askPrice", 0)),
        "last": safe_float(raw_quote.get("lastPrice")),
        "timestamp": format_timestamp(raw_quote.get("time", 0)),
        "volume": safe_float(raw_quote.get("dayVolume")),
        "updated_at": dj_timezone.now().isoformat(),
    }


def format_trade_data(trade_event, existing_quote: dict) -> dict:
    """Format trade data and merge with existing quote."""
    updated_quote = existing_quote.copy()
    updated_quote.update(
        {
            "last": safe_float(trade_event.price),
            "last_size": safe_float(trade_event.size),
            "timestamp": format_timestamp(trade_event.time),
            "updated_at": dj_timezone.now().isoformat(),
        }
    )
    return updated_quote


def format_summary_data(summary_event, existing_quote: dict) -> dict:
    """Format summary data and merge with existing quote."""
    updated_quote = existing_quote.copy()
    updated_quote.update(
        {
            "open": safe_float(summary_event.open_price),
            "high": safe_float(summary_event.high_price),
            "low": safe_float(summary_event.low_price),
            "close": safe_float(summary_event.close_price),
            "volume": safe_float(summary_event.day_volume),
            "timestamp": format_timestamp(summary_event.day_close_time),
            "updated_at": dj_timezone.now().isoformat(),
        }
    )
    return updated_quote


def is_option_symbol(symbol: str) -> bool:
    """Check if symbol is an option symbol (contains spaces or starts with dot)."""
    return " " in symbol or symbol.startswith(".")


def extract_leg_symbols(occ_bundle: dict) -> list[str]:
    """Extract leg symbols from OCC bundle."""
    if not occ_bundle or not isinstance(occ_bundle, dict):
        return []

    legs = occ_bundle.get("legs", {})
    if not legs:
        return []

    return list(legs.values())


def create_broadcast_message(message_type: str, data: dict, user_id: int | None = None) -> dict:
    """Create standardized broadcast message."""
    message = {"type": message_type, "data": data, "timestamp": dj_timezone.now().isoformat()}

    if user_id is not None:
        message["user_id"] = user_id

    return message
