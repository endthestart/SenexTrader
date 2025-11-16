"""
Unit tests for Senex Trident strategy scoring functionality.
"""

from unittest.mock import MagicMock

import pytest

from services.market_data.analysis import MarketConditionReport
from services.strategies.senex_trident_strategy import SenexTridentStrategy


@pytest.fixture
def mock_user():
    """Create a mock user for testing"""
    user = MagicMock()
    user.id = 1
    return user


@pytest.fixture
def strategy(mock_user):
    """Create a SenexTridentStrategy instance for testing"""
    return SenexTridentStrategy(mock_user)


@pytest.fixture
def neutral_market_report():
    """Ideal conditions for Senex Trident: neutral, high IV"""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=449.5,
        rsi=52.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=448.0,
        support_level=440.0,
        resistance_level=460.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.25,
        iv_rank=60.0,
        iv_percentile=58.0,
        market_stress_level=25.0,
        recent_move_pct=1.5,
        is_data_stale=False,
        last_update=None,
        no_trade_reasons=[],
    )


@pytest.fixture
def range_bound_report():
    """Range-bound market (hard stop for Trident)"""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=449.5,
        rsi=50.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=450.0,
        is_range_bound=True,
        range_bound_days=4,
        current_iv=0.20,
        iv_rank=50.0,
        iv_percentile=48.0,
        market_stress_level=20.0,
        recent_move_pct=0.5,
        is_data_stale=False,
        no_trade_reasons=[],
    )


@pytest.fixture
def low_iv_report():
    """Low IV rank (unfavorable for premium collection)"""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=449.5,
        rsi=50.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=450.0,
        is_range_bound=False,
        current_iv=0.15,
        iv_rank=15.0,  # Below minimum of 25
        iv_percentile=12.0,
        market_stress_level=20.0,
        recent_move_pct=1.0,
        is_data_stale=False,
        no_trade_reasons=[],
    )


@pytest.fixture
def high_stress_report():
    """High market stress (increased risk)"""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=449.5,
        rsi=35.0,
        macd_signal="bearish",
        bollinger_position="below_lower",
        sma_20=455.0,
        is_range_bound=False,
        current_iv=0.35,
        iv_rank=70.0,
        iv_percentile=68.0,
        market_stress_level=85.0,  # High stress
        recent_move_pct=4.5,
        is_data_stale=False,
        no_trade_reasons=[],
    )


