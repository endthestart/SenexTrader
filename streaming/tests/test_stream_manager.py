"""
Tests for stream manager functionality.

Validates existing UserStreamManager and GlobalStreamManager behavior.
"""

import asyncio
from unittest.mock import patch

from django.core.cache import cache

from services.core.cache import CacheManager
from streaming.models import UserStreamContext
from streaming.services.stream_manager import GlobalStreamManager, UserStreamManager
from streaming.tests.base import AsyncStreamingTestCase, StreamingTestPatches


class UserStreamManagerTests(AsyncStreamingTestCase):
    """Tests for UserStreamManager functionality."""

    async def test_create_user_stream_manager(self):
        """Test creating a UserStreamManager instance."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        assert manager.user_id == user.id
        assert isinstance(manager.context, UserStreamContext)
        assert not manager.is_streaming

    async def test_add_remove_websocket_connections(self):
        """Test adding and removing WebSocket connections."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        # Initially no connections
        assert manager.context.reference_count == 0
        assert not manager.context.is_active

        # Add first connection
        manager.context.add_channel("channel_1")
        assert manager.context.reference_count == 1
        assert manager.context.is_active

        # Add second connection (multi-tab support)
        manager.context.add_channel("channel_2")
        assert manager.context.reference_count == 2
        assert manager.context.is_active

        # Remove first connection
        manager.context.remove_channel("channel_1")
        assert manager.context.reference_count == 1
        assert manager.context.is_active

        # Remove second connection (last one)
        manager.context.remove_channel("channel_2")
        assert manager.context.reference_count == 0
        assert not manager.context.is_active

    async def test_start_streaming_no_trading_account(self):
        """Test start_streaming fails when no trading account exists."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        with patch("streaming.services.stream_manager.TradingAccount") as mock_ta:
            # Mock no trading account found - use AsyncMock for async methods
            from unittest.mock import AsyncMock

            mock_filter = AsyncMock()
            mock_filter.afirst = AsyncMock(return_value=None)
            mock_ta.objects.filter.return_value = mock_filter

            await manager.start_streaming(["QQQ"])
            # Just verify it didn't start streaming
            assert not manager.is_streaming

    async def test_start_streaming_no_refresh_token(self):
        """Test start_streaming fails when no OAuth session."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        # Patch the OAuth session getter to return None - it's in services.data_access
        with patch("services.data_access.get_oauth_session") as mock_oauth:

            mock_oauth.return_value = None

            await manager.start_streaming(["QQQ"])
            assert not manager.is_streaming, "Should fail when no OAuth session"

    async def test_start_streaming_oauth_session_failure(self):
        """Test start_streaming fails when OAuth session creation fails."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        # Patch the OAuth session getter to return None - it's in services.data_access
        with patch("services.data_access.get_oauth_session") as mock_oauth:

            mock_oauth.return_value = None

            await manager.start_streaming(["QQQ"])
            assert not manager.is_streaming, "Should fail when OAuth session creation fails"

    async def test_start_streaming_success(self):
        """Test successful streaming start."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        with StreamingTestPatches():
            # Mock the OAuth session and TradingAccount
            with patch("services.data_access.get_oauth_session") as mock_oauth:
                from unittest.mock import AsyncMock

                mock_oauth.return_value = self.create_mock_oauth_session()

                with patch("streaming.services.stream_manager.TradingAccount") as mock_ta:
                    mock_account = self.create_mock_trading_account(user)
                    mock_filter = AsyncMock()
                    mock_filter.afirst = AsyncMock(return_value=mock_account)
                    mock_ta.objects.filter.return_value = mock_filter

                    await manager.start_streaming(["QQQ", "SPY"])

                    # Give streaming task time to start
                    await asyncio.sleep(0.1)

                    # Verify streaming state
                    assert manager.streaming_task is not None
                    assert manager.is_streaming or manager.streaming_task is not None

        # Clean up tasks
        await manager.stop_streaming()

    async def test_streaming_already_active_update_symbols(self):
        """Test that starting streaming when already active updates symbols."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        with StreamingTestPatches():
            with patch("services.data_access.get_oauth_session") as mock_oauth:
                from unittest.mock import AsyncMock

                mock_oauth.return_value = self.create_mock_oauth_session()

                with patch("streaming.services.stream_manager.TradingAccount") as mock_ta:
                    mock_account = self.create_mock_trading_account(user)
                    mock_filter = AsyncMock()
                    mock_filter.afirst = AsyncMock(return_value=mock_account)
                    mock_ta.objects.filter.return_value = mock_filter

                    # First start
                    await manager.start_streaming(["QQQ"])
                    await asyncio.sleep(0.1)

                    # Mark as streaming and add data streamer (use AsyncMock for await expressions)
                    manager.is_streaming = True
                    from unittest.mock import AsyncMock

                    mock_streamer = AsyncMock()
                    mock_streamer.subscribe = AsyncMock()
                    manager.context.data_streamer = mock_streamer

                    # Second start with different symbols should update subscriptions
                    await manager.start_streaming(["SPY", "AAPL"])
                    await asyncio.sleep(0.1)

        await manager.stop_streaming()

    async def test_context_properties(self):
        """Test UserStreamContext properties."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        # Add some connections
        manager.context.add_channel("channel_1")
        manager.context.add_channel("channel_2")

        assert manager.context.reference_count == 2
        assert manager.context.is_active
        assert len(manager.context.connected_channels) == 2

    async def test_stop_streaming_cleanup(self):
        """Test that stop_streaming properly cleans up resources."""
        user = await self.create_test_user()
        manager = UserStreamManager(user.id)

        with StreamingTestPatches():
            with patch("services.data_access.get_oauth_session") as mock_oauth:
                from unittest.mock import AsyncMock

                mock_oauth.return_value = self.create_mock_oauth_session()

                with patch("streaming.services.stream_manager.TradingAccount") as mock_ta:
                    mock_account = self.create_mock_trading_account(user)
                    mock_filter = AsyncMock()
                    mock_filter.afirst = AsyncMock(return_value=mock_account)
                    mock_ta.objects.filter.return_value = mock_filter

                    # Start streaming
                    await manager.start_streaming(["QQQ"])
                    await asyncio.sleep(0.1)

                    # Verify tasks might be running

                    # Stop streaming
                    await manager.stop_streaming()

                    # Verify cleanup
                    assert not manager.is_streaming
                    assert manager.context.data_streamer is None

    async def test_cache_integration(self):
        """Test cache operations for quotes and balance data."""
        user = await self.create_test_user()
        UserStreamManager(user.id)

        # Test quote caching
        quote_data = self.create_test_quote_data("QQQ", 450.75)
        cache_key = CacheManager.quote("QQQ")

        # Manually set cache data (simulates quote listener)
        cache.set(cache_key, quote_data, 30)

        # Verify cache retrieval
        cached_quote = cache.get(cache_key)
        assert cached_quote is not None
        assert cached_quote["symbol"] == "QQQ"
        assert cached_quote["last"] == 450.75

        # Test balance data
        balance_data = self.create_test_balance_data(15000.0, 7500.0)

        # This would be called by _handle_balance_update
        # (We're testing the data structure, not the full flow)
        assert balance_data["net_liquidating_value"] == 15000.0
        assert balance_data["buying_power"] == 7500.0


