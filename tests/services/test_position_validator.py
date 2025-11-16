"""Tests for position validator service."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import TradingAccount
from services.positions.validator import PositionValidator
from trading.models import Position

User = get_user_model()


class TestPositionValidator(TestCase):
    """Test position validation functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="12345",
            is_primary=True,
            is_active=True,
        )

        self.validator = PositionValidator()

    def test_validate_valid_position(self):
        """Test validation of a valid position."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            avg_price=Decimal("1.50"),
            unrealized_pnl=Decimal("75.00"),
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                "strikes": {
                    "short_put": "590",
                    "long_put": "585",
                    "short_call": "600",
                    "long_call": "605",
                },
                "legs": [
                    {"symbol": "QQQ 251107P00590000", "quantity": -1},
                    {"symbol": "QQQ 251107P00585000", "quantity": 1},
                ],
            },
        )

        issues = self.validator.validate_position(position)
        assert len(issues) == 0, "Valid position should have no issues"

    def test_validate_missing_symbol(self):
        """Test detection of missing symbol."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="",  # Missing symbol
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
        )

        issues = self.validator.validate_position(position)
        assert "Missing underlying symbol" in issues

    def test_validate_app_managed_missing_suggestion_id(self):
        """Test detection of missing suggestion_id in app-managed position."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={  # Missing suggestion_id
                "strikes": {"short_put": "590"},
                "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            },
        )

        issues = self.validator.validate_position(position)
        assert any(
            "suggestion_id" in issue for issue in issues
        ), "Should detect missing suggestion_id"

    def test_validate_app_managed_missing_strikes(self):
        """Test detection of missing strikes data."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                # Missing strikes
                "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            },
        )

        issues = self.validator.validate_position(position)
        assert any("strikes" in issue for issue in issues), "Should detect missing strikes data"

    def test_validate_missing_legs(self):
        """Test detection of missing legs data."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            metadata={},  # No legs
        )

        issues = self.validator.validate_position(position)
        assert any("legs" in issue for issue in issues), "Should detect missing legs data"

    def test_validate_unusually_large_pnl(self):
        """Test detection of unusually large P&L."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            unrealized_pnl=Decimal("150000.00"),  # Unusually large
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}]},
        )

        issues = self.validator.validate_position(position)
        assert any(
            "Unusually large P&L" in issue for issue in issues
        ), "Should detect unusually large P&L"

    def test_validate_all_positions(self):
        """Test validation of all user positions."""
        # Create a mix of valid and invalid positions
        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                "strikes": {"short_put": "590"},
                "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            },
        )

        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={},  # Missing required data
        )

        results = self.validator.validate_all_positions(self.user)

        assert results["total_positions"] == 2
        assert results["positions_with_issues"] == 1
        assert len(results["issues_by_position"]) == 1

    def test_get_health_score_perfect(self):
        """Test health score for perfect portfolio."""
        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                "strikes": {"short_put": "590"},
                "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            },
        )

        health = self.validator.get_health_score(self.user)

        assert health["score"] == 100.0
        assert health["grade"] == "A"
        assert health["issues"] == 0

    def test_get_health_score_with_issues(self):
        """Test health score with some problematic positions."""
        # Valid position
        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                "strikes": {"short_put": "590"},
                "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            },
        )

        # Invalid position (50% of positions)
        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={},  # Missing data
        )

        health = self.validator.get_health_score(self.user)

        assert health["score"] == 50.0
        assert health["grade"] == "F"
        assert health["issues"] == 1
        assert len(health["recommendations"]) > 0
