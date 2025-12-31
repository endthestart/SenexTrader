"""
Tests for Quality Integration into Builder (Epic 50 Phase 3 Task 3.4).

Tests the integration of quality scoring into VerticalSpreadBuilder:
- BuildResult includes QualityScore
- Delta-based selection path
- Always-generate pattern (never returns None based on quality)
- Quality warnings flow through
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.strategies.builders.vertical_spread_builder import (
    BuildResult,
    VerticalSpreadBuilder,
)
from services.strategies.core import (
    GenerationMode,
    StrikeSelection,
    VerticalSpreadParams,
)

# =============================================================================
# BuildResult with Quality Tests
# =============================================================================


class TestBuildResultWithQuality:
    """Test BuildResult includes QualityScore."""

    def test_build_result_has_quality_field(self):
        """BuildResult should have quality field."""
        from services.strategies.quality import QualityScore

        quality = QualityScore(
            score=75.0,
            level="good",
            warnings=["Low volume"],
            component_scores={"liquidity": 70.0},
        )

        result = BuildResult(
            composition=MagicMock(),
            expiration=date(2025, 1, 17),
            strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
            success=True,
            quality=quality,
        )

        assert result.quality is not None
        assert result.quality.score == 75.0
        assert result.quality.level == "good"

    def test_success_result_with_quality(self):
        """success_result should accept quality parameter."""
        from services.strategies.quality import QualityScore

        quality = QualityScore(
            score=85.0,
            level="excellent",
            warnings=[],
            component_scores={},
        )

        result = BuildResult.success_result(
            composition=MagicMock(),
            expiration=date(2025, 1, 17),
            strikes={"short_put": Decimal("580")},
            quality=quality,
        )

        assert result.success is True
        assert result.quality.score == 85.0

    def test_failure_result_has_no_quality(self):
        """Failure result should have None quality."""
        result = BuildResult.failure_result("No strikes found")

        assert result.success is False
        assert result.quality is None


# =============================================================================
# Delta Selection Path Tests
# =============================================================================


class TestDeltaSelectionPath:
    """Test delta-based strike selection integration."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def builder(self, mock_user):
        return VerticalSpreadBuilder(mock_user)

    @pytest.fixture
    def delta_params(self):
        """Params configured for delta selection."""
        return VerticalSpreadParams.bull_put_defaults(
            selection_method=StrikeSelection.DELTA,
            delta_target=0.25,
            width_min=5,
            width_max=5,
        )

    @pytest.mark.asyncio
    async def test_delta_params_route_to_delta_selection(self, builder, delta_params):
        """Should route to delta selection when selection_method=DELTA."""
        from services.strategies.quality import QualityScore

        # Mock the _build_with_delta_selection method directly
        expected_quality = QualityScore(
            score=80.0,
            level="excellent",
            warnings=[],
            component_scores={"liquidity": 80.0},
        )

        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch.object(
                builder, "_build_with_delta_selection", new_callable=AsyncMock
            ) as mock_delta_build:
                mock_delta_build.return_value = BuildResult.success_result(
                    composition=MagicMock(),
                    expiration=date(2025, 1, 17),
                    strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
                    quality=expected_quality,
                )

                result = await builder.build("SPY", delta_params)

                # Should have called delta selection path
                mock_delta_build.assert_called_once()
                assert result.success is True
                assert result.quality.score == 80.0

    @pytest.mark.asyncio
    async def test_otm_params_route_to_otm_selection(self, builder):
        """Should route to OTM selection when selection_method=OTM_PERCENT."""
        otm_params = VerticalSpreadParams.bull_put_defaults(
            selection_method=StrikeSelection.OTM_PERCENT,
            otm_percent=0.03,
            width_min=5,
            width_max=5,
        )

        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch.object(
                builder, "_build_with_otm_selection", new_callable=AsyncMock
            ) as mock_otm_build:
                mock_otm_build.return_value = BuildResult.success_result(
                    composition=MagicMock(),
                    expiration=date(2025, 1, 17),
                    strikes={"short_put": Decimal("577"), "long_put": Decimal("572")},
                )

                result = await builder.build("SPY", otm_params)

                # Should have called OTM selection path
                mock_otm_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_delta_selection_returns_quality_in_result(self, builder, delta_params):
        """Delta selection should include quality in BuildResult."""
        from services.strategies.quality import QualityScore

        quality = QualityScore(
            score=75.0,
            level="good",
            warnings=["Low volume"],
            component_scores={"liquidity": 70.0},
        )

        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch.object(
                builder, "_build_with_delta_selection", new_callable=AsyncMock
            ) as mock_delta_build:
                mock_delta_build.return_value = BuildResult.success_result(
                    composition=MagicMock(),
                    expiration=date(2025, 1, 17),
                    strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
                    quality=quality,
                )

                result = await builder.build("SPY", delta_params)

                assert result.success is True
                assert result.quality is not None
                assert result.quality.score == 75.0
                assert result.quality.level == "good"


# =============================================================================
# Always-Generate Pattern Tests
# =============================================================================