class GlobalStreamManagerTests(AsyncStreamingTestCase):
    """Tests for GlobalStreamManager functionality."""

    async def test_singleton_behavior(self):
        """Test that GlobalStreamManager is a singleton."""
        manager1 = GlobalStreamManager()
        manager2 = GlobalStreamManager()

        assert manager1 is manager2, "Should be the same instance"

    async def test_get_user_manager(self):
        """Test getting user managers."""
        user1 = await self.create_test_user(username="user1", email="user1@test.com")
        user2 = await self.create_test_user(username="user2", email="user2@test.com")

        global_manager = GlobalStreamManager()

        # Get managers for different users
        manager1 = await global_manager.get_user_manager(user1.id)
        manager2 = await global_manager.get_user_manager(user2.id)

        assert manager1 != manager2
        assert manager1.user_id == user1.id
        assert manager2.user_id == user2.id

        # Getting same user again returns same manager
        manager1_again = await global_manager.get_user_manager(user1.id)
        assert manager1 is manager1_again

    async def test_remove_user_manager(self):
        """Test removing user managers."""
        user = await self.create_test_user()
        global_manager = GlobalStreamManager()

        # Create user manager
        await global_manager.get_user_manager(user.id)
        assert user.id in global_manager._user_managers

        # Remove user manager
        await global_manager.remove_user_manager(user.id)
        assert user.id not in global_manager._user_managers

    async def test_activity_tracking(self):
        """Test activity tracking for user managers."""
        user1 = await self.create_test_user(username="user1", email="user1@test.com")
        user2 = await self.create_test_user(username="user2", email="user2@test.com")

        global_manager = GlobalStreamManager()

        # Create managers for both users
        manager1 = await global_manager.get_user_manager(user1.id)
        manager2 = await global_manager.get_user_manager(user2.id)

        # Add connections
        manager1.context.add_channel("channel_1")
        manager2.context.add_channel("channel_2")

        # Verify managers exist
        assert user1.id in global_manager._user_managers
        assert user2.id in global_manager._user_managers

        # Verify isolation
        assert manager1.context.reference_count == 1
        assert manager2.context.reference_count == 1

    async def test_concurrent_user_manager_creation(self):
        """Test thread-safe user manager creation."""
        user = await self.create_test_user()
        global_manager = GlobalStreamManager()

        async def get_manager():
            return await global_manager.get_user_manager(user.id)

        # Create multiple concurrent requests for same user manager
        managers = await asyncio.gather(get_manager(), get_manager(), get_manager())

        # All should return the same manager instance
        assert managers[0] is managers[1]
        assert managers[1] is managers[2]

    async def test_manager_isolation(self):
        """Test that user managers are isolated from each other."""
        user1 = await self.create_test_user(username="user1", email="user1@test.com")
        user2 = await self.create_test_user(username="user2", email="user2@test.com")

        global_manager = GlobalStreamManager()

        # Get managers
        manager1 = await global_manager.get_user_manager(user1.id)
        manager2 = await global_manager.get_user_manager(user2.id)

        # Add connections to user1
        manager1.context.add_channel("user1_channel_1")
        manager1.context.add_channel("user1_channel_2")

        # Add connection to user2
        manager2.context.add_channel("user2_channel_1")

        # Verify isolation
        assert manager1.context.reference_count == 2
        assert manager2.context.reference_count == 1

        # Remove user1 completely
        await global_manager.remove_user_manager(user1.id)

        # User2 should be unaffected
        assert manager2.context.reference_count == 1
        assert user2.id in global_manager._user_managers
        assert user1.id not in global_manager._user_managers
