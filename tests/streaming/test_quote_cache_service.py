import types

from streaming.services.quote_cache_service import (
    build_quote_payload,
    build_summary_payload,
    build_trade_payload,
)


class DummyQuote(types.SimpleNamespace):
    pass


def test_build_quote_payload_computes_midpoint_and_change():
    quote = DummyQuote(
        event_symbol="SPY",
        bid_price="100",
        ask_price="102",
        event_time=1,
    )
    existing = {"previous_close": 99.0}

    payload = build_quote_payload(quote, existing)

    assert payload["symbol"] == "SPY"
    assert payload["bid"] == 100.0
    assert payload["ask"] == 102.0
    assert payload["last"] == 101.0  # midpoint
    assert payload["previous_close"] == 99.0
    assert payload["change"] == 2.0
    assert payload["change_percent"] == 2.02
    assert payload["source"] == "consolidated_streaming"


def test_build_trade_payload_overrides_last_and_volume():
    trade = DummyQuote(
        event_symbol="AAPL",
        price="150.5",
        day_volume=1234,
        change="-1.2",
        size=10,
        time=5,
    )
    existing = {"last": 140.0}

    payload = build_trade_payload(trade, existing)

    assert payload["symbol"] == "AAPL"
    assert payload["last"] == 150.5
    assert payload["volume"] == 1234
    assert payload["trade_change"] == -1.2
    assert payload["trade_size"] == 10
    assert payload["updated_at"].endswith("Z") or payload["updated_at"].endswith("+00:00")


def test_build_summary_payload_adds_day_fields_and_change():
    summary = DummyQuote(
        event_symbol="TSLA",
        prev_day_close_price="220",
        day_open_price="221",
        day_high_price="230",
        day_low_price="215",
    )
    existing = {"last": 225.0}

    payload = build_summary_payload(summary, existing, now_provider=lambda: "2024-01-01T00:00:00Z")

    assert payload["symbol"] == "TSLA"
    assert payload["previous_close"] == 220.0
    assert payload["day_open"] == 221.0
    assert payload["day_high"] == 230.0
    assert payload["day_low"] == 215.0
    assert payload["change"] == 5.0
    assert payload["change_percent"] == 2.27
    assert payload["updated_at"] == "2024-01-01T00:00:00Z"
