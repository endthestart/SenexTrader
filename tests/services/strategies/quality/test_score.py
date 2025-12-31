"""
Tests for QualityScore dataclass (Epic 50 Phase 3 Task 3.1).

Tests the core quality scoring infrastructure:
- QualityScore dataclass immutability and properties
- Quality level determination (excellent, good, fair, poor)
- Score combination for multi-spread strategies
- Always-generate pattern (never None)
"""


import pytest


class TestQualityScoreDataclass:
    """Test QualityScore dataclass structure and properties."""

    def test_quality_score_creation(self):
        """QualityScore should be creatable with all fields."""
        from services.strategies.quality import QualityScore

        score = QualityScore(
            score=75.0,
            level="good",
            warnings=["Low open interest"],
            component_scores={"liquidity": 60.0, "spread": 80.0, "activity": 70.0},
        )

        assert score.score == 75.0
        assert score.level == "good"
        assert score.warnings == ["Low open interest"]
        assert score.component_scores["liquidity"] == 60.0

    def test_quality_score_is_frozen(self):
        """QualityScore should be immutable (frozen dataclass)."""
        from services.strategies.quality import QualityScore

        score = QualityScore(
            score=75.0,
            level="good",
            warnings=[],
            component_scores={},
        )

        with pytest.raises(AttributeError):
            score.score = 50.0  # Should raise - frozen

    def test_quality_score_empty_warnings(self):
        """QualityScore with no warnings should have empty list."""
        from services.strategies.quality import QualityScore

        score = QualityScore(
            score=95.0,
            level="excellent",
            warnings=[],
            component_scores={"liquidity": 95.0},
        )

        assert score.warnings == []
        assert len(score.warnings) == 0


class TestQualityLevelDetermination:
    """Test quality level string determination from score."""

    def test_excellent_level_at_80_plus(self):
        """Score >= 80 should be 'excellent'."""
        from services.strategies.quality import determine_quality_level

        assert determine_quality_level(80.0) == "excellent"
        assert determine_quality_level(95.0) == "excellent"
        assert determine_quality_level(100.0) == "excellent"

    def test_good_level_at_60_to_79(self):
        """Score 60-79 should be 'good'."""
        from services.strategies.quality import determine_quality_level

        assert determine_quality_level(60.0) == "good"
        assert determine_quality_level(70.0) == "good"
        assert determine_quality_level(79.9) == "good"

    def test_fair_level_at_40_to_59(self):
        """Score 40-59 should be 'fair'."""
        from services.strategies.quality import determine_quality_level

        assert determine_quality_level(40.0) == "fair"
        assert determine_quality_level(50.0) == "fair"
        assert determine_quality_level(59.9) == "fair"

    def test_poor_level_below_40(self):
        """Score < 40 should be 'poor'."""
        from services.strategies.quality import determine_quality_level

        assert determine_quality_level(0.0) == "poor"
        assert determine_quality_level(20.0) == "poor"
        assert determine_quality_level(39.9) == "poor"


class TestQualityScoreCombination:
    """Test combining multiple QualityScores for multi-leg strategies."""

    def test_combine_two_scores(self):
        """Combining two scores should average and merge warnings."""
        from services.strategies.quality import QualityScore

        score1 = QualityScore(
            score=80.0,
            level="excellent",
            warnings=["Warning A"],
            component_scores={"liquidity": 80.0},
        )
        score2 = QualityScore(
            score=60.0,
            level="good",
            warnings=["Warning B"],
            component_scores={"liquidity": 60.0},
        )

        combined = QualityScore.combine([score1, score2])

        assert combined.score == 70.0  # Average
        assert combined.level == "good"  # Based on averaged score
        assert "Warning A" in combined.warnings
        assert "Warning B" in combined.warnings

    def test_combine_single_score_returns_same(self):
        """Combining single score should return equivalent score."""
        from services.strategies.quality import QualityScore

        score = QualityScore(
            score=75.0,
            level="good",
            warnings=["Test warning"],
            component_scores={"liquidity": 75.0},
        )

        combined = QualityScore.combine([score])

        assert combined.score == 75.0
        assert combined.level == "good"

    def test_combine_empty_list_returns_zero_score(self):
        """Combining empty list should return zero score with warning."""
        from services.strategies.quality import QualityScore

        combined = QualityScore.combine([])

        assert combined.score == 0.0
        assert combined.level == "poor"
        assert len(combined.warnings) > 0  # Should have warning about no scores

    def test_combine_preserves_all_component_scores(self):
        """Combined score should include all component scores averaged."""
        from services.strategies.quality import QualityScore

        score1 = QualityScore(
            score=80.0,
            level="excellent",
            warnings=[],
            component_scores={"liquidity": 80.0, "spread": 90.0},
        )
        score2 = QualityScore(
            score=60.0,
            level="good",
            warnings=[],
            component_scores={"liquidity": 60.0, "spread": 70.0},
        )

        combined = QualityScore.combine([score1, score2])

        assert combined.component_scores["liquidity"] == 70.0  # (80+60)/2
        assert combined.component_scores["spread"] == 80.0  # (90+70)/2


class TestQualityScoreFactoryMethods:
    """Test factory methods for creating QualityScores."""

    def test_create_minimum_score(self):
        """Should create a minimum quality score with appropriate warnings."""
        from services.strategies.quality import QualityScore

        score = QualityScore.minimum(reason="No market data available")

        assert score.score == 0.0
        assert score.level == "poor"
        assert "No market data available" in score.warnings

    def test_create_from_components(self):
        """Should create score by summing weighted components."""
        from services.strategies.quality import QualityScore

        score = QualityScore.from_components(
            component_scores={
                "market_alignment": 35.0,  # max 40
                "strike_deviation": 25.0,  # max 30
                "dte_optimality": 15.0,  # max 20
                "liquidity": 8.0,  # max 10
            },
            warnings=["Slightly wide spread"],
        )

        assert score.score == 83.0  # Sum of components
        assert score.level == "excellent"
        assert "Slightly wide spread" in score.warnings
