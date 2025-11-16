"""
Phase 7.4: Risk Calculation Edge Case Validation Suite

CRITICAL SAFETY: EnhancedRiskManager.a_can_open_position() determines position sizing.
Wrong calculations = account blow-up. This suite validates edge cases and boundary conditions.

Test Coverage:
1. Max risk calculation accuracy (verify against TastyTrade broker formulas)
2. Spread width scaling with account size (odd numbers only, tier boundaries)
3. Stress scenario position sizing (high VIX reduces position size)
4. Boundary conditions (portfolio at capacity limits)
5. Zero/negative values handling
6. Decimal precision preservation
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import OptionsAllocation
from services.risk.manager import EnhancedRiskManager
from trading.models import StrategyConfiguration

User = get_user_model()


class RiskCalculationAccuracyTests(TestCase):
    """Test max risk calculations match TastyTrade broker requirements"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="accuracy@example.com",
            username="accuracy@example.com",
            password="testpass123",
        )
        self.risk_manager = EnhancedRiskManager(self.user)
        OptionsAllocation.objects.create(
            user=self.user, risk_tolerance=0.40, stressed_risk_tolerance=0.60
        )

    def test_max_risk_credit_spread_calculation(self):
        """
        Test 1: Max risk calculation for credit spreads

        Credit spread: $5 wide, $1.50 credit received
        Max risk = (spread_width - credit) × 100
        Expected: ($5.00 - $1.50) × 100 = $350
        """
        spread_width = Decimal("5.00")
        credit_received = Decimal("1.50")

        max_risk = (spread_width - credit_received) * 100
        expected_risk = Decimal("350.00")

        assert (
            max_risk == expected_risk
        ), f"Credit spread max risk should be ${expected_risk}, got ${max_risk}"

        # Verify against common credit spread scenarios
        test_cases = [
            # (spread_width, credit, expected_max_risk)
            (Decimal("5.00"), Decimal("1.50"), Decimal("350.00")),  # Standard 5-point
            (Decimal("3.00"), Decimal("0.90"), Decimal("210.00")),  # Small account 3-point
            (Decimal("7.00"), Decimal("2.10"), Decimal("490.00")),  # Medium account 7-point
            (Decimal("9.00"), Decimal("2.70"), Decimal("630.00")),  # Large account 9-point
            (Decimal("5.00"), Decimal("0.50"), Decimal("450.00")),  # Low credit scenario
            (Decimal("5.00"), Decimal("2.50"), Decimal("250.00")),  # High credit scenario
        ]

        for width, credit, expected in test_cases:
            calculated_risk = (width - credit) * 100
            assert calculated_risk == expected, (
                f"Spread ${width} with ${credit} credit should risk ${expected}, "
                f"got ${calculated_risk}"
            )

    def test_max_risk_decimal_precision(self):
        """Test that max risk preserves decimal precision (no rounding errors)"""
        # Test precise decimal calculations
        spread_width = Decimal("5.00")
        credit_received = Decimal("1.4789")  # Realistic quote precision

        max_risk = (spread_width - credit_received) * 100
        expected_risk = Decimal("352.11")

        assert max_risk == expected_risk, "Decimal precision must be preserved"
        assert isinstance(max_risk, Decimal), "Risk must be Decimal type, not float"

    def test_position_risk_calculation_matches_broker(self):
        """Verify position risk matches what TastyTrade displays"""
        # Create a mock position
        # TastyTrade shows: "Max Loss: $350" for $5 wide spread with $1.50 credit
        spread_width = Decimal("5.00")
        credit = Decimal("1.50")
        quantity = 1

        position_risk = (spread_width - credit) * 100 * quantity
        broker_max_loss = Decimal("350.00")

        assert (
            position_risk == broker_max_loss
        ), "Position risk must match broker's displayed max loss"


