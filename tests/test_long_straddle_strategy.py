"""
Unit tests for LongStraddleStrategy.

Tests cover:
- Scoring logic for various market conditions
- IV rank scoring (LOW IV preferred for buying)
- HV/IV ratio scoring (want IV underpriced)
- ADX/trend analysis (strong trends preferred)
- Strike selection (ATM)
- Breakeven calculations
- Max loss calculations
- Net delta (should be near zero)
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.long_straddle_strategy import LongStraddleStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create LongStraddleStrategy instance."""
    return LongStraddleStrategy(mock_user)


@pytest.mark.asyncio
class TestLongStraddleScoring:
    """Test scoring logic for long straddle strategy."""

    async def test_ideal_conditions_low_iv_strong_trend(self, strategy):
        """Test scoring with ideal conditions (low IV, strong trend)."""
        report = create_neutral_market_report()
        # Ideal: IV < 20, HV/IV > 1.4, ADX > 35, neutral
        report.iv_rank = 18.0  # Very low - excellent for buying
        report.hv_iv_ratio = 1.45  # IV severely underpriced
        report.adx = 36.0  # Very strong trend
        report.macd_signal = "neutral"  # Direction unknown
        report.bollinger_position = "within_bands"  # Consolidation
        report.market_stress_level = 65.0  # High stress = volatility potential

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 + 30 (IV<20) + 25 (HV/IV>1.4) + 20 (ADX>35) + 15 (neutral) + 10 (middle BB) + 5 (high stress)
        assert score >= 100.0
        assert any("excellent value" in r.lower() for r in reasons)
        assert any("underpriced" in r.lower() for r in reasons)
        assert any("very strong trend" in r.lower() for r in reasons)

    async def test_poor_conditions_high_iv_weak_trend(self, strategy):
        """Test scoring with poor conditions (high IV, weak trend)."""
        report = create_neutral_market_report()
        # Poor: IV > 60, HV/IV < 0.9, ADX < 15, low stress
        report.iv_rank = 72.0  # Very high - expensive
        report.hv_iv_ratio = 0.68  # IV overpriced
        report.adx = 12.0  # Very weak trend
        report.macd_signal = "neutral"
        report.market_stress_level = 15.0  # Low stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 - 30 (IV>60) - 20 (HV/IV<0.9) - 10 (ADX<15) + 15 (neutral) - 5 (low stress) = 0
        assert score <= 15.0
        assert any("very expensive" in r.lower() for r in reasons)
        assert any("overpriced" in r.lower() for r in reasons)
        assert any("very weak trend" in r.lower() for r in reasons)

    async def test_iv_rank_below_20_excellent(self, strategy):
        """Test excellent score for IV rank < 20 (very cheap options)."""
        report = create_neutral_market_report()
        report.iv_rank = 15.0  # Bottom 15% - very cheap

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 70.0
        assert any("excellent value" in r.lower() and "very cheap" in r.lower() for r in reasons)

    async def test_iv_rank_20_30_good(self, strategy):
        """Test good score for IV rank 20-30."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0  # Optimal range

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 65.0
        assert any("optimal range" in r.lower() and "good value" in r.lower() for r in reasons)

    async def test_iv_rank_above_60_penalty(self, strategy):
        """Test penalty for IV rank > 60 (expensive)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0  # Very expensive

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score <= 40.0
        assert any("very expensive" in r.lower() and "avoid" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_4_excellent(self, strategy):
        """Test excellent score for HV/IV > 1.4 (IV severely underpriced)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.hv_iv_ratio = 1.5  # Severely underpriced

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 85.0
        assert any("severely underpriced" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_1_2_to_1_4_good(self, strategy):
        """Test good score for HV/IV 1.2-1.4 range."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.hv_iv_ratio = 1.3  # Underpriced

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 75.0
        assert any("underpriced" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_below_0_9_penalty(self, strategy):
        """Test penalty for HV/IV < 0.9 (IV overpriced)."""
        report = create_neutral_market_report()
        report.iv_rank = 35.0
        report.hv_iv_ratio = 0.75  # Overpriced

        _score, reasons = await strategy._score_market_conditions_impl(report)

        # Note: penalty is -20, but other factors still contribute
        assert any("overpriced" in r.lower() and "poor buying" in r.lower() for r in reasons)

    async def test_adx_above_35_very_strong(self, strategy):
        """Test bonus for ADX > 35 (very strong trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 38.0  # Very strong

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very strong trend" in r.lower() and "big move" in r.lower() for r in reasons)

    async def test_adx_25_35_strong(self, strategy):
        """Test bonus for ADX 25-35 range."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 28.0  # Strong

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("strong trend" in r.lower() for r in reasons)

    async def test_adx_below_15_penalty(self, strategy):
        """Test penalty for ADX < 15 (weak trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 12.0  # Weak

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very weak trend" in r.lower() and "unlikely" in r.lower() for r in reasons)

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets suggest potential for move."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.macd_signal = "neutral"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        # "Neutral market - potential for move in either direction"
        assert any(
            "neutral market" in r.lower() and "either direction" in r.lower()
            for r in reasons
        )

    async def test_directional_market_acceptable(self, strategy):
        """Test that bullish/bearish markets are acceptable."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.macd_signal = "bullish"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        # "Bullish direction - some potential for move"
        assert any("potential for move" in r.lower() for r in reasons)

    async def test_bollinger_within_bands_consolidation_bonus(self, strategy):
        """Test bonus for price in middle of Bollinger Bands."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.bollinger_position = "within_bands"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("consolidation before expansion" in r.lower() for r in reasons)

    async def test_bollinger_extremes_bonus(self, strategy):
        """Test bonus for price at Bollinger extremes."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.bollinger_position = "above_upper"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("extremes" in r.lower() and "big move" in r.lower() for r in reasons)

    async def test_high_market_stress_bonus(self, strategy):
        """Test bonus for high market stress (volatility potential)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.market_stress_level = 75.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "elevated market stress" in r.lower() and "expansion potential" in r.lower()
            for r in reasons
        )

    async def test_low_market_stress_penalty(self, strategy):
        """Test penalty for very low market stress."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.market_stress_level = 15.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very low" in r.lower() and "lack catalyst" in r.lower() for r in reasons)


class TestLongStraddleCalculations:
    """Test calculation methods."""

    def test_find_atm_strike(self, strategy):
        """Test ATM strike selection."""
        current_price = Decimal("550.00")
        strike = strategy._find_atm_strike(current_price)

        # Should round to nearest even strike
        assert strike == Decimal("550")  # Rounds to 550

    def test_find_atm_strike_odd_price(self, strategy):
        """Test ATM strike with odd price."""
        current_price = Decimal("553.75")
        strike = strategy._find_atm_strike(current_price)

        # Should round to nearest even: 553.75 -> 554
        assert strike == Decimal("554")
        assert strike % 2 == 0

    def test_calculate_breakevens(self, strategy):
        """Test breakeven calculation."""
        strike = Decimal("100.00")
        total_debit = Decimal("8.00")  # $5 call + $3 put

        breakeven_up, breakeven_down = strategy._calculate_breakevens(strike, total_debit)

        assert breakeven_up == Decimal("108.00")  # Strike + debit
        assert breakeven_down == Decimal("92.00")  # Strike - debit

    def test_calculate_breakevens_high_debit(self, strategy):
        """Test breakevens with higher debit."""
        strike = Decimal("200.00")
        total_debit = Decimal("15.50")

        breakeven_up, breakeven_down = strategy._calculate_breakevens(strike, total_debit)

        assert breakeven_up == Decimal("215.50")
        assert breakeven_down == Decimal("184.50")

    def test_calculate_max_loss_single_contract(self, strategy):
        """Test max loss with single contract."""
        call_premium = Decimal("5.00")
        put_premium = Decimal("3.00")

        max_loss = strategy._calculate_max_loss(call_premium, put_premium, quantity=1)

        # (5 + 3) × 100 = $800
        assert max_loss == Decimal("800.00")

    def test_calculate_max_loss_multiple_contracts(self, strategy):
        """Test max loss with multiple contracts."""
        call_premium = Decimal("5.00")
        put_premium = Decimal("3.00")

        max_loss = strategy._calculate_max_loss(call_premium, put_premium, quantity=3)

        # (5 + 3) × 100 × 3 = $2,400
        assert max_loss == Decimal("2400.00")

    def test_calculate_net_delta_balanced(self, strategy):
        """Test net delta calculation (should be near zero)."""
        call_delta = 0.52  # Positive (long call)
        put_delta = -0.48  # Negative (long put)

        net_delta = strategy._calculate_net_delta(call_delta, put_delta)

        # Should be very close to zero
        assert abs(net_delta) < 0.10
        assert net_delta == pytest.approx(0.04, abs=1e-9)

    def test_calculate_net_delta_perfect_atm(self, strategy):
        """Test net delta with perfect ATM (both 0.50)."""
        call_delta = 0.50
        put_delta = -0.50

        net_delta = strategy._calculate_net_delta(call_delta, put_delta)

        assert net_delta == 0.0  # Perfect delta neutral


class TestLongStraddleStrategyProperties:
    """Test strategy properties and configuration."""

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.strategy_name == "long_straddle"

    def test_automation_disabled_by_default(self, strategy):
        """Test that automation is disabled (high risk, timing critical)."""
        assert strategy.automation_enabled_by_default() is False

    def test_profit_targets_enabled(self, strategy):
        """Test that profit targets are enabled."""
        from unittest.mock import Mock

        mock_position = Mock()
        assert strategy.should_place_profit_targets(mock_position) is True

    def test_dte_exit_threshold(self, strategy):
        """Test DTE exit threshold (21 DTE to avoid rapid decay)."""
        from unittest.mock import Mock

        mock_position = Mock()
        threshold = strategy.get_dte_exit_threshold(mock_position)
        assert threshold == 21

    def test_constants(self, strategy):
        """Test strategy constants are set correctly."""
        assert strategy.MAX_IV_RANK == 40
        assert strategy.OPTIMAL_IV_RANK == 25
        assert strategy.MIN_HV_IV_RATIO == 1.1
        assert strategy.OPTIMAL_HV_IV_RATIO == 1.3
        assert strategy.MIN_ADX_TREND == 20
        assert strategy.OPTIMAL_ADX == 30
        assert strategy.PROFIT_TARGET_PCT == 50