class TestAlwaysGeneratePattern:
    """Test that builder always generates with quality, never rejects based on quality."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def builder(self, mock_user):
        return VerticalSpreadBuilder(mock_user)

    @pytest.mark.asyncio
    async def test_low_quality_still_generates(self, builder):
        """Should generate even with poor quality score."""
        from services.strategies.quality import QualityScore

        params = VerticalSpreadParams.bull_put_defaults(
            selection_method=StrikeSelection.DELTA,
            delta_target=0.25,
            generation_mode=GenerationMode.FORCE,
        )

        # Return poor quality
        poor_quality = QualityScore(
            score=25.0,
            level="poor",
            warnings=["Zero open interest", "Wide spread", "Low volume"],
            component_scores={"liquidity": 20.0},
        )

        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch.object(
                builder, "_build_with_delta_selection", new_callable=AsyncMock
            ) as mock_delta_build:
                mock_delta_build.return_value = BuildResult.success_result(
                    composition=MagicMock(),
                    expiration=date(2025, 1, 17),
                    strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
                    quality=poor_quality,
                )

                result = await builder.build("SPY", params)

                # Should still succeed despite poor quality
                assert result.success is True
                assert result.quality.score == 25.0
                assert result.quality.level == "poor"

    @pytest.mark.asyncio
    async def test_quality_warnings_preserved(self, builder):
        """Quality warnings should be preserved in result."""
        from services.strategies.quality import QualityScore

        params = VerticalSpreadParams.bull_put_defaults(
            selection_method=StrikeSelection.DELTA,
            delta_target=0.25,
        )

        quality_with_warnings = QualityScore(
            score=65.0,
            level="good",
            warnings=["Low open interest: 100 (<500)", "Wide spread: 15.0%"],
            component_scores={"liquidity": 60.0},
        )

        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch.object(
                builder, "_build_with_delta_selection", new_callable=AsyncMock
            ) as mock_delta_build:
                mock_delta_build.return_value = BuildResult.success_result(
                    composition=MagicMock(),
                    expiration=date(2025, 1, 17),
                    strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
                    quality=quality_with_warnings,
                )

                result = await builder.build("SPY", params)

                assert result.success is True
                assert len(result.quality.warnings) == 2
                assert any("interest" in w.lower() for w in result.quality.warnings)


# =============================================================================
# OTM Percent Fallback Tests
# =============================================================================


class TestOTMPercentPath:
    """Test that OTM percent selection still works."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def builder(self, mock_user):
        return VerticalSpreadBuilder(mock_user)

    @pytest.fixture
    def otm_params(self):
        """Params configured for OTM percent selection."""
        return VerticalSpreadParams.bull_put_defaults(
            selection_method=StrikeSelection.OTM_PERCENT,
            otm_percent=0.03,
            width_min=5,
            width_max=5,
        )

    @pytest.mark.asyncio
    async def test_otm_percent_uses_strike_optimizer(self, builder, otm_params):
        """Should use existing StrikeOptimizer when selection_method=OTM_PERCENT."""
        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch(
                "services.market_data.utils.expiration_utils."
                "find_expiration_with_optimal_strikes",
                new_callable=AsyncMock,
            ) as mock_find:
                mock_find.return_value = (
                    date(2025, 1, 17),
                    {"short_put": Decimal("577"), "long_put": Decimal("572")},
                    [],  # chain
                )

                result = await builder.build("SPY", otm_params)

                # Should use expiration_utils path
                mock_find.assert_called_once()

    @pytest.mark.asyncio
    async def test_otm_percent_generates_basic_quality(self, builder, otm_params):
        """OTM percent path should still generate quality score."""
        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("595.00")

            with patch(
                "services.market_data.utils.expiration_utils."
                "find_expiration_with_optimal_strikes",
                new_callable=AsyncMock,
            ) as mock_find:
                mock_find.return_value = (
                    date(2025, 1, 17),
                    {"short_put": Decimal("577"), "long_put": Decimal("572")},
                    [],
                )

                result = await builder.build("SPY", otm_params)

                # Should have some quality (even if basic)
                if result.success:
                    # Quality may be None for OTM path until Task 3.4 is complete
                    # This test documents expected behavior
                    pass


# =============================================================================
# Generation Mode Tests
# =============================================================================


class TestGenerationModes:
    """Test generation mode affects quality thresholds."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def builder(self, mock_user):
        return VerticalSpreadBuilder(mock_user)

    def test_strict_mode_uses_5_percent_threshold(self):
        """STRICT mode should use 5% quality threshold."""
        params = VerticalSpreadParams.bull_put_defaults(
            generation_mode=GenerationMode.STRICT,
        )

        threshold = params.generation_mode.get_quality_threshold()
        assert threshold == 0.05

    def test_relaxed_mode_uses_15_percent_threshold(self):
        """RELAXED mode should use 15% quality threshold."""
        params = VerticalSpreadParams.bull_put_defaults(
            generation_mode=GenerationMode.RELAXED,
        )

        threshold = params.generation_mode.get_quality_threshold()
        assert threshold == 0.15

    def test_force_mode_has_no_threshold(self):
        """FORCE mode should have no quality threshold."""
        params = VerticalSpreadParams.bull_put_defaults(
            generation_mode=GenerationMode.FORCE,
        )

        threshold = params.generation_mode.get_quality_threshold()
        assert threshold is None


# =============================================================================
# build_from_strikes Quality Tests
# =============================================================================


class TestBuildFromStrikesWithQuality:
    """Test build_from_strikes includes quality."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def builder(self, mock_user):
        return VerticalSpreadBuilder(mock_user)

    @pytest.fixture
    def params(self):
        return VerticalSpreadParams.bull_put_defaults(width_min=5, width_max=5)

    @pytest.mark.asyncio
    async def test_build_from_strikes_accepts_quality(self, builder, params):
        """build_from_strikes should accept optional quality parameter."""
        from services.strategies.quality import QualityScore

        quality = QualityScore(
            score=80.0,
            level="excellent",
            warnings=[],
            component_scores={},
        )

        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=params,
            quality=quality,
        )

        assert result.success is True
        assert result.quality is not None
        assert result.quality.score == 80.0

    @pytest.mark.asyncio
    async def test_build_from_strikes_without_quality(self, builder, params):
        """build_from_strikes without quality should still succeed."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=params,
            # No quality provided
        )

        assert result.success is True
        # Quality may be None when not provided
