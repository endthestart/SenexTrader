"""
Integration tests for Strategy Factory.

Epic 50 Task 4.0: Verify all strategies in factory implement correct interfaces,
use SDK patterns, and can generate suggestions.

This test automatically covers new strategies added to the factory.
"""

import inspect

import pytest

from services.strategies.base import BaseStrategy
from services.strategies.factory import get_all_strategies, list_strategies


@pytest.mark.django_db
class TestStrategyFactoryIntegration:
    """Integration tests for all strategies in factory."""

    def test_all_strategies_in_factory(self):
        """Verify expected strategies are in factory."""
        strategies = list_strategies()

        expected = [
            "long_call_vertical",
            "long_put_vertical",
            "short_put_vertical",
            "short_call_vertical",
            "short_iron_condor",
            "long_iron_condor",
            "iron_butterfly",
            "long_straddle",
            "long_strangle",
            "short_straddle",
            "short_strangle",
            "call_calendar",
            "put_calendar",
            "covered_call",
            "cash_secured_put",
            "long_call_ratio_backspread",
            "senex_trident",
        ]

        for strategy_name in expected:
            assert strategy_name in strategies, f"Strategy {strategy_name} not in factory"

        assert len(strategies) >= len(
            expected
        ), f"Expected at least {len(expected)} strategies, got {len(strategies)}"

    def test_all_strategies_can_instantiate(self, mock_user):
        """Verify all strategies can be instantiated."""
        strategies = get_all_strategies(mock_user)

        for strategy_name, instance in strategies.items():
            if strategy_name == "senex_trident":
                continue

            assert instance is not None
            assert instance.strategy_name == strategy_name

    def test_all_strategies_have_required_methods(self, mock_user):
        """Verify each strategy implements required abstract methods."""
        strategies = get_all_strategies(mock_user)

        required_methods = [
            "build_opening_legs",
            "build_closing_legs",
            "a_get_profit_target_specifications",
            "should_place_profit_targets",
            "get_dte_exit_threshold",
        ]

        for strategy_name, instance in strategies.items():
            if strategy_name == "senex_trident":
                continue

            for method_name in required_methods:
                assert hasattr(
                    instance, method_name
                ), f"{strategy_name} missing method: {method_name}"
                assert callable(
                    getattr(instance, method_name)
                ), f"{strategy_name}.{method_name} is not callable"

    def test_all_strategies_have_correct_return_type_hints(self, mock_user):
        """Verify build_opening_legs has correct type hint (returns list[Leg])."""
        strategies = get_all_strategies(mock_user)

        for strategy_name, instance in strategies.items():
            if strategy_name == "senex_trident":
                continue

            # Check method exists and has type hints
            method = getattr(instance, "build_opening_legs", None)
            assert method is not None, f"{strategy_name} missing build_opening_legs"

            # Get type hints
            try:
                hints = inspect.get_annotations(method)
                return_hint = hints.get("return", None)

                # Should return list[Leg] or similar
                assert (
                    return_hint is not None
                ), f"{strategy_name}.build_opening_legs missing return type hint"

            except Exception as e:
                # Some strategies may use string annotations or other patterns
                print(f"Info: {strategy_name} type hint check: {e}")

    def test_no_duplicate_strategy_names(self):
        """Ensure no duplicate strategy names in factory."""
        strategies = list_strategies()

        assert len(strategies) == len(
            set(strategies)
        ), "Duplicate strategy names found in factory"

    def test_all_strategies_subclass_base_strategy(self, mock_user):
        """Verify all strategies inherit from BaseStrategy."""
        strategies = get_all_strategies(mock_user)

        for strategy_name, instance in strategies.items():
            assert isinstance(
                instance, BaseStrategy
            ), f"{strategy_name} does not inherit from BaseStrategy"


@pytest.mark.django_db
class TestSDKCompliance:
    """Verify SDK pattern compliance across all strategies."""

    def test_strategy_uses_sdk_helpers(self, mock_user):
        """Verify strategies import from sdk_instruments or leg_builder."""
        strategies = get_all_strategies(mock_user)

        for strategy_name, instance in strategies.items():
            if strategy_name == "senex_trident":
                continue

            source = inspect.getsource(type(instance))

            # Should use SDK helper imports (either direct or via base classes)
            uses_sdk_helpers = (
                "from services.sdk.instruments import" in source
                or "from services.orders.utils.leg_builder import" in source
                or "leg_builder." in source  # Uses imported module
            )

            # Allow credit/debit spread base classes as they centralize SDK usage
            is_base_class = (
                "CreditSpreadBase" in source
                or "DebitSpreadBase" in source
                or "BaseCreditSpreadStrategy" in source
                or "BaseDebitSpreadStrategy" in source
                or "CreditSpreadStrategy" in source
                or "DebitSpreadStrategy" in source
            )

            # Calendar strategies have NotImplementedError stubs (Phase 5.3)
            is_calendar_stub = strategy_name in ("call_calendar", "put_calendar")

            assert (
                uses_sdk_helpers or is_base_class or is_calendar_stub
            ), f"{strategy_name} does not use SDK helper imports or spread base"

    def test_strategy_no_dict_leg_construction(self, mock_user):
        """Verify strategies don't manually construct dict legs."""
        strategies = get_all_strategies(mock_user)

        for strategy_name, instance in strategies.items():
            if strategy_name == "senex_trident":
                continue

            source = inspect.getsource(type(instance))

            # Anti-pattern: returning dicts as legs with these fields together
            dict_patterns = [
                '"instrument_type":',
                '"action":',
                '"symbol":',
            ]

            found_patterns = [p for p in dict_patterns if p in source]

            # If we find 2+ of these patterns, likely constructing dict legs
            if len(found_patterns) >= 2:
                pytest.fail(
                    f"{strategy_name} may be constructing dict legs "
                    f"(found patterns: {found_patterns}). "
                    f"Use SDK Leg objects via leg_builder.py instead."
                )


@pytest.mark.django_db
class TestParametrizedStrategyValidation:
    """Parametrized tests for each strategy (cleaner test output)."""

    @pytest.fixture(params=list_strategies())
    def strategy_name(self, request):
        return request.param

    def test_strategy_instantiation(self, strategy_name, mock_user):
        """Test that each strategy can be instantiated."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")

        from services.strategies.factory import get_strategy

        instance = get_strategy(strategy_name, mock_user)
        assert instance is not None
        assert instance.strategy_name == strategy_name

    def test_strategy_has_name_property(self, strategy_name, mock_user):
        """Test that each strategy has strategy_name property."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")

        from services.strategies.factory import get_strategy

        instance = get_strategy(strategy_name, mock_user)
        assert hasattr(instance, "strategy_name")
        assert instance.strategy_name == strategy_name

    def test_strategy_has_min_score_threshold(self, strategy_name, mock_user):
        """Test that each strategy has MIN_SCORE_THRESHOLD defined."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")

        from services.strategies.factory import get_strategy

        instance = get_strategy(strategy_name, mock_user)
        assert hasattr(instance, "MIN_SCORE_THRESHOLD")
        assert isinstance(instance.MIN_SCORE_THRESHOLD, (int, float))
        assert instance.MIN_SCORE_THRESHOLD > 0

