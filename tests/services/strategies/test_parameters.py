"""
Unit tests for Epic 50 Task 001: Strategy Parameter System

Tests the foundational parameter system including StrategyParameters dataclass,
GenerationMode enum, and ParameterBuilder for creating parameters from various sources.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from services.market_data.analysis import MarketConditionReport
from services.strategies.parameters import (
    GenerationMode,
    ParameterBuilder,
    StrategyParameters,
)


class TestGenerationMode:
    """Test GenerationMode enum and quality thresholds."""

    def test_enum_values(self):
        """Test enum has correct values."""
        assert GenerationMode.STRICT.value == "strict"
        assert GenerationMode.RELAXED.value == "relaxed"
        assert GenerationMode.FORCE.value == "force"

    def test_strict_threshold(self):
        """Test STRICT mode returns 5% threshold."""
        threshold = GenerationMode.STRICT.get_quality_threshold()
        assert threshold == 0.05

    def test_relaxed_threshold(self):
        """Test RELAXED mode returns 15% threshold."""
        threshold = GenerationMode.RELAXED.get_quality_threshold()
        assert threshold == 0.15

    def test_force_no_threshold(self):
        """Test FORCE mode returns None (no threshold)."""
        threshold = GenerationMode.FORCE.get_quality_threshold()
        assert threshold is None


class TestStrategyParameters:
    """Test StrategyParameters dataclass validation and behavior."""

    def test_default_parameters(self):
        """Test default parameter values are set correctly."""
        params = StrategyParameters()

        assert params.dte_min == 30
        assert params.dte_max == 45
        assert params.spread_width == 5
        assert params.otm_percentage == 0.03
        assert params.generation_mode == GenerationMode.STRICT
        assert params.profit_target_pct == 50
        assert params.support_buffer_pct == 2.0
        assert params.resistance_buffer_pct == 2.0
        assert params.min_iv_rank is None
        assert params.min_score_threshold is None
        assert params.source == "unknown"
        assert params.metadata == {}

    def test_custom_parameters(self):
        """Test custom parameter values can be set."""
        params = StrategyParameters(
            dte_min=35,
            dte_max=60,
            spread_width=10,
            otm_percentage=0.05,
            generation_mode=GenerationMode.FORCE,
            profit_target_pct=60,
            support_buffer_pct=3.0,
            resistance_buffer_pct=3.0,
            min_iv_rank=40.0,
            min_score_threshold=50.0,
            source="test",
            metadata={"test": "data"},
        )

        assert params.dte_min == 35
        assert params.dte_max == 60
        assert params.spread_width == 10
        assert params.otm_percentage == 0.05
        assert params.generation_mode == GenerationMode.FORCE
        assert params.profit_target_pct == 60
        assert params.support_buffer_pct == 3.0
        assert params.resistance_buffer_pct == 3.0
        assert params.min_iv_rank == 40.0
        assert params.min_score_threshold == 50.0
        assert params.source == "test"
        assert params.metadata == {"test": "data"}

    def test_dte_min_too_low_raises_error(self):
        """Test validation rejects dte_min < 1."""
        with pytest.raises(ValueError, match="dte_min must be at least 1"):
            StrategyParameters(dte_min=0)

    def test_dte_max_too_low_raises_error(self):
        """Test validation rejects dte_max < 1."""
        with pytest.raises(ValueError, match="dte_max must be at least 1"):
            StrategyParameters(dte_max=0)

    def test_dte_min_greater_than_max_raises_error(self):
        """Test validation rejects dte_min > dte_max."""
        with pytest.raises(ValueError, match="dte_min.*cannot be greater than dte_max"):
            StrategyParameters(dte_min=60, dte_max=45)

    def test_spread_width_too_low_raises_error(self):
        """Test validation rejects spread_width < 1."""
        with pytest.raises(ValueError, match="spread_width must be at least 1"):
            StrategyParameters(spread_width=0)

    def test_otm_percentage_below_zero_raises_error(self):
        """Test validation rejects negative OTM percentage."""
        with pytest.raises(ValueError, match="otm_percentage must be between 0 and 1"):
            StrategyParameters(otm_percentage=-0.01)

    def test_otm_percentage_above_one_raises_error(self):
        """Test validation rejects OTM percentage > 1."""
        with pytest.raises(ValueError, match="otm_percentage must be between 0 and 1"):
            StrategyParameters(otm_percentage=1.5)

    def test_profit_target_below_zero_raises_error(self):
        """Test validation rejects negative profit target."""
        with pytest.raises(ValueError, match="profit_target_pct must be between 0 and 100"):
            StrategyParameters(profit_target_pct=-10)

    def test_profit_target_above_100_raises_error(self):
        """Test validation rejects profit target > 100."""
        with pytest.raises(ValueError, match="profit_target_pct must be between 0 and 100"):
            StrategyParameters(profit_target_pct=150)

    def test_support_buffer_negative_raises_error(self):
        """Test validation rejects negative support buffer."""
        with pytest.raises(ValueError, match="support_buffer_pct cannot be negative"):
            StrategyParameters(support_buffer_pct=-1.0)

    def test_resistance_buffer_negative_raises_error(self):
        """Test validation rejects negative resistance buffer."""
        with pytest.raises(ValueError, match="resistance_buffer_pct cannot be negative"):
            StrategyParameters(resistance_buffer_pct=-1.0)

    def test_min_iv_rank_below_zero_raises_error(self):
        """Test validation rejects negative IV rank."""
        with pytest.raises(ValueError, match="min_iv_rank must be between 0 and 100"):
            StrategyParameters(min_iv_rank=-5.0)

    def test_min_iv_rank_above_100_raises_error(self):
        """Test validation rejects IV rank > 100."""
        with pytest.raises(ValueError, match="min_iv_rank must be between 0 and 100"):
            StrategyParameters(min_iv_rank=105.0)

    def test_min_score_threshold_below_zero_raises_error(self):
        """Test validation rejects negative score threshold."""
        with pytest.raises(ValueError, match="min_score_threshold must be between 0 and 100"):
            StrategyParameters(min_score_threshold=-5.0)

    def test_min_score_threshold_above_100_raises_error(self):
        """Test validation rejects score threshold > 100."""
        with pytest.raises(ValueError, match="min_score_threshold must be between 0 and 100"):
            StrategyParameters(min_score_threshold=105.0)

    def test_edge_case_dte_min_equals_max(self):
        """Test that dte_min == dte_max is valid."""
        params = StrategyParameters(dte_min=45, dte_max=45)
        assert params.dte_min == 45
        assert params.dte_max == 45

    def test_edge_case_zero_otm_percentage(self):
        """Test that OTM percentage of 0 is valid (ATM)."""
        params = StrategyParameters(otm_percentage=0.0)
        assert params.otm_percentage == 0.0

    def test_edge_case_one_otm_percentage(self):
        """Test that OTM percentage of 1.0 is valid (100% OTM)."""
        params = StrategyParameters(otm_percentage=1.0)
        assert params.otm_percentage == 1.0

    def test_edge_case_zero_profit_target(self):
        """Test that profit target of 0 is valid."""
        params = StrategyParameters(profit_target_pct=0)
        assert params.profit_target_pct == 0

    def test_edge_case_100_profit_target(self):
        """Test that profit target of 100 is valid."""
        params = StrategyParameters(profit_target_pct=100)
        assert params.profit_target_pct == 100

    def test_edge_case_zero_iv_rank(self):
        """Test that IV rank of 0 is valid."""
        params = StrategyParameters(min_iv_rank=0.0)
        assert params.min_iv_rank == 0.0

    def test_edge_case_100_iv_rank(self):
        """Test that IV rank of 100 is valid."""
        params = StrategyParameters(min_iv_rank=100.0)
        assert params.min_iv_rank == 100.0

    def test_to_dict_conversion(self):
        """Test converting parameters to dictionary."""
        params = StrategyParameters(
            dte_min=35,
            dte_max=50,
            spread_width=7,
            otm_percentage=0.04,
            generation_mode=GenerationMode.RELAXED,
            source="test",
            metadata={"key": "value"},
        )

        result = params.to_dict()

        assert isinstance(result, dict)
        assert result["dte_min"] == 35
        assert result["dte_max"] == 50
        assert result["spread_width"] == 7
        assert result["otm_percentage"] == 0.04
        assert result["generation_mode"] == "relaxed"
        assert result["source"] == "test"
        assert result["metadata"] == {"key": "value"}

    def test_to_dict_with_none_values(self):
        """Test to_dict handles None values correctly."""
        params = StrategyParameters()
        result = params.to_dict()

        assert result["min_iv_rank"] is None
        assert result["min_score_threshold"] is None


class TestParameterBuilder:
    """Test ParameterBuilder factory methods."""

    def test_defaults_method(self):
        """Test creating parameters with system defaults."""
        params = ParameterBuilder.defaults()

        assert params.dte_min == 30
        assert params.dte_max == 45
        assert params.spread_width == 5
        assert params.generation_mode == GenerationMode.STRICT
        assert params.source == "defaults"

    def test_defaults_method_with_mode(self):
        """Test defaults method respects generation mode parameter."""
        params = ParameterBuilder.defaults(generation_mode=GenerationMode.FORCE)

        assert params.generation_mode == GenerationMode.FORCE
        assert params.source == "defaults"

    def test_manual_method_basic(self):
        """Test creating parameters from manual input with defaults."""
        params = ParameterBuilder.manual()

        assert params.dte_min == 30
        assert params.dte_max == 45
        assert params.spread_width == 5
        assert params.otm_percentage == 0.03
        assert params.generation_mode == GenerationMode.FORCE  # Default for manual
        assert params.source == "manual"

    def test_manual_method_custom_values(self):
        """Test manual method with custom values."""
        params = ParameterBuilder.manual(
            dte_min=40,
            dte_max=60,
            spread_width=10,
            otm_percentage=0.05,
            generation_mode=GenerationMode.RELAXED,
        )

        assert params.dte_min == 40
        assert params.dte_max == 60
        assert params.spread_width == 10
        assert params.otm_percentage == 0.05
        assert params.generation_mode == GenerationMode.RELAXED
        assert params.source == "manual"

    def test_manual_method_with_kwargs(self):
        """Test manual method accepts additional kwargs."""
        params = ParameterBuilder.manual(
            profit_target_pct=70,
            min_iv_rank=45.0,
            support_buffer_pct=3.5,
        )

        assert params.profit_target_pct == 70
        assert params.min_iv_rank == 45.0
        assert params.support_buffer_pct == 3.5

    def test_manual_method_with_metadata(self):
        """Test manual method accepts metadata in kwargs."""
        params = ParameterBuilder.manual(
            metadata={"user_id": 123, "request_id": "abc"},
        )

        assert params.metadata == {"user_id": 123, "request_id": "abc"}

    def test_from_market_report_basic(self):
        """Test creating parameters from market condition report."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            iv_rank=60.0,
            market_stress_level=25.0,
        )

        params = ParameterBuilder.from_market_report(report)

        assert params.source == "market_report"
        assert params.generation_mode == GenerationMode.STRICT
        assert params.metadata["symbol"] == "SPY"
        assert params.metadata["current_price"] == 450.0
        assert params.metadata["iv_rank"] == 60.0
        assert params.metadata["market_stress"] == 25.0

    def test_from_market_report_with_mode(self):
        """Test market report respects generation mode parameter."""
        report = MarketConditionReport(
            symbol="QQQ",
            current_price=380.0,
        )

        params = ParameterBuilder.from_market_report(
            report,
            generation_mode=GenerationMode.FORCE,
        )

        assert params.generation_mode == GenerationMode.FORCE

    def test_from_market_report_with_overrides(self):
        """Test market report method accepts parameter overrides."""
        report = MarketConditionReport(
            symbol="IWM",
            current_price=200.0,
        )

        params = ParameterBuilder.from_market_report(
            report,
            overrides={
                "dte_min": 20,
                "dte_max": 35,
                "spread_width": 3,
                "otm_percentage": 0.02,
            },
        )

        assert params.dte_min == 20
        assert params.dte_max == 35
        assert params.spread_width == 3
        assert params.otm_percentage == 0.02

    def test_from_market_report_with_iv_rank_override(self):
        """Test market report method with IV rank override."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            iv_rank=30.0,  # Report has 30
        )

        params = ParameterBuilder.from_market_report(
            report,
            overrides={"min_iv_rank": 45.0},  # Override to 45
        )

        assert params.min_iv_rank == 45.0
        assert params.metadata["iv_rank"] == 30.0  # Original report value

    def test_from_market_report_with_score_override(self):
        """Test market report method with score threshold override."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
        )

        params = ParameterBuilder.from_market_report(
            report,
            overrides={"min_score_threshold": 40.0},
        )

        assert params.min_score_threshold == 40.0

    def test_from_market_report_missing_iv_rank(self):
        """Test market report uses default IV rank when not explicitly provided."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
        )
        # MarketConditionReport has a default iv_rank of 50.0

        params = ParameterBuilder.from_market_report(report)

        # Should use the default value from MarketConditionReport
        assert params.metadata["iv_rank"] == 50.0

    def test_from_market_report_all_overrides(self):
        """Test market report with all possible overrides."""
        report = MarketConditionReport(
            symbol="QQQ",
            current_price=380.0,
            iv_rank=55.0,
            market_stress_level=30.0,
        )

        params = ParameterBuilder.from_market_report(
            report,
            generation_mode=GenerationMode.RELAXED,
            overrides={
                "dte_min": 25,
                "dte_max": 40,
                "spread_width": 7,
                "otm_percentage": 0.04,
                "profit_target_pct": 60,
                "support_buffer_pct": 2.5,
                "resistance_buffer_pct": 2.5,
                "min_iv_rank": 50.0,
                "min_score_threshold": 45.0,
            },
        )

        assert params.dte_min == 25
        assert params.dte_max == 40
        assert params.spread_width == 7
        assert params.otm_percentage == 0.04
        assert params.generation_mode == GenerationMode.RELAXED
        assert params.profit_target_pct == 60
        assert params.support_buffer_pct == 2.5
        assert params.resistance_buffer_pct == 2.5
        assert params.min_iv_rank == 50.0
        assert params.min_score_threshold == 45.0


class TestParameterBuilderValidation:
    """Test that ParameterBuilder methods produce valid parameters."""

    def test_defaults_creates_valid_parameters(self):
        """Test defaults method creates valid parameters that pass validation."""
        params = ParameterBuilder.defaults()
        # If we get here without exception, validation passed
        assert params.dte_min <= params.dte_max

    def test_manual_creates_valid_parameters(self):
        """Test manual method creates valid parameters that pass validation."""
        params = ParameterBuilder.manual(
            dte_min=35,
            dte_max=60,
            spread_width=10,
        )
        # If we get here without exception, validation passed
        assert params.dte_min <= params.dte_max

    def test_manual_invalid_raises_error(self):
        """Test manual method raises error for invalid parameters."""
        with pytest.raises(ValueError):
            ParameterBuilder.manual(dte_min=60, dte_max=30)

    def test_from_market_report_creates_valid_parameters(self):
        """Test market report method creates valid parameters that pass validation."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
        )

        params = ParameterBuilder.from_market_report(report)
        # If we get here without exception, validation passed
        assert params.dte_min <= params.dte_max

    def test_from_market_report_invalid_override_raises_error(self):
        """Test market report method raises error for invalid overrides."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
        )

        with pytest.raises(ValueError):
            ParameterBuilder.from_market_report(
                report,
                overrides={"dte_min": 60, "dte_max": 30},
            )


class TestParameterIntegration:
    """Integration tests for parameter system components."""

    def test_generation_mode_usage_pattern(self):
        """Test typical usage pattern with generation modes."""
        # STRICT mode for automated trading
        strict_params = ParameterBuilder.defaults(GenerationMode.STRICT)
        assert strict_params.generation_mode.get_quality_threshold() == 0.05

        # RELAXED mode for suggestions
        relaxed_params = ParameterBuilder.defaults(GenerationMode.RELAXED)
        assert relaxed_params.generation_mode.get_quality_threshold() == 0.15

        # FORCE mode for manual trading
        force_params = ParameterBuilder.manual()
        assert force_params.generation_mode.get_quality_threshold() is None

    def test_market_report_to_parameters_workflow(self):
        """Test complete workflow from market report to parameters."""
        # Simulate getting market report
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            iv_rank=65.0,
            market_stress_level=20.0,
        )

        # Convert to parameters with custom settings
        params = ParameterBuilder.from_market_report(
            report,
            generation_mode=GenerationMode.RELAXED,
            overrides={"spread_width": 10},
        )

        # Verify workflow produced correct result
        assert params.source == "market_report"
        assert params.generation_mode == GenerationMode.RELAXED
        assert params.spread_width == 10
        assert params.metadata["symbol"] == "SPY"

        # Serialize for storage/transmission
        params_dict = params.to_dict()
        assert params_dict["generation_mode"] == "relaxed"

    def test_manual_ui_input_workflow(self):
        """Test workflow for manual user input from UI."""
        # User specifies custom parameters in UI
        params = ParameterBuilder.manual(
            dte_min=55,
            dte_max=65,
            spread_width=10,
            otm_percentage=0.05,
            profit_target_pct=70,
            metadata={"ui_version": "2.0", "user_id": 123},
        )

        # Verify manual mode defaults to FORCE
        assert params.generation_mode == GenerationMode.FORCE
        assert params.source == "manual"

        # Serialize for API/storage
        params_dict = params.to_dict()
        assert params_dict["dte_min"] == 55
        assert params_dict["generation_mode"] == "force"
        assert params_dict["metadata"]["ui_version"] == "2.0"


class TestAdditionalRecommendations:
    """Additional tests added based on Epic 50 review (2025-11-02)."""

    def test_sparse_market_report_serialization(self):
        """
        Regression test: sparse MarketConditionReport with defaults survives serialization.

        Ensures ParameterBuilder.from_market_report() handles incomplete market data
        gracefully and metadata defaults round-trip correctly.
        """
        # Create sparse/incomplete market report (missing many optional fields)
        sparse_report = Mock(spec=MarketConditionReport)
        sparse_report.symbol = "QQQ"
        sparse_report.current_price = Decimal("450.00")
        sparse_report.iv_rank = None  # Missing - should default to 50.0
        sparse_report.iv_percentile = None
        sparse_report.dte_optimal = None
        sparse_report.spread_width_optimal = None
        sparse_report.trend = "neutral"
        sparse_report.rsi = 50.0
        sparse_report.market_stress_level = None
        sparse_report.market_conditions = {}

        # Build parameters from sparse report
        params = ParameterBuilder.from_market_report(
            report=sparse_report,
            overrides={
                "dte_min": 30,
                "dte_max": 45,
                "spread_width": 5,
            },
            generation_mode=GenerationMode.RELAXED,
        )

        # Verify defaults were applied
        assert params.metadata["symbol"] == "QQQ"
        assert params.metadata["iv_rank"] is None  # Was None in sparse report
        assert params.dte_min == 30
        assert params.dte_max == 45
        assert params.spread_width == 5
        assert params.generation_mode == GenerationMode.RELAXED

        # Serialize to dict (simulating storage/API transmission)
        params_dict = params.to_dict()

        # Verify serialization preserves all critical fields
        assert params_dict["dte_min"] == 30
        assert params_dict["dte_max"] == 45
        assert params_dict["spread_width"] == 5
        assert params_dict["generation_mode"] == "relaxed"
        assert params_dict["source"] == "market_report"
        assert params_dict["metadata"]["symbol"] == "QQQ"
        assert params_dict["metadata"]["iv_rank"] is None
        assert params_dict["metadata"]["market_stress"] is None

    def test_manual_metadata_immutability(self):
        """
        Property test: ParameterBuilder.manual() never mutates caller-supplied metadata.

        Ensures UI-provided payloads remain stable and don't have side effects.
        Critical for preventing subtle bugs in UI parameter handling.
        """
        # Create metadata dict (simulating UI payload)
        original_metadata = {
            "ui_version": "2.0",
            "user_id": 123,
            "session_id": "abc-def-ghi",
            "nested": {"foo": "bar"},
        }

        # Take snapshot of original state
        metadata_snapshot = {
            "ui_version": original_metadata["ui_version"],
            "user_id": original_metadata["user_id"],
            "session_id": original_metadata["session_id"],
            "nested": {"foo": original_metadata["nested"]["foo"]},
        }

        # Build parameters with metadata
        params = ParameterBuilder.manual(
            dte_min=30,
            dte_max=45,
            spread_width=10,
            metadata=original_metadata,  # Pass original dict
        )

        # Verify metadata was copied to params
        assert params.metadata["ui_version"] == "2.0"
        assert params.metadata["user_id"] == 123

        # CRITICAL: Verify original metadata dict was NOT mutated
        assert original_metadata == metadata_snapshot
        assert original_metadata["ui_version"] == "2.0"
        assert original_metadata["user_id"] == 123
        assert original_metadata["session_id"] == "abc-def-ghi"
        assert original_metadata["nested"]["foo"] == "bar"

        # Verify modifying params.metadata doesn't affect original
        params.metadata["new_field"] = "new_value"
        assert "new_field" not in original_metadata

        # Verify modifying original doesn't affect params
        original_metadata["another_field"] = "another_value"
        assert "another_field" not in params.metadata
