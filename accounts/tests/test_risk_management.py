import contextlib
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

import pytest

from accounts.models import OptionsAllocation
from services.market_data.analysis import MarketAnalyzer
from services.risk.manager import EnhancedRiskManager

User = get_user_model()


def delete_default_allocation(user):
    with contextlib.suppress(OptionsAllocation.DoesNotExist):
        user.options_allocation.delete()


class OptionsAllocationModelTests(TestCase):
    """Test OptionsAllocation model creation, validation, and defaults"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="riskuser@example.com",
            username="riskuser@example.com",
            password="testpass123",
        )
        delete_default_allocation(self.user)

    def test_options_allocation_creation_with_defaults(self):
        """Test creating OptionsAllocation with default values"""
        allocation = OptionsAllocation.objects.create(user=self.user)

        assert allocation.user == self.user
        assert allocation.allocation_method == "conservative"
        assert allocation.risk_tolerance == 0.4
        assert allocation.stressed_risk_tolerance == 0.6
        assert allocation.strategy_power == Decimal("0")
        assert allocation.last_calculated

    def test_options_allocation_creation_custom_values(self):
        """Test creating OptionsAllocation with custom values"""
        allocation = OptionsAllocation.objects.create(
            user=self.user,
            allocation_method="user_defined",
            risk_tolerance=0.25,
            stressed_risk_tolerance=0.45,
            strategy_power=Decimal("15000.00"),
        )

        assert allocation.allocation_method == "user_defined"
        assert allocation.risk_tolerance == 0.25
        assert allocation.stressed_risk_tolerance == 0.45
        assert allocation.strategy_power == Decimal("15000.00")

    def test_options_allocation_onetoone_relationship(self):
        """Test OneToOneField relationship with User"""
        allocation = OptionsAllocation.objects.create(user=self.user)

        # Test accessing from user side
        assert self.user.options_allocation == allocation

        # Test that creating second allocation for same user raises error
        with pytest.raises(IntegrityError):
            OptionsAllocation.objects.create(user=self.user)

    def test_options_allocation_method_choices(self):
        """Test allocation method choices validation"""
        valid_choices = ["conservative", "user_defined"]

        for choice in valid_choices:
            allocation = OptionsAllocation.objects.create(user=self.user, allocation_method=choice)
            assert allocation.allocation_method == choice
            # Clean up for next iteration
            allocation.delete()

    def test_options_allocation_string_representation(self):
        """Test __str__ method returns expected format"""
        allocation = OptionsAllocation.objects.create(
            user=self.user, allocation_method="user_defined"
        )

        expected = f"{self.user.email} - User Defined Risk Tolerance"
        assert str(allocation) == expected

    def test_options_allocation_help_text(self):
        """Test that help_text is properly set on fields"""
        allocation = OptionsAllocation()

        risk_tolerance_field = allocation._meta.get_field("risk_tolerance")
        stressed_risk_tolerance_field = allocation._meta.get_field("stressed_risk_tolerance")
        strategy_power_field = allocation._meta.get_field("strategy_power")

        assert risk_tolerance_field.help_text == "Normal market risk tolerance (0.01-0.80)"
        assert (
            stressed_risk_tolerance_field.help_text == "Stressed market risk tolerance (0.01-0.80)"
        )
        assert strategy_power_field.help_text == "Risk Budget: Risk Tolerance × Tradeable Capital"

    def test_options_allocation_decimal_precision(self):
        """Test decimal field precision for strategy_power"""
        allocation = OptionsAllocation.objects.create(
            user=self.user,
            strategy_power=Decimal("123456789012345.67"),  # max_digits=15, decimal_places=2
        )

        assert allocation.strategy_power == Decimal("123456789012345.67")

    def test_options_allocation_cascade_deletion_with_user(self):
        """Test that deleting user cascades to delete allocation"""
        allocation = OptionsAllocation.objects.create(user=self.user)
        allocation_id = allocation.id

        # Delete user should cascade delete allocation
        self.user.delete()

        # Allocation should be deleted
        with pytest.raises(OptionsAllocation.DoesNotExist):
            OptionsAllocation.objects.get(id=allocation_id)

    def test_options_allocation_risk_tolerance_bounds(self):
        """Test risk tolerance values within expected bounds"""
        # Test valid values
        valid_tolerances = [0.01, 0.25, 0.40, 0.60, 0.80]

        for tolerance in valid_tolerances:
            allocation = OptionsAllocation.objects.create(
                user=self.user,
                risk_tolerance=tolerance,
                stressed_risk_tolerance=tolerance + 0.10,
            )
            assert allocation.risk_tolerance == tolerance
            allocation.delete()

    def test_options_allocation_auto_update_last_calculated(self):
        """Test that last_calculated is automatically updated"""
        allocation = OptionsAllocation.objects.create(user=self.user)
        original_time = allocation.last_calculated

        # Update strategy_power
        allocation.strategy_power = Decimal("25000.00")
        allocation.save()

        # last_calculated should be updated (auto_now=True)
        allocation.refresh_from_db()
        assert allocation.last_calculated > original_time

    def test_options_allocation_related_name(self):
        """Test related_name 'options_allocation' works correctly"""
        allocation = OptionsAllocation.objects.create(user=self.user)

        # Should be accessible via related_name
        assert self.user.options_allocation == allocation

        # Should work in queries
        users_with_allocation = User.objects.filter(
            options_allocation__allocation_method="conservative"
        )
        assert self.user in users_with_allocation

    def test_options_allocation_choice_display_methods(self):
        """Test get_allocation_method_display() method"""
        conservative_allocation = OptionsAllocation.objects.create(
            user=self.user, allocation_method="conservative"
        )

        assert (
            conservative_allocation.get_allocation_method_display()
            == "Conservative (40% Risk Tolerance)"
        )

        # Create another user for user_defined test
        user2 = User.objects.create_user(
            email="user2@example.com",
            username="user2@example.com",
            password="testpass123",
        )
        delete_default_allocation(user2)

        user_defined_allocation = OptionsAllocation.objects.create(
            user=user2, allocation_method="user_defined"
        )

        assert (
            user_defined_allocation.get_allocation_method_display() == "User Defined Risk Tolerance"
        )

    def test_options_allocation_default_values_match_conservative(self):
        """Test that default values align with conservative choice"""
        allocation = OptionsAllocation.objects.create(user=self.user)

        # Conservative defaults should be 40% normal, 60% stressed
        assert allocation.allocation_method == "conservative"
        assert allocation.risk_tolerance == 0.4
        assert allocation.stressed_risk_tolerance == 0.6

    def test_options_allocation_strategy_power_calculation_cache(self):
        """Test strategy_power as cached calculation field"""
        allocation = OptionsAllocation.objects.create(
            user=self.user, strategy_power=Decimal("50000.00")
        )

        # Strategy power should be stored value, not calculated
        assert allocation.strategy_power == Decimal("50000.00")

        # Verify it's a stored field, not a property
        assert hasattr(OptionsAllocation, "strategy_power")
        field = OptionsAllocation._meta.get_field("strategy_power")
        assert field.__class__.__name__ == "DecimalField"


class EnhancedRiskManagerTests(TestCase):
    """Test EnhancedRiskManager with enhanced features"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="enhanced@example.com",
            username="enhanced@example.com",
            password="testpass123",
        )
        delete_default_allocation(self.user)
        self.risk_manager = EnhancedRiskManager(self.user)

    def test_spread_width_tiers_return_odd_numbers(self):
        """Test all spread width tiers return odd numbers only"""
        from trading.models import StrategyConfiguration

        # Create strategy configuration for user
        config = StrategyConfiguration.objects.create(user=self.user)

        # Test all account value tiers
        test_cases = [
            (20000, 3),  # Under $25k
            (24999, 3),  # Just under $25k
            (25000, 5),  # Exactly $25k
            (30000, 5),  # $25k-$50k range
            (49999, 5),  # Just under $50k
            (50000, 7),  # Exactly $50k
            (60000, 7),  # $50k-$75k range
            (74999, 7),  # Just under $75k
            (75000, 9),  # Exactly $75k (NEW TIER)
            (80000, 9),  # Above $75k
            (100000, 9),  # Well above $75k
            (1000000, 9),  # Very high account value
        ]

        for account_value, expected_width in test_cases:
            width = config.get_spread_width(Decimal(str(account_value)))
            assert width == expected_width, (
                f"Account value ${account_value} should return "
                f"{expected_width}-point spread, got {width}"
            )
            # Verify it's an odd number
            assert width % 2 == 1, f"Spread width {width} must be odd"

    def test_risk_tolerance_templates(self):
        """Test all three risk tolerance templates"""
        templates = OptionsAllocation.RISK_TOLERANCE_TEMPLATES

        # Test Conservative template
        conservative = templates["conservative"]
        assert conservative["normal_tolerance"] == 0.4
        assert conservative["stressed_tolerance"] == 0.6

        # Test Moderate template
        moderate = templates["moderate"]
        assert moderate["normal_tolerance"] == 0.5
        assert moderate["stressed_tolerance"] == 0.7

        # Test Aggressive template
        aggressive = templates["aggressive"]
        assert aggressive["normal_tolerance"] == 0.6
        assert aggressive["stressed_tolerance"] == 0.8

    def test_calculate_strategy_max(self):
        """Test calculate_strategy_max method"""
        # Create allocation for user
        allocation = OptionsAllocation.objects.create(
            user=self.user,
            allocation_method="conservative",
            stressed_risk_tolerance=Decimal("0.60"),
        )

        # Mock the risk manager's get_tradeable_capital
        with patch.object(EnhancedRiskManager, "get_tradeable_capital") as mock_get:
            # Simulate having $50,000 tradeable capital
            mock_get.return_value = (Decimal("50000"), True)

            strategy_max = allocation.calculate_strategy_max()
            # Should be 60% of $50,000 = $30,000
            assert strategy_max == Decimal("30000")

            # Test when data unavailable
            mock_get.return_value = (Decimal("0"), False)
            strategy_max = allocation.calculate_strategy_max()
            assert strategy_max == Decimal("0")

    def test_get_remaining_budget(self):
        """Test remaining budget calculation with normal and stressed markets"""
        # Create allocation for user
        OptionsAllocation.objects.create(
            user=self.user, risk_tolerance=0.40, stressed_risk_tolerance=0.60
        )

        # Mock async tradeable capital method
        async def mock_tradeable_capital():
            return (Decimal("100000"), True)

        # Mock async app-managed risk method (private method used internally)
        async def mock_app_risk():
            return Decimal("10000")

        with patch.object(self.risk_manager, "a_get_tradeable_capital", new=mock_tradeable_capital):
            with patch.object(
                self.risk_manager, "_a_calculate_app_managed_risk", new=mock_app_risk
            ):
                # Normal market: 40% of $100k = $40k - $10k used = $30k remaining
                remaining, available = self.risk_manager.get_remaining_budget(is_stressed=False)
                assert available
                assert remaining == Decimal("30000")

                # Stressed market: 60% of $100k = $60k - $10k used = $50k remaining
                remaining, available = self.risk_manager.get_remaining_budget(is_stressed=True)
                assert available
                assert remaining == Decimal("50000")

    def test_calculate_strategy_power(self):
        """Test strategy power calculation for normal vs stressed markets"""
        # Create allocation for user
        OptionsAllocation.objects.create(
            user=self.user, risk_tolerance=Decimal("0.40"), stressed_risk_tolerance=Decimal("0.60")
        )

        # Mock async tradeable capital method
        async def mock_tradeable_capital():
            return (Decimal("100000"), True)

        with patch.object(self.risk_manager, "a_get_tradeable_capital", new=mock_tradeable_capital):
            # Normal market: 40% of $100k = $40k strategy power
            strategy_power, available = self.risk_manager.calculate_strategy_power(
                is_stressed=False
            )
            assert available
            assert strategy_power == Decimal("40000")

            # Stressed market: 60% of $100k = $60k strategy power
            strategy_power, available = self.risk_manager.calculate_strategy_power(is_stressed=True)
            assert available
            assert strategy_power == Decimal("60000")

    def test_allocation_method_choices_include_all_templates(self):
        """Test that all risk templates are available as choices"""
        choices = dict(OptionsAllocation.ALLOCATION_METHODS)

        assert "conservative" in choices
        assert "moderate" in choices
        assert "aggressive" in choices
        assert "user_defined" in choices

        # Verify display names
        assert choices["conservative"] == "Conservative (40% Risk Tolerance)"
        assert choices["moderate"] == "Moderate (50% Risk Tolerance)"
        assert choices["aggressive"] == "Aggressive (60% Risk Tolerance)"
        assert choices["user_defined"] == "User Defined Risk Tolerance"


