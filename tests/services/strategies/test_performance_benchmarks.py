"""
Performance Benchmarks for Strategy Architecture - Epic 50 Task 6.2

Ensures the unified strategy architecture does not regress performance.
Measures:
- Strategy instantiation time
- Market condition scoring time
- Factory lookup time
"""

import time
from decimal import Decimal
from statistics import mean, stdev
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_user():
    """Create mock user."""
    user = MagicMock()
    user.id = 1
    return user


@pytest.fixture
def mock_market_report():
    """Create comprehensive market report for scoring."""
    report = MagicMock()
    report.current_price = 550.0
    report.open_price = 548.0
    report.symbol = "QQQ"
    report.data_available = True
    report.iv_rank = 45.0
    report.hv_iv_ratio = 1.0
    report.adx = 25.0
    report.macd_signal = "neutral"
    report.market_stress_level = 40.0
    report.recent_move_pct = 0.5
    report.bollinger_position = "within_bands"
    report.rsi = 50.0
    report.sma_20 = 545.0
    report.regime_confidence = 75.0
    report.current_regime = "neutral"
    report.regime_primary = None
    report.trend_strength = "moderate"
    report.historical_volatility = 20.0
    report.current_iv = 0.22
    report.iv_percentile = 45.0
    report.is_range_bound = True
    report.range_bound_days = 10
    report.volume_ratio = 1.0
    report.put_call_ratio = 1.0
    report.vix = 20.0
    report.is_overbought = False
    report.is_oversold = False
    report.overbought_warnings = 0
    report.oversold_warnings = 0
    report.momentum_signal = None
    report.momentum_confidence = 50.0
    report.earnings_soon = False
    report.support_level = 530.0
    report.resistance_level = 570.0
    return report


class TestStrategyInstantiationPerformance:
    """Benchmark strategy instantiation times."""

    # Performance thresholds (in milliseconds)
    MAX_SINGLE_INSTANTIATION_MS = 50  # Single strategy should instantiate < 50ms
    MAX_ALL_STRATEGIES_MS = 500  # All strategies should instantiate < 500ms

    def test_single_strategy_instantiation_time(self, mock_user):
        """Single strategy should instantiate quickly."""
        from services.strategies.factory import get_strategy

        times = []
        iterations = 100

        for _ in range(iterations):
            start = time.perf_counter()
            strategy = get_strategy("short_put_vertical", mock_user)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)
        max_time = max(times)

        assert avg_time < self.MAX_SINGLE_INSTANTIATION_MS, (
            f"Average instantiation time {avg_time:.2f}ms exceeds threshold "
            f"{self.MAX_SINGLE_INSTANTIATION_MS}ms"
        )

        # Log results for visibility
        print(f"\nSingle strategy instantiation ({iterations} iterations):")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  Max: {max_time:.3f}ms")
        print(f"  Std Dev: {stdev(times):.3f}ms")

    def test_all_strategies_instantiation_time(self, mock_user):
        """All strategies should instantiate within threshold."""
        from services.strategies.factory import get_all_strategies

        times = []
        iterations = 10

        for _ in range(iterations):
            start = time.perf_counter()
            strategies = get_all_strategies(mock_user)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)
        strategy_count = len(strategies)

        assert avg_time < self.MAX_ALL_STRATEGIES_MS, (
            f"All strategies instantiation time {avg_time:.2f}ms exceeds threshold "
            f"{self.MAX_ALL_STRATEGIES_MS}ms"
        )

        print(f"\nAll {strategy_count} strategies instantiation ({iterations} iterations):")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  Per strategy: {avg_time/strategy_count:.3f}ms")


class TestFactoryLookupPerformance:
    """Benchmark factory lookup times."""

    MAX_LOOKUP_MS = 1  # Factory lookup should be < 1ms

    def test_factory_lookup_time(self):
        """Factory lookup should be very fast."""
        from services.strategies.factory import is_strategy_registered

        times = []
        iterations = 1000

        for _ in range(iterations):
            start = time.perf_counter()
            is_strategy_registered("short_put_vertical")
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)

        assert avg_time < self.MAX_LOOKUP_MS, (
            f"Factory lookup time {avg_time:.4f}ms exceeds threshold {self.MAX_LOOKUP_MS}ms"
        )

        print(f"\nFactory lookup ({iterations} iterations):")
        print(f"  Average: {avg_time:.6f}ms")

    def test_list_strategies_time(self):
        """Listing strategies should be fast."""
        from services.strategies.factory import list_strategies

        times = []
        iterations = 100

        for _ in range(iterations):
            start = time.perf_counter()
            strategies = list_strategies()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)

        assert avg_time < 5, f"List strategies time {avg_time:.4f}ms exceeds 5ms threshold"

        print(f"\nList strategies ({iterations} iterations):")
        print(f"  Average: {avg_time:.6f}ms")
        print(f"  Strategy count: {len(strategies)}")


