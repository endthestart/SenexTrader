"""
Unit tests for ShortIronCondorStrategy.

Tests cover:
- Scoring logic for various market conditions
- IV rank scoring (HIGH IV preferred - premium selling)
- ADX scoring (range-bound preferred - low ADX)
- HV/IV ratio scoring (want IV > HV - overpriced options)
- Strike calculations (16 delta targets)
- Max profit/loss calculations
- Breakeven calculations
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.short_iron_condor_strategy import ShortIronCondorStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create ShortIronCondorStrategy instance."""
    return ShortIronCondorStrategy(mock_user)


@pytest.mark.asyncio
class TestShortIronCondorScoring:
    """Test scoring logic for short iron condor strategy."""

    async def test_ideal_conditions_high_iv_range_bound(self, strategy):
        """Test scoring with ideal conditions (high IV, range-bound)."""
        report = create_neutral_market_report()
        # Ideal: IV > 70, ADX < 20, HV/IV < 0.8, neutral direction
        report.iv_rank = 75.0  # Exceptional premium
        report.adx = 18.0  # Range-bound
        report.hv_iv_ratio = 0.75  # IV high relative to HV
        report.macd_signal = "neutral"  # No directional bias
        report.bollinger_position = "within_bands"  # Not at extremes
        report.market_stress_level = 30.0  # Low stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 + 30 (IV>70) + 25 (ADX<20) + 20 (HV/IV<0.8) + 15 (neutral) + 10 (middle) + 5 (low stress)
        assert score >= 120.0
        assert any("exceptional premium" in r.lower() for r in reasons)
        assert any("range-bound" in r.lower() and "ideal" in r.lower() for r in reasons)
        assert any("excellent for premium selling" in r.lower() for r in reasons)

    async def test_poor_conditions_low_iv_strong_trend(self, strategy):
        """Test scoring with poor conditions (low IV, strong trend)."""
        report = create_neutral_market_report()
        # Poor: IV < 35, ADX > 35, HV/IV > 1.2
        report.iv_rank = 30.0  # Too low
        report.adx = 38.0  # Strong trend
        report.hv_iv_ratio = 1.3  # IV underpriced
        report.bollinger_position = "above_upper"  # At extremes
        report.market_stress_level = 75.0  # High stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 - 20 (IV<35) - 25 (ADX>35) - 15 (HV/IV>1.2) - 8 (extremes) - 10 (high stress)
        assert score <= 20.0
        assert any("insufficient premium" in r.lower() for r in reasons)
        assert any("avoid iron condor" in r.lower() for r in reasons)
        assert any("iv underpriced" in r.lower() for r in reasons)

    async def test_iv_rank_above_70_exceptional(self, strategy):
        """Test exceptional score for IV rank > 70."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 70.0
        assert any("exceptional premium" in r.lower() for r in reasons)

    async def test_iv_rank_60_70_optimal(self, strategy):
        """Test optimal score for IV rank 60-70 range."""
        report = create_neutral_market_report()
        report.iv_rank = 65.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 65.0
        assert any("optimal range" in r.lower() and "excellent" in r.lower() for r in reasons)

    async def test_iv_rank_45_60_adequate(self, strategy):
        """Test adequate score for IV rank 45-60."""
        report = create_neutral_market_report()
        report.iv_rank = 50.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 55.0
        assert any("adequate" in r.lower() and "acceptable" in r.lower() for r in reasons)

    async def test_iv_rank_below_35_insufficient(self, strategy):
        """Test penalty for IV rank < 35 (insufficient premium)."""
        report = create_neutral_market_report()
        report.iv_rank = 30.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("insufficient premium" in r.lower() for r in reasons)

    async def test_adx_below_20_ideal_range_bound(self, strategy):
        """Test ideal score for ADX < 20 (range-bound)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.adx = 18.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("range-bound" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_adx_20_25_weak_trend(self, strategy):
        """Test good score for ADX 20-25 (weak trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.adx = 23.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("weak trend" in r.lower() and "favorable" in r.lower() for r in reasons)

    async def test_adx_above_35_strong_trend_avoid(self, strategy):
        """Test penalty for ADX > 35 (strong trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.adx = 40.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("strong trend" in r.lower() and "avoid" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_below_0_8_excellent(self, strategy):
        """Test excellent score for HV/IV < 0.8 (IV very high)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.hv_iv_ratio = 0.75

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("excellent for premium selling" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_0_8_0_9_moderate(self, strategy):
        """Test moderate score for HV/IV 0.8-0.9."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.hv_iv_ratio = 0.85

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("moderately elevated" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_2_poor(self, strategy):
        """Test penalty for HV/IV > 1.2 (IV underpriced)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.hv_iv_ratio = 1.3

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("iv underpriced" in r.lower() and "poor" in r.lower() for r in reasons)

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets are ideal (no directional bias)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.macd_signal = "neutral"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "ideal for iron condor" in r.lower() and "no directional bias" in r.lower()
            for r in reasons
        )

    async def test_directional_bias_manageable(self, strategy):
        """Test that directional bias is manageable but not ideal."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.macd_signal = "bullish"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "manageable" in r.lower() and "watch threatened side" in r.lower() for r in reasons
        )

    async def test_bollinger_within_bands_ideal(self, strategy):
        """Test bonus for price in middle of Bollinger Bands."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.bollinger_position = "within_bands"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("within bollinger" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_bollinger_extremes_penalty(self, strategy):
        """Test penalty for price at Bollinger extremes."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.bollinger_position = "above_upper"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("bollinger extremes" in r.lower() and "risky" in r.lower() for r in reasons)

    async def test_low_market_stress_bonus(self, strategy):
        """Test bonus for low market stress (stable environment)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.market_stress_level = 30.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("low market stress" in r.lower() and "stable" in r.lower() for r in reasons)

    async def test_very_high_market_stress_penalty(self, strategy):
        """Test penalty for very high market stress (directional risk)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.market_stress_level = 75.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "very high market stress" in r.lower() and "directional movement risk" in r.lower()
            for r in reasons
        )


class TestShortIronCondorCalculations:
    """Test calculation methods."""

    def test_calculate_short_strikes(self, strategy):
        """Test short strike calculation (16 delta targets)."""
        current_price = Decimal("100.00")
        put_short, call_short = strategy._calculate_short_strikes(current_price)

        # Put short: 8% below = 92, rounds to 92
        # Call short: 8% above = 108, rounds to 108
        assert put_short < current_price
        assert call_short > current_price
        assert put_short == Decimal("92")
        assert call_short == Decimal("108")
        assert put_short % 2 == 0
        assert call_short % 2 == 0

    def test_calculate_short_strikes_large_price(self, strategy):
        """Test short strikes with larger price."""
        current_price = Decimal("550.00")
        put_short, call_short = strategy._calculate_short_strikes(current_price)

        # Put short: 8% below = 506, rounds to 506
        # Call short: 8% above = 594, rounds to 594
        assert put_short == Decimal("506")
        assert call_short == Decimal("594")

    def test_calculate_long_strikes(self, strategy):
        """Test long strike calculation ($5 wings)."""
        put_short = Decimal("92.00")
        call_short = Decimal("108.00")
        put_long, call_long = strategy._calculate_long_strikes(put_short, call_short)

        # Wings are $5 wide
        assert put_long == Decimal("87.00")  # 92 - 5
        assert call_long == Decimal("113.00")  # 108 + 5

    def test_calculate_max_profit_single_contract(self, strategy):
        """Test max profit with single contract."""
        credit_received = Decimal("2.50")

        max_profit = strategy._calculate_max_profit(credit_received, quantity=1)

        # 2.50 × 100 = $250
        assert max_profit == Decimal("250.00")

    def test_calculate_max_profit_multiple_contracts(self, strategy):
        """Test max profit with multiple contracts."""
        credit_received = Decimal("3.00")

        max_profit = strategy._calculate_max_profit(credit_received, quantity=2)

        # 3.00 × 100 × 2 = $600
        assert max_profit == Decimal("600.00")

    def test_calculate_max_loss_single_contract(self, strategy):
        """Test max loss with single contract."""
        wing_width = 5
        credit_received = Decimal("2.50")

        max_loss = strategy._calculate_max_loss(wing_width, credit_received, quantity=1)

        # (5 - 2.50) × 100 = $250
        assert max_loss == Decimal("250.00")

    def test_calculate_max_loss_multiple_contracts(self, strategy):
        """Test max loss with multiple contracts."""
        wing_width = 5
        credit_received = Decimal("2.00")

        max_loss = strategy._calculate_max_loss(wing_width, credit_received, quantity=2)

        # (5 - 2.00) × 100 × 2 = $600
        assert max_loss == Decimal("600.00")

    def test_calculate_breakevens(self, strategy):
        """Test breakeven calculation."""
        put_short_strike = Decimal("92.00")
        call_short_strike = Decimal("108.00")
        credit_received = Decimal("2.50")

        breakeven_down, breakeven_up = strategy._calculate_breakevens(
            put_short_strike, call_short_strike, credit_received
        )

        # Lower: 92 - 2.50 = 89.50
        # Upper: 108 + 2.50 = 110.50
        assert breakeven_down == Decimal("89.50")
        assert breakeven_up == Decimal("110.50")

    def test_calculate_breakevens_higher_credit(self, strategy):
        """Test breakevens with higher credit (wider profit zone)."""
        put_short_strike = Decimal("190.00")
        call_short_strike = Decimal("210.00")
        credit_received = Decimal("4.00")

        breakeven_down, breakeven_up = strategy._calculate_breakevens(
            put_short_strike, call_short_strike, credit_received
        )

        # Lower: 190 - 4 = 186
        # Upper: 210 + 4 = 214
        assert breakeven_down == Decimal("186.00")
        assert breakeven_up == Decimal("214.00")

    def test_profit_zone_width(self, strategy):
        """Test that profit zone is reasonable."""
        current_price = Decimal("100.00")
        put_short, call_short = strategy._calculate_short_strikes(current_price)
        credit = Decimal("2.50")
        breakeven_down, breakeven_up = strategy._calculate_breakevens(put_short, call_short, credit)

        # Profit zone should be ~16% wide (8% on each side)
        profit_zone_width = breakeven_up - breakeven_down
        assert profit_zone_width > Decimal("15.0")  # At least 15% wide
        assert profit_zone_width < Decimal("25.0")  # Not too wide


class TestShortIronCondorStrategyProperties:
    """Test strategy properties and configuration."""

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.strategy_name == "short_iron_condor"

    def test_automation_disabled_by_default(self, strategy):
        """Test that automation is disabled (needs active management)."""
        assert strategy.automation_enabled_by_default() is False

    def test_profit_targets_enabled(self, strategy):
        """Test that profit targets are enabled."""
        from unittest.mock import Mock

        mock_position = Mock()
        assert strategy.should_place_profit_targets(mock_position) is True

    def test_dte_exit_threshold(self, strategy):
        """Test DTE exit threshold (21 DTE to avoid gamma risk)."""
        from unittest.mock import Mock

        mock_position = Mock()
        threshold = strategy.get_dte_exit_threshold(mock_position)
        assert threshold == 21

    def test_constants(self, strategy):
        """Test strategy constants are set correctly."""
        assert strategy.MIN_IV_RANK == 45
        assert strategy.OPTIMAL_IV_RANK == 60
        assert strategy.MAX_ADX == 25
        assert strategy.IDEAL_ADX_MAX == 20
        assert strategy.TARGET_DELTA == 0.16
        assert strategy.WING_WIDTH == 5
        assert strategy.TARGET_DTE == 45
        assert strategy.PROFIT_TARGET_PCT == 50
