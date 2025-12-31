"""
Tests for quality scoring calculators (Epic 50 Phase 3 Task 3.1).

Tests the individual scoring functions:
- Market alignment score (0-40 points)
- Strike deviation score (0-30 points)
- DTE optimality score (0-20 points)
- Liquidity score (0-10 points)

Each calculator follows the "always generate" pattern - never returns None.
"""

from decimal import Decimal

# =============================================================================
# Market Alignment Score Tests (0-40 points)
# =============================================================================


class TestMarketAlignmentScore:
    """Test market alignment scoring (0-40 points max)."""

    def test_perfect_alignment_bullish(self):
        """Bullish strategy + bullish trend = max alignment score."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=55.0,
            iv_rank=60.0,
        )

        assert score >= 35.0  # Near max (40)
        assert len(warnings) == 0

    def test_perfect_alignment_bearish(self):
        """Bearish strategy + bearish trend = max alignment score."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bearish",
            market_trend="bearish",
            rsi=45.0,
            iv_rank=60.0,
        )

        assert score >= 35.0
        assert len(warnings) == 0

    def test_counter_trend_low_score(self):
        """Bullish strategy + bearish trend = low alignment score."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bearish",
            rsi=30.0,
            iv_rank=20.0,
        )

        assert score <= 15.0  # Low score for counter-trend
        assert len(warnings) > 0  # Should warn about counter-trend

    def test_neutral_trend_moderate_score(self):
        """Any strategy + neutral trend = moderate alignment."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="neutral",
            rsi=50.0,
            iv_rank=50.0,
        )

        assert 15.0 <= score <= 30.0  # Moderate range

    def test_missing_rsi_gives_partial_credit(self):
        """Missing RSI should give partial credit, not zero."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=None,  # Missing
            iv_rank=50.0,
        )

        assert score > 20.0  # Still gets trend alignment + partial RSI
        assert any("rsi" in w.lower() for w in warnings)

    def test_missing_iv_rank_gives_partial_credit(self):
        """Missing IV rank should give partial credit."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score, warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=50.0,
            iv_rank=None,  # Missing
        )

        assert score > 25.0
        assert any("iv" in w.lower() for w in warnings)

    def test_high_iv_rank_bonus_for_credit_spreads(self):
        """High IV rank should give bonus points (credit spreads prefer high IV)."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        score_high_iv, _ = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=50.0,
            iv_rank=70.0,  # High IV
        )

        score_low_iv, _ = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=50.0,
            iv_rank=20.0,  # Low IV
        )

        assert score_high_iv > score_low_iv

    def test_normalized_trend_strings(self):
        """Should handle various trend string formats."""
        from services.strategies.quality.calculators import calculate_market_alignment_score

        # All these should be treated as bullish
        for trend in ["bullish", "strong_bullish", "bullish_exhausted"]:
            score, _ = calculate_market_alignment_score(
                strategy_direction="bullish",
                market_trend=trend,
                rsi=50.0,
                iv_rank=50.0,
            )
            assert score >= 25.0  # Good alignment


# =============================================================================
# Strike Deviation Score Tests (0-30 points)
# =============================================================================


class TestStrikeDeviationScore:
    """Test strike deviation scoring (0-30 points max)."""

    def test_exact_match_full_points(self):
        """Exact strike match should give full points."""
        from services.strategies.quality.calculators import calculate_strike_deviation_score

        score, warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("580"),
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("575"),
        )

        assert score == 30.0
        assert len(warnings) == 0

    def test_small_deviation_high_points(self):
        """< 1% deviation should give near-full points."""
        from services.strategies.quality.calculators import calculate_strike_deviation_score

        score, warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("581"),  # 0.17% deviation
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("576"),  # 0.17% deviation
        )

        assert score >= 28.0  # Near max

    def test_moderate_deviation_reduced_points(self):
        """3-5% deviation should give reduced points."""
        from services.strategies.quality.calculators import calculate_strike_deviation_score

        score, warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("600"),  # 3.4% deviation
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("595"),  # 3.5% deviation
        )

        assert 10.0 <= score <= 20.0  # Reduced range

    def test_large_deviation_low_points(self):
        """> 10% deviation should give low/zero points."""
        from services.strategies.quality.calculators import calculate_strike_deviation_score

        score, warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("650"),  # 12% deviation
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("640"),  # 11% deviation
        )

        assert score <= 10.0
        assert len(warnings) > 0  # Should warn about large deviation

    def test_short_strike_weighted_more_than_long(self):
        """Short strike deviation should impact score more than long."""
        from services.strategies.quality.calculators import calculate_strike_deviation_score

        # Bad short strike, good long strike
        score_bad_short, _ = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("610"),  # Bad
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("575"),  # Perfect
        )

        # Good short strike, bad long strike
        score_bad_long, _ = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("580"),  # Perfect
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("545"),  # Bad
        )

        # Short strike matters more (20 points vs 10 points max)
        assert score_bad_long > score_bad_short


# =============================================================================
# DTE Optimality Score Tests (0-20 points)
# =============================================================================


class TestDTEOptimalityScore:
    """Test DTE optimality scoring (0-20 points max)."""

    def test_exact_dte_match_full_points(self):
        """Exact DTE match should give full 20 points."""
        from services.strategies.quality.calculators import calculate_dte_optimality_score

        score, warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=45,
        )

        assert score == 20.0
        assert len(warnings) == 0

    def test_within_5_days_high_points(self):
        """Within 5 days of target should give 18-20 points."""
        from services.strategies.quality.calculators import calculate_dte_optimality_score

        score, warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=42,  # 3 days off
        )

        assert 18.0 <= score <= 20.0

    def test_within_10_days_good_points(self):
        """Within 10 days of target should give 15-18 points."""
        from services.strategies.quality.calculators import calculate_dte_optimality_score

        score, warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=38,  # 7 days off
        )

        assert 15.0 <= score <= 18.0

    def test_far_from_target_low_points(self):
        """Far from target DTE should give low points with warning."""
        from services.strategies.quality.calculators import calculate_dte_optimality_score

        score, warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=20,  # 25 days off
        )

        assert score <= 10.0
        assert len(warnings) > 0

    def test_very_far_dte_zero_points(self):
        """Extremely far from target should give ~0 points."""
        from services.strategies.quality.calculators import calculate_dte_optimality_score

        score, warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=5,  # 40 days off (too short)
        )

        assert score <= 5.0


# =============================================================================
# Liquidity Score Tests (0-10 points)
# =============================================================================


class TestLiquidityScore:
    """Test liquidity scoring (0-10 points max)."""

    def test_excellent_liquidity_full_points(self):
        """Tight spread, high volume, high OI = full points."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=Decimal("1.20"),
            ask=Decimal("1.22"),  # $0.02 spread (tight)
            volume=500,
            open_interest=2000,
        )

        assert score >= 9.0
        assert len(warnings) == 0

    def test_wide_spread_reduces_score(self):
        """Wide bid-ask spread should reduce score significantly."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=Decimal("1.00"),
            ask=Decimal("1.30"),  # $0.30 spread (wide, 30%)
            volume=500,
            open_interest=2000,
        )

        assert score <= 6.0
        assert any("spread" in w.lower() for w in warnings)

    def test_low_volume_reduces_score(self):
        """Low volume should reduce score."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=Decimal("1.20"),
            ask=Decimal("1.22"),
            volume=5,  # Very low
            open_interest=2000,
        )

        assert score <= 8.0
        assert any("volume" in w.lower() for w in warnings)

    def test_low_open_interest_reduces_score(self):
        """Low open interest should reduce score."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=Decimal("1.20"),
            ask=Decimal("1.22"),
            volume=500,
            open_interest=5,  # Very low
        )

        assert score <= 8.0
        assert any("interest" in w.lower() for w in warnings)

    def test_missing_data_gives_partial_credit(self):
        """Missing liquidity data should give partial credit, not zero."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=None,
            ask=None,
            volume=None,
            open_interest=None,
        )

        assert 3.0 <= score <= 6.0  # Partial credit range
        assert len(warnings) > 0  # Should note missing data

    def test_zero_bid_handled_gracefully(self):
        """Zero bid price should not cause division error."""
        from services.strategies.quality.calculators import calculate_liquidity_score

        score, warnings = calculate_liquidity_score(
            bid=Decimal("0"),
            ask=Decimal("0.05"),
            volume=100,
            open_interest=500,
        )

        # Should not raise, should give reduced score
        assert score >= 0.0
        assert score <= 10.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestQualityCalculatorIntegration:
    """Test combining all calculators into final score."""

    def test_all_components_sum_to_100_max(self):
        """Component max points should sum to 100."""
        # Market alignment: 40
        # Strike deviation: 30
        # DTE optimality: 20
        # Liquidity: 10
        # Total: 100
        assert 40 + 30 + 20 + 10 == 100

    def test_excellent_quality_scenario(self):
        """Perfect inputs should produce excellent quality score."""
        from services.strategies.quality import QualityScore
        from services.strategies.quality.calculators import (
            calculate_dte_optimality_score,
            calculate_liquidity_score,
            calculate_market_alignment_score,
            calculate_strike_deviation_score,
        )

        market_score, market_warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bullish",
            rsi=55.0,
            iv_rank=60.0,
        )

        strike_score, strike_warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("580"),
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("575"),
        )

        dte_score, dte_warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=45,
        )

        liquidity_score, liquidity_warnings = calculate_liquidity_score(
            bid=Decimal("1.20"),
            ask=Decimal("1.22"),
            volume=500,
            open_interest=2000,
        )

        total_score = market_score + strike_score + dte_score + liquidity_score
        all_warnings = market_warnings + strike_warnings + dte_warnings + liquidity_warnings

        quality = QualityScore.from_components(
            component_scores={
                "market_alignment": market_score,
                "strike_deviation": strike_score,
                "dte_optimality": dte_score,
                "liquidity": liquidity_score,
            },
            warnings=all_warnings,
        )

        assert quality.score >= 80.0
        assert quality.level == "excellent"

    def test_poor_quality_scenario(self):
        """Bad inputs should produce poor quality score with warnings."""
        from services.strategies.quality import QualityScore
        from services.strategies.quality.calculators import (
            calculate_dte_optimality_score,
            calculate_liquidity_score,
            calculate_market_alignment_score,
            calculate_strike_deviation_score,
        )

        market_score, market_warnings = calculate_market_alignment_score(
            strategy_direction="bullish",
            market_trend="bearish",  # Counter-trend
            rsi=25.0,  # Oversold
            iv_rank=10.0,  # Low IV
        )

        strike_score, strike_warnings = calculate_strike_deviation_score(
            ideal_short_strike=Decimal("580"),
            selected_short_strike=Decimal("620"),  # Large deviation
            ideal_long_strike=Decimal("575"),
            selected_long_strike=Decimal("610"),  # Large deviation
        )

        dte_score, dte_warnings = calculate_dte_optimality_score(
            target_dte=45,
            actual_dte=10,  # Way off target
        )

        liquidity_score, liquidity_warnings = calculate_liquidity_score(
            bid=Decimal("0.50"),
            ask=Decimal("1.00"),  # Wide spread
            volume=5,  # Low volume
            open_interest=10,  # Low OI
        )

        total_score = market_score + strike_score + dte_score + liquidity_score
        all_warnings = market_warnings + strike_warnings + dte_warnings + liquidity_warnings

        quality = QualityScore.from_components(
            component_scores={
                "market_alignment": market_score,
                "strike_deviation": strike_score,
                "dte_optimality": dte_score,
                "liquidity": liquidity_score,
            },
            warnings=all_warnings,
        )

        assert quality.score < 40.0
        assert quality.level == "poor"
        assert len(all_warnings) > 0  # Should have multiple warnings
