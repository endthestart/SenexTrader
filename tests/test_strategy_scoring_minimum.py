"""
Comprehensive tests for strategy scoring minimum enforcement (0 floor).

Verifies that all strategies:
1. Never return negative scores
2. Properly enforce 0 minimum
3. Handle extreme negative market conditions
4. Return valid explanations at all score levels
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model

import pytest

from services.strategies.cash_secured_put_strategy import CashSecuredPutStrategy
from services.strategies.covered_call_strategy import CoveredCallStrategy
from services.strategies.credit_spread_strategy import (
    ShortCallVerticalStrategy,
    ShortPutVerticalStrategy,
)
from services.strategies.debit_spread_strategy import (
    LongCallVerticalStrategy,
    LongPutVerticalStrategy,
)
from tests.helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def bear_call_strategy(mock_user):
    return ShortCallVerticalStrategy(mock_user)


@pytest.fixture
def bear_put_strategy(mock_user):
    return LongPutVerticalStrategy(mock_user)


@pytest.fixture
def bull_call_strategy(mock_user):
    return LongCallVerticalStrategy(mock_user)


@pytest.fixture
def bull_put_strategy(mock_user):
    return ShortPutVerticalStrategy(mock_user)


@pytest.fixture
def cash_secured_put_strategy(mock_user):
    return CashSecuredPutStrategy(mock_user)


@pytest.fixture
def covered_call_strategy(mock_user):
    return CoveredCallStrategy(mock_user)


@pytest.mark.asyncio
async def test_bear_put_spread_no_negative_scores(bear_put_strategy):
    """
    Regression test: Bear Put Spread previously returned negative scores.
    Verify it now enforces 0 minimum even in extreme bullish conditions.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bullish"
    report.current_price = 480.0
    report.sma_20 = 440.0
    report.rsi = 80.0
    report.current_iv = 0.08
    report.iv_rank = 10.0
    report.market_stress_level = 15.0
    report.recent_move_pct = 0.5

    score, explanation = await bear_put_strategy.a_score_market_conditions(report)

    assert score >= 0.0, f"Bear Put Spread returned negative score: {score}"
    assert score <= 100.0
    assert isinstance(explanation, str)
    assert len(explanation) > 0


@pytest.mark.asyncio
async def test_bull_call_spread_no_negative_scores(bull_call_strategy):
    """
    Test Bull Call Spread (also uses debit spread base) enforces 0 minimum.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bearish"
    report.current_price = 420.0
    report.sma_20 = 460.0
    report.rsi = 20.0
    report.current_iv = 0.08
    report.iv_rank = 10.0
    report.market_stress_level = 85.0
    report.recent_move_pct = -5.0

    score, explanation = await bull_call_strategy.a_score_market_conditions(report)

    assert score >= 0.0, f"Bull Call Spread returned negative score: {score}"
    assert score <= 100.0
    assert isinstance(explanation, str)
    assert len(explanation) > 0


@pytest.mark.asyncio
async def test_cash_secured_put_no_negative_scores(cash_secured_put_strategy):
    """
    Test Cash Secured Put enforces 0 minimum in bearish markets.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bearish"
    report.current_price = 420.0
    report.sma_20 = 460.0
    report.rsi = 25.0
    report.current_iv = 0.08
    report.iv_rank = 10.0
    report.market_stress_level = 80.0
    report.recent_move_pct = -4.0

    score, explanation = await cash_secured_put_strategy.a_score_market_conditions(report)

    assert score >= 0.0, f"Cash Secured Put returned negative score: {score}"
    assert score <= 100.0
    assert isinstance(explanation, str)
    assert len(explanation) > 0


@pytest.mark.asyncio
async def test_covered_call_no_negative_scores(covered_call_strategy):
    """
    Test Covered Call enforces 0 minimum without existing position.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bullish"
    report.current_price = 480.0
    report.sma_20 = 440.0
    report.rsi = 75.0
    report.current_iv = 0.08
    report.iv_rank = 10.0
    report.market_stress_level = 20.0
    report.recent_move_pct = 3.0

    with patch.object(
        covered_call_strategy.stock_detector, "has_sufficient_shares", return_value=False
    ):
        score, explanation = await covered_call_strategy.a_score_market_conditions(report)

    assert score >= 0.0, f"Covered Call returned negative score: {score}"
    assert score <= 100.0
    assert isinstance(explanation, str)
    assert len(explanation) > 0


@pytest.mark.asyncio
async def test_bear_call_spread_extreme_conditions(bear_call_strategy):
    """
    Test Bear Call Spread handles extreme bullish conditions gracefully.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bullish"
    report.current_price = 490.0
    report.sma_20 = 430.0
    report.rsi = 85.0
    report.current_iv = 0.06
    report.iv_rank = 5.0
    report.market_stress_level = 10.0

    score, explanation = await bear_call_strategy.a_score_market_conditions(report)

    assert 0.0 <= score <= 100.0
    assert isinstance(explanation, str)


