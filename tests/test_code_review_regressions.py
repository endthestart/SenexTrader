"""
Regression tests for code review findings.

Tests for issues identified in external code review:
1. IV scaling consistency (market_analysis.py)
2. strikes_list UnboundLocalError (option_chain_service.py)
3. ADX directional gating (debit_spread_base.py)
"""

import pytest

from services.market_data.analysis import MarketConditionReport
from tests.helpers.market_helpers import create_neutral_market_report


class TestIVScalingRegression:
    """
    Test 1: IV ratio test - Verify scale consistency after Epic 28 Task 011.

    Epic 28 Task 011 standardized current_iv to 0-100 scale (e.g., 28.5 for 28.5%).
    Before the fix, __post_init__ multiplied by 100, causing hv_iv_ratio to be near-zero.
    """

    def test_hv_iv_ratio_with_standardized_scale(self):
        """Test that HV/IV ratio calculation works correctly with 0-100 scale IV."""
        # Create a report with current_iv already in 0-100 scale (Epic 28 Task 011)
        # hv_iv_ratio is calculated in __post_init__, so we must pass values at construction
        from datetime import UTC, datetime

        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            current_iv=28.5,  # Already 0-100 scale (28.5%)
            historical_volatility=35.0,  # Also 0-100 scale (35%)
            iv_rank=45.0,
            adx=25.0,
            last_update=datetime.now(UTC),
        )

        # Expected: HV/IV = 35.0 / 28.5 = 1.228
        # Bug would have: HV/IV = 35.0 / (28.5 * 100) = 0.012
        assert report.hv_iv_ratio == pytest.approx(1.228, abs=0.01)
        assert 1.2 < report.hv_iv_ratio < 1.3

    def test_hv_iv_ratio_below_one(self):
        """Test HV/IV ratio when IV > HV (options expensive)."""
        from datetime import UTC, datetime

        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            current_iv=40.0,  # 40%
            historical_volatility=30.0,  # 30%
            iv_rank=45.0,
            adx=25.0,
            last_update=datetime.now(UTC),
        )

        # Expected: HV/IV = 30.0 / 40.0 = 0.75
        assert report.hv_iv_ratio == pytest.approx(0.75, abs=0.01)


class TestStrikesListInitialization:
    """
    Test 2: strikes_list test - Guard against UnboundLocalError scenario.

    If _find_closest_expiration returns a date but the chain iterator never matches,
    strikes_list would be undefined before the fix at option_chain_service.py:412.
    """

    def test_strikes_list_defensive_initialization(self):
        """Verify strikes_list is initialized before the loop to prevent UnboundLocalError."""
        # Read the source file directly to verify the fix
        with open("services/market_data/option_chains.py") as f:
            source = f.read()

        # Verify defensive initialization exists
        # The fix should have: strikes_list = []  # Initialize to prevent UnboundLocalError
        assert "strikes_list = []" in source, (
            "strikes_list must be initialized before the chain iteration loop "
            "to prevent UnboundLocalError when no expiration matches"
        )

        # Verify initialization happens before "for chain_item in chains"
        strikes_init_pos = source.find("strikes_list = []")
        chain_loop_pos = source.find("for chain_item in chains")

        assert strikes_init_pos > 0, "Could not find strikes_list initialization"
        assert chain_loop_pos > 0, "Could not find chain iteration loop"
        assert (
            strikes_init_pos < chain_loop_pos
        ), "strikes_list initialization must occur before the chain iteration loop"


class TestADXDirectionalGating:
    """
    Test 3: ADX directional test - Prove directional strategies don't get ADX bonus
    in wrong-direction trends.

    Before fix: Bear Put in strong bull trend got +20 (ADX) - 50 (MACD) = -30 net
    After fix: Bear Put in strong bull trend gets 0 (no ADX) - 50 (MACD) = -50 net
    """

    @pytest.mark.asyncio
    async def test_bear_put_no_adx_bonus_in_bull_trend(self, mock_user):
        """Bear Put should NOT get ADX bonus when MACD shows strong bullish trend."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_vertical", mock_user)

        # Strong bull trend: High ADX + strong_bullish MACD
        report = create_neutral_market_report()
        report.macd_signal = "strong_bullish"  # Wrong direction for Bear Put
        report.adx = 35.0  # Strong trend (> OPTIMAL_ADX=30)

        _score, explanation = await strategy.a_score_market_conditions(report)

        # The key test: verify ADX bonus was NOT awarded due to wrong direction
        assert "wrong direction" in explanation.lower() or "no adx bonus" in explanation.lower()

        # Should NOT see the "excellent momentum" or "correct direction" message
        assert "excellent momentum for directional play" not in explanation.lower()

    @pytest.mark.asyncio
    async def test_bull_call_no_adx_bonus_in_bear_trend(self, mock_user):
        """Bull Call should NOT get ADX bonus when MACD shows strong bearish trend."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_call_vertical", mock_user)

        # Strong bear trend: High ADX + strong_bearish MACD
        report = create_neutral_market_report()
        report.macd_signal = "strong_bearish"  # Wrong direction for Bull Call
        report.adx = 35.0  # Strong trend (> OPTIMAL_ADX=30)

        _score, explanation = await strategy.a_score_market_conditions(report)

        # The key test: verify ADX bonus was NOT awarded due to wrong direction
        assert "wrong direction" in explanation.lower() or "no adx bonus" in explanation.lower()

        # Should NOT see the "excellent momentum" or "correct direction" message
        assert "excellent momentum for directional play" not in explanation.lower()

    @pytest.mark.asyncio
    async def test_bear_put_gets_adx_bonus_in_bear_trend(self, mock_user):
        """Bear Put SHOULD get ADX bonus when MACD shows strong bearish trend."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_vertical", mock_user)

        # Strong bear trend: High ADX + strong_bearish MACD (correct direction)
        report = create_neutral_market_report()
        report.macd_signal = "strong_bearish"  # Correct direction for Bear Put
        report.adx = 35.0  # Strong trend

        _score, explanation = await strategy.a_score_market_conditions(report)

        # Verify ADX bonus WAS awarded
        assert (
            "correct direction" in explanation.lower()
            or "excellent momentum" in explanation.lower()
        )

        # Should NOT see the "wrong direction" message
        assert "wrong direction" not in explanation.lower()
