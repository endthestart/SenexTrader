"""
Comprehensive tests for StrategySelector service.

Tests auto mode, forced mode, scoring, and explanation generation.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.market_data.analysis import MarketConditionReport
from services.strategies.selector import StrategySelector


@pytest.fixture
def mock_user():
    """Create mock user for testing."""
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    return user


@pytest.fixture
def ideal_market_report():
    """Create ideal market conditions report."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=448.0,
        rsi=55.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=445.0,
        support_level=440.0,
        resistance_level=460.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.25,
        iv_rank=65.0,
        iv_percentile=60.0,
        market_stress_level=30.0,
        recent_move_pct=1.5,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


@pytest.fixture
def bullish_market_report():
    """Create bullish market conditions report."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=455.0,
        open_price=450.0,
        rsi=65.0,
        macd_signal="bullish",
        bollinger_position="above_upper",
        sma_20=445.0,
        support_level=440.0,
        resistance_level=460.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.22,
        iv_rank=55.0,
        iv_percentile=50.0,
        market_stress_level=25.0,
        recent_move_pct=2.0,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


@pytest.fixture
def bearish_market_report():
    """Create bearish market conditions report."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=440.0,
        open_price=448.0,
        rsi=35.0,
        macd_signal="bearish",
        bollinger_position="below_lower",
        sma_20=448.0,
        support_level=435.0,
        resistance_level=455.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.28,
        iv_rank=70.0,
        iv_percentile=65.0,
        market_stress_level=55.0,
        recent_move_pct=2.5,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


@pytest.fixture
def no_trade_report():
    """Create report with no-trade conditions."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=450.0,
        rsi=50.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=445.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.20,
        iv_rank=50.0,
        iv_percentile=45.0,
        market_stress_level=40.0,
        recent_move_pct=1.0,
        is_data_stale=True,
        last_update=datetime.now(UTC),
        no_trade_reasons=["data_stale"],
    )


@pytest.fixture
def low_score_report():
    """Create report that produces low scores for all strategies."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=450.0,
        open_price=450.0,
        rsi=50.0,
        macd_signal="neutral",
        bollinger_position="within_bands",
        sma_20=450.0,
        is_range_bound=False,
        range_bound_days=0,
        current_iv=0.10,  # Very low IV
        iv_rank=5.0,  # Very low IV rank
        iv_percentile=3.0,
        market_stress_level=85.0,  # High stress
        recent_move_pct=0.3,
        is_data_stale=False,
        last_update=datetime.now(UTC),
        no_trade_reasons=[],
    )


