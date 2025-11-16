"""Tests for LegMatcher."""

import pytest

from services.positions.lifecycle.leg_matcher import LegMatcher


class TestLegMatcher:
    """Test suite for LegMatcher."""

    @pytest.fixture
    def sample_legs_map(self):
        """Sample leg lookup map for testing."""
        return {
            "QQQ   251107P00594000": {
                "symbol": "QQQ   251107P00594000",
                "quantity": -1,
                "quantity_direction": "short",
                "average_open_price": 5.50,
                "mark_price": 3.25,
                "multiplier": 100,
            },
            "QQQ   251107P00589000": {
                "symbol": "QQQ   251107P00589000",
                "quantity": 1,
                "quantity_direction": "long",
                "average_open_price": 3.00,
                "mark_price": 1.75,
                "multiplier": 100,
            },
            "SPY   251121C00600000": {
                "symbol": "SPY   251121C00600000",
                "quantity": -2,
                "quantity_direction": "short",
                "average_open_price": 8.00,
                "mark_price": 6.50,
                "multiplier": 100,
            },
        }

    def test_match_legs_all_found(self, sample_legs_map):
        """Test matching when all legs are found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["QQQ   251107P00594000", "QQQ   251107P00589000"]
        matched = matcher.match_legs(symbols)

        assert len(matched) == 2
        assert matched[0]["symbol"] == "QQQ   251107P00594000"
        assert matched[1]["symbol"] == "QQQ   251107P00589000"

    def test_match_legs_partial_match(self, sample_legs_map):
        """Test matching when some legs are not found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = [
            "QQQ   251107P00594000",
            "QQQ   251107P00999000",  # This one doesn't exist
        ]
        matched = matcher.match_legs(symbols)

        # Should only return the found leg
        assert len(matched) == 1
        assert matched[0]["symbol"] == "QQQ   251107P00594000"

    def test_match_legs_none_found(self, sample_legs_map):
        """Test matching when no legs are found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["INVALID1", "INVALID2"]
        matched = matcher.match_legs(symbols)

        assert len(matched) == 0
        assert matched == []

    def test_match_legs_empty_list(self, sample_legs_map):
        """Test matching with empty symbol list."""
        matcher = LegMatcher(sample_legs_map)

        matched = matcher.match_legs([])

        assert len(matched) == 0
        assert matched == []

    def test_match_leg_found(self, sample_legs_map):
        """Test matching a single leg when found."""
        matcher = LegMatcher(sample_legs_map)

        leg = matcher.match_leg("QQQ   251107P00594000")

        assert leg is not None
        assert leg["symbol"] == "QQQ   251107P00594000"
        assert leg["mark_price"] == 3.25

    def test_match_leg_not_found(self, sample_legs_map):
        """Test matching a single leg when not found."""
        matcher = LegMatcher(sample_legs_map)

        leg = matcher.match_leg("INVALID_SYMBOL")

        assert leg is None

    def test_has_leg_exists(self, sample_legs_map):
        """Test checking if leg exists when it does."""
        matcher = LegMatcher(sample_legs_map)

        assert matcher.has_leg("QQQ   251107P00594000") is True

    def test_has_leg_not_exists(self, sample_legs_map):
        """Test checking if leg exists when it doesn't."""
        matcher = LegMatcher(sample_legs_map)

        assert matcher.has_leg("INVALID_SYMBOL") is False

    def test_get_missing_legs_all_found(self, sample_legs_map):
        """Test getting missing legs when all are found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["QQQ   251107P00594000", "QQQ   251107P00589000"]
        missing = matcher.get_missing_legs(symbols)

        assert len(missing) == 0
        assert missing == []

    def test_get_missing_legs_some_missing(self, sample_legs_map):
        """Test getting missing legs when some are missing."""
        matcher = LegMatcher(sample_legs_map)

        symbols = [
            "QQQ   251107P00594000",  # Found
            "INVALID1",  # Missing
            "QQQ   251107P00589000",  # Found
            "INVALID2",  # Missing
        ]
        missing = matcher.get_missing_legs(symbols)

        assert len(missing) == 2
        assert "INVALID1" in missing
        assert "INVALID2" in missing

    def test_get_missing_legs_all_missing(self, sample_legs_map):
        """Test getting missing legs when all are missing."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["INVALID1", "INVALID2", "INVALID3"]
        missing = matcher.get_missing_legs(symbols)

        assert len(missing) == 3
        assert missing == symbols

    def test_get_matched_count_all_found(self, sample_legs_map):
        """Test counting matched legs when all are found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["QQQ   251107P00594000", "QQQ   251107P00589000"]
        count = matcher.get_matched_count(symbols)

        assert count == 2

    def test_get_matched_count_partial(self, sample_legs_map):
        """Test counting matched legs when some are missing."""
        matcher = LegMatcher(sample_legs_map)

        symbols = [
            "QQQ   251107P00594000",  # Found
            "INVALID1",  # Missing
            "QQQ   251107P00589000",  # Found
        ]
        count = matcher.get_matched_count(symbols)

        assert count == 2

    def test_get_matched_count_none_found(self, sample_legs_map):
        """Test counting matched legs when none are found."""
        matcher = LegMatcher(sample_legs_map)

        symbols = ["INVALID1", "INVALID2"]
        count = matcher.get_matched_count(symbols)

        assert count == 0

    def test_get_matched_count_empty_list(self, sample_legs_map):
        """Test counting matched legs with empty list."""
        matcher = LegMatcher(sample_legs_map)

        count = matcher.get_matched_count([])

        assert count == 0

    def test_empty_legs_map(self):
        """Test matcher with empty legs map."""
        matcher = LegMatcher({})

        symbols = ["QQQ   251107P00594000"]
        matched = matcher.match_legs(symbols)

        assert len(matched) == 0
        assert matcher.has_leg("QQQ   251107P00594000") is False
        assert matcher.match_leg("QQQ   251107P00594000") is None

    def test_match_legs_preserves_order(self, sample_legs_map):
        """Test that matched legs preserve input order."""
        matcher = LegMatcher(sample_legs_map)

        symbols = [
            "SPY   251121C00600000",
            "QQQ   251107P00594000",
            "QQQ   251107P00589000",
        ]
        matched = matcher.match_legs(symbols)

        assert len(matched) == 3
        assert matched[0]["symbol"] == "SPY   251121C00600000"
        assert matched[1]["symbol"] == "QQQ   251107P00594000"
        assert matched[2]["symbol"] == "QQQ   251107P00589000"

    def test_match_legs_with_duplicates(self, sample_legs_map):
        """Test matching with duplicate symbols in input."""
        matcher = LegMatcher(sample_legs_map)

        # Input has duplicate
        symbols = [
            "QQQ   251107P00594000",
            "QQQ   251107P00594000",  # Duplicate
        ]
        matched = matcher.match_legs(symbols)

        # Should return both (duplicates preserved)
        assert len(matched) == 2
        assert matched[0]["symbol"] == "QQQ   251107P00594000"
        assert matched[1]["symbol"] == "QQQ   251107P00594000"

    def test_match_legs_returns_actual_leg_data(self, sample_legs_map):
        """Test that matched legs contain all expected data."""
        matcher = LegMatcher(sample_legs_map)

        matched = matcher.match_legs(["QQQ   251107P00594000"])

        assert len(matched) == 1
        leg = matched[0]

        # Verify all fields are present
        assert leg["symbol"] == "QQQ   251107P00594000"
        assert leg["quantity"] == -1
        assert leg["quantity_direction"] == "short"
        assert leg["average_open_price"] == 5.50
        assert leg["mark_price"] == 3.25
        assert leg["multiplier"] == 100
