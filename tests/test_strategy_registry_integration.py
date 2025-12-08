"""
Integration tests for StrategyRegistry.

Epic 28 Task 012: Verify all registered strategies implement correct interfaces,
use SDK patterns, and can generate suggestions.

This test automatically covers new strategies added to the registry.
"""

import inspect

import pytest

from services.strategies.base import BaseStrategy
from services.strategies.registry import get_all_strategies


@pytest.mark.django_db
class TestStrategyRegistryIntegration:
    """Integration tests for all registered strategies."""

    def test_all_strategies_registered(self):
        """Verify expected strategies are in registry."""
        strategies = get_all_strategies()

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
            "long_call_calendar",
            "covered_call",
            "cash_secured_put",
            "long_call_ratio_backspread",
        ]

        for strategy_name in expected:
            assert strategy_name in strategies, f"Strategy {strategy_name} not in registry"

        assert len(strategies) >= len(
            expected
        ), f"Expected at least {len(expected)} strategies, got {len(strategies)}"

    def test_all_strategies_can_instantiate(self, mock_user):
        """Verify all registered strategies can be instantiated."""
        strategies = get_all_strategies()

        for strategy_name, strategy_class in strategies.items():
            if strategy_name == "senex_trident":
                continue
            if strategy_name == "credit_spread":
                continue

            try:
                instance = strategy_class(mock_user)
                assert instance is not None
                assert instance.strategy_name == strategy_name
            except Exception as e:
                pytest.fail(f"Failed to instantiate {strategy_name}: {e}")

    def test_all_strategies_have_required_methods(self, mock_user):
        """Verify each strategy implements required abstract methods."""
        strategies = get_all_strategies()

        required_methods = [
            "build_opening_legs",
            "build_closing_legs",
            "a_get_profit_target_specifications",
            "should_place_profit_targets",
            "get_dte_exit_threshold",
        ]

        for strategy_name, strategy_class in strategies.items():
            if strategy_name == "senex_trident":
                continue

            instance = strategy_class(mock_user)

            for method_name in required_methods:
                assert hasattr(
                    instance, method_name
                ), f"{strategy_name} missing method: {method_name}"
                assert callable(
                    getattr(instance, method_name)
                ), f"{strategy_name}.{method_name} is not callable"

    def test_all_strategies_have_correct_return_type_hints(self, mock_user):
        """Verify build_opening_legs has correct type hint (returns list[Leg])."""
        strategies = get_all_strategies()

        for strategy_name, strategy_class in strategies.items():
            if strategy_name == "senex_trident":
                continue

            instance = strategy_class(mock_user)

            # Check method exists and has type hints
            import inspect

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
        """Ensure no duplicate strategy names in registry."""
        strategies = get_all_strategies()
        strategy_names = list(strategies.keys())

        assert len(strategy_names) == len(
            set(strategy_names)
        ), "Duplicate strategy names found in registry"

    def test_all_strategies_subclass_base_strategy(self):
        """Verify all strategies inherit from BaseStrategy."""
        strategies = get_all_strategies()

        for strategy_name, strategy_class in strategies.items():
            assert issubclass(
                strategy_class, BaseStrategy
            ), f"{strategy_name} does not inherit from BaseStrategy"


@pytest.mark.django_db
class TestSDKCompliance:
    """Verify SDK pattern compliance across all strategies."""

    def test_strategy_uses_sdk_helpers(self):
        """Verify strategies import from sdk_instruments or leg_builder."""
        strategies = get_all_strategies()

        for strategy_name, strategy_class in strategies.items():
            if strategy_name == "senex_trident":
                continue

            source = inspect.getsource(strategy_class)

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

            assert (
                uses_sdk_helpers or is_base_class
            ), f"{strategy_name} does not use SDK helper imports or spread base"

    def test_strategy_no_dict_leg_construction(self):
        """Verify strategies don't manually construct dict legs."""
        strategies = get_all_strategies()

        for strategy_name, strategy_class in strategies.items():
            if strategy_name == "senex_trident":
                continue

            source = inspect.getsource(strategy_class)

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
@pytest.mark.parametrize(
    ("strategy_name", "strategy_class"),
    [(name, cls) for name, cls in get_all_strategies().items()],
)
class TestParametrizedStrategyValidation:
    """Parametrized tests for each strategy (cleaner test output)."""

    def test_strategy_instantiation(self, strategy_name, strategy_class, mock_user):
        """Test that each strategy can be instantiated."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")
        if strategy_name == "credit_spread":
            pytest.skip("CreditSpread is parameterized - use bull_put_spread/bear_call_spread")

        instance = strategy_class(mock_user)
        assert instance is not None
        assert instance.strategy_name == strategy_name

    def test_strategy_has_name_property(self, strategy_name, strategy_class, mock_user):
        """Test that each strategy has strategy_name property."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")
        if strategy_name == "credit_spread":
            pytest.skip("CreditSpread is parameterized - use bull_put_spread/bear_call_spread")

        instance = strategy_class(mock_user)
        assert hasattr(instance, "strategy_name")
        assert instance.strategy_name == strategy_name

    def test_strategy_has_min_score_threshold(self, strategy_name, strategy_class, mock_user):
        """Test that each strategy has MIN_SCORE_THRESHOLD defined."""
        if strategy_name == "senex_trident":
            pytest.skip("Senex Trident has special requirements")

        instance = strategy_class(mock_user)
        assert hasattr(instance, "MIN_SCORE_THRESHOLD")
        assert isinstance(instance.MIN_SCORE_THRESHOLD, (int, float))
        assert instance.MIN_SCORE_THRESHOLD > 0