class BollingerBandsTests(TestCase):
    """Test Bollinger Bands real-time implementation"""

    def setUp(self):
        self.analyzer = MarketAnalyzer()

    def test_bollinger_bands_calculation(self):
        """Test 19 historical + 1 current price Bollinger Bands"""
        # Create 19 historical prices around 100
        prices = [100.0] * 19

        # Test data insufficient case
        result = self.analyzer.calculate_bollinger_bands(prices[:10])
        assert result["upper"] is None
        assert result["middle"] is None
        assert result["lower"] is None
        assert result["position"] == "unknown"

        # Test full 20-period calculation
        prices.append(95.0)  # Add 20th price below average
        result = self.analyzer.calculate_bollinger_bands(prices)

        assert result["upper"] is not None
        assert result["middle"] is not None
        assert result["lower"] is not None
        assert result["current_price"] == 95.0
        assert len(prices) == 20  # Verify we have exactly 20 prices

    def test_bollinger_bands_realtime(self):
        """Test real-time Bollinger Bands with mock data"""
        # Mock historical prices
        with patch.object(self.analyzer, "_get_historical_prices") as mock_historical:
            mock_historical.return_value = [100.0] * 19

            # Mock current quote
            with patch.object(self.analyzer, "_get_current_quote") as mock_quote:
                mock_quote.return_value = 95.0

                bands = self.analyzer.calculate_bollinger_bands_realtime("SPY")

                assert bands["upper"] is not None
                assert bands["middle"] is not None
                assert bands["lower"] is not None
                assert bands["current"] == 95.0
                assert bands["position"] in ["above_upper", "below_lower", "within_bands"]


class IntegrationTests(TestCase):
    """Test integration between risk management and market analysis"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="integration@example.com",
            username="integration@example.com",
            password="testpass123",
        )
        self.risk_manager = EnhancedRiskManager(self.user)
        self.analyzer = MarketAnalyzer()
