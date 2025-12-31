"""
Tests for Strategy Factory (Epic 50 Task 4.0).

Tests the simple factory pattern that replaces the decorator-based registry.
"""

from unittest.mock import MagicMock

import pytest


class TestGetStrategy:
    """Test get_strategy factory function."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_get_strategy_short_put_vertical(self, mock_user):
        """Should return strategy for short_put_vertical."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_put_vertical", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "short_put_vertical"

    def test_get_strategy_short_call_vertical(self, mock_user):
        """Should return strategy for short_call_vertical."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_call_vertical", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "short_call_vertical"

    def test_get_strategy_long_call_vertical(self, mock_user):
        """Should return strategy for long_call_vertical."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_call_vertical", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_call_vertical"

    def test_get_strategy_long_put_vertical(self, mock_user):
        """Should return strategy for long_put_vertical."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_vertical", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_put_vertical"

    def test_get_strategy_senex_trident(self, mock_user):
        """Should return strategy for senex_trident."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("senex_trident", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "senex_trident"

    def test_get_strategy_iron_butterfly(self, mock_user):
        """Should return strategy for iron_butterfly."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("iron_butterfly", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "iron_butterfly"

    def test_get_strategy_short_iron_condor(self, mock_user):
        """Should return strategy for short_iron_condor."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_iron_condor", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "short_iron_condor"

    def test_get_strategy_long_iron_condor(self, mock_user):
        """Should return strategy for long_iron_condor."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_iron_condor", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_iron_condor"

    def test_get_strategy_covered_call(self, mock_user):
        """Should return strategy for covered_call."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("covered_call", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "covered_call"

    def test_get_strategy_cash_secured_put(self, mock_user):
        """Should return strategy for cash_secured_put."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("cash_secured_put", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "cash_secured_put"

    def test_get_strategy_long_straddle(self, mock_user):
        """Should return strategy for long_straddle."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_straddle", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_straddle"

    def test_get_strategy_long_strangle(self, mock_user):
        """Should return strategy for long_strangle."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_strangle", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_strangle"

    def test_get_strategy_call_calendar(self, mock_user):
        """Should return strategy for call_calendar."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("call_calendar", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "call_calendar"

    def test_get_strategy_long_call_ratio_backspread(self, mock_user):
        """Should return strategy for long_call_ratio_backspread."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_call_ratio_backspread", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_call_ratio_backspread"

    def test_get_strategy_long_put_ratio_backspread(self, mock_user):
        """Should return strategy for long_put_ratio_backspread."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_ratio_backspread", mock_user)

        assert strategy is not None
        assert strategy.strategy_name == "long_put_ratio_backspread"

    def test_get_strategy_unknown_raises_error(self, mock_user):
        """Should raise ValueError for unknown strategy."""
        from services.strategies.factory import get_strategy

        with pytest.raises(ValueError) as exc_info:
            get_strategy("unknown_strategy", mock_user)

        assert "Unknown strategy" in str(exc_info.value)
        assert "unknown_strategy" in str(exc_info.value)


class TestListStrategies:
    """Test list_strategies function."""

    def test_list_strategies_returns_all(self):
        """Should return all registered strategy names."""
        from services.strategies.factory import list_strategies

        strategies = list_strategies()

        assert isinstance(strategies, list)
        assert len(strategies) >= 17  # At least 17 strategies (with unified straddle/strangle/iron condor)
        assert "short_put_vertical" in strategies
        assert "short_call_vertical" in strategies
        assert "long_call_vertical" in strategies
        assert "long_put_vertical" in strategies
        assert "senex_trident" in strategies

    def test_list_strategies_sorted(self):
        """Should return sorted list."""
        from services.strategies.factory import list_strategies

        strategies = list_strategies()

        assert strategies == sorted(strategies)


class TestIsStrategyRegistered:
    """Test is_strategy_registered function."""

    def test_known_strategy_returns_true(self):
        """Should return True for known strategies."""
        from services.strategies.factory import is_strategy_registered

        assert is_strategy_registered("short_put_vertical") is True
        assert is_strategy_registered("senex_trident") is True

    def test_unknown_strategy_returns_false(self):
        """Should return False for unknown strategies."""
        from services.strategies.factory import is_strategy_registered

        assert is_strategy_registered("unknown_strategy") is False
        assert is_strategy_registered("") is False


class TestGetAllStrategies:
    """Test get_all_strategies function."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_get_all_strategies_returns_dict(self, mock_user):
        """Should return dict mapping name to instantiated strategy."""
        from services.strategies.factory import get_all_strategies

        strategies = get_all_strategies(mock_user)

        assert isinstance(strategies, dict)
        assert len(strategies) >= 17
        assert "short_put_vertical" in strategies
        assert strategies["short_put_vertical"].strategy_name == "short_put_vertical"


class TestStrategyInheritance:
    """Test that all strategies inherit from BaseStrategy."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_all_strategies_inherit_from_base(self, mock_user):
        """All strategies should inherit from BaseStrategy."""
        from services.strategies.base import BaseStrategy
        from services.strategies.factory import get_all_strategies

        strategies = get_all_strategies(mock_user)

        for name, strategy in strategies.items():
            assert isinstance(strategy, BaseStrategy), (
                f"Strategy '{name}' does not inherit from BaseStrategy"
            )
