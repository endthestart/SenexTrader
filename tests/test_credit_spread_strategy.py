"""
Tests for unified CreditSpreadStrategy.

Tests the direction-parameterized strategy behavior for both bullish and bearish directions.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.credit_spread_strategy import (
    ShortCallVerticalStrategy,
    ShortPutVerticalStrategy,
    SpreadDirection,
)
from tests.helpers import create_neutral_market_report

User = get_user_model()


@pytest.mark.asyncio
class TestCreditSpreadDirectionParity:
    """Test unified credit spread strategy with direction parameter."""

    async def test_bullish_direction_high_score(self, mock_user):
        """Test bullish direction scores high for bullish conditions."""
        unified = ShortPutVerticalStrategy(mock_user)

        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.current_price = 455.0
        report.iv_rank = 60.0
        report.market_stress_level = 25.0

        unified_score, unified_explanation = await unified.a_score_market_conditions(report)

        assert unified_score >= 90.0
        assert unified.spread_direction == SpreadDirection.BULLISH

    async def test_bearish_direction_high_score(self, mock_user):
        """Test bearish direction scores high for bearish conditions."""
        unified = ShortCallVerticalStrategy(mock_user)

        report = create_neutral_market_report()
        report.macd_signal = "bearish"
        report.current_price = 440.0
        report.rsi = 35.0
        report.current_iv = 0.25
        report.market_stress_level = 65.0

        unified_score, unified_explanation = await unified.a_score_market_conditions(report)

        assert unified_score >= 60.0
        assert unified.spread_direction == SpreadDirection.BEARISH

    async def test_multiple_market_conditions_bullish(self, mock_user):
        """Test bullish direction across multiple market conditions."""
        unified = ShortPutVerticalStrategy(mock_user)

        test_cases = [
            {
                "macd_signal": "bearish",
                "current_price": 440.0,
                "iv_rank": 20.0,
                "expected_low": True,
            },
            {
                "macd_signal": "neutral",
                "current_price": 455.0,
                "iv_rank": 40.0,
                "expected_low": False,
            },
            {"current_price": 440.0, "market_stress_level": 85.0, "expected_low": True},
        ]

        for params in test_cases:
            expected_low = params.pop("expected_low")
            report = create_neutral_market_report()
            for key, value in params.items():
                setattr(report, key, value)

            unified_score, _ = await unified.a_score_market_conditions(report)

            if expected_low:
                assert unified_score < 70.0, f"Expected low score for {params}, got {unified_score}"
            else:
                assert (
                    unified_score >= 70.0
                ), f"Expected moderate score for {params}, got {unified_score}"

    async def test_multiple_market_conditions_bearish(self, mock_user):
        """Test bearish direction across multiple market conditions."""
        unified = ShortCallVerticalStrategy(mock_user)

        test_cases = [
            {"macd_signal": "bullish", "current_price": 460.0, "rsi": 65.0, "expected_low": True},
            {"macd_signal": "neutral", "current_price": 452.0, "rsi": 50.0, "expected_low": False},
            {
                "current_price": 440.0,
                "rsi": 40.0,
                "market_stress_level": 70.0,
                "expected_low": False,
            },
        ]

        for params in test_cases:
            expected_low = params.pop("expected_low")
            report = create_neutral_market_report()
            for key, value in params.items():
                setattr(report, key, value)

            unified_score, _ = await unified.a_score_market_conditions(report)

            if expected_low:
                assert unified_score < 65.0, f"Expected low score for {params}, got {unified_score}"
            else:
                assert (
                    unified_score >= 50.0
                ), f"Expected moderate score for {params}, got {unified_score}"

    async def test_string_direction_parameter(self, mock_user):
        """Test that wrapper classes set direction correctly."""
        bullish = ShortPutVerticalStrategy(mock_user)
        bearish = ShortCallVerticalStrategy(mock_user)

        assert bullish.spread_direction == SpreadDirection.BULLISH
        assert bearish.spread_direction == SpreadDirection.BEARISH
        assert bullish.strategy_name == "bull_put_spread"
        assert bearish.strategy_name == "bear_call_spread"


class TestCreditSpreadTargetCriteria:
    """Test target criteria generation for strike optimization."""

    def test_bull_put_target_criteria_default(self, mock_user):
        """Test bull put spread target criteria without support level."""
        strategy = ShortPutVerticalStrategy(mock_user)
        report = create_neutral_market_report()
        report.support_level = None
        current_price = Decimal("450.00")
        spread_width = 5

        criteria = strategy._get_target_criteria(current_price, spread_width, report)

        assert criteria["spread_type"] == "bull_put"
        assert criteria["otm_pct"] == 0.03
        assert criteria["spread_width"] == 5
        assert criteria["current_price"] == current_price
        assert criteria["support_level"] is None
        assert criteria["resistance_level"] is None

    def test_bull_put_target_criteria_with_support(self, mock_user):
        """Test bull put spread target criteria respects support level."""
        strategy = ShortPutVerticalStrategy(mock_user)
        report = create_neutral_market_report()
        report.support_level = 440.0
        current_price = Decimal("450.00")
        spread_width = 5

        criteria = strategy._get_target_criteria(current_price, spread_width, report)

        assert criteria["spread_type"] == "bull_put"
        assert criteria["support_level"] == Decimal("440.0")
        assert criteria["resistance_level"] is None

    def test_bear_call_target_criteria_default(self, mock_user):
        """Test bear call spread target criteria without resistance level."""
        strategy = ShortCallVerticalStrategy(mock_user)
        report = create_neutral_market_report()
        report.resistance_level = None
        current_price = Decimal("450.00")
        spread_width = 5

        criteria = strategy._get_target_criteria(current_price, spread_width, report)

        assert criteria["spread_type"] == "bear_call"
        assert criteria["otm_pct"] == 0.03
        assert criteria["spread_width"] == 5
        assert criteria["current_price"] == current_price
        assert criteria["support_level"] is None
        assert criteria["resistance_level"] is None

    def test_bear_call_target_criteria_with_resistance(self, mock_user):
        """Test bear call spread target criteria respects resistance level."""
        strategy = ShortCallVerticalStrategy(mock_user)
        report = create_neutral_market_report()
        report.resistance_level = 460.0
        current_price = Decimal("450.00")
        spread_width = 5

        criteria = strategy._get_target_criteria(current_price, spread_width, report)

        assert criteria["spread_type"] == "bear_call"
        assert criteria["support_level"] is None
        assert criteria["resistance_level"] == Decimal("460.0")

    def test_target_criteria_contract_consistency(self, mock_user):
        """
        Test that target criteria structure matches expiration_utils.py contract.

        This test ensures the consolidation didn't break the contract expected by
        find_expiration_with_optimal_strikes() which requires:
        - spread_type
        - otm_pct
        - spread_width
        - current_price
        - support_level (optional)
        - resistance_level (optional)
        """
        bull_put = ShortPutVerticalStrategy(mock_user)
        bear_call = ShortCallVerticalStrategy(mock_user)
        report = create_neutral_market_report()
        current_price = Decimal("450.00")
        spread_width = 5

        for strategy, expected_type in [
            (bull_put, "bull_put"),
            (bear_call, "bear_call"),
        ]:
            criteria = strategy._get_target_criteria(current_price, spread_width, report)

            # Verify all required keys exist
            required_keys = {
                "spread_type",
                "otm_pct",
                "spread_width",
                "current_price",
                "support_level",
                "resistance_level",
            }
            assert set(criteria.keys()) == required_keys, (
                f"Missing or extra keys in {expected_type} criteria. "
                f"Expected: {required_keys}, Got: {set(criteria.keys())}"
            )

            # Verify types
            assert criteria["spread_type"] == expected_type
            assert isinstance(criteria["otm_pct"], float)
            assert isinstance(criteria["spread_width"], int)
            assert isinstance(criteria["current_price"], Decimal)
