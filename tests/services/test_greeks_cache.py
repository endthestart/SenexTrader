"""Tests for Greeks caching functionality."""

import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from accounts.models import TradingAccount
from services.market_data.greeks import GreeksService
from trading.models import Position

User = get_user_model()


class TestGreeksCaching(TestCase):
    """Test Greeks caching layer."""

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

        self.service = GreeksService()

        # Clear cache before each test
        cache.clear()

    def test_position_greeks_cached_first_call(self):
        """Test that first call calculates Greeks (cache miss)."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "action": "SELL", "quantity": 1}]},
        )

        # Mock the underlying get_position_greeks method
        with patch.object(
            self.service,
            "get_position_greeks",
            return_value={
                "delta": 0.15,
                "gamma": 0.02,
                "theta": -0.45,
                "vega": 0.30,
                "rho": 0.05,
            },
        ) as mock_calc:
            greeks = self.service.get_position_greeks_cached(position)

            # Should call the underlying method
            mock_calc.assert_called_once_with(position)

            # Should return the Greeks
            assert greeks["delta"] == 0.15

    def test_position_greeks_cached_second_call(self):
        """Test that second call uses cache (cache hit)."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "action": "SELL", "quantity": 1}]},
        )

        expected_greeks = {
            "delta": 0.15,
            "gamma": 0.02,
            "theta": -0.45,
            "vega": 0.30,
            "rho": 0.05,
        }

        # Mock the underlying calculation method
        with patch.object(
            self.service, "get_position_greeks", return_value=expected_greeks
        ) as mock_calc:
            # First call - cache miss
            greeks1 = self.service.get_position_greeks_cached(position)
            assert mock_calc.call_count == 1

            # Second call - cache hit
            greeks2 = self.service.get_position_greeks_cached(position)
            assert mock_calc.call_count == 1  # Not called again

            # Should return same Greeks
            assert greeks1 == greeks2

    def test_position_greeks_cache_expires(self):
        """Test that cache expires after TTL."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "action": "SELL", "quantity": 1}]},
        )

        expected_greeks = {
            "delta": 0.15,
            "gamma": 0.02,
            "theta": -0.45,
            "vega": 0.30,
            "rho": 0.05,
        }

        with patch.object(
            self.service, "get_position_greeks", return_value=expected_greeks
        ) as mock_calc:
            # First call
            self.service.get_position_greeks_cached(position)
            assert mock_calc.call_count == 1

            # Wait for cache to expire (6 seconds > 5 second TTL)
            time.sleep(6)

            # Should recalculate after expiration
            self.service.get_position_greeks_cached(position)
            assert mock_calc.call_count == 2

    def test_portfolio_greeks_cached_first_call(self):
        """Test portfolio Greeks caching on first call."""
        Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "action": "SELL", "quantity": 1}]},
        )

        expected_greeks = {
            "delta": 0.25,
            "gamma": 0.05,
            "theta": -1.20,
            "vega": 0.80,
            "rho": 0.15,
            "position_count": 1,
        }

        with patch.object(
            self.service, "get_portfolio_greeks", return_value=expected_greeks
        ) as mock_calc:
            greeks = self.service.get_portfolio_greeks_cached(self.user)

            # Should call the underlying method
            mock_calc.assert_called_once_with(self.user)

            # Should return the Greeks
            assert greeks["delta"] == 0.25
            assert greeks["position_count"] == 1

    def test_portfolio_greeks_cached_second_call(self):
        """Test portfolio Greeks uses cache on second call."""
        expected_greeks = {
            "delta": 0.25,
            "gamma": 0.05,
            "theta": -1.20,
            "vega": 0.80,
            "rho": 0.15,
            "position_count": 1,
        }

        with patch.object(
            self.service, "get_portfolio_greeks", return_value=expected_greeks
        ) as mock_calc:
            # First call - cache miss
            greeks1 = self.service.get_portfolio_greeks_cached(self.user)
            assert mock_calc.call_count == 1

            # Second call - cache hit
            greeks2 = self.service.get_portfolio_greeks_cached(self.user)
            assert mock_calc.call_count == 1  # Not called again

            # Should return same Greeks
            assert greeks1 == greeks2

    def test_separate_cache_per_user(self):
        """Test that different users have separate caches."""
        user2 = User.objects.create_user(
            email="test2@example.com", username="testuser2", password="testpass123"
        )

        greeks1 = {"delta": 0.10, "position_count": 1}
        greeks2 = {"delta": 0.20, "position_count": 2}

        with patch.object(self.service, "get_portfolio_greeks", side_effect=[greeks1, greeks2]):
            # Cache for user 1
            result1 = self.service.get_portfolio_greeks_cached(self.user)

            # Cache for user 2 (different cache key)
            result2 = self.service.get_portfolio_greeks_cached(user2)

            # Should have different results
            assert result1["delta"] == 0.1
            assert result2["delta"] == 0.2

    def test_separate_cache_per_position(self):
        """Test that different positions have separate caches."""
        position1 = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "QQQ 251107P00590000", "action": "SELL", "quantity": 1}]},
        )

        position2 = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            quantity=1,
            lifecycle_state="open_full",
            metadata={"legs": [{"symbol": "SPY 251107P00450000", "action": "SELL", "quantity": 1}]},
        )

        greeks1 = {"delta": 0.10}
        greeks2 = {"delta": 0.20}

        with patch.object(self.service, "get_position_greeks", side_effect=[greeks1, greeks2]):
            # Cache for position 1
            result1 = self.service.get_position_greeks_cached(position1)

            # Cache for position 2 (different cache key)
            result2 = self.service.get_position_greeks_cached(position2)

            # Should have different results
            assert result1["delta"] == 0.1
            assert result2["delta"] == 0.2
