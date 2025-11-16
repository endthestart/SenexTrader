"""
Base test utilities and fixtures for streaming tests.

Provides common test patterns for streaming infrastructure without
modifying existing working code.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from tastytrade import Session
from tastytrade.dxfeed import Quote

from services.core.cache import CacheManager
from streaming.consumers import StreamingConsumer
from streaming.services.stream_manager import GlobalStreamManager

User = get_user_model()


class StreamingTestMixin:
    """Common utilities for streaming tests."""

    def setUp(self):
        super().setUp()
        # Clear cache before each test
        cache.clear()

        # Clear global stream manager
        GlobalStreamManager._user_managers.clear()

    def tearDown(self):
        cache.clear()
        GlobalStreamManager._user_managers.clear()
        super().tearDown()

    @sync_to_async
    def create_test_user(self, username="testuser", email="test@example.com"):
        """Create a test user (async-safe version)."""
        from accounts.models import TradingAccount  # noqa: PLC0415

        user = User.objects.create_user(username=username, email=email, password="testpass123")
        # Create a trading account for the user so they can connect to WebSocket
        TradingAccount.objects.create(
            user=user,
            connection_type="TASTYTRADE",
            account_number=f"TEST{user.id}",
            is_primary=True,
            is_active=True,
            access_token="test_access_token",
            refresh_token="test_refresh_token",
        )
        return user

    async def acreate_test_user(self, username="testuser", email="test@example.com"):
        """Create a test user (async version - calls create_test_user)."""
        return await self.create_test_user(username, email)

    def create_mock_oauth_session(self):
        """Create a mock OAuth session."""
        mock_session = MagicMock(spec=Session)
        mock_session.refresh = MagicMock()
        return mock_session

    def create_mock_trading_account(self, user, account_number="TEST123"):
        """Create a mock trading account."""

        # Create a mock instead of real account to avoid external dependencies
        mock_account = MagicMock()
        mock_account.user_id = user.id
        mock_account.account_number = account_number
        mock_account.connection_type = "TASTYTRADE"
        mock_account.is_primary = True
        mock_account.refresh_token = "mock_refresh_token"
        mock_account.get_oauth_session.return_value = self.create_mock_oauth_session()

        return mock_account

    def create_test_quote_data(self, symbol="QQQ", last_price=450.50):
        """Create test quote data."""
        return {
            "symbol": symbol,
            "last": last_price,
            "bid": last_price - 0.01,
            "ask": last_price + 0.01,
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "test_data",
        }

    def create_test_balance_data(self, balance=10000.0, buying_power=5000.0):
        """Create test balance data."""
        return {
            "net_liquidating_value": balance,
            "buying_power": buying_power,
            "cash_balance": balance * 0.1,
            "available_trading_funds": buying_power * 0.8,
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        }

    def mock_tastytrade_quote(self, symbol="QQQ", last_price=450.50):
        """Create a mock DXFeed Quote object."""
        mock_quote = MagicMock(spec=Quote)
        mock_quote.event_symbol = symbol
        mock_quote.last_price = last_price
        mock_quote.bid_price = last_price - 0.01
        mock_quote.ask_price = last_price + 0.01
        mock_quote.event_time = int(datetime.now(UTC).timestamp() * 1000)
        return mock_quote

    def assert_cache_has_quote(self, symbol, expected_last=None):
        """Assert that cache has quote data for symbol."""
        cache_key = CacheManager.quote(symbol)
        cached_data = cache.get(cache_key)

        assert cached_data is not None, f"No cached quote data for {symbol}"
        assert cached_data["symbol"] == symbol

        if expected_last is not None:
            assert cached_data["last"] == expected_last

    def assert_websocket_message_type(self, message_data, expected_type):
        """Assert WebSocket message has expected type."""
        assert isinstance(message_data, dict)
        assert message_data.get("type") == expected_type


class StreamingTestCase(StreamingTestMixin, TestCase):
    """Base test case for synchronous streaming tests."""


class AsyncStreamingTestCase(StreamingTestMixin, TransactionTestCase):
    """Base test case for asynchronous streaming tests."""

    async def async_setUp(self):
        """Async setup for async tests."""
        await super().setUp()

    async def async_tearDown(self):
        """Async teardown for async tests."""
        await super().tearDown()

    async def create_websocket_communicator(self, user=None):
        """Create a WebSocket communicator for testing."""
        if user is None:
            user = await self.acreate_test_user()

        communicator = WebsocketCommunicator(
            StreamingConsumer.as_asgi(),
            "/ws/streaming/",
        )

        # Mock user authentication
        communicator.scope["user"] = user

        return communicator, user

    async def connect_websocket(self, user=None):
        """Connect a WebSocket and return communicator."""
        communicator, user = await self.create_websocket_communicator(user)

        connected, _subprotocol = await communicator.connect()
        assert connected, "WebSocket connection failed"

        # Note: Current consumer implementation doesn't send connection_established
        # It may send cached QQQ data if available, but that's optional
        # Just return the connected communicator

        return communicator, user

    async def disconnect_websocket(self, communicator):
        """Disconnect WebSocket communicator."""
        await communicator.disconnect()


class MockDXLinkStreamer:
    """Mock DXLinkStreamer for testing without external dependencies."""

    def __init__(self, session):
        self.session = session
        self.subscriptions = {}
        self.is_closed = False
        self._quote_queue = asyncio.Queue()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def subscribe(self, event_type, symbols):
        """Mock subscription."""
        if event_type not in self.subscriptions:
            self.subscriptions[event_type] = set()
        self.subscriptions[event_type].update(symbols)

    async def listen(self, event_type):
        """Mock listener that yields from queue."""
        while not self.is_closed:
            try:
                # Use timeout to prevent infinite blocking
                event = await asyncio.wait_for(self._quote_queue.get(), timeout=0.1)
                yield event
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def close(self):
        """Mock close."""
        self.is_closed = True

    def add_mock_quote(self, quote):
        """Add a mock quote to the queue."""
        self._quote_queue.put_nowait(quote)


class StreamingTestPatches:
    """Context manager for common streaming test patches."""

    def __init__(self):
        self.patches = []

    def __enter__(self):
        # Patch DXLinkStreamer to use our mock
        dxlink_patch = patch("streaming.services.stream_manager.DXLinkStreamer", MockDXLinkStreamer)
        self.patches.append(dxlink_patch)

        # NOTE: Removed TradingAccount patch - we now create real TradingAccount objects
        # in create_test_user() to support async queries

        # Mock session creation to avoid real API calls with fake tokens
        from unittest.mock import AsyncMock  # noqa: PLC0415

        session_mock = MagicMock()
        session_mock.refresh = MagicMock()
        async_create_session = AsyncMock(
            return_value={
                "success": True,
                "session": session_mock,
                "account_streamer_url": "test_url",
            }
        )
        session_patch = patch(
            "services.brokers.tastytrade.session.TastyTradeSessionService.create_session",
            new=async_create_session,
        )
        self.patches.append(session_patch)

        # Start all patches
        mocks = {}
        for p in self.patches:
            mock = p.start()
            mocks[p.attribute if hasattr(p, "attribute") else "mock"] = mock

        return mocks

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self.patches:
            p.stop()
