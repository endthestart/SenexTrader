"""
Tests for StrikeQualityScorer (Epic 50 Phase 3 Task 3.3).

Tests the strike-level quality scoring:
- Liquidity scoring (open interest)
- Spread scoring (bid-ask)
- Activity scoring (volume, last trade time)
- Combined quality levels and warnings
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

# =============================================================================
# StrikeQualityMetrics Tests
# =============================================================================


class TestStrikeQualityMetrics:
    """Test StrikeQualityMetrics dataclass."""

    def test_create_with_all_fields(self):
        """Should create metrics with all fields."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.20"),
            ask=Decimal("1.25"),
            volume=200,
            last_trade_time=datetime.now(UTC),
            delta=-0.25,
            implied_volatility=0.30,
        )

        assert metrics.open_interest == 1000
        assert metrics.bid == Decimal("1.20")
        assert metrics.delta == -0.25

    def test_create_with_minimal_fields(self):
        """Should create metrics with only some fields."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=500,
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
        )

        assert metrics.open_interest == 500
        assert metrics.volume is None
        assert metrics.delta is None

    def test_metrics_is_frozen(self):
        """StrikeQualityMetrics should be immutable."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(open_interest=500)

        with pytest.raises(AttributeError):
            metrics.open_interest = 1000


# =============================================================================
# StrikeQualityResult Tests
# =============================================================================


class TestStrikeQualityResult:
    """Test StrikeQualityResult dataclass."""

    def test_result_structure(self):
        """Should have score, component_scores, warnings, level."""
        from services.strategies.strike_selection import StrikeQualityResult

        result = StrikeQualityResult(
            score=75.0,
            component_scores={"liquidity": 80.0, "spread": 70.0, "activity": 75.0},
            warnings=["Low volume"],
            level="good",
        )

        assert result.score == 75.0
        assert result.level == "good"
        assert "liquidity" in result.component_scores

    def test_result_is_frozen(self):
        """StrikeQualityResult should be immutable."""
        from services.strategies.strike_selection import StrikeQualityResult

        result = StrikeQualityResult(
            score=75.0,
            component_scores={},
            warnings=[],
            level="good",
        )

        with pytest.raises(AttributeError):
            result.score = 50.0


# =============================================================================
# StrikeQualityScorer Tests
# =============================================================================


class TestStrikeQualityScorerCreation:
    """Test StrikeQualityScorer instantiation."""

    def test_create_with_default_weights(self):
        """Should use default weights when none provided."""
        from services.strategies.strike_selection import StrikeQualityScorer

        scorer = StrikeQualityScorer()

        assert scorer.weights["liquidity"] == 0.40
        assert scorer.weights["spread"] == 0.40
        assert scorer.weights["activity"] == 0.20

    def test_create_with_custom_weights(self):
        """Should accept custom weights."""
        from services.strategies.strike_selection import StrikeQualityScorer

        custom_weights = {
            "liquidity": 0.50,
            "spread": 0.30,
            "activity": 0.20,
        }
        scorer = StrikeQualityScorer(weights=custom_weights)

        assert scorer.weights["liquidity"] == 0.50


# =============================================================================
# Liquidity Scoring Tests
# =============================================================================


class TestLiquidityScoring:
    """Test liquidity (open interest) scoring component."""

    @pytest.fixture
    def scorer(self):
        from services.strategies.strike_selection import StrikeQualityScorer

        return StrikeQualityScorer()

    def test_high_open_interest_high_score(self, scorer):
        """High open interest should give high liquidity score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=2000,  # Well above MIN_OPEN_INTEREST (500)
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["liquidity"] >= 80.0

    def test_low_open_interest_low_score(self, scorer):
        """Low open interest should give low liquidity score with warning."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=50,  # Below MIN_OPEN_INTEREST (500)
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["liquidity"] < 50.0
        assert any("interest" in w.lower() for w in result.warnings)

    def test_zero_open_interest_zero_score(self, scorer):
        """Zero open interest should give zero liquidity score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=0,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["liquidity"] == 0.0

    def test_missing_open_interest_partial_score(self, scorer):
        """Missing open interest should give partial score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=None,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
        )

        result = scorer.score_strike(metrics)

        # Should give partial credit, not zero
        assert 30.0 <= result.component_scores["liquidity"] <= 50.0


# =============================================================================
# Spread Scoring Tests
# =============================================================================


class TestSpreadScoring:
    """Test bid-ask spread scoring component."""

    @pytest.fixture
    def scorer(self):
        from services.strategies.strike_selection import StrikeQualityScorer

        return StrikeQualityScorer()

    def test_tight_spread_high_score(self, scorer):
        """Tight bid-ask spread should give high spread score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),  # 2% spread - tight
            volume=100,
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["spread"] >= 80.0

    def test_wide_spread_low_score(self, scorer):
        """Wide bid-ask spread should give low spread score with warning."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.20"),  # 20% spread - wide
            volume=100,
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["spread"] < 50.0
        assert any("spread" in w.lower() for w in result.warnings)

    def test_missing_bid_ask_partial_score(self, scorer):
        """Missing bid/ask should give partial score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=None,
            ask=None,
            volume=100,
        )

        result = scorer.score_strike(metrics)

        # Should give partial credit
        assert 30.0 <= result.component_scores["spread"] <= 50.0

    def test_zero_mid_price_handled(self, scorer):
        """Zero mid price should not cause division error."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("0"),
            ask=Decimal("0"),
            volume=100,
        )

        result = scorer.score_strike(metrics)

        # Should not raise, should give low/zero score
        assert result.component_scores["spread"] >= 0.0


