"""
Pytest configuration and shared fixtures for Senex Trader tests.

This file provides common test fixtures and configuration that can be used
across all test modules in the project.
"""

import asyncio
import os
from unittest.mock import MagicMock, patch

import django

import pytest

# Configure Django before any imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senex_trader.settings.development")
# Set test encryption key for encrypted fields
if "FIELD_ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet

    os.environ["FIELD_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
django.setup()

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from accounts.models import TradingAccount
from tests.mocks.dxfeed_mocks import (
    DXFeedMockPatcher,
    MockMarketDataGenerator,
    create_mock_dxlink_streamer,
    create_mock_session,
)

User = get_user_model()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def clear_cache():
    """Clear Django cache before and after each test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def test_user():
    """Create a test user for testing."""
    return User.objects.create_user(
        email="test@example.com", username="testuser", password="testpass123"
    )


@pytest.fixture
def mock_user():
    """Create a mock user for unit tests (does not touch database)."""
    from unittest.mock import Mock

    user = Mock(spec=get_user_model())
    user.id = 1
    user.username = "testuser"
    user.email = "test@example.com"
    return user


@pytest.fixture
def test_trading_account(test_user):
    """Create a test trading account."""
    return TradingAccount.objects.create(
        user=test_user,
        account_number="TEST123456",
        connection_type="TASTYTRADE",
        account_nickname="Test Account",
    )


@pytest.fixture
def mock_dxfeed():
    """Pytest fixture for DXFeed mocking."""
    with DXFeedMockPatcher():
        yield


@pytest.fixture
def mock_dxlink_streamer():
    """Pytest fixture providing a mock DXLinkStreamer."""
    session = create_mock_session()
    return create_mock_dxlink_streamer(session, symbols=["SPY", "AAPL"])


@pytest.fixture
def mock_tastytrade_session():
    """Pytest fixture providing a mock TastyTrade session."""
    return create_mock_session()


@pytest.fixture
def market_data_generator():
    """Pytest fixture providing realistic market data generator."""
    return MockMarketDataGenerator()


@pytest.fixture
def mock_tastytrade_session_service():
    """Mock the TastyTrade session service."""
    from services.brokers.tastytrade.session import TastyTradeSessionService

    with patch.object(TastyTradeSessionService, "get_session") as mock_get_session:
        mock_session = create_mock_session()
        mock_get_session.return_value = mock_session
        yield mock_get_session


@pytest.fixture
def mock_streaming_auth():
    """Mock the streaming authentication service."""
    from streaming.services.auth_service import streaming_auth

    with patch.object(streaming_auth, "authenticate_account") as mock_auth:
        mock_session = create_mock_session()
        mock_auth.return_value = mock_session
        yield mock_auth


@pytest.fixture
def mock_redis_store():
    """Mock the Redis store for testing."""
    from streaming.services.redis_store import redis_store

    mock_client = MagicMock()
    mock_client.blpop.return_value = None  # No commands by default

    with patch.object(redis_store, "client", mock_client):
        yield mock_client


@pytest.fixture
def mock_channel_layer():
    """Mock Django Channels layer."""

    mock_layer = MagicMock()
    mock_layer.group_send = MagicMock()

    with patch("channels.layers.get_channel_layer", return_value=mock_layer):
        yield mock_layer


# Async test utilities
class AsyncTestCase(TestCase):
    """Test case class with async support."""

    def setUp(self):
        """Set up async test case."""
        super().setUp()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        """Tear down async test case."""
        self.loop.close()
        super().tearDown()

    def run_async(self, coro):
        """Run an async coroutine in the test loop."""
        return self.loop.run_until_complete(coro)


# Test data factories
class TestDataFactory:
    """Factory for creating test data objects."""

    @staticmethod
    def create_test_user(email="test@example.com", username="testuser"):
        """Create a test user."""
        return User.objects.create_user(email=email, username=username, password="testpass123")

    @staticmethod
    def create_test_trading_account(user, account_number="TEST123456"):
        """Create a test trading account."""
        return TradingAccount.objects.create(
            user=user,
            account_number=account_number,
            broker_name="tastytrade",
            nickname="Test Account",
        )

    @staticmethod
    def create_test_symbols():
        """Return a list of test symbols for market data."""
        return [
            "SPY",  # ETF
            "AAPL",  # Stock
            "MSFT",  # Stock
            "SPY 240119C00460000",  # Call option
            "SPY 240119P00440000",  # Put option
        ]


# Performance testing utilities
class PerformanceTimer:
    """Simple timer for performance testing."""

    def __init__(self):
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        import time

        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time

        self.end_time = time.time()

    @property
    def elapsed(self):
        """Get elapsed time in seconds."""
        if self.start_time is None or self.end_time is None:
            return None
        return self.end_time - self.start_time


# Mock data presets
MOCK_MARKET_DATA_PRESETS = {
    "bull_market": {
        "SPY": {"base_price": 480.0, "volatility": 0.15, "trend": "up"},
        "AAPL": {"base_price": 190.0, "volatility": 0.25, "trend": "up"},
        "MSFT": {"base_price": 380.0, "volatility": 0.20, "trend": "up"},
    },
    "bear_market": {
        "SPY": {"base_price": 420.0, "volatility": 0.35, "trend": "down"},
        "AAPL": {"base_price": 160.0, "volatility": 0.45, "trend": "down"},
        "MSFT": {"base_price": 320.0, "volatility": 0.40, "trend": "down"},
    },
    "high_volatility": {
        "SPY": {"base_price": 450.0, "volatility": 0.50, "trend": "sideways"},
        "AAPL": {"base_price": 175.0, "volatility": 0.60, "trend": "sideways"},
        "MSFT": {"base_price": 350.0, "volatility": 0.55, "trend": "sideways"},
    },
}


@pytest.fixture(params=MOCK_MARKET_DATA_PRESETS.keys())
def market_scenario(request):
    """Pytest fixture providing different market scenarios."""
    scenario_name = request.param
    scenario_data = MOCK_MARKET_DATA_PRESETS[scenario_name]
    return scenario_name, scenario_data


# Database fixtures
@pytest.fixture
def transactional_db():
    """Enable database transactions for tests."""
    from django.test import TransactionTestCase

    return TransactionTestCase
