"""
Unit tests for CashSecuredPutStrategy.

Tests cover:
- Scoring logic for various market conditions
- IV rank hard stop enforcement
- ADX/trend analysis
- HV/IV ratio scoring
- Cash requirement calculations
- Strike selection logic
- Annualized return calculations
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.cash_secured_put_strategy import CashSecuredPutStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create CashSecuredPutStrategy instance."""
    return CashSecuredPutStrategy(mock_user)


@pytest.mark.asyncio
class TestCashSecuredPutScoring:
    """Test scoring logic for cash-secured put strategy."""

    async def test_ideal_conditions_high_iv_range_bound(self, strategy):
        """Test scoring with ideal conditions (high IV, range-bound)."""
        report = create_neutral_market_report()
        # Ideal: IV > 70, ADX < 20, neutral/bullish, low stress
        report.iv_rank = 75.0  # Exceptional
        report.adx = 15.0  # Range-bound
        report.hv_iv_ratio = 1.35  # Options overpriced
        report.macd_signal = "neutral"
        report.market_stress_level = 30.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 50 (base) + 30 (IV>70) + 20 (ADX<20) + 20 (HV/IV>1.3) + 15 (premium) + 10 (neutral) + 5 (low stress)
        assert score >= 100.0
        assert any("exceptional premium" in r.lower() for r in reasons)
        assert any("range-bound" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_iv_rank_below_minimum_hard_stop(self, strategy):
        """Test severe penalty when IV Rank < 50."""
        report = create_neutral_market_report()
        report.iv_rank = 45.0  # Below minimum

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Severe penalty applied, not a hard stop (base 50 - 30 penalty + other factors)
        assert score < 50.0, "Score should be penalized for low IV rank"
        assert score > 0.0, "Not a hard stop, just severe penalty"

        # Verify critical warning exists
        critical_warnings = [r for r in reasons if "CRITICAL" in r and "DO NOT EXECUTE" in r]
        assert len(critical_warnings) >= 1, "Should have critical warning about low IV"
        assert "below minimum" in critical_warnings[0].lower()
        assert "50" in critical_warnings[0]  # MIN_IV_RANK

    async def test_strong_bearish_trend_penalty(self, strategy):
        """Test avoidance of strong bearish trends (ADX > 40, bearish)."""
        report = create_neutral_market_report()
        report.iv_rank = 65.0  # Good IV
        report.adx = 45.0  # Strong trend
        report.macd_signal = "bearish"  # Wrong direction

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Should be heavily penalized: -40 from bearish trend
        assert score < 50.0
        assert any("AVOID" in r for r in reasons)
        assert any("bearish" in r.lower() for r in reasons)
        assert any("assignment risk" in r.lower() for r in reasons)

    async def test_optimal_iv_range(self, strategy):
        """Test scoring with optimal IV range (60-70)."""
        report = create_neutral_market_report()
        report.iv_rank = 65.0  # Optimal range
        report.adx = 18.0  # Range-bound

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 80.0
        assert any("optimal range" in r.lower() for r in reasons)
        assert any("excellent premiums" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_overpriced_bonus(self, strategy):
        """Test bonus when HV/IV ratio shows overpriced options."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.hv_iv_ratio = 1.4  # IV >> HV, options expensive

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 70.0
        assert any("overpriced" in r.lower() for r in reasons)
        assert any("1.4" in r or "1.40" in r for r in reasons)

    async def test_hv_iv_ratio_underpriced_penalty(self, strategy):
        """Test penalty when options are underpriced."""
        report = create_neutral_market_report()
        report.iv_rank = 55.0  # Above minimum
        report.hv_iv_ratio = 0.75  # HV > IV, options cheap

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Note: penalty is -10, but other factors still contribute
        assert any("underpriced" in r.lower() for r in reasons)

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets are ideal for CSP."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.macd_signal = "neutral"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("ideal for cash-secured puts" in r.lower() for r in reasons)

    async def test_bullish_market_favorable(self, strategy):
        """Test that bullish markets are favorable (lower assignment risk)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.macd_signal = "bullish"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "favorable" in r.lower() and "lower assignment risk" in r.lower() for r in reasons
        )

    async def test_bollinger_below_lower_bonus(self, strategy):
        """Test bonus for price at lower Bollinger (bounce opportunity)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.bollinger_position = "below_lower"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("lower bollinger" in r.lower() and "bounce" in r.lower() for r in reasons)

    async def test_bollinger_above_upper_penalty(self, strategy):
        """Test penalty for price at upper Bollinger (extended)."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.bollinger_position = "above_upper"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("upper bollinger" in r.lower() and "extended" in r.lower() for r in reasons)

    async def test_market_stress_low_bonus(self, strategy):
        """Test bonus for low market stress."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.market_stress_level = 30.0  # Low

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("low market stress" in r.lower() for r in reasons)

    async def test_market_stress_high_penalty(self, strategy):
        """Test penalty for high market stress."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.market_stress_level = 75.0  # High

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("elevated market stress" in r.lower() for r in reasons)
        assert any("75" in r for r in reasons)

    async def test_adx_moderate_bullish_acceptable(self, strategy):
        """Test that moderate bullish trend is acceptable."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.adx = 28.0  # Moderate
        report.macd_signal = "bullish"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 60.0
        assert any("moderate bullish trend" in r.lower() for r in reasons)

    async def test_adx_weak_trend_with_bullish(self, strategy):
        """Test weak trend with bullish bias."""
        report = create_neutral_market_report()
        report.iv_rank = 60.0
        report.adx = 22.0  # Weak
        report.macd_signal = "bullish"

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 70.0
        assert any("weak trend" in r.lower() and "favorable" in r.lower() for r in reasons)


class TestCashSecuredPutCalculations:
    """Test calculation methods."""

    def test_cash_requirement_calculation(self, strategy):
        """Test cash requirement formula (strike × 100)."""
        strike = Decimal("100.00")
        required = strategy._calculate_cash_requirement(strike)

        assert required == Decimal("10000.00")  # $100 × 100 shares

    def test_cash_requirement_fractional_strike(self, strategy):
        """Test cash requirement with fractional strike."""
        strike = Decimal("55.50")
        required = strategy._calculate_cash_requirement(strike)

        assert required == Decimal("5550.00")  # $55.50 × 100

    def test_net_cash_outlay(self, strategy):
        """Test net cash calculation after premium."""
        strike = Decimal("100.00")
        premium = Decimal("3.00")
        net = strategy._calculate_net_cash_outlay(strike, premium)

        # $10,000 - ($3 × 100) = $9,700
        assert net == Decimal("9700.00")

    def test_net_cash_outlay_high_premium(self, strategy):
        """Test net cash with high premium."""
        strike = Decimal("50.00")
        premium = Decimal("2.50")
        net = strategy._calculate_net_cash_outlay(strike, premium)

        # $5,000 - ($2.50 × 100) = $4,750
        assert net == Decimal("4750.00")

    def test_breakeven_calculation(self, strategy):
        """Test breakeven price calculation."""
        strike = Decimal("100.00")
        premium = Decimal("3.00")
        breakeven = strategy._calculate_breakeven(strike, premium)

        assert breakeven == Decimal("97.00")  # Strike - premium

    def test_breakeven_high_premium(self, strategy):
        """Test breakeven with higher premium."""
        strike = Decimal("200.00")
        premium = Decimal("8.50")
        breakeven = strategy._calculate_breakeven(strike, premium)

        assert breakeven == Decimal("191.50")

    def test_strike_selection_below_current_price(self, strategy):
        """Test strike selection places put OTM (below current)."""
        current_price = Decimal("550.00")
        strike = strategy._select_strike(current_price)

        assert strike < current_price  # Must be OTM
        # 7% OTM: 550 * 0.93 = 511.50, rounds to 512
        expected = Decimal("512")  # Rounded to even strike
        assert strike == expected

    def test_strike_selection_rounding(self, strategy):
        """Test strike rounding to even numbers."""
        current_price = Decimal("100.00")
        strike = strategy._select_strike(current_price)

        # 100 * 0.93 = 93.00, round_to_even_strike rounds to 92
        assert strike == Decimal("92")
        assert strike % 2 == 0  # Even number

    def test_assignment_probability_from_delta(self, strategy):
        """Test assignment probability calculation."""
        delta = 0.30
        probability = strategy._calculate_assignment_probability(delta)

        assert probability == 30.0  # 30% assignment risk

    def test_assignment_probability_higher_delta(self, strategy):
        """Test assignment probability with higher delta."""
        delta = 0.45
        probability = strategy._calculate_assignment_probability(delta)

        assert probability == 45.0

    def test_annualized_return_calculation(self, strategy):
        """Test annualized return formula."""
        premium = Decimal("3.00")
        strike = Decimal("100.00")
        dte = 45

        annualized = strategy._calculate_annualized_return(premium, strike, dte)

        # (3/100) × (365/45) = 0.03 × 8.111... = ~24.3%
        assert annualized > Decimal("24.0")
        assert annualized < Decimal("25.0")

    def test_annualized_return_short_dte(self, strategy):
        """Test annualized return with shorter DTE (higher annualized)."""
        premium = Decimal("2.00")
        strike = Decimal("100.00")
        dte = 30

        annualized = strategy._calculate_annualized_return(premium, strike, dte)

        # (2/100) × (365/30) = 0.02 × 12.166... = ~24.3%
        assert annualized > Decimal("24.0")
        assert annualized < Decimal("25.0")

    def test_annualized_return_long_dte(self, strategy):
        """Test annualized return with longer DTE (lower annualized)."""
        premium = Decimal("5.00")
        strike = Decimal("100.00")
        dte = 90

        annualized = strategy._calculate_annualized_return(premium, strike, dte)

        # (5/100) × (365/90) = 0.05 × 4.055... = ~20.3%
        assert annualized > Decimal("20.0")
        assert annualized < Decimal("21.0")


class TestCashSecuredPutStrategyProperties:
    """Test strategy properties and configuration."""

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.strategy_name == "cash_secured_put"

    def test_automation_disabled_by_default(self, strategy):
        """Test that automation is disabled (requires manual stock purchase intent)."""
        assert strategy.automation_enabled_by_default() is False

    def test_profit_targets_enabled(self, strategy):
        """Test that profit targets are enabled."""
        # Create a minimal mock position
        from unittest.mock import Mock

        mock_position = Mock()
        assert strategy.should_place_profit_targets(mock_position) is True

    def test_dte_exit_threshold(self, strategy):
        """Test DTE exit threshold (21 DTE to avoid assignment)."""
        from unittest.mock import Mock

        mock_position = Mock()
        threshold = strategy.get_dte_exit_threshold(mock_position)
        assert threshold == 21

    def test_constants(self, strategy):
        """Test strategy constants are set correctly."""
        assert strategy.MIN_IV_RANK == 50
        assert strategy.OPTIMAL_IV_RANK == 60
        assert strategy.TARGET_DELTA == 0.30
        assert strategy.MIN_PREMIUM_YIELD == 1.5
        assert strategy.OPTIMAL_PREMIUM_YIELD == 2.5
        assert strategy.MAX_ADX_BEARISH == 40
        assert strategy.IDEAL_ADX_MAX == 20
        assert strategy.PROFIT_TARGET_PCT == 50
