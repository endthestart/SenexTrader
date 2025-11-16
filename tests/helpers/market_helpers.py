"""Market condition helper functions for testing.

Provides standardized MarketConditionReport fixtures for different market scenarios.
Eliminates duplication across test files.
"""

from datetime import UTC, datetime

from django.utils import timezone

from services.market_data.analysis import MarketConditionReport


def create_ideal_bullish_report(symbol: str = "SPY") -> MarketConditionReport:
    """Create ideal bullish conditions for Bull Put Spread.

    Used in strategy selector integration tests.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=455.0,
        open_price=450.0,
        rsi=65.0,
        macd_signal="bullish",
        bollinger_position="within_bands",
        sma_20=445.0,
        support_level=440.0,
        resistance_level=465.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.25,
        iv_rank=60.0,
        iv_percentile=58.0,
        market_stress_level=25.0,
        recent_move_pct=1.8,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


def create_ideal_bearish_report(symbol: str = "SPY") -> MarketConditionReport:
    """Create ideal bearish conditions for Bear Call Spread.

    Used in strategy selector integration tests.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=440.0,
        open_price=448.0,
        rsi=35.0,
        macd_signal="bearish",
        bollinger_position="below_lower",
        sma_20=448.0,
        support_level=435.0,
        resistance_level=455.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.28,
        iv_rank=70.0,
        iv_percentile=68.0,
        market_stress_level=55.0,
        recent_move_pct=2.8,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


def create_neutral_market_report(symbol: str = "SPY") -> MarketConditionReport:
    """Create neutral market conditions for baseline testing.

    Used in unit tests as a starting point for condition variations.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.0,
        open_price=448.0,
        rsi=50.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=445.0,
        support_level=440.0,
        resistance_level=460.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.25,
        iv_rank=50.0,
        iv_percentile=50.0,
        market_stress_level=30.0,
        recent_move_pct=1.5,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


def create_bullish_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create market conditions favorable for Bull Put Spread.

    Used in integration tests for strategy coordination.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=445.00,
        macd_signal="bullish",
        rsi=65.0,
        iv_rank=45.0,
        current_iv=0.20,
        is_range_bound=False,
        bollinger_position="upper",
        market_stress_level=25.0,
        sma_20=445.00,
        no_trade_reasons=[],
        is_data_stale=False,
        last_update=timezone.now(),
    )


def create_bearish_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create market conditions favorable for Bear Call Spread.

    Used in integration tests for strategy coordination.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=455.00,
        macd_signal="bearish",
        rsi=35.0,
        iv_rank=50.0,
        current_iv=0.22,
        is_range_bound=False,
        bollinger_position="lower",
        market_stress_level=30.0,
        sma_20=455.00,
        no_trade_reasons=[],
        is_data_stale=False,
        last_update=timezone.now(),
    )


def create_high_iv_neutral_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create market conditions favorable for Senex Trident.

    High IV + neutral sentiment = ideal for credit spread strategies.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=448.00,
        macd_signal="neutral",
        rsi=52.0,
        iv_rank=70.0,  # High IV - key for Trident
        current_iv=0.28,
        is_range_bound=False,  # NOT range-bound - critical
        bollinger_position="within_bands",
        market_stress_level=35.0,
        sma_20=448.00,
        no_trade_reasons=[],
        is_data_stale=False,
        last_update=timezone.now(),
    )


def create_range_bound_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create range-bound market (blocks Senex Trident).

    Range-bound conditions trigger hard stop for Trident strategy.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=450.00,
        macd_signal="neutral",
        rsi=50.0,
        iv_rank=60.0,
        current_iv=0.25,
        is_range_bound=True,  # RANGE-BOUND - blocks Trident
        bollinger_position="within_bands",
        market_stress_level=20.0,
        sma_20=450.00,
        no_trade_reasons=[],
        is_data_stale=False,
        last_update=timezone.now(),
    )


def create_unfavorable_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create unfavorable market conditions (low scores for all strategies).

    Low IV and neutral conditions = poor for premium selling strategies.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=450.00,
        macd_signal="neutral",
        rsi=50.0,
        iv_rank=20.0,  # Low IV - unfavorable for premium selling
        current_iv=0.12,
        is_range_bound=False,
        bollinger_position="within_bands",
        market_stress_level=10.0,
        sma_20=450.00,
        no_trade_reasons=[],
        is_data_stale=False,
        last_update=timezone.now(),
    )


def create_stale_data_market(symbol: str = "SPY") -> MarketConditionReport:
    """Create market with stale data (hard stop).

    Stale data triggers hard stop preventing all trading.
    """
    return MarketConditionReport(
        symbol=symbol,
        current_price=450.00,
        open_price=450.00,
        macd_signal="neutral",
        rsi=50.0,
        iv_rank=50.0,
        current_iv=0.20,
        is_range_bound=False,
        bollinger_position="within_bands",
        market_stress_level=25.0,
        sma_20=450.00,
        no_trade_reasons=["stale_data"],
        is_data_stale=True,
        last_update=timezone.now() - timezone.timedelta(hours=2),
    )