class TestMarketConditionScoringPerformance:
    """Benchmark market condition scoring times."""

    MAX_SCORING_MS = 10  # Scoring should complete < 10ms

    @pytest.mark.asyncio
    async def test_single_strategy_scoring_time(self, mock_user, mock_market_report):
        """Single strategy scoring should be fast."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_put_vertical", mock_user)
        times = []
        iterations = 100

        for _ in range(iterations):
            start = time.perf_counter()
            score, explanation = await strategy.a_score_market_conditions(mock_market_report)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)

        assert avg_time < self.MAX_SCORING_MS, (
            f"Scoring time {avg_time:.2f}ms exceeds threshold {self.MAX_SCORING_MS}ms"
        )

        print(f"\nSingle strategy scoring ({iterations} iterations):")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  Max: {max(times):.3f}ms")

    @pytest.mark.asyncio
    async def test_all_strategies_scoring_time(self, mock_user, mock_market_report):
        """Scoring all strategies should complete in reasonable time."""
        from services.strategies.factory import get_all_strategies

        strategies = get_all_strategies(mock_user)
        times = []
        iterations = 5

        for _ in range(iterations):
            start = time.perf_counter()
            for name, strategy in strategies.items():
                if hasattr(strategy, "a_score_market_conditions"):
                    await strategy.a_score_market_conditions(mock_market_report)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = mean(times)
        strategy_count = len(strategies)

        # Allow 10ms per strategy
        max_total_time = strategy_count * self.MAX_SCORING_MS

        assert avg_time < max_total_time, (
            f"All strategies scoring {avg_time:.2f}ms exceeds {max_total_time}ms "
            f"({strategy_count} strategies * {self.MAX_SCORING_MS}ms)"
        )

        print(f"\nAll {strategy_count} strategies scoring ({iterations} iterations):")
        print(f"  Average total: {avg_time:.3f}ms")
        print(f"  Per strategy: {avg_time/strategy_count:.3f}ms")


class TestMemoryUsage:
    """Basic memory usage tests."""

    def test_strategy_memory_footprint(self, mock_user):
        """Strategies should have reasonable memory footprint."""
        import sys

        from services.strategies.factory import get_all_strategies

        strategies = get_all_strategies(mock_user)

        # Get approximate memory size
        total_size = sum(sys.getsizeof(s) for s in strategies.values())

        # Should be less than 1MB for all strategies
        max_bytes = 1024 * 1024  # 1MB

        assert total_size < max_bytes, (
            f"Total strategy memory {total_size/1024:.1f}KB exceeds 1MB limit"
        )

        print(f"\nMemory usage ({len(strategies)} strategies):")
        print(f"  Total: {total_size/1024:.2f}KB")
        print(f"  Per strategy: {total_size/len(strategies)/1024:.2f}KB")


class TestBuildPerformance:
    """Benchmark builder performance (if available)."""

    @pytest.mark.asyncio
    async def test_vertical_spread_builder_speed(self, mock_user):
        """VerticalSpreadBuilder should be fast."""
        from unittest.mock import AsyncMock, patch

        from services.strategies.builders import VerticalSpreadBuilder
        from services.strategies.core import Direction, OptionType, VerticalSpreadParams

        builder = VerticalSpreadBuilder(mock_user)
        params = VerticalSpreadParams(
            direction=Direction.BULLISH,
            option_type=OptionType.PUT,
            width_min=5,
            width_max=5,
        )

        # Mock the external calls
        with patch.object(builder, "_get_current_price", new_callable=AsyncMock) as mock_price:
            with patch(
                "services.market_data.utils.expiration_utils.find_expiration_with_optimal_strikes",
                new_callable=AsyncMock,
            ) as mock_exp:
                mock_price.return_value = Decimal("550.00")
                mock_exp.return_value = None  # Simulate no expiration found

                times = []
                iterations = 50

                for _ in range(iterations):
                    start = time.perf_counter()
                    await builder.build("QQQ", params)
                    elapsed = (time.perf_counter() - start) * 1000
                    times.append(elapsed)

                avg_time = mean(times)

                # Builder should complete quickly even with mocked calls
                assert avg_time < 50, f"Builder time {avg_time:.2f}ms exceeds 50ms threshold"

                print(f"\nVerticalSpreadBuilder.build ({iterations} iterations):")
                print(f"  Average: {avg_time:.3f}ms")