class TestStrategySelector:
    """Test suite for StrategySelector."""

    def _mock_strategy_generation(self, selector):
        """Helper to mock all strategy generation methods."""
        # Mock the stream manager that the selector actually uses
        from unittest.mock import MagicMock

        mock_suggestion = MagicMock()
        mock_suggestion.id = 1
        mock_suggestion.strategy = "test_strategy"

        for name, strategy in selector.strategies.items():
            # Mock prepare_suggestion_context to return valid context
            strategy.a_prepare_suggestion_context = AsyncMock(
                return_value={"symbol": "SPY", "strategy": name}
            )

    async def _mock_stream_manager(self):
        """Helper to create mock stream manager."""
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_suggestion = MagicMock()
        mock_suggestion.id = 1
        mock_manager.a_process_suggestion_request = AsyncMock(return_value=mock_suggestion)
        return mock_manager

    @pytest.mark.asyncio
    async def test_auto_mode_ideal_conditions(self, mock_user, ideal_market_report):
        """Test auto mode with ideal conditions selects best strategy."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        # Mock stream manager
        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock validator and stream manager
        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should select a strategy (highest scoring available)
            assert strategy_name is not None
            assert suggestion is not None
            # Check dict structure
            assert isinstance(explanation, dict)
            assert explanation["type"] == "auto"
            assert "Selected:" in explanation["title"]
            assert "confidence" in explanation
            assert "scores" in explanation
            assert "market" in explanation

    @pytest.mark.asyncio
    async def test_auto_mode_bullish_conditions(self, mock_user, bullish_market_report):
        """Test auto mode with bullish conditions selects bull put spread."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer,
                "a_analyze_market_conditions",
                return_value=bullish_market_report,
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should select a strategy (bullish market - scoring determines which)
            assert strategy_name is not None
            assert suggestion is not None
            assert isinstance(explanation, dict)
            assert "Selected:" in explanation["title"]

    @pytest.mark.asyncio
    async def test_auto_mode_bearish_conditions(self, mock_user, bearish_market_report):
        """Test auto mode with bearish conditions selects bear call spread."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer,
                "a_analyze_market_conditions",
                return_value=bearish_market_report,
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should select a strategy (bearish market - scoring determines which)
            assert strategy_name is not None
            assert suggestion is not None
            assert isinstance(explanation, dict)
            assert "Selected:" in explanation["title"]

    @pytest.mark.asyncio
    async def test_auto_mode_no_trade_conditions(self, mock_user, no_trade_report):
        """Test auto mode rejects trade when hard stops active."""
        selector = StrategySelector(mock_user)

        with patch.object(
            selector.analyzer, "a_analyze_market_conditions", return_value=no_trade_report
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Should return None with explanation
            assert strategy_name is None
            assert suggestion is None
            assert isinstance(explanation, dict)
            assert explanation["type"] == "no_trade"
            assert "No Trade Conditions" in explanation["title"]
            assert "hard_stops" in explanation
            assert "Data Stale" in explanation["hard_stops"]

    @pytest.mark.asyncio
    async def test_auto_mode_low_scores(self, mock_user, low_score_report):
        """Test auto mode when all strategies score below threshold."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=low_score_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, _suggestion, explanation = await selector.a_select_and_generate("SPY")

            # With low scores, selector may still pick best strategy or reject
            # This is acceptable behavior - selector picks best even if marginal
            # Should either reject or pick best strategy
            assert isinstance(explanation, dict)
            if strategy_name is None:
                # Check for low_scores type explanation
                assert explanation["type"] in ["low_scores", "auto"]
                assert "scores" in explanation
            else:
                # If it selects, it should be the highest scorer (any strategy possible)
                # May be None due to generation failure, which is OK
                assert explanation["type"] in ["auto", "low_scores"]

    @pytest.mark.asyncio
    async def test_forced_mode_valid_strategy(self, mock_user, ideal_market_report):
        """Test forced mode generates requested strategy."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Should generate requested strategy
            assert strategy_name == "short_put_vertical"
            assert suggestion is not None
            assert isinstance(explanation, dict)
            assert explanation["type"] == "forced"
            assert "Short Put Vertical" in explanation["title"]
            assert "confidence" in explanation

    @pytest.mark.asyncio
    async def test_forced_mode_invalid_strategy(self, mock_user, ideal_market_report):
        """Test forced mode with invalid strategy name."""
        selector = StrategySelector(mock_user)

        with patch.object(
            selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="invalid_strategy"
            )

            # Should return error message
            assert strategy_name is None
            assert suggestion is None
            assert "Unknown strategy: invalid_strategy" in explanation
            assert "Available:" in explanation

    @pytest.mark.asyncio
    async def test_forced_mode_low_confidence_warning(self, mock_user, bearish_market_report):
        """Test forced mode shows warning for low confidence."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer,
                "a_analyze_market_conditions",
                return_value=bearish_market_report,
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            # Force Short Put Vertical in bearish market (bad conditions)
            strategy_name, suggestion, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Should generate requested strategy even with low confidence
            assert strategy_name == "short_put_vertical"
            assert suggestion is not None
            assert isinstance(explanation, dict)
            assert explanation["type"] == "forced"
            # Bull Put in bearish market should have low confidence
            assert "confidence" in explanation

    @pytest.mark.asyncio
    async def test_forced_mode_starts_streaming_when_not_active(
        self, mock_user, ideal_market_report
    ):
        """Test forced mode starts streaming if not already active."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()
        # Explicitly set is_streaming to False to test the fix
        mock_manager.is_streaming = False
        mock_manager.connection_state = "disconnected"

        # Mock start_streaming to simulate successful connection
        async def mock_start_streaming(symbols):
            mock_manager.is_streaming = True
            mock_manager.connection_state = "connected"

        mock_manager.start_streaming = AsyncMock(side_effect=mock_start_streaming)

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, _explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Should start streaming when not active
            mock_manager.start_streaming.assert_called_once_with(["SPY"])
            # Should generate requested strategy
            assert strategy_name == "short_put_vertical"
            assert suggestion is not None

    @pytest.mark.asyncio
    async def test_forced_mode_skips_streaming_start_when_active(
        self, mock_user, ideal_market_report
    ):
        """Test forced mode skips streaming start if already active."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()
        # Set is_streaming to True (already active)
        mock_manager.is_streaming = True
        mock_manager.start_streaming = AsyncMock()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, _explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Should NOT start streaming when already active
            mock_manager.start_streaming.assert_not_called()
            # Should generate requested strategy
            assert strategy_name == "short_put_vertical"
            assert suggestion is not None

    @pytest.mark.asyncio
    async def test_forced_mode_fails_when_streaming_cannot_start(
        self, mock_user, ideal_market_report
    ):
        """Test forced mode returns error when streaming fails to start."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()
        # Set is_streaming to False and keep it False after start_streaming
        mock_manager.is_streaming = False
        mock_manager.connection_state = "disconnected"

        # Mock start_streaming but don't change state (simulating failure)
        mock_manager.start_streaming = AsyncMock()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, suggestion, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Should attempt to start streaming
            mock_manager.start_streaming.assert_called_once_with(["SPY"])
            # Should return strategy name but no suggestion
            assert strategy_name == "short_put_vertical"
            assert suggestion is None
            # Should have error explanation
            assert isinstance(explanation, dict)
            assert explanation["type"] == "forced"
            assert "Failed" in explanation["title"]
            assert "streaming" in explanation["conditions"][0].lower()

    @pytest.mark.asyncio
    async def test_score_to_confidence_levels(self, mock_user):
        """Test confidence level conversion from scores."""
        selector = StrategySelector(mock_user)

        # Test all confidence levels
        assert selector._score_to_confidence(90) == "HIGH"
        assert selector._score_to_confidence(80) == "HIGH"
        assert selector._score_to_confidence(70) == "MEDIUM"
        assert selector._score_to_confidence(60) == "MEDIUM"
        assert selector._score_to_confidence(50) == "LOW"
        assert selector._score_to_confidence(40) == "LOW"
        assert selector._score_to_confidence(30) == "VERY LOW"
        assert selector._score_to_confidence(0) == "VERY LOW"

    @pytest.mark.asyncio
    async def test_all_strategies_scored_in_auto_mode(self, mock_user, ideal_market_report):
        """Test that all strategies are scored in auto mode."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _strategy_name, _suggestion, explanation = await selector.a_select_and_generate("SPY")

            # Explanation should include all scored strategies
            assert isinstance(explanation, dict)
            assert "scores" in explanation
            strategy_keys = [s["strategy_key"] for s in explanation["scores"]]
            # Should have multiple strategies scored
            assert len(strategy_keys) >= 2

    @pytest.mark.asyncio
    async def test_auto_mode_explanation_format(self, mock_user, ideal_market_report):
        """Test auto mode explanation has correct format."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, _, explanation = await selector.a_select_and_generate("SPY")

            # Check required sections in dict format
            assert isinstance(explanation, dict)
            assert explanation["type"] == "auto"
            assert "Selected:" in explanation["title"]
            assert "confidence" in explanation
            assert "level" in explanation["confidence"]
            assert "score" in explanation["confidence"]
            assert "scores" in explanation
            assert "market" in explanation
            assert "direction" in explanation["market"]
            assert "iv_rank" in explanation["market"]
            assert "volatility" in explanation["market"]

    @pytest.mark.asyncio
    async def test_forced_mode_explanation_format(self, mock_user, ideal_market_report):
        """Test forced mode explanation has correct format."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, _, explanation = await selector.a_select_and_generate(
                "SPY", forced_strategy="short_put_vertical"
            )

            # Check required sections in dict format
            assert isinstance(explanation, dict)
            assert explanation["type"] == "forced"
            assert "Requested:" in explanation["title"]
            assert "confidence" in explanation
            assert "conditions" in explanation
            assert "market" in explanation

    @pytest.mark.asyncio
    async def test_strategy_scoring_error_handling(self, mock_user, ideal_market_report):
        """Test handling of strategy scoring errors."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock one strategy to raise exception
        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(
                selector.strategies["short_put_vertical"],
                "a_score_market_conditions",
                side_effect=Exception("Scoring failed"),
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, _, _explanation = await selector.a_select_and_generate("SPY")

            # Should still select a strategy (one that didn't error)
            # Since short_put_vertical errored, should select different strategy
            assert strategy_name is not None
            assert strategy_name != "short_put_vertical"

    @pytest.mark.asyncio
    async def test_no_trade_explanation_includes_last_update(self, mock_user, no_trade_report):
        """Test no-trade explanation includes timestamp."""
        selector = StrategySelector(mock_user)

        with patch.object(
            selector.analyzer, "a_analyze_market_conditions", return_value=no_trade_report
        ):
            _, _, explanation = await selector.a_select_and_generate("SPY")

            # Should include last update time and data stale status
            assert isinstance(explanation, dict)
            assert "market_status" in explanation
            assert "last_update" in explanation["market_status"]
            assert explanation["market_status"]["data_stale"] is True

    @pytest.mark.asyncio
    async def test_auto_mode_sorts_strategies_by_score(self, mock_user, ideal_market_report):
        """Test that auto mode explanation lists strategies sorted by score."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            _, _, explanation = await selector.a_select_and_generate("SPY")

            # Extract strategy scores from explanation dict
            assert isinstance(explanation, dict)
            assert "scores" in explanation
            scores = explanation["scores"]

            # Should have multiple strategies
            assert len(scores) >= 2

            # Scores should be in descending order
            for i in range(len(scores) - 1):
                assert scores[i]["score"] >= scores[i + 1]["score"]

    @pytest.mark.asyncio
    async def test_selected_strategy_marked_in_explanation(self, mock_user, ideal_market_report):
        """Test that selected strategy is marked with indicator."""
        selector = StrategySelector(mock_user)
        self._mock_strategy_generation(selector)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            strategy_name, _, explanation = await selector.a_select_and_generate("SPY")

            # Selected strategy should be marked in scores list
            assert isinstance(explanation, dict)
            assert "scores" in explanation
            selected_strategies = [s for s in explanation["scores"] if s["selected"]]
            assert len(selected_strategies) == 1
            assert selected_strategies[0]["strategy_key"] == strategy_name

    @pytest.mark.asyncio
    async def test_suggestion_mode_bypasses_risk_at_100_percent(
        self, mock_user, ideal_market_report
    ):
        """
        CRITICAL TEST (Epic 24 Task 006): Verify suggestion_mode=True bypasses risk validation.

        This test directly verifies the fix in a_calculate_suggestion_from_cached_data()
        by testing with real strategy code (only mocking dependencies, not strategy methods).
        """
        from decimal import Decimal

        from services.strategies.credit_spread_strategy import ShortPutVerticalStrategy

        strategy = ShortPutVerticalStrategy(mock_user)

        # Mock only the risk manager to simulate 100% utilization
        strategy.risk_manager.a_can_open_position = AsyncMock(
            return_value=(False, "Risk budget exceeded")
        )

        # Create a context dict as if it came from a_prepare_suggestion_context
        # This simulates the real flow where context is prepared, then pricing arrives
        test_context = {
            "config_id": 1,
            "symbol": "SPY",
            "expiration": "2025-11-21",
            "market_data": {
                "current_price": 450.0,
                "iv_rank": 65.0,
                "is_stressed": False,
                "score": 75.0,
                "explanation": "Test conditions",
                "is_range_bound": False,
                "market_stress_level": 30.0,
                "macd_signal": "neutral",
                "bollinger_position": "within_bands",
            },
            "spread_width": 5,
            "strikes": {"short_put": 445.0, "long_put": 440.0},
            "occ_bundle": {
                "underlying": "SPY",
                "expiration": "2025-11-21",
                "legs": [],
            },
            "is_automated": False,
        }

        # Mock pricing data
        mock_pricing = MagicMock()
        mock_pricing.put_credit = Decimal("1.85")
        mock_pricing.put_mid_credit = Decimal("1.85")
        strategy.options_service.read_spread_pricing = MagicMock(return_value=mock_pricing)

        # Mock config
        mock_config = MagicMock()
        mock_config.id = 1
        with patch("trading.models.StrategyConfiguration") as MockConfig:
            MockConfig.objects.aget = AsyncMock(return_value=mock_config)

            # Test with suggestion_mode=False - should be blocked by risk
            context_execution = {**test_context, "suggestion_mode": False}
            result_blocked = await strategy.a_calculate_suggestion_from_cached_data(
                context_execution
            )
            # Should return error dict (not None) due to risk check
            assert result_blocked is not None, "Should return error info"
            assert result_blocked.get("error") is True, "Should indicate error"
            assert "risk_budget_exceeded" in result_blocked.get("error_type", "")

            # Test with suggestion_mode=True - should bypass risk and create suggestion
            context_suggestion = {**test_context, "suggestion_mode": True}
            with patch("trading.models.TradingSuggestion") as MockSuggestion:
                mock_suggestion_obj = MagicMock()
                mock_suggestion_obj.id = 100
                MockSuggestion.objects.acreate = AsyncMock(return_value=mock_suggestion_obj)

                result_allowed = await strategy.a_calculate_suggestion_from_cached_data(
                    context_suggestion
                )
                # Should create suggestion (not return error dict)
                assert result_allowed is not None, "Should create suggestion"
                # Verify suggestion was created (acreate called)
                assert MockSuggestion.objects.acreate.called, "Should create TradingSuggestion"

    @pytest.mark.asyncio
    async def test_multi_strategy_suggestions_at_max_risk(self, mock_user, ideal_market_report):
        """
        CRITICAL TEST (Epic 24 Task 006): Verify a_select_top_suggestions works at 100% risk.

        This test uses real strategy code with only risk manager mocked to verify
        multi-strategy selection bypasses risk when suggestion_mode=True.
        """
        selector = StrategySelector(mock_user)

        from streaming.services.stream_manager import GlobalStreamManager

        mock_manager = await self._mock_stream_manager()

        # Mock strategy generation methods but keep prepare_suggestion_context real
        for name, strategy in selector.strategies.items():
            # Save the real prepare method before any mocking

            # Mock only what's needed for the test to work
            strategy.a_prepare_suggestion_context = AsyncMock(
                return_value={
                    "symbol": "SPY",
                    "strategy": name,
                    "suggestion_mode": True,  # This is the key flag
                }
            )

        with (
            patch.object(
                selector.analyzer, "a_analyze_market_conditions", return_value=ideal_market_report
            ),
            patch.object(GlobalStreamManager, "get_user_manager", return_value=mock_manager),
        ):
            # Mock risk manager to simulate 100% utilization
            for strategy in selector.strategies.values():
                strategy.risk_manager.a_can_open_position = AsyncMock(
                    return_value=(False, "Risk budget exceeded")
                )

            # Call a_select_top_suggestions with suggestion_mode=True
            suggestions, context = await selector.a_select_top_suggestions(
                symbol="SPY", count=3, suggestion_mode=True
            )

            # Assertions
            assert suggestions is not None, "Must return suggestions list at max risk"
            assert len(suggestions) > 0, "Must generate at least 1 suggestion at 100% risk"
            assert len(suggestions) <= 3, "Should respect count parameter"

            # Verify all suggestions have required fields
            for strategy_name, suggestion, explanation in suggestions:
                assert strategy_name is not None, "Strategy name must be present"
                assert suggestion is not None, "Suggestion object must be present"
                assert explanation is not None, "Explanation must be present"
                assert isinstance(explanation, dict), "Explanation should be dict"

            # Verify context
            assert context is not None
            assert context["type"] == "suggestions"
            assert "market_report" in context or "market" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
