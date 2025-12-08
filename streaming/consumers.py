"""
Production WebSocket consumer for real-time market data streaming.

- Direct WebSocket → UserStreamManager → DXLinkStreamer
- Supports all option symbols
- Comprehensive market data (quotes, Greeks, trades, etc.)
"""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from channels.auth import UserLazyObject
from channels.generic.websocket import AsyncWebsocketConsumer

from services.core.data_access import get_primary_tastytrade_account
from services.core.logging import get_logger
from streaming.services.stream_manager import GlobalStreamManager, UserStreamManager
from trading.models import Watchlist

logger = get_logger(__name__)


class _AuthenticatedUser(Protocol):
    id: Any
    is_authenticated: bool


class StreamingConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time market data streaming."""

    # Instance attributes set during connection lifecycle
    user: _AuthenticatedUser
    stream_manager: UserStreamManager
    control_group_name: str

    async def connect(self) -> None:
        scope_user: _AuthenticatedUser | AnonymousUser | UserLazyObject | None = self.scope.get(
            "user"
        )
        if scope_user is None:
            logger.warning("Scope missing user object, closing WebSocket connection")
            await self.close()
            return

        if not scope_user.is_authenticated:
            await self.close()
            return

        self.user = cast(_AuthenticatedUser, scope_user)
        account = await get_primary_tastytrade_account(self.user)
        if not account or not account.is_configured:
            logger.info(
                f"User {self.user.id}: No configured broker account, closing WebSocket connection"
            )
            await self.close()
            return

        self.stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)

        # Check ref_count BEFORE adding this channel to decide if we need to start streaming
        will_start_streaming = self.stream_manager.context.reference_count == 0

        # Only start streaming if this will be the first connection
        if will_start_streaming:
            logger.info(f"User {self.user.id}: First connection, starting streamers")
            watchlist_symbols = [
                item.symbol
                async for item in Watchlist.objects.filter(user=self.user).order_by(
                    "order", "symbol"
                )
            ]

            # Fallback to DEFAULT_WATCHLIST_SYMBOLS if watchlist is empty
            if not watchlist_symbols:
                # Extract symbols from (symbol, description) tuples
                default_list = getattr(settings, "DEFAULT_WATCHLIST_SYMBOLS", [])
                watchlist_symbols = [s[0] for s in default_list]
                logger.info(
                    f"User {self.user.id}: Empty watchlist, using default symbols: {watchlist_symbols}"
                )

            # Ensure the user's streaming process is running and subscribe to account balance and P&L updates.
            # Use user's watchlist symbols for personalized data availability
            await self.stream_manager.start_streaming(
                watchlist_symbols, subscribe_to_account=True, subscribe_to_pnl=True
            )

        # Join groups to receive data and control messages
        self.control_group_name = f"stream_control_{self.user.id}"
        await self.channel_layer.group_add(self.stream_manager.data_group_name, self.channel_name)
        await self.channel_layer.group_add(self.control_group_name, self.channel_name)

        await self.accept()

        # Register the connection after accept() succeeds to prevent zombie channels
        self.stream_manager.context.add_channel(self.channel_name)
        ref_count = self.stream_manager.context.reference_count

        logger.info(
            f"User {self.user.id}: WebSocket connected "
            f"({self.channel_name}), ref_count={ref_count}"
        )

    async def disconnect(self, close_code: int) -> None:
        # Handle case where connection was rejected before user was set
        if not hasattr(self, "user") or not self.user.is_authenticated:
            return

        if not hasattr(self, "stream_manager"):
            logger.warning(f"User {self.user.id}: Disconnected before stream_manager was set")
            return

        self.stream_manager.context.remove_channel(self.channel_name)
        ref_count = self.stream_manager.context.reference_count

        logger.info(
            f"User {self.user.id}: WebSocket disconnected "
            f"({self.channel_name}), ref_count={ref_count}"
        )

        # Leave groups
        await self.channel_layer.group_discard(
            self.stream_manager.data_group_name, self.channel_name
        )
        await self.channel_layer.group_discard(self.control_group_name, self.channel_name)

        # Schedule cleanup if this was the last connection
        if ref_count == 0:
            logger.info(f"User {self.user.id}: Last connection closed, " f"scheduling cleanup")
            await GlobalStreamManager.schedule_cleanup(self.user.id)

    async def receive(self, text_data: str) -> None:
        data: dict[str, Any] = json.loads(text_data)
        message_type: str | None = data.get("type")

        # Handle heartbeat ping-pong
        if message_type == "ping":
            await GlobalStreamManager.record_activity(self.user.id)

            await self.send(
                text_data=json.dumps({"type": "pong", "timestamp": data.get("timestamp")})
            )
            return

        # Handle subscribe_legs request from positions page
        if message_type == "subscribe_legs":
            symbols: list[str] = data.get("symbols", [])
            if symbols and self.stream_manager:
                logger.info(
                    f"User {self.user.id}: Received subscribe_legs request "
                    f"for {len(symbols)} symbols"
                )
                # Get symbol mapping from subscription manager
                symbol_mapping = self.stream_manager.subscription_manager.get_symbol_mapping(
                    symbols
                )
                await self.stream_manager.subscribe_to_new_symbols(symbols)
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "subscribe_legs_ack",
                            "success": True,
                            "symbols_count": len(symbols),
                            "symbol_mapping": symbol_mapping,  # OCC -> DXFeed mapping
                        }
                    )
                )
            return

        logger.debug(f"User {self.user.id}: Received unhandled message: {data}")

    # Handlers for messages from the channel layer, proxied to the client

    async def ensure_subscriptions(self, event: dict[str, Any]) -> None:
        """Handles the request to ensure specific subscriptions are active."""
        symbols: list[str] = event.get("symbols", [])
        subscribe_to_account: bool = event.get("account", False)

        if (symbols or subscribe_to_account) and hasattr(self, "stream_manager"):
            logger.info(f"Consumer received request to ensure subscriptions: {event}")
            await self.stream_manager.ensure_subscriptions(
                symbols=symbols, subscribe_to_account=subscribe_to_account
            )

    async def subscribe_legs(self, event: dict[str, Any]) -> None:
        """Handles the request to subscribe to new option leg symbols."""
        logger.info(f"Consumer received subscribe_legs event: {event}")
        symbols: list[str] | None = event.get("symbols")
        if symbols and hasattr(self, "stream_manager"):
            await self.stream_manager.subscribe_to_new_symbols(symbols)

    async def generate_suggestion(self, event: dict[str, Any]) -> None:
        """Handles the request to generate a trading suggestion."""
        logger.info(f"User {self.user.id}: Received generate_suggestion event")
        logger.debug(f"User {self.user.id}: Event keys: {list(event.keys())}")

        context: dict[str, Any] | None = event.get("context")
        if not context:
            logger.error(f"User {self.user.id}: No context in generate_suggestion event")
            return

        if not hasattr(self, "stream_manager"):
            logger.error(f"User {self.user.id}: No stream_manager available")
            return

        occ_bundle: dict[str, Any] = context.get("occ_bundle", {})
        legs: dict[str, Any] = occ_bundle.get("legs", {})
        leg_symbols: list[Any] = list(legs.values())
        logger.info(
            f"User {self.user.id}: Processing suggestion with "
            f"{len(legs)} option legs: {leg_symbols}"
        )

        await self.stream_manager.a_process_suggestion_request(context)

    async def suggestion_update(self, event: dict[str, Any]) -> None:
        """Forwards generated suggestion to the client."""
        await self.send(text_data=json.dumps(event))

    async def quote_update(self, event: dict[str, Any]) -> None:
        """Forwards quote updates to the client."""
        await self.send(text_data=json.dumps(event))

    async def summary_update(self, event: dict[str, Any]) -> None:
        """Forwards summary updates to the client."""
        await self.send(text_data=json.dumps(event))

    async def error(self, event: dict[str, Any]) -> None:
        """Forwards error messages to the client."""
        await self.send(text_data=json.dumps(event))

    async def oauth_error(self, event: dict[str, Any]) -> None:
        """Forward OAuth error to client."""
        logger.info(f"User {self.user.id}: Forwarding OAuth error event")
        await self.send(text_data=json.dumps(event))

    # Order status handlers for trading page
    async def order_status(self, event: dict[str, Any]) -> None:
        """Forwards order status updates to the client."""
        logger.debug(f"User {self.user.id}: Order status update: {event}")
        await self.send(text_data=json.dumps(event))

    async def order_fill(self, event: dict[str, Any]) -> None:
        """Forwards order fill notifications to the client."""
        logger.info(f"User {self.user.id}: Order filled: {event}")
        await self.send(text_data=json.dumps(event))

    async def profit_target_update(self, event: dict[str, Any]) -> None:
        """Forwards profit target status updates to the client."""
        logger.info(f"User {self.user.id}: Profit target update: {event}")
        await self.send(text_data=json.dumps(event))

    async def position_sync_complete(self, event: dict[str, Any]) -> None:
        """Forwards position sync completion to the client."""
        logger.info(f"User {self.user.id}: Position sync complete: {event}")
        await self.send(text_data=json.dumps(event))

    async def position_pnl_update(self, event: dict[str, Any]) -> None:
        """Forwards real-time position P&L updates to the client."""
        logger.debug(
            f"User {self.user.id}: Broadcasting P&L update for {len(event.get('positions', []))} positions"
        )
        await self.send(text_data=json.dumps(event))

    async def position_metrics_update(self, event: dict[str, Any]) -> None:
        """Forwards unified position metrics (Greeks + P&L + Balance) to the client."""
        position_count = len(event.get("positions", []))
        has_balance = "balance" in event
        logger.debug(
            f"User {self.user.id}: Broadcasting unified metrics - "
            f"{position_count} positions" + (", balance included" if has_balance else "")
        )
        await self.send(text_data=json.dumps(event))