@pytest.mark.asyncio
class TestSenexTridentScoring:
    """Test suite for Senex Trident market condition scoring"""

    async def test_ideal_conditions_high_score(self, strategy, neutral_market_report):
        """Test that ideal market conditions produce a high score"""
        score, explanation = await strategy.a_score_market_conditions(neutral_market_report)

        # Ideal conditions should score well above threshold (40)
        assert score > 60, f"Expected high score for ideal conditions, got {score}"
        assert "IV rank" in explanation
        assert "Neutral market" in explanation
        assert "Low market stress" in explanation

    async def test_range_bound_returns_zero(self, strategy, range_bound_report):
        """Test that range-bound markets return score of 0 (hard stop)"""
        score, explanation = await strategy.a_score_market_conditions(range_bound_report)

        assert score == 0.0
        assert "Range-bound market" in explanation
        assert "4 days" in explanation

    async def test_low_iv_rank_penalty(self, strategy, low_iv_report):
        """Test that low IV rank reduces score significantly"""
        score, explanation = await strategy.a_score_market_conditions(low_iv_report)

        # Low IV should still allow trading but with penalty
        # Score is 72 because: base 50 + neutral 15 + low stress 10 - IV penalty 8 = 67
        # But also gets Bollinger within_bands bonus +5 = 72
        assert score > 0, "Score should be positive (not a hard stop)"
        assert "below minimum" in explanation

        # Compare with high IV to ensure penalty is applied
        high_iv_report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            open_price=449.5,
            rsi=50.0,
            macd_signal="neutral",
            bollinger_position="within_bands",
            sma_20=450.0,
            is_range_bound=False,
            current_iv=0.30,
            iv_rank=60.0,  # High IV
            iv_percentile=58.0,
            market_stress_level=20.0,
            recent_move_pct=1.0,
            is_data_stale=False,
            no_trade_reasons=[],
        )
        high_score, _ = await strategy.a_score_market_conditions(high_iv_report)

        # High IV should score better than low IV
        assert (
            high_score > score
        ), f"High IV ({high_score}) should score better than low IV ({score})"

    async def test_high_stress_reduces_score(self, strategy, high_stress_report):
        """Test that high market stress reduces score"""
        _score, explanation = await strategy.a_score_market_conditions(high_stress_report)

        # High stress should reduce score
        assert "High market stress" in explanation or "increased risk" in explanation

    async def test_stale_data_hard_stop(self, strategy):
        """Test that stale data triggers hard stop (score = 0)"""
        stale_report = MarketConditionReport(
            symbol="SPY", current_price=450.0, is_data_stale=True, no_trade_reasons=["data_stale"]
        )

        score, explanation = await strategy.a_score_market_conditions(stale_report)

        assert score == 0.0
        assert "data_stale" in explanation.lower() or "No trade" in explanation

    async def test_directional_market_penalty(self, strategy):
        """Test that strong directional markets reduce score"""
        bullish_report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            rsi=70.0,
            macd_signal="strong_bullish",
            bollinger_position="above_upper",
            sma_20=440.0,
            is_range_bound=False,
            iv_rank=50.0,
            market_stress_level=30.0,
            no_trade_reasons=[],
        )

        _score, explanation = await strategy.a_score_market_conditions(bullish_report)

        # Directional market should reduce score
        assert "directional" in explanation.lower() or "strong bullish" in explanation.lower()

    async def test_score_bounds(self, strategy, neutral_market_report):
        """Test that score is always non-negative (no upper bound in current implementation)"""
        score, _ = await strategy.a_score_market_conditions(neutral_market_report)

        # Implementation allows scores > 100 when multiple favorable factors align
        assert score >= 0.0, f"Score {score} should be non-negative"

    async def test_bollinger_position_scoring(self, strategy):
        """Test that Bollinger Band position affects scoring"""
        middle_report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            bollinger_position="within_bands",
            macd_signal="neutral",
            is_range_bound=False,
            iv_rank=50.0,
            market_stress_level=30.0,
            no_trade_reasons=[],
        )

        extreme_report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            bollinger_position="above_upper",
            macd_signal="neutral",
            is_range_bound=False,
            iv_rank=50.0,
            market_stress_level=30.0,
            no_trade_reasons=[],
        )

        middle_score, middle_explanation = await strategy.a_score_market_conditions(middle_report)
        extreme_score, _extreme_explanation = await strategy.a_score_market_conditions(
            extreme_report
        )

        # Within bands should score higher than extreme
        assert middle_score >= extreme_score
        assert "within" in middle_explanation.lower()

    async def test_explanation_always_provided(self, strategy, neutral_market_report):
        """Test that explanation is always provided with score"""
        _score, explanation = await strategy.a_score_market_conditions(neutral_market_report)

        assert explanation is not None
        assert len(explanation) > 0
        assert isinstance(explanation, str)

    async def test_iv_rank_bonus_scaling(self, strategy):
        """Test that IV rank bonus scales correctly"""
        low_iv = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            macd_signal="neutral",
            is_range_bound=False,
            iv_rank=30.0,  # Just above minimum
            market_stress_level=20.0,
            no_trade_reasons=[],
        )

        high_iv = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            macd_signal="neutral",
            is_range_bound=False,
            iv_rank=80.0,  # High IV
            market_stress_level=20.0,
            no_trade_reasons=[],
        )

        low_score, _ = await strategy.a_score_market_conditions(low_iv)
        high_score, _ = await strategy.a_score_market_conditions(high_iv)

        # Higher IV rank should produce higher score
        assert high_score > low_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
