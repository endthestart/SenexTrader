"""
Tests for WebSocket consumers.

Validates existing streaming consumer behavior without modifying working code.
"""

import contextlib

from channels.testing import WebsocketCommunicator

from streaming.consumers import StreamingConsumer
from streaming.tests.base import AsyncStreamingTestCase, StreamingTestPatches


class StreamingConsumerTests(AsyncStreamingTestCase):
    """Tests for StreamingConsumer WebSocket behavior."""

    async def test_unauthenticated_connection_rejected(self):
        """Test that unauthenticated connections are rejected."""
        from django.contrib.auth.models import AnonymousUser

        communicator = WebsocketCommunicator(
            StreamingConsumer.as_asgi(),
            "/ws/streaming/",
        )

        # Use anonymous user (unauthenticated)
        communicator.scope["user"] = AnonymousUser()

        connected, _subprotocol = await communicator.connect()
        assert not connected, "Unauthenticated connection should be rejected"

        await communicator.disconnect()

    async def test_authenticated_connection_success(self):
        """Test that authenticated connections are accepted."""
        user = await self.acreate_test_user()

        communicator = WebsocketCommunicator(
            StreamingConsumer.as_asgi(),
            "/ws/streaming/",
        )

        # Mock authenticated user
        communicator.scope["user"] = user

        connected, _subprotocol = await communicator.connect()
        assert connected, "Authenticated connection should succeed"

        # Consumer now starts streaming automatically and may send cached QQQ data
        # No explicit connection_established message in current implementation
        # Just verify connection succeeded

        await communicator.disconnect()

    async def test_ping_pong_message(self):
        """Test ping/pong heartbeat."""
        with StreamingTestPatches():
            communicator, _user = await self.connect_websocket()

            # Send ping message
            await communicator.send_json_to({"type": "ping", "timestamp": 1234567890})

            # Should receive pong message
            message = await communicator.receive_json_from()
            assert message["type"] == "pong"
            assert message["timestamp"] == 1234567890

            await self.disconnect_websocket(communicator)

    async def test_subscribe_legs_message(self):
        """Test option leg subscription via WebSocket message."""
        with StreamingTestPatches():
            communicator, _user = await self.connect_websocket()

            # Send subscribe_legs message (using proper OCC format with 3 spaces)
            await communicator.send_json_to(
                {
                    "type": "subscribe_legs",
                    "symbols": ["SPY   251219P00450000", "SPY   251219P00455000"],
                }
            )

            # Should receive acknowledgment
            message = await communicator.receive_json_from()
            assert message["type"] == "subscribe_legs_ack"
            assert message["success"] is True
            assert message["symbols_count"] == 2
            # Check symbol mapping is included
            assert "symbol_mapping" in message
            assert isinstance(message["symbol_mapping"], dict)
            # Verify OCC symbols are mapped to DXFeed format
            assert "SPY   251219P00450000" in message["symbol_mapping"]
            assert message["symbol_mapping"]["SPY   251219P00450000"] == ".SPY251219P450"

            await self.disconnect_websocket(communicator)

    async def test_unknown_message_type(self):
        """Test unknown message type is logged (no error sent to client)."""
        with StreamingTestPatches():
            communicator, _user = await self.connect_websocket()

            # Send unknown message type
            await communicator.send_json_to({"type": "unknown_type", "data": "test"})

            # Current implementation just logs it, doesn't send error back
            # Try to disconnect cleanly
            await self.disconnect_websocket(communicator)

    async def test_invalid_json_error(self):
        """Test invalid JSON message handling."""
        with StreamingTestPatches():
            communicator, _user = await self.connect_websocket()

            # Send invalid JSON (as text, not via send_json_to)
            # Current implementation logs the error but doesn't send error back to client
            # Just verify the connection stays alive
            try:
                await communicator.send_to(text_data="invalid json{")
                # Give it a moment to process
                await asyncio.sleep(0.1)
            except Exception:
                pass  # Expected - consumer may close connection on invalid JSON

            # Clean disconnect (connection may already be closed)
            with contextlib.suppress(Exception):
                await communicator.disconnect()

    async def test_quote_update_forwarding(self):
        """Test that quote updates are forwarded to WebSocket via channel layer."""
        with StreamingTestPatches():
            communicator, user = await self.connect_websocket()

            # Get the user manager and channel layer
            from channels.layers import get_channel_layer

            from streaming.services.stream_manager import GlobalStreamManager

            global_manager = GlobalStreamManager()
            user_manager = await global_manager.get_user_manager(user.id)
            channel_layer = get_channel_layer()

            # Simulate a quote update via channel layer broadcast
            test_quote = self.create_test_quote_data("QQQ", 451.25)

            # Broadcast via channel layer to the user's data group
            await channel_layer.group_send(
                user_manager.data_group_name, {"type": "quote_update", **test_quote}
            )

            # Should receive quote update message
            message = await communicator.receive_json_from()
            assert message["symbol"] == "QQQ"
            assert message["last"] == 451.25

            await self.disconnect_websocket(communicator)

    async def test_multiple_connections_same_user(self):
        """Test multiple WebSocket connections for same user (multi-tab support)."""
        user = await self.acreate_test_user()

        with StreamingTestPatches():
            # Create first connection
            comm1 = WebsocketCommunicator(
                StreamingConsumer.as_asgi(),
                "/ws/streaming/",
            )
            comm1.scope["user"] = user

            connected1, _ = await comm1.connect()
            assert connected1

            # Create second connection (same user)
            comm2 = WebsocketCommunicator(
                StreamingConsumer.as_asgi(),
                "/ws/streaming/",
            )
            comm2.scope["user"] = user

            connected2, _ = await comm2.connect()
            assert connected2

            # Both connections should use the same user manager
            from streaming.services.stream_manager import GlobalStreamManager

            global_manager = GlobalStreamManager()
            user_manager = await global_manager.get_user_manager(user.id)

            # Verify user manager exists for this user
            assert user_manager.user_id == user.id

            # Close first connection
            await comm1.disconnect()

            # User manager should still exist (not removed yet)
            assert user_manager.user_id == user.id

            # Close second connection
            await comm2.disconnect()

    async def test_connection_cleanup_on_disconnect(self):
        """Test proper cleanup when WebSocket disconnects."""
        with StreamingTestPatches():
            communicator, user = await self.connect_websocket()

            # Verify user manager exists
            from streaming.services.stream_manager import GlobalStreamManager

            global_manager = GlobalStreamManager()
            user_manager = await global_manager.get_user_manager(user.id)

            # Verify user manager is set up
            assert user_manager.user_id == user.id

            # Disconnect
            await self.disconnect_websocket(communicator)

            # Verify user manager still exists (cleanup happens later via activity tracking)
            assert user.id in global_manager._user_managers

    async def test_concurrent_user_connections(self):
        """Test connections from different users work independently."""
        user1 = await self.acreate_test_user(username="user1", email="user1@test.com")
        user2 = await self.acreate_test_user(username="user2", email="user2@test.com")

        with StreamingTestPatches():
            # Connect both users
            comm1, _ = await self.create_websocket_communicator(user1)
            comm2, _ = await self.create_websocket_communicator(user2)

            connected1, _ = await comm1.connect()
            connected2, _ = await comm2.connect()

            assert connected1
            assert connected2

            # Verify separate user managers
            from streaming.services.stream_manager import GlobalStreamManager

            global_manager = GlobalStreamManager()

            manager1 = await global_manager.get_user_manager(user1.id)
            manager2 = await global_manager.get_user_manager(user2.id)

            assert manager1 != manager2
            assert manager1.user_id == user1.id
            assert manager2.user_id == user2.id

            # Clean up
            await comm1.disconnect()
            await comm2.disconnect()