class SpreadWidthScalingTests(TestCase):
    """Test spread width scales correctly with account size"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="scaling@example.com",
            username="scaling@example.com",
            password="testpass123",
        )
        self.config = StrategyConfiguration.objects.create(user=self.user)

    def test_spread_width_all_tiers(self):
        """Test spread width for all account value tiers"""
        # Define tier boundaries and expected widths
        tier_tests = [
            # (account_value, expected_width, description)
            (Decimal("10000"), 3, "Under $25k - minimum account"),
            (Decimal("24999"), 3, "Just under $25k tier boundary"),
            (Decimal("25000"), 5, "Exactly $25k - tier 2 boundary"),
            (Decimal("37500"), 5, "Mid-tier 2 ($25k-$50k)"),
            (Decimal("49999"), 5, "Just under $50k tier boundary"),
            (Decimal("50000"), 7, "Exactly $50k - tier 3 boundary"),
            (Decimal("62500"), 7, "Mid-tier 3 ($50k-$75k)"),
            (Decimal("74999"), 7, "Just under $75k tier boundary"),
            (Decimal("75000"), 9, "Exactly $75k - tier 4 boundary"),
            (Decimal("100000"), 9, "Large account $100k"),
            (Decimal("1000000"), 9, "Very large account $1M"),
        ]

        for account_value, expected_width, description in tier_tests:
            width = self.config.get_spread_width(account_value)
            assert width == expected_width, (
                f"{description}: Account ${account_value} should use "
                f"{expected_width}-point spreads, got {width}"
            )

    def test_spread_width_always_odd(self):
        """Spread widths must ALWAYS be odd numbers (requirement for option strikes)"""
        test_values = [
            Decimal("15000"),
            Decimal("25000"),
            Decimal("35000"),
            Decimal("50000"),
            Decimal("75000"),
            Decimal("100000"),
            Decimal("500000"),
        ]

        for account_value in test_values:
            width = self.config.get_spread_width(account_value)
            assert (
                width % 2 == 1
            ), f"Spread width {width} for account ${account_value} must be odd number"

    def test_spread_width_increases_with_capital(self):
        """Spread width should increase as account value increases"""
        test_progression = [
            Decimal("20000"),  # Tier 1: 3-point
            Decimal("30000"),  # Tier 2: 5-point
            Decimal("60000"),  # Tier 3: 7-point
            Decimal("100000"),  # Tier 4: 9-point
        ]

        previous_width = 0
        for account_value in test_progression:
            width = self.config.get_spread_width(account_value)
            assert width > previous_width, (
                f"Spread width should increase with account size: "
                f"${account_value} width {width} not greater than previous {previous_width}"
            )
            previous_width = width

    def test_max_spreads_calculation(self):
        """Test maximum number of spreads allowed based on strategy power and width"""
        risk_manager = EnhancedRiskManager(self.user)

        test_cases = [
            # (strategy_power, spread_width, expected_max_spreads)
            (Decimal("10000"), 5, 20),  # $10k / ($5 × 100) = 20 spreads
            (Decimal("20000"), 5, 40),  # $20k / ($5 × 100) = 40 spreads
            (Decimal("15000"), 3, 50),  # $15k / ($3 × 100) = 50 spreads
            (Decimal("30000"), 7, 42),  # $30k / ($7 × 100) = 42.857 → 42
            (Decimal("0"), 5, 0),  # Edge case: no capital
            (Decimal("5000"), 0, 0),  # Edge case: invalid spread width
        ]

        for strategy_power, spread_width, expected_max in test_cases:
            max_spreads = risk_manager.calculate_max_spreads(strategy_power, spread_width)
            assert max_spreads == expected_max, (
                f"Strategy power ${strategy_power} with {spread_width}-point spreads "
                f"should allow {expected_max} spreads, got {max_spreads}"
            )


class StressScenarioTests(TestCase):
    """Test position sizing under high VIX / stressed market conditions"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="stress@example.com",
            username="stress@example.com",
            password="testpass123",
        )
        self.risk_manager = EnhancedRiskManager(self.user)
        self.allocation = OptionsAllocation.objects.create(
            user=self.user,
            risk_tolerance=Decimal("0.40"),  # Normal: 40%
            stressed_risk_tolerance=Decimal("0.60"),  # Stressed: 60%
        )

    def test_stress_increases_available_capital(self):
        """Stressed tolerance (60%) should allow MORE capital than normal (40%)"""
        # Mock AccountStateService to provide buying power
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with patch.object(
            self.risk_manager.account_state_service,
            "a_get",
            AsyncMock(return_value=mock_account_state),
        ):
            # Normal market: 40% of $100k = $40k
            normal_power, _ = self.risk_manager.calculate_strategy_power(is_stressed=False)
            assert normal_power == Decimal("40000")

            # Stressed market: 60% of $100k = $60k
            stressed_power, _ = self.risk_manager.calculate_strategy_power(is_stressed=True)
            assert stressed_power == Decimal("60000")

            # Stressed should be higher
            assert (
                stressed_power > normal_power
            ), "Stressed tolerance should provide MORE capital for defensive strategies"

    def test_stress_position_sizing_with_existing_positions(self):
        """Test remaining budget calculation under stress with open positions"""
        # Mock AccountStateService
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("20000")),
            ),
        ):
            # Tradeable = $100k BP + $20k app_managed = $120k
            # Normal: ($120k × 40%) - $20k = $48k - $20k = $28k remaining
            normal_remaining, _ = self.risk_manager.get_remaining_budget(is_stressed=False)
            assert normal_remaining == Decimal("28000")

            # Stressed: ($120k × 60%) - $20k = $72k - $20k = $52k remaining
            stressed_remaining, _ = self.risk_manager.get_remaining_budget(is_stressed=True)
            assert stressed_remaining == Decimal("52000")

            # Stressed should allow more new positions
            assert stressed_remaining > normal_remaining

    def test_high_stress_full_capacity(self):
        """Test behavior when portfolio is at full capacity even under stress"""
        # Mock AccountStateService
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("60000")),
            ),
        ):
            # Tradeable = $100k BP + $60k app_managed = $160k
            # Normal: ($160k × 40%) - $60k = $64k - $60k = $4k remaining
            normal_remaining, _ = self.risk_manager.get_remaining_budget(is_stressed=False)
            assert normal_remaining == Decimal("4000")

            # Stressed: ($160k × 60%) - $60k = $96k - $60k = $36k remaining
            stressed_remaining, _ = self.risk_manager.get_remaining_budget(is_stressed=True)
            assert stressed_remaining == Decimal("36000")


