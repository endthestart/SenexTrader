"""
Test market stress calculation to ensure correct unit handling.

This test guards against the bug where recent_move_pct was treated as a 0-1 fraction
instead of percentage points, causing routine 1% moves to add 30 stress points.
"""

from services.market_data.analysis import MarketAnalyzer


class TestMarketStressCalculation:
    """Test _calculate_market_stress_level with correct percentage units."""

    def test_normal_market_low_stress(self):
        """A 1% move with moderate IV should result in low stress."""
        analyzer = MarketAnalyzer()

        # Typical calm market: IV rank 30, 1% recent move
        stress = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=1.0,  # 1% move (percentage points)
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Should be low stress (< 30)
        assert stress < 30, f"1% move should not cause high stress, got {stress}"
        assert stress >= 0, "Stress should be non-negative"

    def test_moderate_volatility_moderate_stress(self):
        """A 2% move with elevated IV should result in moderate stress."""
        analyzer = MarketAnalyzer()

        # Slightly elevated market: IV rank 55, 2% move
        stress = analyzer._calculate_market_stress_level(
            iv_rank=55.0,
            recent_move_pct=2.0,  # 2% move
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Should be moderate stress (IV contributes 11, move is < 3% so no volatility component)
        assert 10 <= stress <= 15, f"2% move with IV 55 should be low-moderate stress, got {stress}"

    def test_high_volatility_high_stress(self):
        """A 10% move with high IV should result in high stress."""
        analyzer = MarketAnalyzer()

        # High volatility market: IV rank 80, 10% move
        stress = analyzer._calculate_market_stress_level(
            iv_rank=80.0,
            recent_move_pct=10.0,  # 10% move
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Should be high stress (> 60, approaching cap)
        assert stress > 60, f"10% move with IV 80 should cause high stress, got {stress}"
        assert stress <= 100, "Stress should be capped at 100"

    def test_extreme_market_capped_stress(self):
        """Extreme conditions should result in very high stress."""
        analyzer = MarketAnalyzer()

        # Crisis conditions: IV rank 95, 20% move, breaking support
        stress = analyzer._calculate_market_stress_level(
            iv_rank=95.0,
            recent_move_pct=20.0,  # 20% move
            current_price=400.0,
            support_level=440.0,  # Broke through support
            resistance_level=460.0,
        )

        # Should be very high stress (components: IV ~38 + volatility 30 + support break 15 = 83)
        assert stress >= 80, f"Crisis conditions should cause extreme stress, got {stress}"
        assert stress <= 100, "Stress should be capped at 100"

    def test_calm_market_minimal_stress(self):
        """Very calm market should have minimal stress."""
        analyzer = MarketAnalyzer()

        # Very calm: IV rank 20, 0.5% move
        stress = analyzer._calculate_market_stress_level(
            iv_rank=20.0,
            recent_move_pct=0.5,  # 0.5% move
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Should be very low stress (< 15)
        assert stress < 15, f"Calm market should have minimal stress, got {stress}"

    def test_threshold_boundaries(self):
        """Test behavior at key thresholds."""
        analyzer = MarketAnalyzer()

        # Test 3% threshold (lower bound for moderate volatility contribution)
        stress_at_3pct = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=3.0,
            current_price=450.0,
            support_level=None,
            resistance_level=None,
        )

        # Test 5% threshold (upper bound for moderate, lower for high)
        stress_at_5pct = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=5.0,
            current_price=450.0,
            support_level=None,
            resistance_level=None,
        )

        # 5% should contribute more than 3%
        assert stress_at_5pct > stress_at_3pct, "5% move should add more stress than 3%"

    def test_negative_move_treated_as_positive(self):
        """Negative moves should contribute same stress as positive moves."""
        analyzer = MarketAnalyzer()

        stress_positive = analyzer._calculate_market_stress_level(
            iv_rank=40.0,
            recent_move_pct=4.0,
            current_price=450.0,
            support_level=None,
            resistance_level=None,
        )

        stress_negative = analyzer._calculate_market_stress_level(
            iv_rank=40.0,
            recent_move_pct=-4.0,
            current_price=450.0,
            support_level=None,
            resistance_level=None,
        )

        assert stress_positive == stress_negative, "Direction should not matter for stress"

    def test_none_recent_move_handled(self):
        """None recent_move_pct should be treated as 0."""
        analyzer = MarketAnalyzer()

        stress = analyzer._calculate_market_stress_level(
            iv_rank=40.0,
            recent_move_pct=None,
            current_price=450.0,
            support_level=None,
            resistance_level=None,
        )

        # Should work without error and give low stress
        assert 0 <= stress < 30, "None move should result in low stress"

    def test_support_break_adds_stress(self):
        """Breaking through support should add stress points."""
        analyzer = MarketAnalyzer()

        # Price well above support
        stress_normal = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=1.0,
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Price broke through support (2% below)
        stress_broken = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=1.0,
            current_price=431.0,  # < 440 * 0.98
            support_level=440.0,
            resistance_level=460.0,
        )

        assert stress_broken > stress_normal, "Breaking support should add stress"
        assert stress_broken - stress_normal >= 15, "Support break should add ~15 points"

    def test_resistance_break_adds_stress(self):
        """Breaking through resistance should add stress points."""
        analyzer = MarketAnalyzer()

        # Price well below resistance
        stress_normal = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=1.0,
            current_price=450.0,
            support_level=440.0,
            resistance_level=460.0,
        )

        # Price broke through resistance (2% above)
        stress_broken = analyzer._calculate_market_stress_level(
            iv_rank=30.0,
            recent_move_pct=1.0,
            current_price=470.0,  # > 460 * 1.02
            support_level=440.0,
            resistance_level=460.0,
        )

        assert stress_broken > stress_normal, "Breaking resistance should add stress"
        assert stress_broken - stress_normal >= 15, "Resistance break should add ~15 points"