@pytest.mark.asyncio
async def test_bull_put_spread_extreme_conditions(bull_put_strategy):
    """
    Test Bull Put Spread handles extreme bearish conditions gracefully.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bearish"
    report.current_price = 410.0
    report.sma_20 = 470.0
    report.rsi = 15.0
    report.current_iv = 0.45
    report.iv_rank = 95.0
    report.market_stress_level = 90.0

    score, explanation = await bull_put_strategy.a_score_market_conditions(report)

    assert 0.0 <= score <= 100.0
    assert isinstance(explanation, str)


@pytest.mark.asyncio
async def test_all_strategies_with_hard_stop(
    bear_call_strategy,
    bear_put_strategy,
    bull_call_strategy,
    bull_put_strategy,
    cash_secured_put_strategy,
    covered_call_strategy,
):
    """
    Test strategies enforce 0 minimum with hard stop conditions.
    Note: Hard stops are checked at strategy_selector level, not individual strategies.
    This test verifies strategies can handle reports with no_trade_reasons gracefully.
    """
    report = create_neutral_market_report()
    report.no_trade_reasons = ["data_stale"]

    strategies = [
        bear_call_strategy,
        bear_put_strategy,
        bull_call_strategy,
        bull_put_strategy,
        cash_secured_put_strategy,
    ]

    for strategy in strategies:
        score, explanation = await strategy.a_score_market_conditions(report)
        assert score >= 0.0, f"{strategy.__class__.__name__} returned negative score with hard stop"
        assert score <= 100.0

    with patch.object(
        covered_call_strategy.stock_detector, "has_sufficient_shares", return_value=True
    ):
        score, explanation = await covered_call_strategy.a_score_market_conditions(report)
        assert score >= 0.0, "CoveredCallStrategy returned negative score with hard stop"
        assert score <= 100.0


@pytest.mark.asyncio
async def test_bear_put_spread_edge_case_boundary(bear_put_strategy):
    """
    Test Bear Put Spread at scoring boundary that could result in negative.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bullish"
    report.current_price = 465.0
    report.sma_20 = 445.0
    report.rsi = 70.0
    report.current_iv = 0.10
    report.iv_rank = 15.0
    report.market_stress_level = 25.0

    score, explanation = await bear_put_strategy.a_score_market_conditions(report)

    assert score >= 0.0
    assert score <= 100.0


@pytest.mark.asyncio
async def test_covered_call_without_position_low_iv(covered_call_strategy):
    """
    Test Covered Call scoring without existing position in low IV.
    Should score low but not negative.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bullish"
    report.current_price = 480.0
    report.sma_20 = 440.0
    report.rsi = 70.0
    report.current_iv = 0.08
    report.iv_rank = 12.0
    report.market_stress_level = 20.0

    with patch.object(
        covered_call_strategy.stock_detector, "has_sufficient_shares", return_value=False
    ):
        score, explanation = await covered_call_strategy.a_score_market_conditions(report)

    assert score >= 0.0
    assert score <= 100.0


@pytest.mark.asyncio
async def test_cash_secured_put_multiple_negative_factors(cash_secured_put_strategy):
    """
    Test Cash Secured Put with multiple negative scoring factors.
    """
    report = create_neutral_market_report()

    report.macd_signal = "bearish"
    report.current_price = 425.0
    report.sma_20 = 465.0
    report.rsi = 22.0
    report.current_iv = 0.07
    report.iv_rank = 8.0
    report.market_stress_level = 85.0
    report.recent_move_pct = -4.5

    score, explanation = await cash_secured_put_strategy.a_score_market_conditions(report)

    assert score >= 0.0
    assert score <= 100.0
    assert len(explanation) > 0


@pytest.mark.asyncio
async def test_all_credit_spreads_minimum_enforcement(bear_call_strategy, bull_put_strategy):
    """
    Test credit spread strategies enforce minimum with inappropriate directional signals.
    """
    report = create_neutral_market_report()

    report.current_iv = 0.25
    report.iv_rank = 60.0

    report.macd_signal = "bullish"
    report.current_price = 470.0
    report.sma_20 = 440.0
    report.rsi = 72.0
    score_bear_call, _ = await bear_call_strategy.a_score_market_conditions(report)
    assert score_bear_call >= 0.0

    report.macd_signal = "bearish"
    report.current_price = 430.0
    report.sma_20 = 460.0
    report.rsi = 28.0
    score_bull_put, _ = await bull_put_strategy.a_score_market_conditions(report)
    assert score_bull_put >= 0.0


@pytest.mark.asyncio
async def test_all_debit_spreads_minimum_enforcement(bear_put_strategy, bull_call_strategy):
    """
    Test debit spread strategies enforce minimum with inappropriate directional signals.
    """
    report = create_neutral_market_report()

    report.current_iv = 0.18
    report.iv_rank = 45.0

    report.macd_signal = "bullish"
    report.current_price = 475.0
    report.sma_20 = 440.0
    report.rsi = 75.0
    score_bear_put, _ = await bear_put_strategy.a_score_market_conditions(report)
    assert score_bear_put >= 0.0

    report.macd_signal = "bearish"
    report.current_price = 425.0
    report.sma_20 = 465.0
    report.rsi = 25.0
    score_bull_call, _ = await bull_call_strategy.a_score_market_conditions(report)
    assert score_bull_call >= 0.0
