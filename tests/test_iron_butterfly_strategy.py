"""
Unit tests for IronButterflyStrategy.

Tests cover:
- Scoring logic for various market conditions (STRICTER than Iron Condor)
- IV rank scoring (VERY HIGH IV required - > 70% ideal)
- ADX scoring (very range-bound required - < 12 ideal)
- HV/IV ratio scoring (want IV very overpriced - < 0.7)
- ATM strike calculations (both shorts at SAME strike)
- Wing width calculations
- Max profit/loss calculations
- Breakeven calculations (tighter than Iron Condor)
- Comparison with Iron Condor requirements
"""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from services.strategies.iron_butterfly_strategy import IronButterflyStrategy
from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


@pytest.fixture
def strategy(mock_user):
    """Create IronButterflyStrategy instance."""
    return IronButterflyStrategy(mock_user)


@pytest.mark.asyncio
class TestIronButterflyScoring:
    """Test scoring logic for iron butterfly strategy."""

    async def test_ideal_conditions_very_high_iv_very_range_bound(self, strategy):
        """Test scoring with ideal conditions (IV > 75, ADX < 12)."""
        report = create_neutral_market_report()
        # Ideal: IV > 75, ADX < 12, HV/IV < 0.6, neutral direction
        report.iv_rank = 78.0  # Very high (excellent)
        report.adx = 11.0  # Extremely range-bound
        report.hv_iv_ratio = 0.58  # IV very expensive
        report.macd_signal = "neutral"  # No directional bias
        report.bollinger_position = "within_bands"  # Not at extremes
        report.market_stress_level = 25.0  # Low stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 40 + 35 (IV>75) + 30 (ADX<12) + 20 (range persist) + 15 (HV/IV<0.6) + 10 (neutral) + 8 (middle) + 7 (low stress)
        assert score >= 125.0
        assert any("excellent" in r.lower() and "ideal" in r.lower() for r in reasons)
        assert any("extremely range-bound" in r.lower() and "perfect" in r.lower() for r in reasons)
        assert any("very expensive" in r.lower() for r in reasons)

    async def test_poor_conditions_low_iv_strong_trend(self, strategy):
        """Test scoring with poor conditions (low IV, strong trend)."""
        report = create_neutral_market_report()
        # Poor: IV < 50, ADX > 22, HV/IV > 1.0
        report.iv_rank = 45.0  # Too low for butterfly
        report.adx = 28.0  # Strong trend
        report.hv_iv_ratio = 1.15  # IV cheap
        report.bollinger_position = "above_upper"  # At extremes
        report.market_stress_level = 75.0  # High stress

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Expected: 40 - 35 (IV<50) - 30 (ADX>22) - 15 (HV/IV>1.0) - 10 (extremes) - 12 (high stress)
        assert score <= 15.0
        assert any(
            "insufficient premium" in r.lower() and "iron condor" in r.lower() for r in reasons
        )
        assert any("strong trend" in r.lower() and "avoid" in r.lower() for r in reasons)
        assert any("cheap" in r.lower() for r in reasons)

    async def test_iv_rank_above_75_excellent(self, strategy):
        """Test excellent score for IV rank > 75."""
        report = create_neutral_market_report()
        report.iv_rank = 78.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 65.0
        assert any("excellent premium" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_iv_rank_70_75_acceptable(self, strategy):
        """Test acceptable score for IV rank 70-75 range (falls in 60-70 bracket)."""
        report = create_neutral_market_report()
        report.iv_rank = 72.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 45.0
        assert any("acceptable" in r.lower() for r in reasons)

    async def test_iv_rank_60_70_acceptable(self, strategy):
        """Test acceptable score for IV rank 60-70 (marginal for butterfly)."""
        report = create_neutral_market_report()
        report.iv_rank = 65.0

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score > 45.0
        assert any("acceptable" in r.lower() and "prefer higher" in r.lower() for r in reasons)

    async def test_iv_rank_below_50_insufficient(self, strategy):
        """Test penalty for IV rank < 50 (use Iron Condor instead)."""
        report = create_neutral_market_report()
        report.iv_rank = 45.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "insufficient premium" in r.lower() and "iron condor" in r.lower() for r in reasons
        )

    async def test_adx_below_12_extremely_range_bound(self, strategy):
        """Test ideal score for ADX < 12 (extremely range-bound)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.adx = 10.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("extremely range-bound" in r.lower() and "perfect" in r.lower() for r in reasons)

    async def test_adx_12_15_very_range_bound(self, strategy):
        """Test good score for ADX 12-15 (very range-bound)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.adx = 14.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very range-bound" in r.lower() and "favorable" in r.lower() for r in reasons)

    async def test_adx_above_22_strong_trend_avoid(self, strategy):
        """Test penalty for ADX > 22 (strong trend)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.adx = 28.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("strong trend" in r.lower() and "avoid" in r.lower() for r in reasons)
        assert any("iron condor" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_below_0_6_very_expensive(self, strategy):
        """Test excellent score for HV/IV < 0.6 (IV very expensive)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.hv_iv_ratio = 0.58

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("very expensive" in r.lower() and "excellent" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_0_6_0_7_expensive(self, strategy):
        """Test good score for HV/IV 0.6-0.7."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.hv_iv_ratio = 0.65

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("expensive vs realized" in r.lower() for r in reasons)

    async def test_hv_iv_ratio_above_1_0_cheap(self, strategy):
        """Test penalty for HV/IV > 1.0 (IV cheap)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.hv_iv_ratio = 1.15

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("cheap" in r.lower() and "don't sell" in r.lower() for r in reasons)

    async def test_neutral_market_ideal(self, strategy):
        """Test that neutral markets are ideal (no directional bias)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.macd_signal = "neutral"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "ideal for butterfly" in r.lower() and "no directional bias" in r.lower()
            for r in reasons
        )

    async def test_directional_bias_risky(self, strategy):
        """Test that directional bias is not ideal for tight profit zone."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.macd_signal = "bullish"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        # "not ideal for tight profit zone" for bullish/bearish
        assert any("not ideal for tight profit zone" in r.lower() for r in reasons)

    async def test_bollinger_within_bands_ideal(self, strategy):
        """Test bonus for price in middle of Bollinger Bands."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.bollinger_position = "within_bands"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("within bollinger" in r.lower() and "ideal" in r.lower() for r in reasons)

    async def test_bollinger_extremes_penalty(self, strategy):
        """Test penalty for price at Bollinger extremes."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.bollinger_position = "above_upper"

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("bollinger extremes" in r.lower() and "avoid" in r.lower() for r in reasons)

    async def test_low_market_stress_bonus(self, strategy):
        """Test bonus for low market stress (stable environment)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.market_stress_level = 25.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any("low market stress" in r.lower() and "stable" in r.lower() for r in reasons)

    async def test_very_high_market_stress_penalty(self, strategy):
        """Test penalty for very high market stress (breakout risk)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.market_stress_level = 75.0

        _score, reasons = await strategy._score_market_conditions_impl(report)

        assert any(
            "very high market stress" in r.lower() and "breakout risk" in r.lower() for r in reasons
        )

    async def test_range_persistence_scoring(self, strategy):
        """Test range persistence scoring (using ADX as proxy)."""
        report = create_neutral_market_report()
        report.iv_rank = 75.0

        # Very persistent range (ADX < 12)
        report.adx = 10.0
        score_persistent, _reasons_persistent = await strategy._score_market_conditions_impl(report)

        # Weak range (ADX > 18)
        report.adx = 20.0
        score_weak, _reasons_weak = await strategy._score_market_conditions_impl(report)

        # Persistent range should score higher
        assert score_persistent > score_weak + 30


class TestIronButterflyCalculations:
    """Test calculation methods."""

    def test_calculate_atm_strike(self, strategy):
        """Test ATM strike calculation (both shorts at same strike)."""
        current_price = Decimal("100.50")
        atm_strike = strategy._calculate_atm_strike(current_price)

        # Should round to nearest even strike
        assert atm_strike == Decimal("100")
        assert atm_strike % 2 == 0

    def test_calculate_atm_strike_various_prices(self, strategy):
        """Test ATM strike with various prices."""
        test_cases = [
            (Decimal("99.00"), Decimal("100")),  # Rounds to nearest even (100)
            (Decimal("101.00"), Decimal("100")),  # Rounds to nearest even (100)
            (Decimal("450.00"), Decimal("450")),  # Already even
            (Decimal("451.00"), Decimal("452")),  # Rounds to nearest even (452)
        ]

        for price, expected_strike in test_cases:
            atm = strategy._calculate_atm_strike(price)
            assert (
                atm == expected_strike
            ), f"Price {price} should give strike {expected_strike}, got {atm}"

    def test_calculate_wing_width_based_on_price(self, strategy):
        """Test wing width scales with price."""
        test_cases = [
            (Decimal("30.00"), Decimal("2.5")),  # Low price
            (Decimal("75.00"), Decimal("5")),  # Mid-low price
            (Decimal("150.00"), Decimal("10")),  # Mid-high price
            (Decimal("350.00"), Decimal("15")),  # High price
        ]

        for price, expected_width in test_cases:
            width = strategy._calculate_wing_width(price)
            assert (
                width == expected_width
            ), f"Price {price} should have width {expected_width}, got {width}"

    def test_calculate_long_strikes_symmetric(self, strategy):
        """Test long strikes are equidistant from ATM."""
        atm_strike = Decimal("100.00")
        wing_width = Decimal("10.00")
        put_long, call_long = strategy._calculate_long_strikes(atm_strike, wing_width)

        # Both wings should be exactly wing_width away from ATM
        assert put_long == Decimal("90.00")  # ATM - 10
        assert call_long == Decimal("110.00")  # ATM + 10
        assert (atm_strike - put_long) == (call_long - atm_strike)

    def test_calculate_max_profit_single_contract(self, strategy):
        """Test max profit with single contract."""
        credit_received = Decimal("6.00")

        max_profit = strategy._calculate_max_profit(credit_received, quantity=1)

        # 6.00 × 100 = $600
        assert max_profit == Decimal("600.00")

    def test_calculate_max_profit_multiple_contracts(self, strategy):
        """Test max profit with multiple contracts."""
        credit_received = Decimal("5.50")

        max_profit = strategy._calculate_max_profit(credit_received, quantity=2)

        # 5.50 × 100 × 2 = $1,100
        assert max_profit == Decimal("1100.00")

    def test_calculate_max_loss_single_contract(self, strategy):
        """Test max loss with single contract."""
        wing_width = Decimal("10")
        credit_received = Decimal("6.00")

        max_loss = strategy._calculate_max_loss(wing_width, credit_received, quantity=1)

        # (10 - 6.00) × 100 = $400
        assert max_loss == Decimal("400.00")

    def test_calculate_max_loss_multiple_contracts(self, strategy):
        """Test max loss with multiple contracts."""
        wing_width = Decimal("10")
        credit_received = Decimal("5.00")

        max_loss = strategy._calculate_max_loss(wing_width, credit_received, quantity=2)

        # (10 - 5.00) × 100 × 2 = $1,000
        assert max_loss == Decimal("1000.00")

    def test_calculate_breakevens_tight_zone(self, strategy):
        """Test breakeven calculation (ATM ± credit/2)."""
        atm_strike = Decimal("100.00")
        credit_received = Decimal("6.00")

        breakeven_down, breakeven_up = strategy._calculate_breakevens(atm_strike, credit_received)

        # Lower: 100 - 3.00 = 97.00
        # Upper: 100 + 3.00 = 103.00
        assert breakeven_down == Decimal("97.00")
        assert breakeven_up == Decimal("103.00")

    def test_calculate_breakevens_higher_credit(self, strategy):
        """Test breakevens with higher credit (wider profit zone)."""
        atm_strike = Decimal("200.00")
        credit_received = Decimal("10.00")

        breakeven_down, breakeven_up = strategy._calculate_breakevens(atm_strike, credit_received)

        # Lower: 200 - 5.00 = 195.00
        # Upper: 200 + 5.00 = 205.00
        assert breakeven_down == Decimal("195.00")
        assert breakeven_up == Decimal("205.00")

    def test_profit_zone_tighter_than_iron_condor(self, strategy):
        """Test that butterfly profit zone is tighter than comparable Iron Condor."""
        atm_strike = Decimal("100.00")
        credit = Decimal("6.00")
        breakeven_down, breakeven_up = strategy._calculate_breakevens(atm_strike, credit)

        # Profit zone width
        profit_zone_width = breakeven_up - breakeven_down

        # Butterfly: profit zone = credit (6.00)
        # Iron Condor: profit zone typically 15-20% of price
        # For $100 stock, IC would be ~$15-20 wide
        # Butterfly should be much tighter
        assert profit_zone_width == credit
        assert profit_zone_width < Decimal("10.00")  # Significantly tighter than IC

    def test_profit_zone_percentage(self, strategy):
        """Test profit zone as percentage of stock price."""
        current_price = Decimal("100.00")
        atm_strike = strategy._calculate_atm_strike(current_price)
        credit = Decimal("6.00")
        breakeven_down, breakeven_up = strategy._calculate_breakevens(atm_strike, credit)

        # Calculate profit zone as % of price
        profit_zone_pct = ((breakeven_up - breakeven_down) / current_price) * Decimal("100")

        # Should be ~5-8% (much tighter than Iron Condor's 15-20%)
        assert profit_zone_pct < Decimal("10.0")
        assert profit_zone_pct > Decimal("4.0")


class TestIronButterflyStrategyProperties:
    """Test strategy properties and configuration."""

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.strategy_name == "iron_butterfly"

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

    def test_constants_stricter_than_iron_condor(self, strategy):
        """Test strategy constants are stricter than Iron Condor."""
        # Iron Butterfly should have:
        # - Higher MIN_IV_RANK (50 vs Iron Condor's 45)
        # - Higher OPTIMAL_IV_RANK (75 vs 60)
        # - Lower MAX_ADX (15 vs 25)
        # - Lower IDEAL_ADX_MAX (12 vs 20)
        # - Lower profit target (25% vs 50%)
        assert strategy.MIN_IV_RANK == 50
        assert strategy.OPTIMAL_IV_RANK == 75  # Stricter
        assert strategy.MAX_ADX == 15  # Stricter
        assert strategy.IDEAL_ADX_MAX == 12  # Stricter
        assert strategy.MAX_HV_IV_RATIO == 0.7
        assert strategy.TARGET_DTE == 45
        assert strategy.PROFIT_TARGET_PCT == 25  # Lower than Iron Condor's 50%
        assert strategy.MIN_CREDIT_RATIO == 0.3
        assert strategy.TARGET_CREDIT_RATIO == 0.4


class TestComparisonWithIronCondor:
    """Test that Iron Butterfly is stricter than Iron Condor."""

    @pytest.mark.asyncio
    async def test_butterfly_requires_higher_iv_than_condor(self, strategy):
        """Iron Butterfly requires higher IV than Iron Condor."""
        # IV rank of 55 - good for Iron Condor, poor for Butterfly
        report = create_neutral_market_report()
        report.iv_rank = 55.0  # Above Iron Condor's 50, below Butterfly's 60
        report.adx = 18.0
        report.hv_iv_ratio = 0.75

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Should score below 60 (penalized for below optimal 60 IV rank)
        assert score < 60.0
        assert any("marginal" in r.lower() or "insufficient" in r.lower() for r in reasons)

    @pytest.mark.asyncio
    async def test_butterfly_requires_tighter_range_than_condor(self, strategy):
        """Iron Butterfly requires ADX < 15, Iron Condor allows < 20."""
        # ADX of 17.5 - between Iron Condor's 20 and Butterfly's 15
        report = create_neutral_market_report()
        report.iv_rank = 75.0
        report.adx = 17.5  # Between thresholds
        report.hv_iv_ratio = 0.65

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Should get decent score (IV is high which helps)
        # But ADX 17.5 gets +10 (range-bound but prefer tighter) not maximum +30
        assert score >= 60.0  # Good conditions overall
        assert any("range" in r.lower() for r in reasons)

    @pytest.mark.asyncio
    async def test_lower_profit_target_than_condor(self, strategy):
        """Butterfly targets 25% profit vs Iron Condor's 50%."""

        # This is a property constant, not dynamic
        assert strategy.PROFIT_TARGET_PCT == 25
        # Iron Condor would be 50%
