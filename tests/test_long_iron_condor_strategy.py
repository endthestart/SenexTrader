"""
Unit tests for LongIronCondorStrategy.

Tests cover:
- Scoring logic for various market conditions (OPPOSITE of Short Iron Condor)
- IV rank scoring (LOW IV required - < 40% ideal)
- ADX scoring (range-bound required - < 20 ideal)
- HV/IV ratio scoring (want IV contracting - < 1.0)
- Strike selection (profit zone structure)
- Max profit/loss calculations
- Breakeven calculations
- Risk-reward ratio validation
- Comparison with Short Iron Condor requirements
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.long_iron_condor_strategy import LongIronCondorStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create LongIronCondorStrategy instance."""
    return LongIronCondorStrategy(mock_user)


@pytest.mark.asyncio
class TestLongIronCondorScoring:
    """Test scoring logic for long iron condor strategy."""

    async def test_ideal_conditions_low_iv_range_bound(self, strategy):
        """Test scoring with ideal conditions (IV < 20, ADX < 20)."""
        report = create_neutral_market_report()
        # Ideal: IV < 20, ADX < 20, HV/IV < 0.8, neutral direction
        report.iv_rank = 18.0  # Very low (cheap options)
        report.adx = 15.0  # Range-bound
        report.hv_iv_ratio = 0.75  # Volatility contracting
        report.macd_signal = "neutral"  # No directional bias
        report.bollinger_position = "within_bands"  # Not at extremes
        report.market_stress_level = 30.0  # Low stress
        report.recent_move_pct = 1.0  # Minimal movement

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 + 35 (IV<20) + 25 (ADX<20) + 20 (HV/IV<0.8) + 15 (neutral) + 10 (middle) + 10 (low stress) + 5 (minimal move)
        assert score >= 140.0
        assert any("exceptionally cheap" in r.lower() and "ideal" in r.lower() for r in reasons)
        assert any("range-bound" in r.lower() and "ideal" in r.lower() for r in reasons)
        assert any("contracting" in r.lower() for r in reasons)

    async def test_hard_stop_high_iv(self, strategy):
        """Test hard stop when IV > 50 (use Short Iron Condor instead)."""
        report = create_neutral_market_report()
        report.iv_rank = 55.0  # Too high for long condor
        report.adx = 15.0
        report.hv_iv_ratio = 0.9

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score == 0.0  # HARD STOP
        assert any("SHORT Iron Condor" in r for r in reasons)
        assert any("SELL premium" in r for r in reasons)

    async def test_poor_conditions_high_iv_strong_trend(self, strategy):
        """Test scoring with poor conditions (high IV boundary, strong trend)."""
        report = create_neutral_market_report()
        # Poor: IV = 48 (near limit), ADX > 30, HV/IV > 1.3
        report.iv_rank = 48.0  # High but not hard stop
        report.adx = 35.0  # Strong trend
        report.hv_iv_ratio = 1.35  # High realized volatility
        report.macd_signal = "strong_bullish"  # Strong direction
        report.bollinger_position = "above_upper"  # At extremes
        report.market_stress_level = 65.0  # High stress
        report.recent_move_pct = 6.0  # Large move

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 - 15 (IV elevated) - 30 (strong trend) - 10 (HV/IV high) - 20 (strong direction) - 5 (extremes) - 15 (high stress) - 10 (large move)
        assert score <= 0.0
        assert any("avoid" in r.lower() for r in reasons)
        assert any("strong trend" in r.lower() for r in reasons)

    async def test_iv_rank_below_20_excellent(self, strategy):
        """Test excellent score for IV rank < 20."""
        report = create_neutral_market_report()
        report.iv_rank = 18.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 80.0
        assert any("exceptionally cheap" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_iv_rank_20_30_excellent(self, strategy):
        """Test excellent score for IV rank 20-30."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 75.0
        assert any("excellent low iv" in r.lower() for r in reasons)

    async def test_iv_rank_30_40_acceptable(self, strategy):
        """Test acceptable score for IV rank 30-40."""
        report = create_neutral_market_report()
        report.iv_rank = 35.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 65.0
        assert any("acceptable" in r.lower() for r in reasons)

    async def test_iv_rank_above_40_penalty(self, strategy):
        """Test penalty for IV rank > 40 but < 50."""
        report = create_neutral_market_report()
        report.iv_rank = 45.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("elevated" in r.lower() and "short iron condor" in r.lower() for r in reasons)

    async def test_adx_below_20_ideal(self, strategy):
        """Test ideal score for ADX < 20 (range-bound)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 15.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("range-bound" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_adx_20_25_favorable(self, strategy):
        """Test good score for ADX 20-25 (weak trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 22.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("weak trend" in r.lower() and "favorable" in r.lower() for r in reasons)

    async def test_adx_above_30_avoid(self, strategy):
        """Test penalty for ADX > 30 (strong trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.adx = 35.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("avoid" in r.lower() for r in reasons)
        assert any("directional move" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_below_0_8_excellent(self, strategy):
        """Test excellent score for HV/IV < 0.8 (volatility contracting)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.hv_iv_ratio = 0.75

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("contracting" in r.lower() and "excellent" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_0_8_1_0_moderate(self, strategy):
        """Test moderate score for HV/IV 0.8-1.0."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.hv_iv_ratio = 0.9

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("moderate" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_3_penalty(self, strategy):
        """Test penalty for HV/IV > 1.3 (high realized volatility)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.hv_iv_ratio = 1.35

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("high" in r.lower() and "risky" in r.lower() for r in reasons)

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets are ideal (no directional bias)."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.macd_signal = "neutral"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("ideal for iron condor" in r.lower() for r in reasons)

    async def test_strong_directional_bias_penalty(self, strategy):
        """Test penalty for strong directional bias."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.macd_signal = "strong_bearish"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("reduces probability" in r.lower() for r in reasons)

    async def test_bollinger_within_bands_bonus(self, strategy):
        """Test bonus for price in middle of Bollinger Bands."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.bollinger_position = "within_bands"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("centered in range" in r.lower() for r in reasons)

    async def test_bollinger_extremes_penalty(self, strategy):
        """Test penalty for price at Bollinger extremes."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.bollinger_position = "below_lower"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("potential for continued move" in r.lower() for r in reasons)

    async def test_low_market_stress_bonus(self, strategy):
        """Test bonus for low market stress."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.market_stress_level = 30.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("stable environment" in r.lower() for r in reasons)

    async def test_high_market_stress_penalty(self, strategy):
        """Test penalty for high market stress."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.market_stress_level = 70.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("increased risk" in r.lower() and "breakout" in r.lower() for r in reasons)

    async def test_minimal_movement_bonus(self, strategy):
        """Test bonus for minimal recent movement."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.recent_move_pct = 1.5

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("consolidating" in r.lower() for r in reasons)

    async def test_large_movement_penalty(self, strategy):
        """Test penalty for large recent movement."""
        report = create_neutral_market_report()
        report.iv_rank = 25.0
        report.recent_move_pct = 6.5

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("may continue trending" in r.lower() for r in reasons)


@pytest.mark.asyncio
class TestLongIronCondorCalculations:
    """Test calculation methods for long iron condor."""

    def test_strike_selection(self, strategy):
        """Test strike selection creates proper profit zone."""
        current_price = Decimal("550.00")
        strikes = strategy._select_strikes(current_price, target_profit_zone_pct=10.0)

        # Verify structure: outer_put < inner_put < current < inner_call < outer_call
        assert strikes["outer_put"] < strikes["inner_put"]
        assert strikes["inner_put"] < current_price
        assert current_price < strikes["inner_call"]
        assert strikes["inner_call"] < strikes["outer_call"]

        # Verify profit zone width (~10% of price)
        profit_zone = strikes["inner_call"] - strikes["inner_put"]
        expected_zone = current_price * Decimal("0.10")

        assert abs(profit_zone - expected_zone) < Decimal("10")  # Within $10

    def test_profit_zone_width_calculation(self, strategy):
        """Test profit zone width calculation."""
        strikes = {
            "outer_put": Decimal("520.00"),
            "inner_put": Decimal("525.00"),
            "inner_call": Decimal("575.00"),
            "outer_call": Decimal("580.00"),
        }

        width = strategy._calculate_profit_zone_width(strikes)

        # Width = 575 - 525 = $50
        assert width == Decimal("50.00")

    def test_max_profit_calculation(self, strategy):
        """Test max profit formula."""
        put_spread_width = Decimal("5.00")
        call_spread_width = Decimal("5.00")
        debit_paid = Decimal("2.00")

        max_profit = strategy._calculate_max_profit(put_spread_width, call_spread_width, debit_paid)

        # Max profit = $5 (wing width) - $2 (total debit) = $3
        # Occurs when one spread maxes out, other expires worthless
        assert max_profit == Decimal("3.00")

    def test_max_loss_calculation(self, strategy):
        """Test max loss formula."""
        debit_paid = Decimal("2.50")

        max_loss = strategy._calculate_max_loss(debit_paid)

        # Max loss = debit paid
        assert max_loss == Decimal("2.50")

    def test_breakeven_calculation(self, strategy):
        """Test breakeven point calculation."""
        strikes = {
            "outer_put": Decimal("520.00"),
            "inner_put": Decimal("525.00"),
            "inner_call": Decimal("575.00"),
            "outer_call": Decimal("580.00"),
        }
        debit_paid = Decimal("2.00")

        lower_be, upper_be = strategy._calculate_breakeven_points(strikes, debit_paid)

        # Lower BE = 525 + 1 = 526
        # Upper BE = 575 - 1 = 574
        assert lower_be == Decimal("526.00")
        assert upper_be == Decimal("574.00")

    def test_risk_reward_ratio_calculation(self, strategy):
        """Test risk-reward calculation."""
        max_profit = Decimal("8.00")
        max_loss = Decimal("2.00")

        ratio = strategy._calculate_risk_reward_ratio(max_profit, max_loss)

        # 8/2 = 4:1 ratio
        assert ratio == Decimal("4.0")

    def test_risk_reward_ratio_zero_loss(self, strategy):
        """Test risk-reward with zero max loss."""
        max_profit = Decimal("10.00")
        max_loss = Decimal("0.00")

        ratio = strategy._calculate_risk_reward_ratio(max_profit, max_loss)

        assert ratio == Decimal("0")

    def test_validate_risk_reward_acceptable(self, strategy):
        """Test validation with acceptable risk-reward ratio."""
        strikes = {
            "outer_put": Decimal("520.00"),
            "inner_put": Decimal("525.00"),
            "inner_call": Decimal("575.00"),
            "outer_call": Decimal("580.00"),
        }
        estimated_debit = Decimal("2.00")  # 3/2 = 1.5:1 ratio (meets 1.5:1 target)

        is_valid, reason = strategy._validate_risk_reward(strikes, estimated_debit)

        assert is_valid is True
        assert "1.50:1" in reason
        assert "acceptable" in reason.lower()

    def test_validate_risk_reward_unacceptable(self, strategy):
        """Test validation with unacceptable risk-reward ratio."""
        strikes = {
            "outer_put": Decimal("520.00"),
            "inner_put": Decimal("525.00"),
            "inner_call": Decimal("575.00"),
            "outer_call": Decimal("580.00"),
        }
        estimated_debit = Decimal("4.00")  # 1/4 = 0.25:1 ratio (< 1.5:1 target)

        is_valid, reason = strategy._validate_risk_reward(strikes, estimated_debit)

        assert is_valid is False
        assert "0.25:1" in reason
        assert "below minimum" in reason.lower()
