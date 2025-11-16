"""
Unit tests for LongCallRatioBackspreadStrategy.

Tests cover:
- Scoring logic for bullish trend conditions
- Bullish bias requirement (hard stop if not bullish)
- Trend strength scoring (ADX > 25)
- IV rank scoring (LOW IV preferred - < 40)
- HV/IV ratio scoring (want underpriced options > 1.2)
- Strike selection (2:1 ratio)
- Danger zone calculations
- Breakeven calculations
- Complex risk profile
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.call_backspread_strategy import LongCallRatioBackspreadStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create LongCallRatioBackspreadStrategy instance."""
    return LongCallRatioBackspreadStrategy(mock_user)


@pytest.mark.asyncio
class TestCallBackspreadScoring:
    """Test scoring logic for call backspread strategy."""

    async def test_ideal_conditions_strong_bullish_low_iv(self, strategy):
        """Test scoring with ideal conditions (strong bullish + low IV + underpriced)."""
        report = create_neutral_market_report()
        # Ideal: strong bullish, ADX > 35, IV < 25, HV/IV > 1.3
        report.macd_signal = "strong_bullish"
        report.adx = 38.0  # Very strong trend
        report.iv_rank = 22.0  # Low IV (cheap calls)
        report.hv_iv_ratio = 1.35  # Options severely underpriced
        report.market_stress_level = 30.0  # Low stress
        report.recent_move_pct = 3.5  # Moderate bullish momentum

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 30 + 30 (strong bull) + 25 (ADX>35) + 20 (IV<25) + 15 (HV/IV>1.3) + 10 (low IV expansion) + 5 (moderate move) + 5 (low stress)
        assert score >= 120.0
        assert any("strong bullish" in r.lower() and "excellent" in r.lower() for r in reasons)
        assert any("very strong trend" in r.lower() for r in reasons)
        assert any("options cheap" in r.lower() for r in reasons)

    async def test_hard_stop_not_bullish(self, strategy):
        """Test hard stop when market is not bullish."""
        report = create_neutral_market_report()
        report.macd_signal = "neutral"  # Not bullish
        report.adx = 30.0
        report.iv_rank = 25.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score == 0.0  # HARD STOP
        assert any("not bullish" in r.lower() for r in reasons)
        assert any("requires strong bullish outlook" in r.lower() for r in reasons)

    async def test_hard_stop_bearish(self, strategy):
        """Test hard stop when market is bearish."""
        report = create_neutral_market_report()
        report.macd_signal = "bearish"
        report.adx = 30.0
        report.iv_rank = 25.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score == 0.0
        assert any("not bullish" in r.lower() for r in reasons)

    async def test_poor_conditions_weak_trend_high_iv(self, strategy):
        """Test scoring with poor conditions (weak trend, high IV)."""
        report = create_neutral_market_report()
        # Poor: bullish but weak trend, high IV, expensive options
        report.macd_signal = "bullish"  # Minimum to avoid hard stop
        report.adx = 18.0  # Weak trend
        report.iv_rank = 55.0  # High IV (expensive)
        report.hv_iv_ratio = 0.95  # Options not underpriced
        report.market_stress_level = 75.0  # High stress
        report.recent_move_pct = 12.0  # Exhaustion risk

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 30 + 20 (bullish) - 20 (weak trend) - 15 (high IV) - 10 (HV/IV low) - 10 (high stress) - 10 (large move)
        assert score <= 10.0
        assert any(
            "weak trend" in r.lower() or "insufficient momentum" in r.lower() for r in reasons
        )
        assert any("expensive" in r.lower() for r in reasons)

    async def test_strong_bullish_bonus(self, strategy):
        """Test bonus for strong bullish signal."""
        report = create_neutral_market_report()
        report.macd_signal = "strong_bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("strong bullish" in r.lower() and "excellent" in r.lower() for r in reasons)

    async def test_bullish_acceptable(self, strategy):
        """Test acceptable score for bullish (not strong) signal."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 50.0
        assert any("bullish" in r.lower() and "prefer stronger" in r.lower() for r in reasons)

    async def test_adx_above_35_excellent(self, strategy):
        """Test excellent score for ADX > 35 (very strong trend)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 38.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "very strong trend" in r.lower() and "high probability" in r.lower() for r in reasons
        )

    async def test_adx_25_35_favorable(self, strategy):
        """Test favorable score for ADX 25-35 (strong trend)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 28.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("strong trend" in r.lower() and "favorable" in r.lower() for r in reasons)

    async def test_adx_below_20_penalty(self, strategy):
        """Test penalty for ADX < 20 (weak trend)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 18.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "weak trend" in r.lower() or "insufficient momentum" in r.lower() for r in reasons
        )

    async def test_iv_rank_below_25_ideal(self, strategy):
        """Test ideal score for IV rank < 25 (cheap calls)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 22.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("cheap to buy" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_iv_rank_25_40_acceptable(self, strategy):
        """Test acceptable score for IV rank 25-40."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 35.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("acceptable for buying calls" in r.lower() for r in reasons)

    async def test_iv_rank_above_50_penalty(self, strategy):
        """Test penalty for IV rank > 50 (expensive)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 55.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("too expensive to buy calls" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_3_excellent(self, strategy):
        """Test excellent score for HV/IV > 1.3 (severely underpriced)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.35

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("severely underpriced" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_1_2_1_3_favorable(self, strategy):
        """Test favorable score for HV/IV 1.2-1.3."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("underpriced vs realized" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_below_1_0_penalty(self, strategy):
        """Test penalty for HV/IV < 1.0 (not underpriced)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 0.95

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("not underpriced" in r.lower() for r in reasons)

    async def test_moderate_momentum_bonus(self, strategy):
        """Test bonus for moderate bullish momentum."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25
        report.recent_move_pct = 3.5

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "moderate bullish momentum" in r.lower() and "trend developing" in r.lower()
            for r in reasons
        )

    async def test_exhaustion_penalty(self, strategy):
        """Test penalty for potential exhaustion (large recent move)."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25
        report.recent_move_pct = 12.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("exhausted" in r.lower() or "risky" in r.lower() for r in reasons)

    async def test_danger_zone_warning_present(self, strategy):
        """Test that danger zone warning is always present."""
        report = create_neutral_market_report()
        report.macd_signal = "bullish"
        report.adx = 30.0
        report.iv_rank = 30.0
        report.hv_iv_ratio = 1.25

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("advanced strategy" in r.lower() and "danger zone" in r.lower() for r in reasons)


@pytest.mark.asyncio
class TestCallBackspreadCalculations:
    """Test calculation methods for call backspread."""

    def test_strike_selection(self, strategy):
        """Test strike selection with 2:1 ratio."""
        current_price = Decimal("550.00")
        strikes = strategy._select_strikes(current_price)

        # Verify ATM short call
        assert abs(strikes["short_call"] - current_price) < Decimal("5")

        # Verify OTM long calls (~5% above)
        expected_long = current_price * Decimal("1.05")
        assert abs(strikes["long_calls"] - expected_long) < Decimal("10")

        # Verify 2:1 ratio
        assert strikes["quantity_short"] == 1
        assert strikes["quantity_long"] == 2

    def test_danger_zone_calculation_with_credit(self, strategy):
        """Test danger zone calculation when position opened for credit."""
        short_strike = Decimal("550.00")
        long_strike = Decimal("565.00")
        credit = Decimal("1.00")  # Received $1.00 credit

        danger = strategy._calculate_danger_zone(short_strike, long_strike, credit)

        # Danger zone at long strikes
        assert danger["danger_zone_price"] == Decimal("565.00")

        # Max loss = (long - short) - credit = 15 - 1 = $14 per spread
        assert danger["max_loss_per_spread"] == Decimal("14.00")
        assert danger["max_loss_total"] == Decimal("1400.00")  # × 100

        # Probability ~25%
        assert danger["probability"] == 0.25

        # Warning message
        assert "Max loss" in danger["warning"]
        assert "$1400" in danger["warning"]
        assert "$565" in danger["warning"]

    def test_danger_zone_calculation_with_debit(self, strategy):
        """Test danger zone calculation when position opened for debit."""
        short_strike = Decimal("550.00")
        long_strike = Decimal("565.00")
        debit = Decimal("-0.50")  # Paid $0.50 debit (negative)

        danger = strategy._calculate_danger_zone(short_strike, long_strike, debit)

        # Max loss = (long - short) - debit = 15 - (-0.50) = 15 + 0.50 = $15.50
        assert danger["max_loss_per_spread"] == Decimal("15.50")
        assert danger["max_loss_total"] == Decimal("1550.00")

    def test_breakeven_calculation_with_credit(self, strategy):
        """Test breakeven calculation when opened for credit."""
        short_strike = Decimal("550.00")
        long_strike = Decimal("565.00")
        credit = Decimal("1.00")

        lower_be, upper_be = strategy._calculate_breakevens(short_strike, long_strike, credit)

        # Spread width = 15
        # Adjustment = 15 - 1 = 14
        # Lower BE = 550 + 14 = 564
        # Upper BE = 565 + 14 = 579
        assert lower_be == Decimal("564.00")
        assert upper_be == Decimal("579.00")

    def test_breakeven_calculation_with_debit(self, strategy):
        """Test breakeven calculation when opened for debit."""
        short_strike = Decimal("550.00")
        long_strike = Decimal("565.00")
        debit = Decimal("-0.50")

        lower_be, upper_be = strategy._calculate_breakevens(short_strike, long_strike, debit)

        # Spread width = 15
        # Adjustment = 15 - (-0.50) = 15.50
        # Lower BE = 550 + 15.50 = 565.50
        # Upper BE = 565 + 15.50 = 580.50
        assert lower_be == Decimal("565.50")
        assert upper_be == Decimal("580.50")

    def test_ratio_configuration(self, strategy):
        """Test that ratio is configured correctly."""
        assert strategy.SELL_QUANTITY == 1
        assert strategy.BUY_QUANTITY == 2
        assert strategy.RATIO == 2.0

    def test_otm_distance_configuration(self, strategy):
        """Test OTM distance configuration."""
        assert strategy.OTM_DISTANCE_PCT == 5.0