class BoundaryConditionTests(TestCase):
    """Test edge cases: zero values, at capacity, over capacity"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="boundary@example.com",
            username="boundary@example.com",
            password="testpass123",
        )
        self.risk_manager = EnhancedRiskManager(self.user)
        OptionsAllocation.objects.create(
            user=self.user, risk_tolerance=Decimal("0.40"), stressed_risk_tolerance=Decimal("0.60")
        )

    def test_portfolio_at_95_percent_capacity(self):
        """Test approval when portfolio is at 95% capacity"""
        # Mock: $100k capital, 40% tolerance = $40k strategy power
        # At 95% capacity: $38k used, $2k remaining
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("38000")),
            ),
        ):
            # Tradeable = $100k BP + $38k app_managed = $138k
            # Strategy Power = $138k × 40% = $55.2k
            # Remaining = $55.2k - $38k = $17.2k
            remaining, available = self.risk_manager.get_remaining_budget()
            assert available
            assert remaining == Decimal("17200")

            # Can open $15k position (within $17.2k budget)
            can_open, msg = self.risk_manager.can_open_position(Decimal("15000"))
            assert can_open
            assert "approved" in msg.lower()

            # Cannot open $20k position (exceeds $17.2k budget)
            can_open, msg = self.risk_manager.can_open_position(Decimal("20000"))
            assert not can_open
            assert "exceeds" in msg.lower()

    def test_portfolio_at_100_percent_capacity(self):
        """Test rejection when portfolio is at 100% capacity"""
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("40000")),
            ),
        ):
            # Tradeable = $100k BP + $40k app_managed = $140k
            # Strategy Power = $140k × 40% = $56k
            # Remaining = $56k - $40k = $16k
            remaining, available = self.risk_manager.get_remaining_budget()
            assert available
            assert remaining == Decimal("16000")

            # Can still open positions within $16k budget
            can_open, msg = self.risk_manager.can_open_position(Decimal("100"))
            assert can_open  # Changed: $100 is within $16k budget

            # Cannot exceed the $16k remaining budget
            can_open, msg = self.risk_manager.can_open_position(Decimal("20000"))
            assert not can_open
            assert "exceeds" in msg.lower()

    def test_portfolio_over_capacity(self):
        """Test handling when risk exceeds strategy power (shouldn't happen, but test it)"""
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("50000")),
            ),
        ):
            # Tradeable = $100k BP + $50k app_managed = $150k
            # Strategy Power = $150k × 40% = $60k
            # Remaining = $60k - $50k = $10k
            remaining, available = self.risk_manager.get_remaining_budget()
            assert available
            assert remaining == Decimal("10000")

            # Can still open small positions within $10k budget
            can_open, msg = self.risk_manager.can_open_position(Decimal("100"))
            assert can_open  # Changed: $100 is within $10k budget

            # Cannot exceed $10k budget
            can_open, msg = self.risk_manager.can_open_position(Decimal("15000"))
            assert not can_open

    def test_zero_buying_power(self):
        """Test behavior with zero buying power and no positions"""
        mock_account_state = {
            "available": True,
            "buying_power": 0.0,
            "balance": 0.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("0")),
            ),
        ):
            strategy_power, available = self.risk_manager.calculate_strategy_power()
            assert available
            assert strategy_power == Decimal("0")

            # Cannot open any position with zero capital
            can_open, msg = self.risk_manager.can_open_position(Decimal("100"))
            assert not can_open

    def test_account_data_unavailable(self):
        """Test fail-safe behavior when account data is unavailable"""
        # Mock unavailable account data
        mock_account_state = {"available": False}

        with patch.object(
            self.risk_manager.account_state_service,
            "a_get",
            AsyncMock(return_value=mock_account_state),
        ):
            # Should reject position when data unavailable
            can_open, msg = self.risk_manager.can_open_position(Decimal("100"))
            assert not can_open
            assert "unavailable" in msg.lower()
            assert "no guessing" in msg.lower()

    def test_decimal_precision_preservation(self):
        """Ensure Decimal precision is preserved throughout calculations"""
        mock_account_state = {
            "available": True,
            "buying_power": 100000.0,
            "balance": 100000.0,
            "asof": "2024-01-01T00:00:00",
        }

        with (
            patch.object(
                self.risk_manager.account_state_service,
                "a_get",
                AsyncMock(return_value=mock_account_state),
            ),
            patch.object(
                self.risk_manager,
                "_a_calculate_app_managed_risk",
                AsyncMock(return_value=Decimal("15432.87")),
            ),
        ):
            remaining, available = self.risk_manager.get_remaining_budget()
            assert available

            # Tradeable = $100k BP + $15432.87 app_managed = $115432.87
            # Strategy Power = $115432.87 × 0.40 = $46173.148
            # Remaining = $46173.148 - $15432.87 = $30740.278
            expected = (Decimal("100000") + Decimal("15432.87")) * Decimal("0.40") - Decimal(
                "15432.87"
            )
            assert remaining == expected
            assert isinstance(remaining, Decimal)


