"""
Unit tests for LongStrangleStrategy.

Tests cover:
- Scoring logic for various market conditions
- IV rank scoring (VERY LOW IV preferred - stricter than straddle)
- HV/IV ratio scoring (want IV severely underpriced)
- ADX/trend analysis (very strong trends preferred - stricter than straddle)
- OTM strike selection (5% on each side)
- Breakeven calculations
- Max loss calculations
- Net delta (should be near zero)
- Move required calculations
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.long_strangle_strategy import LongStrangleStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create LongStrangleStrategy instance."""
    return LongStrangleStrategy(mock_user)


@pytest.mark.asyncio
class TestLongStrangleScoring:
    """Test scoring logic for long strangle strategy."""

    async def test_ideal_conditions_very_low_iv_strong_trend(self, strategy):
        """Test scoring with ideal conditions (very low IV, very strong trend)."""
        report = create_neutral_market_report()
        # Ideal: IV < 20, HV/IV > 1.5, ADX > 40, neutral
        report.iv_rank = 18.0  # Exceptional - OTM options dirt cheap
        report.hv_iv_ratio = 1.52  # IV severely underpriced
        report.adx = 42.0  # Extremely strong trend
        report.macd_signal = "neutral"  # Direction unknown
        report.bollinger_position = "within_bands"  # Consolidation
        report.market_stress_level = 75.0  # Very high stress = volatility potential

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 + 35 (IV<20) + 25 (HV/IV>1.5) + 25 (ADX>40) + 10 (neutral) + 5 (middle) + 8 (high stress)
        assert score >= 100.0
        assert any("exceptional value" in r.lower() and "dirt cheap" in r.lower() for r in reasons)
        assert any("severely underpriced" in r.lower() for r in reasons)
        assert any(
            "extremely strong trend" in r.lower() and "massive" in r.lower() for r in reasons
        )

    async def test_poor_conditions_high_iv_weak_trend(self, strategy):
        """Test scoring with poor conditions (high IV, weak trend)."""
        report = create_neutral_market_report()
        # Poor: IV > 50, HV/IV < 0.9, ADX < 15
        report.iv_rank = 62.0  # Very high - expensive
        report.hv_iv_ratio = 0.78  # IV overpriced
        report.adx = 13.0  # Very weak trend
        report.market_stress_level = 15.0  # Low stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 - 35 (IV>50) - 25 (HV/IV<0.9) - 15 (ADX<15) + 5 (neutral) - 8 (low stress) = -28 -> 0
        assert score <= 15.0
        assert any("very expensive" in r.lower() for r in reasons)
        assert any("overpriced" in r.lower() and "very poor" in r.lower() for r in reasons)
        assert any("very weak trend" in r.lower() and "avoid" in r.lower() for r in reasons)

    async def test_iv_rank_below_20_exceptional(self, strategy):
        """Test exceptional score for IV rank < 20 (dirt cheap)."""
        report = create_neutral_market_report()
        report.iv_rank = 15.0  # Bottom 15% - dirt cheap

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 75.0
        assert any("exceptional value" in r.lower() and "dirt cheap" in r.lower() for r in reasons)

    async def test_iv_rank_20_25_excellent(self, strategy):
        """Test excellent score for IV rank 20-25 (optimal range)."""
        report = create_neutral_market_report()
        report.iv_rank = 22.0  # Optimal range

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 70.0
        assert any("optimal range" in r.lower() and "excellent" in r.lower() for r in reasons)

    async def test_iv_rank_25_30_suggest_straddle(self, strategy):
        """Test that IV 25-30 suggests straddle may be better."""
        report = create_neutral_market_report()
        report.iv_rank = 28.0  # Acceptable but not ideal for strangle

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("straddle may be better" in r.lower() for r in reasons)

    async def test_iv_rank_above_50_avoid(self, strategy):
        """Test strong penalty for IV rank > 50."""
        report = create_neutral_market_report()
        report.iv_rank = 65.0  # Very expensive

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score <= 30.0
        assert any("very expensive" in r.lower() and "avoid" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_5_perfect(self, strategy):
        """Test perfect score for HV/IV > 1.5 (severely underpriced)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.hv_iv_ratio = 1.6  # Severely underpriced

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 90.0
        assert any("severely underpriced" in r.lower() and "perfect" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_1_3_to_1_5_significant(self, strategy):
        """Test good score for HV/IV 1.3-1.5 range."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.hv_iv_ratio = 1.4  # Significantly underpriced

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 80.0
        assert any("significantly underpriced" in r.lower() for r in reasons)

    async def test_adx_above_40_extreme(self, strategy):
        """Test bonus for ADX > 40 (extremely strong trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.adx = 45.0  # Extremely strong

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "extremely strong trend" in r.lower() and "massive move likely" in r.lower()
            for r in reasons
        )

    async def test_adx_30_40_very_strong(self, strategy):
        """Test bonus for ADX 30-40 range."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.adx = 35.0  # Very strong

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very strong trend" in r.lower() for r in reasons)

    async def test_adx_25_30_suggest_straddle(self, strategy):
        """Test that ADX 25-30 suggests considering straddle."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.adx = 28.0  # Moderate-strong

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("consider straddle" in r.lower() for r in reasons)

    async def test_adx_below_15_avoid(self, strategy):
        """Test penalty for ADX < 15 (very weak trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.adx = 12.0  # Very weak

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "very weak trend" in r.lower() and "avoid strangle" in r.lower() for r in reasons
        )

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets are ideal (massive move direction unknown)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.macd_signal = "neutral"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "ideal for strangle" in r.lower() and "direction unknown" in r.lower() for r in reasons
        )

    async def test_very_high_market_stress_bonus(self, strategy):
        """Test bonus for very high market stress (extreme volatility potential)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.market_stress_level = 75.0  # Very high

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "very high market stress" in r.lower() and "extreme" in r.lower() for r in reasons
        )

    async def test_very_low_market_stress_penalty(self, strategy):
        """Test penalty for very low market stress (no catalyst)."""
        report = create_neutral_market_report()
        report.iv_rank = 20.0
        report.market_stress_level = 15.0  # Very low

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very low" in r.lower() and "10%+ move required" in r.lower() for r in reasons)


class TestLongStrangleCalculations:
    """Test calculation methods."""

    def test_find_otm_strikes(self, strategy):
        """Test OTM strike selection (5% on each side)."""
        current_price = Decimal("100.00")
        call_strike, put_strike = strategy._find_otm_strikes(current_price)

        # Call: 5% above = 105, rounds to 104 (105/2=52.5, round to 52, *2=104)
        # Put: 5% below = 95, rounds to 96 (95/2=47.5, round to 48, *2=96)
        assert call_strike > current_price
        assert put_strike < current_price
        assert call_strike == Decimal("104")  # 105 rounds to 104
        assert put_strike == Decimal("96")  # 95 rounds to 96
        assert call_strike % 2 == 0
        assert put_strike % 2 == 0

    def test_find_otm_strikes_large_price(self, strategy):
        """Test OTM strikes with larger price."""
        current_price = Decimal("550.00")
        call_strike, put_strike = strategy._find_otm_strikes(current_price)

        # Call: 5% above = 577.50, rounds to 578
        # Put: 5% below = 522.50, rounds to 522
        assert call_strike == Decimal("578")
        assert put_strike == Decimal("522")

    def test_calculate_breakevens(self, strategy):
        """Test breakeven calculation."""
        call_strike = Decimal("105.00")
        put_strike = Decimal("95.00")
        total_debit = Decimal("4.50")  # $2.50 call + $2.00 put

        breakeven_up, breakeven_down = strategy._calculate_breakevens(
            call_strike, put_strike, total_debit
        )

        assert breakeven_up == Decimal("109.50")  # Call strike + debit
        assert breakeven_down == Decimal("90.50")  # Put strike - debit

    def test_calculate_breakevens_higher_cost(self, strategy):
        """Test breakevens with higher cost strangle."""
        call_strike = Decimal("210.00")
        put_strike = Decimal("190.00")
        total_debit = Decimal("8.00")

        breakeven_up, breakeven_down = strategy._calculate_breakevens(
            call_strike, put_strike, total_debit
        )

        assert breakeven_up == Decimal("218.00")
        assert breakeven_down == Decimal("182.00")

    def test_calculate_max_loss_single_contract(self, strategy):
        """Test max loss with single contract."""
        call_premium = Decimal("2.50")
        put_premium = Decimal("2.00")

        max_loss = strategy._calculate_max_loss(call_premium, put_premium, quantity=1)

        # (2.50 + 2.00) × 100 = $450
        assert max_loss == Decimal("450.00")

    def test_calculate_max_loss_multiple_contracts(self, strategy):
        """Test max loss with multiple contracts."""
        call_premium = Decimal("3.00")
        put_premium = Decimal("2.50")

        max_loss = strategy._calculate_max_loss(call_premium, put_premium, quantity=2)

        # (3.00 + 2.50) × 100 × 2 = $1,100
        assert max_loss == Decimal("1100.00")

    def test_calculate_net_delta_otm_balanced(self, strategy):
        """Test net delta calculation with OTM options (lower deltas)."""
        call_delta = 0.35  # Positive (OTM long call, lower than ATM's 0.50)
        put_delta = -0.30  # Negative (OTM long put, lower magnitude than ATM's 0.50)

        net_delta = strategy._calculate_net_delta(call_delta, put_delta)

        # Should be very close to zero
        assert abs(net_delta) < 0.10
        assert net_delta == pytest.approx(0.05, abs=1e-9)

    def test_calculate_move_required_pct(self, strategy):
        """Test calculation of percentage move required."""
        current_price = Decimal("100.00")
        breakeven_up = Decimal("110.00")
        breakeven_down = Decimal("90.00")

        upside_pct, downside_pct = strategy._calculate_move_required_pct(
            current_price, breakeven_up, breakeven_down
        )

        # (110 - 100) / 100 = 10% upside
        # (100 - 90) / 100 = 10% downside
        assert upside_pct == Decimal("10.00")
        assert downside_pct == Decimal("10.00")

    def test_calculate_move_required_pct_asymmetric(self, strategy):
        """Test move required with asymmetric breakevens."""
        current_price = Decimal("200.00")
        breakeven_up = Decimal("225.00")
        breakeven_down = Decimal("175.00")

        upside_pct, downside_pct = strategy._calculate_move_required_pct(
            current_price, breakeven_up, breakeven_down
        )

        # (225 - 200) / 200 = 12.5% upside
        # (200 - 175) / 200 = 12.5% downside
        assert upside_pct == Decimal("12.50")
        assert downside_pct == Decimal("12.50")


class TestLongStrangleStrategyProperties:
    """Test strategy properties and configuration."""

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.strategy_name == "long_strangle"

    def test_automation_disabled_by_default(self, strategy):
        """Test that automation is disabled (very high risk, timing critical)."""
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
        """Test strategy constants are set correctly (stricter than straddle)."""
        assert strategy.MAX_IV_RANK == 35  # Stricter than straddle's 40
        assert strategy.OPTIMAL_IV_RANK == 20  # Stricter than straddle's 25
        assert strategy.MIN_HV_IV_RATIO == 1.1
        assert strategy.OPTIMAL_HV_IV_RATIO == 1.4  # Higher than straddle's 1.3
        assert strategy.MIN_ADX_TREND == 25  # Stricter than straddle's 20
        assert strategy.OPTIMAL_ADX == 35  # Stricter than straddle's 30
        assert strategy.OTM_PERCENTAGE == 0.05  # 5% OTM
        assert strategy.PROFIT_TARGET_PCT == 100  # Higher than straddle's 50
