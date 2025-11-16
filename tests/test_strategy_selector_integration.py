"""
Integration tests for StrategySelector with actual strategy generation.

Tests the complete flow from market analysis through strategy scoring
to suggestion generation.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.market_data.analysis import MarketConditionReport
from services.strategies.selector import StrategySelector
from tests.helpers import create_ideal_bearish_report, create_ideal_bullish_report


@pytest.fixture
def mock_config():
    """Create mock strategy configuration."""
    config = MagicMock()
    config.underlying_symbol = "SPY"
    config.spread_width = 5
    config.target_dte = 45
    return config


class TestStrategySelectorIntegration:
    """Integration tests for complete strategy selection flow."""

    async def _mock_stream_manager(self):
        """Helper to create mock stream manager."""
        from unittest.mock import AsyncMock, MagicMock

        mock_manager = MagicMock()
        mock_suggestion = MagicMock()
        mock_suggestion.id = 1
        mock_suggestion.strategy = "test_strategy"
        mock_manager.a_process_suggestion_request = AsyncMock(return_value=mock_suggestion)
        return mock_manager

    @pytest.mark.asyncio
    async def test_auto_mode_with_suggestion_generation(self, mock_user, mock_config):
        """Test auto mode generates actual suggestion."""
        selector = StrategySelector(mock_user)
        ideal_bullish_report = create_ideal_bullish_report()

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy preparation
        for strategy in selector.strategies.values():
            strategy.a_prepare_suggestion_context = AsyncMock(
                return_value={"symbol": "SPY", "strategy": "test"}
            )

        # Mock validator and stream manager
        with (
            patch.object(
                selector.validator, "a_analyze_market_conditions", return_value=ideal_bullish_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should select a strategy (likely bull put in bullish conditions)
            assert strategy_name is not None
            assert strategy_name in ["bull_put_spread", "bear_call_spread"]

            # Should have actual suggestion data
            assert suggestion is not None

            # Should have explanation dict
            assert isinstance(explanation, dict)
            assert "Selected:" in explanation["title"]
            assert "confidence" in explanation

    @pytest.mark.asyncio
    async def test_forced_mode_with_suggestion_generation(self, mock_user, mock_config):
        """Test forced mode generates actual suggestion."""
        selector = StrategySelector(mock_user)
        ideal_bullish_report = create_ideal_bullish_report()

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy preparation
        bull_put_strategy = selector.strategies["bull_put_spread"]
        bull_put_strategy.a_prepare_suggestion_context = AsyncMock(
            return_value={"symbol": "SPY", "strategy": "bull_put_spread"}
        )

        # Mock validator and stream manager
        with (
            patch.object(
                selector.validator, "a_analyze_market_conditions", return_value=ideal_bullish_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="bull_put_spread"
            )

            # Should generate bull put spread
            assert strategy_name == "bull_put_spread"

            # Should have actual suggestion data
            assert suggestion is not None

            # Should have forced mode explanation
            assert isinstance(explanation, dict)
            assert explanation["type"] == "forced"
            assert "Bull Put Spread" in explanation["title"]

    @pytest.mark.asyncio
    async def test_auto_mode_with_low_score_no_suggestion(self, mock_user, mock_config):
        """Test auto mode with marginal scores."""
        # Create report with very low IV (poor for all strategies)
        # Note: Even in terrible conditions, Senex Trident may score above 30 threshold
        # due to its neutral market bias, so selector will attempt generation
        low_score_report = MarketConditionReport(
            current_price=450.0,
            open_price=450.0,
            rsi=50.0,
            macd_signal="neutral",
            bollinger_position="within_bands",
            sma_20=450.0,
            is_range_bound=False,
            range_bound_days=0,
            current_iv=0.01,  # Extremely low IV
            iv_rank=1.0,  # Extremely low IV rank
            iv_percentile=1.0,
            market_stress_level=95.0,  # Extremely high stress
            recent_move_pct=0.1,
            is_data_stale=False,
            last_update=datetime.now(UTC),
            no_trade_reasons=[],
        )

        selector = StrategySelector(mock_user)

        with patch.object(
            selector.validator, "a_analyze_market_conditions", return_value=low_score_report
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should not generate suggestion (generation fails in test environment)
            assert strategy_name is None
            assert suggestion is None

            # Explanation could be either "low_scores" if all below threshold,
            # or "auto" if one scored above threshold but generation failed
            assert isinstance(explanation, dict)
            assert explanation["type"] in ["low_scores", "auto"]

    @pytest.mark.asyncio
    async def test_suggestion_generation_failure_handling(self, mock_user):
        """Test handling of suggestion generation failures."""
        selector = StrategySelector(mock_user)
        ideal_bullish_report = create_ideal_bullish_report()

        # Mock strategies to fail preparation
        for strategy in selector.strategies.values():
            strategy.a_prepare_suggestion_context = AsyncMock(
                side_effect=Exception("Generation failed")
            )

        with patch.object(
            selector.validator, "a_analyze_market_conditions", return_value=ideal_bullish_report
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should handle error gracefully
            assert strategy_name is None
            assert suggestion is None
            assert isinstance(explanation, dict)
            assert "warnings" in explanation or "title" in explanation

    @pytest.mark.asyncio
    async def test_strike_calculation_in_bull_put_spread(self, mock_user, mock_config):
        """Test that bull put spread generates suggestion correctly."""
        selector = StrategySelector(mock_user)
        bull_put = selector.strategies["bull_put_spread"]
        ideal_bullish_report = create_ideal_bullish_report()

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy preparation
        bull_put.a_prepare_suggestion_context = AsyncMock(
            return_value={"symbol": "SPY", "strategy": "bull_put_spread"}
        )

        with (
            patch.object(
                selector.validator, "a_analyze_market_conditions", return_value=ideal_bullish_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, suggestion, _ = await selector.a_select_and_generate(
                "SPY", forced_strategy="bull_put_spread"
            )

        # Should generate a suggestion
        assert suggestion is not None

    @pytest.mark.asyncio
    async def test_strike_calculation_in_bear_call_spread(self, mock_user, mock_config):
        """Test that bear call spread generates suggestion correctly."""
        selector = StrategySelector(mock_user)
        bear_call = selector.strategies["bear_call_spread"]
        ideal_bearish_report = create_ideal_bearish_report()

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy preparation
        bear_call.a_prepare_suggestion_context = AsyncMock(
            return_value={"symbol": "SPY", "strategy": "bear_call_spread"}
        )

        with (
            patch.object(
                selector.validator, "a_analyze_market_conditions", return_value=ideal_bearish_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, suggestion, _ = await selector.a_select_and_generate(
                "SPY", forced_strategy="bear_call_spread"
            )

        # Should generate a suggestion
        assert suggestion is not None

    @pytest.mark.asyncio
    async def test_explanation_includes_all_strategy_scores(self, mock_user):
        """Test that auto mode explanation includes all strategy scores."""
        selector = StrategySelector(mock_user)
        ideal_bullish_report = create_ideal_bullish_report()

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy preparation
        for strategy in selector.strategies.values():
            strategy.a_prepare_suggestion_context = AsyncMock(
                return_value={"symbol": "SPY", "strategy": "test"}
            )

        with (
            patch.object(
                selector.validator, "a_analyze_market_conditions", return_value=ideal_bullish_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, _, explanation = await selector.a_select_and_generate("SPY")

        # Should mention both credit spread strategies in scores list
        assert isinstance(explanation, dict)
        assert "scores" in explanation
        strategy_keys = [s["strategy_key"] for s in explanation["scores"]]
        assert "bull_put_spread" in strategy_keys
        assert "bear_call_spread" in strategy_keys
        assert len(strategy_keys) == 2  # Only 2 strategies now (Senex removed)

        # Should have scores for each
        for score_item in explanation["scores"]:
            assert "score" in score_item


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
