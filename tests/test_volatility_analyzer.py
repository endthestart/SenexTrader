"""
Unit tests for Volatility Analyzer Service.

Epic 05, Task 005: Volatility Analyzer
"""

import pytest

from services.market_data.volatility import VolatilityAnalyzer


class TestVolatilityAnalyzer:
    """Test Volatility Analyzer service."""

    @pytest.fixture
    def analyzer(self, mock_user):
        """Create analyzer instance."""
        return VolatilityAnalyzer(mock_user)

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        from unittest.mock import MagicMock

        user = MagicMock()
        user.id = 1
        return user

    @pytest.mark.asyncio
    async def test_excellent_selling_conditions(self, analyzer):
        """Test identification of excellent premium selling conditions."""
        # HV 15%, IV 30%, ratio 0.5, IV rank 85%
        analysis = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=15.0,
            implied_volatility=30.0,
            iv_rank=85.0,
            iv_percentile=85.0,
        )

        assert analysis.hv_iv_ratio < 0.8
        assert analysis.volatility_regime == "extreme"
        assert analysis.premium_environment == "expensive"
        assert analysis.is_good_for_selling is True
        assert analysis.is_good_for_buying is False
        assert analysis.recommendation_score > 80

    @pytest.mark.asyncio
    async def test_poor_selling_conditions(self, analyzer):
        """Test identification of poor premium selling conditions."""
        # HV 35%, IV 20%, ratio 1.75, IV rank 15%
        analysis = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=35.0,
            implied_volatility=20.0,
            iv_rank=15.0,
            iv_percentile=15.0,
        )

        assert analysis.hv_iv_ratio > 1.2
        assert analysis.volatility_regime == "low"
        assert analysis.premium_environment == "cheap"
        assert analysis.is_good_for_selling is False
        assert analysis.is_good_for_buying is True
        assert analysis.recommendation_score < 40

    @pytest.mark.asyncio
    async def test_neutral_conditions(self, analyzer):
        """Test neutral market conditions."""
        # HV 25%, IV 25% (0.25), ratio 1.0, IV rank 45% (normal range)
        analysis = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=25.0,
            implied_volatility=25,
            iv_rank=45.0,
            iv_percentile=45.0,
        )

        assert 0.95 < analysis.hv_iv_ratio < 1.05
        assert analysis.volatility_regime == "normal"
        assert analysis.premium_environment == "fair"
        assert 40 < analysis.recommendation_score < 60

    @pytest.mark.asyncio
    async def test_volatility_regime_classification(self, analyzer):
        """Test volatility regime classification."""
        # Low volatility
        analysis_low = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=10.0,
            implied_volatility=10,
            iv_rank=15.0,
            iv_percentile=15.0,
        )
        assert analysis_low.volatility_regime == "low"

        # Normal volatility
        analysis_normal = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=20.0,
            implied_volatility=20,
            iv_rank=45.0,
            iv_percentile=45.0,
        )
        assert analysis_normal.volatility_regime == "normal"

        # Elevated volatility
        analysis_elevated = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=35.0,
            implied_volatility=35,
            iv_rank=70.0,
            iv_percentile=70.0,
        )
        assert analysis_elevated.volatility_regime == "elevated"

        # Extreme volatility
        analysis_extreme = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=50.0,
            implied_volatility=50,
            iv_rank=90.0,
            iv_percentile=90.0,
        )
        assert analysis_extreme.volatility_regime == "extreme"

    @pytest.mark.asyncio
    async def test_premium_environment_classification(self, analyzer):
        """Test premium environment classification."""
        # Cheap premiums (IV low)
        analysis_cheap = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=30.0,
            implied_volatility=20,  # HV/IV = 1.5
            iv_rank=50.0,
            iv_percentile=50.0,
        )
        assert analysis_cheap.premium_environment == "cheap"

        # Fair premiums
        analysis_fair = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=25.0,
            implied_volatility=25,  # HV/IV = 1.0
            iv_rank=50.0,
            iv_percentile=50.0,
        )
        assert analysis_fair.premium_environment == "fair"

        # Expensive premiums (IV high)
        analysis_expensive = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=15.0,
            implied_volatility=25,  # HV/IV = 0.6
            iv_rank=50.0,
            iv_percentile=50.0,
        )
        assert analysis_expensive.premium_environment == "expensive"

    @pytest.mark.asyncio
    async def test_summary_generation(self, analyzer):
        """Test summary string generation."""
        analysis = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=15.0,
            implied_volatility=30.0,
            iv_rank=85.0,
            iv_percentile=85.0,
        )

        # Summary should contain key elements
        assert "SPY" in analysis.summary
        assert "extreme" in analysis.summary.lower() or "Extreme" in analysis.summary
        assert "0.50" in analysis.summary  # HV/IV ratio
        assert "85" in analysis.summary  # IV rank

    @pytest.mark.asyncio
    async def test_recommendation_score_ranges(self, analyzer):
        """Test recommendation score calculation ranges."""
        # Excellent conditions should score high
        excellent = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=12.0,
            implied_volatility=30,
            iv_rank=90.0,
            iv_percentile=90.0,
        )
        assert excellent.recommendation_score >= 80

        # Poor conditions should score low
        poor = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=40.0,
            implied_volatility=20,
            iv_rank=10.0,
            iv_percentile=10.0,
        )
        assert poor.recommendation_score <= 30

        # Neutral conditions should score mid-range
        neutral = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=25.0,
            implied_volatility=25,
            iv_rank=50.0,
            iv_percentile=50.0,
        )
        assert 40 <= neutral.recommendation_score <= 60

    @pytest.mark.asyncio
    async def test_zero_values_handling(self, analyzer):
        """Test handling of zero values."""
        analysis = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=0.0,
            implied_volatility=0,
            iv_rank=0.0,
            iv_percentile=0.0,
        )

        # Should not crash and should default to neutral ratio
        assert analysis.hv_iv_ratio == 1.0
        assert 0 <= analysis.recommendation_score <= 100
        assert analysis.summary is not None

    @pytest.mark.asyncio
    async def test_buying_vs_selling_conditions(self, analyzer):
        """Test that buying and selling conditions are mutually exclusive."""
        # Test multiple scenarios
        scenarios = [
            # (HV, IV, IV_rank)
            (15.0, 0.30, 85.0),  # Great for selling
            (35.0, 0.20, 15.0),  # Great for buying
            (25.0, 0.25, 50.0),  # Neutral
        ]

        for hv, iv, iv_rank in scenarios:
            analysis = await analyzer.analyze(
                symbol="SPY",
                historical_volatility=hv,
                implied_volatility=iv,
                iv_rank=iv_rank,
                iv_percentile=iv_rank,
            )

            # Should not be good for both buying AND selling
            if analysis.is_good_for_selling:
                assert not analysis.is_good_for_buying
            if analysis.is_good_for_buying:
                assert not analysis.is_good_for_selling
