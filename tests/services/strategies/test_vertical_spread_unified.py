"""
Tests for Phase 4: Unified Vertical Spread Strategy Pattern.

These tests verify that the factory can instantiate vertical spreads
with the correct parameters, eliminating the need for separate wrapper classes.

Epic 50 Task 4.1-4.3: Migrate to parameterized vertical spread instantiation.
"""

from unittest.mock import MagicMock

import pytest

from services.strategies.core.types import Direction


class TestVerticalSpreadFactoryIntegration:
    """Test factory instantiation of vertical spreads with parameters."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_short_put_vertical_is_credit_spread(self, mock_user):
        """short_put_vertical should be a credit spread with BULLISH direction."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_put_vertical", mock_user)

        assert strategy.strategy_name == "short_put_vertical"
        assert strategy.spread_direction == Direction.BULLISH

    def test_short_call_vertical_is_credit_spread(self, mock_user):
        """short_call_vertical should be a credit spread with BEARISH direction."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_call_vertical", mock_user)

        assert strategy.strategy_name == "short_call_vertical"
        assert strategy.spread_direction == Direction.BEARISH

    def test_long_call_vertical_is_debit_spread(self, mock_user):
        """long_call_vertical should be a debit spread with BULLISH direction."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_call_vertical", mock_user)

        assert strategy.strategy_name == "long_call_vertical"
        assert strategy.spread_direction == Direction.BULLISH

    def test_long_put_vertical_is_debit_spread(self, mock_user):
        """long_put_vertical should be a debit spread with BEARISH direction."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_vertical", mock_user)

        assert strategy.strategy_name == "long_put_vertical"
        assert strategy.spread_direction == Direction.BEARISH

    def test_all_verticals_have_required_methods(self, mock_user):
        """All vertical strategies should have required BaseStrategy methods."""
        from services.strategies.factory import get_strategy

        vertical_types = [
            "short_put_vertical",
            "short_call_vertical",
            "long_call_vertical",
            "long_put_vertical",
        ]

        required_methods = [
            "a_score_market_conditions",
            "a_get_profit_target_specifications",
            "should_place_profit_targets",
            "get_dte_exit_threshold",
            "build_opening_legs",
            "build_closing_legs",
        ]

        for strategy_type in vertical_types:
            strategy = get_strategy(strategy_type, mock_user)
            for method in required_methods:
                assert hasattr(strategy, method), (
                    f"{strategy_type} missing {method}"
                )
                assert callable(getattr(strategy, method)), (
                    f"{strategy_type}.{method} not callable"
                )


class TestCreditSpreadDirectInstantiation:
    """Test CreditSpreadStrategy can be instantiated directly with parameters."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_credit_spread_bullish_put(self, mock_user):
        """CreditSpreadStrategy with BULLISH direction creates bull put spread."""
        from services.strategies.credit_spread_strategy import CreditSpreadStrategy

        strategy = CreditSpreadStrategy(
            mock_user,
            direction=Direction.BULLISH,
            strategy_name="short_put_vertical",
        )

        assert strategy.strategy_name == "short_put_vertical"
        assert strategy.spread_direction == Direction.BULLISH

    def test_credit_spread_bearish_call(self, mock_user):
        """CreditSpreadStrategy with BEARISH direction creates bear call spread."""
        from services.strategies.credit_spread_strategy import CreditSpreadStrategy

        strategy = CreditSpreadStrategy(
            mock_user,
            direction=Direction.BEARISH,
            strategy_name="short_call_vertical",
        )

        assert strategy.strategy_name == "short_call_vertical"
        assert strategy.spread_direction == Direction.BEARISH

    def test_credit_spread_string_direction(self, mock_user):
        """CreditSpreadStrategy accepts string direction."""
        from services.strategies.credit_spread_strategy import CreditSpreadStrategy

        strategy = CreditSpreadStrategy(
            mock_user,
            direction="bullish",
            strategy_name="short_put_vertical",
        )

        assert strategy.spread_direction == Direction.BULLISH


class TestDebitSpreadDirectInstantiation:
    """Test DebitSpreadStrategy can be instantiated directly with parameters."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_debit_spread_bullish_call(self, mock_user):
        """DebitSpreadStrategy with BULLISH direction creates bull call spread."""
        from services.strategies.debit_spread_strategy import DebitSpreadStrategy

        strategy = DebitSpreadStrategy(
            mock_user,
            direction=Direction.BULLISH,
            strategy_name="long_call_vertical",
        )

        assert strategy.strategy_name == "long_call_vertical"
        assert strategy.spread_direction == Direction.BULLISH

    def test_debit_spread_bearish_put(self, mock_user):
        """DebitSpreadStrategy with BEARISH direction creates bear put spread."""
        from services.strategies.debit_spread_strategy import DebitSpreadStrategy

        strategy = DebitSpreadStrategy(
            mock_user,
            direction=Direction.BEARISH,
            strategy_name="long_put_vertical",
        )

        assert strategy.strategy_name == "long_put_vertical"
        assert strategy.spread_direction == Direction.BEARISH


class TestVerticalSpreadNoLegacyClasses:
    """Verify legacy wrapper classes are removed."""

    def test_no_short_put_vertical_strategy_class(self):
        """ShortPutVerticalStrategy class should not exist."""
        from services.strategies import credit_spread_strategy

        assert not hasattr(credit_spread_strategy, "ShortPutVerticalStrategy")

    def test_no_short_call_vertical_strategy_class(self):
        """ShortCallVerticalStrategy class should not exist."""
        from services.strategies import credit_spread_strategy

        assert not hasattr(credit_spread_strategy, "ShortCallVerticalStrategy")

    def test_no_long_call_vertical_strategy_class(self):
        """LongCallVerticalStrategy class should not exist."""
        from services.strategies import debit_spread_strategy

        assert not hasattr(debit_spread_strategy, "LongCallVerticalStrategy")

    def test_no_long_put_vertical_strategy_class(self):
        """LongPutVerticalStrategy class should not exist."""
        from services.strategies import debit_spread_strategy

        assert not hasattr(debit_spread_strategy, "LongPutVerticalStrategy")
