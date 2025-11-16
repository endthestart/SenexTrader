"""Tests for option chain service with strike selection algorithm (Phase 5F)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

import pytest

from accounts.models import TradingAccount
from services.market_data.option_chains import OptionChainService
from services.strategies.senex_trident_strategy import SenexTridentStrategy

User = get_user_model()


class TestOptionChainService(TestCase):
    """Test strike selection algorithm and option chain functionality."""

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

        self.option_service = OptionChainService()
        self.strategy_service = SenexTridentStrategy(self.user)

        # Clear cache before each test
        cache.clear()

    def test_calculate_base_strike_even(self):
        """Test even strike calculation (critical algorithm) via SenexTridentStrategy."""
        # Test exact even number
        result = self.strategy_service.calculate_base_strike(Decimal("450.00"))
        assert result == Decimal("450")

        # Test odd number (should round to nearest even using round(price/2)*2 formula)
        result = self.strategy_service.calculate_base_strike(Decimal("451.75"))
        assert result == Decimal("452")  # 451.75/2=225.875, round=226, *2=452

        # Test number ending in .5 (should round to nearest even using round(price/2)*2 formula)
        result = self.strategy_service.calculate_base_strike(Decimal("451.00"))
        assert result == Decimal("452")  # 451.00/2=225.5, round=226, *2=452

        result = self.strategy_service.calculate_base_strike(Decimal("452.00"))
        assert result == Decimal("452")

        # Test edge cases
        result = self.strategy_service.calculate_base_strike(Decimal("1.50"))
        assert result == Decimal("2")

    def test_select_strike_with_fallback_exact_match(self):
        """Test strike selection when exact strike is available."""
        available_strikes = {
            Decimal("445"),
            Decimal("450"),
            Decimal("455"),
            Decimal("460"),
        }
        target_strike = Decimal("450")

        result = self.option_service._select_strike_with_fallback(target_strike, available_strikes)
        assert result == Decimal("450")

    def test_select_strike_with_fallback_higher_strike(self):
        """Test strike selection fallback to higher strike for more credit."""
        available_strikes = {
            Decimal("445"),
            Decimal("452"),
            Decimal("455"),
            Decimal("460"),
        }
        target_strike = Decimal("450")  # Not available

        result = self.option_service._select_strike_with_fallback(target_strike, available_strikes)
        assert result == Decimal("452")  # Next higher strike

    def test_select_strike_with_fallback_no_higher(self):
        """Test strike selection when no higher strikes available."""
        available_strikes = {Decimal("440"), Decimal("445"), Decimal("448")}
        target_strike = Decimal("450")  # Higher than all available

        result = self.option_service._select_strike_with_fallback(target_strike, available_strikes)
        assert result is None

    def test_select_put_spread_strikes_valid(self):
        """Test put spread strike selection with valid strikes."""
        base_strike = Decimal("450")
        width = 5
        put_strikes = {
            Decimal("440"),
            Decimal("445"),
            Decimal("450"),
            Decimal("455"),
            Decimal("460"),
        }

        result = self.option_service._select_put_spread_strikes(base_strike, width, put_strikes)

        assert result is not None
        assert result["short"] == Decimal("450")  # At base strike
        assert result["long"] == Decimal("445")  # 5 points below

    def test_select_put_spread_strikes_missing_long(self):
        """Test put spread selection when long strike not available."""
        base_strike = Decimal("450")
        width = 5
        put_strikes = {Decimal("447"), Decimal("450"), Decimal("455")}  # Missing 445

        result = self.option_service._select_put_spread_strikes(base_strike, width, put_strikes)
        assert result is None

    def test_select_call_spread_strikes_valid(self):
        """Test call spread strike selection with valid strikes."""
        base_strike = Decimal("450")
        width = 5
        call_strikes = {
            Decimal("440"),
            Decimal("445"),
            Decimal("450"),
            Decimal("455"),
            Decimal("460"),
        }

        result = self.option_service._select_call_spread_strikes(base_strike, width, call_strikes)

        assert result is not None
        assert result["short"] == Decimal("450")  # At base strike
        assert result["long"] == Decimal("455")  # 5 points above

    def test_select_call_spread_strikes_missing_long(self):
        """Test call spread selection when long strike not available."""
        base_strike = Decimal("450")
        width = 5
        call_strikes = {Decimal("440"), Decimal("445"), Decimal("450")}  # Missing 455

        result = self.option_service._select_call_spread_strikes(base_strike, width, call_strikes)
        assert result is None

    @pytest.mark.asyncio
    async def test_select_strikes_complete_senex_trident(self):
        """Test complete Senex Trident strike selection."""
        current_price = Decimal("450.75")
        width = 5

        # Create Strike objects with both put and call options
        strikes_list = []
        for s in range(440, 465, 5):  # 440, 445, 450, 455, 460
            strikes_list.append(
                {
                    "strike_price": str(s),
                    "put": f"SPY 250101P{s:05d}",
                    "call": f"SPY 250101C{s:05d}",
                }
            )

        mock_chain = {
            "strikes": strikes_list,
        }

        result = await self.option_service.select_strikes(current_price, mock_chain, width)

        assert result is not None

        # Base strike should be 450 (even)
        assert result["short_put"] == Decimal("450")
        assert result["long_put"] == Decimal("445")
        assert result["short_call"] == Decimal("450")
        assert result["long_call"] == Decimal("455")

    @pytest.mark.asyncio
    async def test_select_strikes_invalid_width(self):
        """Test strike selection with invalid spread width."""
        current_price = Decimal("450.00")
        width = 7  # Will cause long strikes to be missing

        # Create Strike objects with limited strikes (missing long strikes)
        strikes_list = [
            {"strike_price": "445", "put": None, "call": "SPY 250101C00445"},
            {"strike_price": "450", "put": "SPY 250101P00450", "call": "SPY 250101C00450"},
            {"strike_price": "455", "put": "SPY 250101P00455", "call": None},
        ]

        mock_chain = {
            "strikes": strikes_list,
        }

        result = await self.option_service.select_strikes(current_price, mock_chain, width)
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_strike_availability_valid(self):
        """Test strike availability validation with valid strikes."""
        strikes = {
            "short_put": Decimal("450"),
            "long_put": Decimal("445"),
            "short_call": Decimal("450"),
            "long_call": Decimal("455"),
        }

        # Create Strike objects
        strikes_list = [
            {"strike_price": "445", "put": "SPY 250101P00445", "call": "SPY 250101C00445"},
            {"strike_price": "450", "put": "SPY 250101P00450", "call": "SPY 250101C00450"},
            {"strike_price": "455", "put": "SPY 250101P00455", "call": "SPY 250101C00455"},
        ]

        mock_chain = {
            "strikes": strikes_list,
        }

        result = await self.option_service.validate_strike_availability(strikes, mock_chain)
        assert result

    @pytest.mark.asyncio
    async def test_validate_strike_availability_invalid(self):
        """Test strike availability validation with missing strikes."""
        strikes = {
            "short_put": Decimal("450"),
            "long_put": Decimal("440"),  # Not available
            "short_call": Decimal("450"),
            "long_call": Decimal("455"),
        }

        # Create Strike objects (missing 440)
        strikes_list = [
            {"strike_price": "445", "put": "SPY 250101P00445", "call": "SPY 250101C00445"},
            {"strike_price": "450", "put": "SPY 250101P00450", "call": "SPY 250101C00450"},
            {"strike_price": "455", "put": "SPY 250101P00455", "call": "SPY 250101C00455"},
        ]

        mock_chain = {
            "strikes": strikes_list,
        }

        result = await self.option_service.validate_strike_availability(strikes, mock_chain)
        assert not result

    @pytest.mark.asyncio
    async def test_check_strike_overlap_no_positions(self):
        """Test strike overlap check when no existing positions."""
        new_strikes = {
            "short_put": Decimal("450"),
            "long_put": Decimal("445"),
            "short_call": Decimal("450"),
            "long_call": Decimal("455"),
        }

        expiration = date.today() + timedelta(days=45)
        has_overlap, reason = await self.option_service.check_strike_overlap(
            self.user, new_strikes, "SPY", expiration
        )

        assert not has_overlap
        assert reason is None

    def test_find_target_expiration_friday(self):
        """Test finding target expiration (next Friday)."""
        import asyncio

        # Mock today as a Monday (2024-01-01 was a Monday)
        with patch("django.utils.timezone.now") as mock_now:
            mock_now.return_value.date.return_value = date(2024, 1, 1)  # Monday

            target_dte = 45
            result = asyncio.run(self.option_service._find_target_expiration(target_dte))

            # Should find the Friday after target date
            expected_date = date(2024, 2, 16)  # 46 days later, a Friday
            assert result == expected_date


# NOTE: TestValidateSenexTridentStrikes class removed
# This functionality has been moved to SenexTridentStrategy as part of separation of concerns refactoring