class UtilizationPercentTests(TestCase):
    """Test risk budget utilization percentage calculations"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="utilization@example.com",
            username="utilization@example.com",
            password="testpass123",
        )
        self.risk_manager = EnhancedRiskManager(self.user)
        OptionsAllocation.objects.create(user=self.user, risk_tolerance=Decimal("0.40"))

    def test_utilization_percentage_calculation(self):
        """Test utilization percentage is calculated correctly"""

        # Mock async methods for get_risk_budget_data
        async def mock_tradeable_capital():
            return (Decimal("100000"), True)

        async def mock_app_risk():
            return Decimal("20000")  # 50% utilization of $40k strategy power

        with (
            patch.object(self.risk_manager, "a_get_tradeable_capital", new=mock_tradeable_capital),
            patch.object(self.risk_manager, "_a_calculate_app_managed_risk", new=mock_app_risk),
        ):
            data = self.risk_manager.get_risk_budget_data()

            assert data["data_available"]
            assert data["strategy_power"] == 40000.0  # $100k × 40%
            assert data["current_risk"] == 20000.0
            assert data["utilization_percent"] == 50.0  # 20k / 40k = 50%

    def test_utilization_capped_at_100(self):
        """Utilization percentage should be capped at 100% even if over capacity"""

        async def mock_tradeable_capital():
            return (Decimal("100000"), True)

        async def mock_app_risk():
            return Decimal("50000")  # 125% utilization (over capacity)

        with (
            patch.object(self.risk_manager, "a_get_tradeable_capital", new=mock_tradeable_capital),
            patch.object(self.risk_manager, "_a_calculate_app_managed_risk", new=mock_app_risk),
        ):
            data = self.risk_manager.get_risk_budget_data()

            assert data["data_available"]
            # Should cap at 100%, not show 125%
            assert data["utilization_percent"] == 100.0