# =============================================================================
# Activity Scoring Tests
# =============================================================================


class TestActivityScoring:
    """Test activity (volume, last trade time) scoring component."""

    @pytest.fixture
    def scorer(self):
        from services.strategies.strike_selection import StrikeQualityScorer

        return StrikeQualityScorer()

    def test_high_volume_high_score(self, scorer):
        """High volume should give high activity score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=500,  # High volume
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["activity"] >= 80.0

    def test_low_volume_low_score(self, scorer):
        """Low volume should give low activity score with warning."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=5,  # Very low
        )

        result = scorer.score_strike(metrics)

        assert result.component_scores["activity"] < 50.0
        assert any("volume" in w.lower() for w in result.warnings)

    def test_stale_last_trade_reduces_score(self, scorer):
        """Old last trade time should reduce activity score."""
        from datetime import timedelta

        from services.strategies.strike_selection import StrikeQualityMetrics

        old_time = datetime.now(UTC) - timedelta(hours=3)

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
            last_trade_time=old_time,
        )

        result = scorer.score_strike(metrics)

        # Should have warning about stale trade
        assert any("trade" in w.lower() or "hour" in w.lower() for w in result.warnings)

    def test_missing_volume_partial_score(self, scorer):
        """Missing volume should give partial score."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=None,
        )

        result = scorer.score_strike(metrics)

        # Should give partial credit
        assert 30.0 <= result.component_scores["activity"] <= 50.0


# =============================================================================
# Quality Level Tests
# =============================================================================


class TestQualityLevelDetermination:
    """Test quality level string determination."""

    @pytest.fixture
    def scorer(self):
        from services.strategies.strike_selection import StrikeQualityScorer

        return StrikeQualityScorer()

    def test_excellent_level(self, scorer):
        """High score should produce 'excellent' level."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=5000,
            bid=Decimal("1.00"),
            ask=Decimal("1.01"),  # Very tight
            volume=1000,
        )

        result = scorer.score_strike(metrics)

        assert result.level == "excellent"
        assert result.score >= 80.0

    def test_good_level(self, scorer):
        """Moderate score should produce 'good' level."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=800,
            bid=Decimal("1.00"),
            ask=Decimal("1.03"),
            volume=150,
            delta=-0.25,  # Provide delta to avoid warning penalty
            implied_volatility=0.25,  # Provide IV to avoid warning penalty
        )

        result = scorer.score_strike(metrics)

        assert result.level in ["good", "excellent"]
        assert result.score >= 60.0

    def test_fair_level(self, scorer):
        """Low-moderate score should produce 'fair' level."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=300,
            bid=Decimal("1.00"),
            ask=Decimal("1.08"),
            volume=30,
        )

        result = scorer.score_strike(metrics)

        assert result.level in ["fair", "good"]

    def test_poor_level(self, scorer):
        """Low score should produce 'poor' level."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=10,
            bid=Decimal("0.50"),
            ask=Decimal("1.00"),  # 100% spread
            volume=1,
        )

        result = scorer.score_strike(metrics)

        assert result.level == "poor"
        assert result.score < 40.0


# =============================================================================
# Warning Aggregation Tests
# =============================================================================


class TestWarningAggregation:
    """Test that warnings are properly collected."""

    @pytest.fixture
    def scorer(self):
        from services.strategies.strike_selection import StrikeQualityScorer

        return StrikeQualityScorer()

    def test_multiple_issues_multiple_warnings(self, scorer):
        """Multiple quality issues should produce multiple warnings."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=10,  # Low
            bid=Decimal("0.50"),
            ask=Decimal("1.00"),  # Wide spread
            volume=1,  # Low volume
        )

        result = scorer.score_strike(metrics)

        # Should have warnings for each issue
        assert len(result.warnings) >= 3

    def test_no_issues_no_warnings(self, scorer):
        """Good metrics with all data should produce minimal warnings."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=5000,
            bid=Decimal("1.00"),
            ask=Decimal("1.01"),
            volume=500,
            delta=-0.25,  # Provide delta
            implied_volatility=0.25,  # Provide IV
        )

        result = scorer.score_strike(metrics)

        # Should have no warnings when all data is provided and good
        assert len(result.warnings) == 0

    def test_missing_delta_warning(self, scorer):
        """Missing delta should produce warning."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
            delta=None,  # Missing
        )

        result = scorer.score_strike(metrics)

        assert any("delta" in w.lower() for w in result.warnings)

    def test_missing_iv_warning(self, scorer):
        """Missing implied volatility should produce warning."""
        from services.strategies.strike_selection import StrikeQualityMetrics

        metrics = StrikeQualityMetrics(
            open_interest=1000,
            bid=Decimal("1.00"),
            ask=Decimal("1.02"),
            volume=100,
            implied_volatility=None,  # Missing
        )

        result = scorer.score_strike(metrics)

        assert any("iv" in w.lower() or "volatility" in w.lower() for w in result.warnings)
