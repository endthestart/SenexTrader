"""
Stream Manager - Coordinates market data streaming, cache priming, and order updates.

Architecture Overview:
    GlobalStreamManager (Singleton)
    ├── Manages all UserStreamManager instances
    ├── Handles user lifecycle (connect/disconnect)
    └── Provides centralized streaming coordination

    UserStreamManager (Per User)
    ├── DXLinkStreamer: Quote, Trade, Summary, and Greeks feeds
    ├── AlertStreamer: Order status/account updates fan-out
    ├── WebSocket broadcasting to connected clients
    └── StreamSubscriptionManager: First-data gating + lifecycle limits

Key Components:
- GlobalStreamManager: In-memory singleton that tracks managers, activity, and cleanup
- UserStreamManager: Owns DXLink/Alert streamers, cache wiring, broadcast helpers
- StreamSubscriptionManager: Normalizes symbols and exposes pending-data events
- AlertStreamer integration: Feeds OrderEventProcessor for actionable events

Event Flow:
1. User connects → GlobalStreamManager provisions a UserStreamManager
2. Strategy requests pricing → Stream manager subscribes and seeds pending events
3. Market data arrives → Cache updates + WebSocket broadcasts unblock waiters
4. Order events/fills → AlertStreamer relays to OrderEventProcessor for follow-up
5. User disconnects/inactive → Timed cleanup closes streamers and frees resources

Production facts:
- One DXLinkStreamer per user, shared across multiple web clients
- Redis/Enhanced cache stores quotes to reduce downstream load
- Subscription limit enforcement + stale data cleanup
- Inactivity and grace-period cleanup to prevent orphaned streamers
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Optional

from django.core.cache import cache

from channels.layers import get_channel_layer
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Greeks, Quote, Summary, Trade
from websockets.exceptions import ConnectionClosedOK

from accounts.models import TradingAccount
from services.core.cache import CacheManager
from services.core.logging import get_logger
from services.sdk.instruments import parse_occ_symbol
from streaming.constants import (
    AUTOMATION_READY_POLL_INTERVAL,
    AUTOMATION_TIMEOUT,
    CACHE_WAIT_TIMEOUT,
    CANCELLATION_TIMEOUT,
    CLEANUP_TIMEOUT_SECONDS,
    DXLINK_CONNECTION_TIMEOUT,
    GREEKS_CACHE_TTL,
    INACTIVITY_TIMEOUT_SECONDS,
    METRICS_TASK_TIMEOUT,
    METRICS_UPDATE_INTERVAL,
    QUOTE_CACHE_TTL,
    STREAMER_CLOSE_TIMEOUT,
    STREAMING_CLEANUP_GRACE_PERIOD,
    STREAMING_DATA_WAIT_TIMEOUT,
    STREAMING_TASK_TIMEOUT,
    SUMMARY_CACHE_TTL,
)
from streaming.models import UserStreamContext
from streaming.services.enhanced_cache import enhanced_cache
from trading.models import HistoricalGreeks

from .order_event_processor import OrderEventProcessor
from .position_metrics_calculator import PositionMetricsCalculator
from .quote_cache_service import (
    build_quote_payload,
    build_summary_payload,
    build_trade_payload,
)
from .stream_helpers import (
    extract_leg_symbols,
    format_timestamp,
    is_option_symbol,
    safe_float,
)
from .stream_subscription_manager import StreamSubscriptionManager

logger = get_logger(__name__)


class UserStreamManager:
    """Manages streaming data and subscriptions for a single user."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.context = UserStreamContext(user_id=self.user_id)
        self.is_streaming = False
        self.streaming_task: asyncio.Task | None = None
        self.metrics_task: asyncio.Task | None = None  # Unified: balance + Greeks + P&L
        self.lock = asyncio.Lock()
        self.channel_layer = get_channel_layer()
        self.data_group_name = f"stream_data_{self.user_id}"
        self.has_received_data = False
        self.last_quote_received = None
        # Connection state tracking for debugging and re-entrancy prevention
        self.connection_state = (
            "disconnected"  # disconnected, connecting, connected, error, stopped
        )

        # Initialize helpers
        self.order_processor = OrderEventProcessor(user_id, self._broadcast)
        self.metrics_calculator = PositionMetricsCalculator(user_id)
        self.subscription_manager = StreamSubscriptionManager(user_id)
        self._greeks_persist_semaphore = asyncio.Semaphore(25)

    def _reset_data_flags(self) -> None:
        """Clear cached streaming state so readiness reflects fresh data."""
        self.has_received_data = False
        self.last_quote_received = None

    async def start_streaming(
        self, symbols: list[str], subscribe_to_account: bool = False, subscribe_to_pnl: bool = False
    ):
        """Ensures the streaming process is running for the user - now idempotent."""
        logger.info(
            f"User {self.user_id}: start_streaming called, "
            f"state={self.connection_state}, is_streaming={self.is_streaming}"
        )
        async with self.lock:
            # CRITICAL FIX: Check both streaming AND connecting states
            if self.is_streaming or self.connection_state == "connecting":
                logger.info(
                    f"User {self.user_id}: Stream already active or connecting "
                    f"(state={self.connection_state}), skipping duplicate start"
                )
                if self.is_streaming:
                    await self.subscribe_to_new_symbols(symbols)
                return

            # Set connecting state BEFORE creating task to prevent re-entrancy
            self.connection_state = "connecting"
            logger.info(
                f"User {self.user_id}: Starting streaming service (entering connecting state)"
            )
            self._reset_data_flags()

            from django.contrib.auth import get_user_model

            User = get_user_model()
            try:
                user = await User.objects.aget(id=self.user_id)
                primary_account = await TradingAccount.objects.filter(
                    user=user, is_primary=True
                ).afirst()
                if not primary_account:
                    logger.warning(f"User {self.user_id}: No primary account, cannot start stream.")
                    self.connection_state = "disconnected"
                    return

                # Get TastyTrade session
                from services.core.data_access import get_oauth_session

                session = await get_oauth_session(user)
                if not session:
                    logger.error(f"User {self.user_id}: Could not get session, aborting stream.")
                    self.connection_state = "disconnected"
                    return

                self.context.oauth_session = session

                # Create streaming task
                self.streaming_task = asyncio.create_task(
                    self._run_streaming(session, symbols, subscribe_to_account, subscribe_to_pnl)
                )

                # Start order monitoring for pending trades
                await self.start_order_monitoring()

            except Exception as e:
                logger.error(
                    f"User {self.user_id}: Error during stream startup: {e}", exc_info=True
                )
                self.is_streaming = False
                self.connection_state = "disconnected"

    async def stop_streaming(self):
        """Stops the streaming service for the user."""
        logger.info(
            f"User {self.user_id}: stop_streaming called, state={self.connection_state}"
        )
        streaming_task = None
        metrics_task = None
        data_streamer = None
        account_streamer = None

        async with self.lock:
            # Early exit if nothing to stop
            if self.connection_state == "disconnected" and not self.streaming_task:
                logger.info(f"User {self.user_id}: Nothing to stop, early exit")
                return

            logger.info(f"User {self.user_id}: Proceeding with stop, collecting tasks")

            # Mark as disconnected first
            self.is_streaming = False
            self.connection_state = "disconnected"
            self._reset_data_flags()

            # Collect all resources to clean
            streaming_task = self.streaming_task
            self.streaming_task = None
            metrics_task = self.metrics_task
            self.metrics_task = None
            data_streamer = self.context.data_streamer
            self.context.data_streamer = None
            account_streamer = self.context.account_streamer
            self.context.account_streamer = None

            # Stop order monitoring
            await self.stop_order_monitoring()

        async def _close_streamer(streamer, name: str, timeout: float = STREAMER_CLOSE_TIMEOUT):
            if not streamer:
                return
            try:
                logger.debug(f"User {self.user_id}: Closing {name}...")
                # Shield critical cleanup to prevent interruption during cleanup
                await asyncio.wait_for(asyncio.shield(streamer.close()), timeout=timeout)
            except TimeoutError:
                logger.warning(f"User {self.user_id}: {name} close timed out")
            except Exception as exc:
                logger.error(f"User {self.user_id}: Error closing {name}: {exc}")

        # Close streamers first - this signals listeners to exit naturally
        await _close_streamer(account_streamer, "AlertStreamer")
        await _close_streamer(data_streamer, "DXLinkStreamer")

        async def _await_task(
            task: asyncio.Task | None, name: str, timeout: float = STREAMING_TASK_TIMEOUT
        ):
            if not task or task.done():
                return
            try:
                logger.debug(f"User {self.user_id}: Waiting for {name} to finish...")
                await asyncio.wait_for(task, timeout=timeout)
            except TimeoutError:
                # CRITICAL FIX: Non-recursive cancellation for Python 3.13
                # Deep task nesting (streaming_task → gather → listeners) causes
                # RecursionError when cancel() propagates through 984+ nested tasks.
                logger.warning(
                    f"User {self.user_id}: {name} did not finish in time; "
                    f"attempting graceful cancellation"
                )
                # Cancel the task
                task.cancel()
                # Wait for cancellation to complete, but with short timeout
                # to avoid blocking indefinitely if recursion occurs
                try:
                    await asyncio.wait_for(task, timeout=CANCELLATION_TIMEOUT)
                except (TimeoutError, asyncio.CancelledError):
                    # Expected outcomes:
                    # - CancelledError: task handled cancellation correctly
                    # - TimeoutError: task didn't finish cancelling (non-fatal)
                    logger.debug(f"User {self.user_id}: {name} cancellation completed")
                except Exception as exc:
                    # Log but don't fail - task cleanup is best-effort
                    logger.debug(f"User {self.user_id}: {name} cancellation raised: {exc}")
            except asyncio.CancelledError:
                # If we're being cancelled, propagate it
                raise
            except Exception as exc:
                logger.error(f"User {self.user_id}: Error awaiting {name}: {exc}")

        await _await_task(metrics_task, "metrics task", timeout=METRICS_TASK_TIMEOUT)
        # Give streaming task extra time after closing streamers - listeners should exit naturally
        await _await_task(streaming_task, "streaming task", timeout=STREAMING_TASK_TIMEOUT)

        logger.info(f"User {self.user_id}: Streaming service stopped successfully")

    async def ensure_streaming_for_automation(self, symbols: list[str]) -> bool:
        """
        Ensure streaming is active for automated tasks.
        Matches UI readiness check: waits for both is_streaming AND has_received_data.

        This method:
        1. Starts streaming if not already active
        2. Waits for actual data to arrive (not just connection)
        3. Subscribes to required symbols
        4. Returns True when ready with data, False on failure

        Used by automated tasks to ensure data availability WITHOUT
        requiring active WebSocket connections.

        Returns:
            bool: True if streaming is ready with data, False if failed
        """
        # Check under lock, but start_streaming must run outside to avoid deadlock.
        should_start = False
        async with self.lock:
            if not self.is_streaming:
                should_start = True

        if should_start:
            logger.info(f"User {self.user_id}: Starting streamers for automated task")

            try:
                # Start streaming with AlertStreamer (will timeout internally after 60s)
                await asyncio.wait_for(
                    self.start_streaming(symbols, subscribe_to_account=True),
                    timeout=AUTOMATION_TIMEOUT,
                )  # Allows AlertStreamer connection + buffer

            except TimeoutError:
                logger.error(f"User {self.user_id}: Streaming startup timeout for automation")
                async with self.lock:
                    self.is_streaming = False
                return False
            except Exception as e:
                logger.error(f"User {self.user_id}: Failed to start streaming: {e}")
                async with self.lock:
                    self.is_streaming = False
                return False

        # NOW MATCH UI BEHAVIOR: Wait for actual data (not just connection)
        max_wait = STREAMING_DATA_WAIT_TIMEOUT
        for i in range(max_wait):
            # Check BOTH flags like UI does!
            if self.is_streaming and self.has_received_data:
                # Also verify we have quotes for requested symbols in cache
                from django.core.cache import cache

                from services.core.cache import CacheManager

                all_symbols_ready = True
                for symbol in symbols:
                    quote_key = CacheManager.quote(symbol)
                    if not cache.get(quote_key):
                        all_symbols_ready = False
                        break

                if all_symbols_ready:
                    logger.info(f"User {self.user_id}: Streaming ready with data after {i+1}s")
                    # Ensure all symbols are subscribed
                    await self.subscribe_to_new_symbols(symbols)
                    return True

            await asyncio.sleep(AUTOMATION_READY_POLL_INTERVAL)

        logger.warning(
            f"User {self.user_id}: Timeout waiting for streaming data after {max_wait}s"
        )
        return False

    async def ensure_subscriptions(
        self,
        symbols: list[str] | None = None,
        subscribe_to_account: bool = False,
        subscribe_to_pnl: bool = False,
    ):
        """
        Ensures the necessary subscriptions are active.
        """
        if symbols:
            await self.subscribe_to_new_symbols(symbols)

        if (subscribe_to_account or subscribe_to_pnl) and not self.metrics_task:
            # Start unified metrics update task (balance + Greeks + P&L)
            self.metrics_task = asyncio.create_task(self._start_position_metrics_updates())
            logger.info(f"User {self.user_id}: Started unified metrics update task")

    async def subscribe_to_new_symbols(self, symbols: list[str]):
        """Subscribes to a new list of symbols if the streamer is active."""
        await self.subscription_manager.subscribe_to_new_symbols(
            self.context.data_streamer, symbols, self.is_streaming
        )

    async def a_process_suggestion_request(self, context: dict):
        """
        Processes a suggestion request: subscribes to legs, waits for data,
        calculates suggestion, and sends result to the client.

        Supports multiple strategies via strategy dispatch pattern.
        """
        logger.info(f"User {self.user_id}: Suggestion request started - processing context")

        is_automated = context.get("is_automated", False)

        occ_bundle = context.get("occ_bundle")
        if not occ_bundle:
            logger.warning(f"User {self.user_id}: No occ_bundle in context")
            return None

        leg_symbols = extract_leg_symbols(occ_bundle)
        logger.info(
            f"User {self.user_id}: Extracted {len(leg_symbols)} leg symbols: {leg_symbols}"
        )

        await self.subscribe_to_new_symbols(leg_symbols)

        # Wait for cache to be populated
        cache_ready = await self._wait_for_cache(leg_symbols)
        if not cache_ready:
            logger.warning(
                f"User {self.user_id}: Timed out waiting for cache for symbols: {leg_symbols}"
            )
            if not is_automated:
                await self._broadcast(
                    "error",
                    {
                        "message": (
                            "Timeout waiting for option prices. This may be due to "
                            "market hours or low trading volume. Please try again."
                        ),
                        "error_type": "suggestion_timeout",
                        "symbols": leg_symbols,
                    },
                )
            return None

        # Get user and dispatch to correct strategy
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = await User.objects.aget(id=self.user_id)

        strategy_type = context.get("strategy", "senex_trident")

        # Dispatch to correct strategy using registry pattern
        # IMPORTANT: Runtime import used here to break circular dependency
        # between streaming and services modules. Do NOT move this import
        # to module level as it will create circular import issues.
        # ruff: noqa: PLC0415
        from services.strategies.factory import get_strategy

        try:
            strategy = get_strategy(strategy_type, user)
        except ValueError as e:
            logger.error(f"Strategy instantiation failed: {e}")
            if not is_automated:
                await self._broadcast(
                    "error",
                    {
                        "message": f"Unknown strategy: {strategy_type}",
                        "error_type": "unknown_strategy",
                    },
                )
            return None

        logger.info(f"User {self.user_id}: Using strategy: {strategy_type}")

        # Calculate suggestion with pricing
        suggestion = await strategy.a_calculate_suggestion_from_cached_data(context)

        if suggestion:
            # Check if this is an error response
            if isinstance(suggestion, dict) and suggestion.get("error"):
                logger.info(
                    f"User {self.user_id}: Strategy returned error: {suggestion.get('message')}"
                )

                # Only broadcast error to UI if NOT automated
                if not is_automated:
                    # Broadcast specific error based on error_type
                    if suggestion.get("error_type") == "risk_budget_exceeded":
                        await self._broadcast(
                            "error",
                            {
                                "message": suggestion.get("message", "Risk budget exceeded"),
                                "error_type": "risk_budget_exceeded",
                                "max_risk": suggestion.get("max_risk"),
                                "strategy": suggestion.get("strategy"),
                            },
                        )
                    else:
                        # Generic error broadcast
                        await self._broadcast(
                            "error",
                            {
                                "message": suggestion.get(
                                    "message", "Unable to generate suggestion"
                                ),
                                "error_type": suggestion.get("error_type", "generation_failed"),
                            },
                        )
                return None  # Return None for error cases

            logger.info(f"User {self.user_id}: Suggestion generated")

            # Only broadcast to UI if NOT automated (NEW)
            if not is_automated:
                # Serialize TradingSuggestion object to dict for WebSocket broadcast
                from services.api.serializers import TradingSuggestionSerializer

                # Handle both TradingSuggestion objects and dicts
                if isinstance(suggestion, dict):
                    suggestion_dict = suggestion
                else:
                    suggestion_dict = TradingSuggestionSerializer.serialize_for_channels(suggestion)

                await self._broadcast("suggestion_update", {"suggestion": suggestion_dict})
            else:
                logger.info(
                    f"User {self.user_id}: Skipping WebSocket broadcast for automated suggestion"
                )
        else:
            logger.warning(f"User {self.user_id}: Failed to generate suggestion from cached data.")

        # Return suggestion object for automated tasks (NEW)
        return suggestion

    def _to_streamer_symbol(self, symbol: str) -> str:
        """Convert OCC option symbol to streamer format if needed."""
        return self.subscription_manager.to_streamer_symbol(symbol)

    async def _wait_for_cache(self, symbols: list[str], timeout: int = CACHE_WAIT_TIMEOUT) -> bool:
        """
        Wait for symbols using event-driven pattern (no polling).

        Aligns with REALTIME_DATA_FLOW_PATTERN.md:
        - Real-Time Events: Immediate signaling on data receipt
        - WebSocket Over Polling: No polling intervals
        """
        from services.streaming.options_cache import OptionsCache

        OptionsCache()

        logger.info(f"User {self.user_id}: Waiting for cache data for {len(symbols)} symbols")

        # Convert OCC symbols to streamer format and identify pending
        # Also check if existing data is stale and needs refresh
        from datetime import UTC, datetime

        from django.utils import timezone as django_timezone

        from services.streaming.dataclasses import DEFAULT_MAX_AGE
        from services.streaming.options_cache import OptionsCache

        options_cache = OptionsCache()
        pending_events = []
        pending_symbol_names = []

        for symbol in symbols:
            # Convert to streamer format for event lookup
            streamer_symbol = self._to_streamer_symbol(symbol)

            # Check if we have existing data and if it's fresh
            quote_data = options_cache.get_quote_payload(symbol)
            needs_fresh_data = True

            if quote_data:
                timestamp = quote_data.get("updated_at") or quote_data.get("timestamp")
                if timestamp:
                    if isinstance(timestamp, str):
                        try:
                            data_time = datetime.fromisoformat(timestamp)
                        except ValueError:
                            data_time = None
                    else:
                        data_time = timestamp

                    if data_time:
                        if data_time.tzinfo is None:
                            data_time = data_time.replace(tzinfo=UTC)
                        age_seconds = (django_timezone.now() - data_time).total_seconds()
                        if age_seconds <= DEFAULT_MAX_AGE:
                            needs_fresh_data = False
                            logger.debug(
                                f"User {self.user_id}: Symbol {symbol} has fresh data "
                                f"(age={age_seconds:.1f}s)"
                            )

            if needs_fresh_data:
                event = self.subscription_manager.get_pending_event(streamer_symbol)
                if event:
                    pending_events.append(event)
                    pending_symbol_names.append(streamer_symbol)
                    logger.debug(
                        f"User {self.user_id}: Symbol {streamer_symbol} pending, will wait for data"
                    )
                else:
                    quote_data_recheck = options_cache.get_quote_payload(symbol)
                    if (
                        quote_data_recheck
                        and quote_data_recheck.get("bid")
                        and quote_data_recheck.get("ask")
                    ):
                        logger.debug(
                            f"User {self.user_id}: Symbol {symbol} data arrived "
                            f"(race condition avoided)"
                        )
                        needs_fresh_data = False
                    else:
                        event = asyncio.Event()
                        self.subscription_manager.pending_symbol_events[streamer_symbol] = event
                        pending_events.append(event)
                        pending_symbol_names.append(streamer_symbol)
                        logger.debug(
                            f"User {self.user_id}: Symbol {streamer_symbol} data missing, "
                            f"created new event"
                        )

        # Await events for symbols that need first data
        if pending_events:
            logger.info(
                f"User {self.user_id}: Awaiting first data for "
                f"{len(pending_events)} new symbols"
            )

            try:
                await asyncio.wait_for(
                    asyncio.gather(*[event.wait() for event in pending_events]),
                    timeout=timeout,
                )
                logger.info(
                    f"User {self.user_id}: All {len(pending_events)} symbols "
                    f"received first data"
                )
            except TimeoutError:
                logger.warning(
                    f"User {self.user_id}: Timeout waiting for symbols: "
                    f"{pending_symbol_names}"
                )
                return False
            finally:
                for symbol in pending_symbol_names:
                    self.subscription_manager.remove_pending_event(symbol)
        else:
            logger.info(
                f"User {self.user_id}: All symbols already have data "
                f"(no pending subscriptions)"
            )

        # Validate cache has valid bid/ask data AND that it's fresh
        # Use the same lookup logic as OptionsCache.get_quote_payload() which handles both formats
        from datetime import UTC, datetime

        from django.utils import timezone as django_timezone

        from services.streaming.dataclasses import DEFAULT_MAX_AGE
        from services.streaming.options_cache import OptionsCache

        options_cache = OptionsCache()
        validated_symbols = []
        invalid_symbols = []

        for symbol in symbols:
            # Use the same lookup logic that works for other strategies
            quote_data = options_cache.get_quote_payload(symbol)

            if quote_data:
                bid = quote_data.get("bid")
                ask = quote_data.get("ask")

                # Check if bid/ask exist
                if bid is not None and ask is not None:
                    # Check freshness - data must be within DEFAULT_MAX_AGE seconds
                    timestamp = quote_data.get("updated_at") or quote_data.get("timestamp")
                    if timestamp:
                        if isinstance(timestamp, str):
                            try:
                                data_time = datetime.fromisoformat(timestamp)
                            except ValueError:
                                data_time = django_timezone.now()
                        else:
                            data_time = timestamp

                        if data_time.tzinfo is None:
                            data_time = data_time.replace(tzinfo=UTC)

                        age_seconds = (django_timezone.now() - data_time).total_seconds()
                        if age_seconds <= DEFAULT_MAX_AGE:
                            validated_symbols.append(symbol)
                        else:
                            logger.debug(
                                f"User {self.user_id}: Cache data for {symbol} is stale "
                                f"(age={age_seconds:.1f}s, max={DEFAULT_MAX_AGE}s)"
                            )
                            invalid_symbols.append(symbol)
                    else:
                        # No timestamp - assume stale and wait for fresh data
                        logger.debug(
                            f"User {self.user_id}: Cache data for {symbol} has no timestamp"
                        )
                        invalid_symbols.append(symbol)
                else:
                    # Data exists but bid/ask are None - log for debugging
                    logger.debug(
                        f"User {self.user_id}: Cache has data for {symbol} but bid={bid}, ask={ask}"
                    )
                    invalid_symbols.append(symbol)
            else:
                invalid_symbols.append(symbol)

        if invalid_symbols:
            logger.warning(
                f"User {self.user_id}: {len(invalid_symbols)} symbols "
                f"missing valid fresh bid/ask: {invalid_symbols}"
            )
            return False

        logger.info(
            f"User {self.user_id}: All {len(symbols)} symbols validated with fresh bid/ask"
        )
        return True

    async def _run_streaming(
        self,
        session,
        symbols: list[str],
        subscribe_to_account: bool = False,
        subscribe_to_pnl: bool = False,
    ):
        """The main streaming loop, using the mandatory async context manager."""
        try:
            self.connection_state = "connecting"
            logger.info(f"User {self.user_id}: Attempting DXLink connection...")

            # Initialize AlertStreamer for account events if requested
            alert_streamer = None
            if subscribe_to_account:
                try:
                    from tastytrade import Account, AlertStreamer

                    # MUST await AlertStreamer to establish websocket connection
                    alert_streamer = await AlertStreamer(session)
                    self.context.account_streamer = alert_streamer

                    # Subscribe to account events for order updates
                    accounts = await Account.a_get(session)
                    await alert_streamer.subscribe_accounts(accounts)

                    logger.info(f"User {self.user_id}: AlertStreamer connected for order updates")
                except Exception as e:
                    logger.error(f"User {self.user_id}: Failed to initialize AlertStreamer: {e}")
                    alert_streamer = None

            # Add timeout wrapper for connection establishment
            if session and hasattr(session, "session_token"):
                token_suffix = session.session_token[-8:]
                logger.info(
                    f"User {self.user_id}: Attempting to connect with "
                    f"session token ending in '...{token_suffix}'"
                )
            else:
                logger.warning(
                    f"User {self.user_id}: No session or session token found before connecting."
                )

            try:
                async with DXLinkStreamer(session) as streamer:
                    # Only timeout the connection and initial setup phase
                    try:
                        async with asyncio.timeout(DXLINK_CONNECTION_TIMEOUT):
                            self.context.data_streamer = streamer
                            self.is_streaming = True
                            self.connection_state = "connected"
                            logger.info(
                                f"User {self.user_id}: DXLinkStreamer connected "
                                f"successfully. Starting listeners."
                            )

                            logger.debug(
                                f"User {self.user_id}: About to subscribe to symbols: {symbols}, "
                                f"is_streaming={self.is_streaming}, "
                                f"streamer={self.context.data_streamer is not None}"
                            )
                            await self.subscribe_to_new_symbols(symbols)
                            logger.debug(
                                f"User {self.user_id}: Finished subscribe_to_new_symbols call"
                            )

                            if subscribe_to_account or subscribe_to_pnl:
                                await self.ensure_subscriptions(
                                    subscribe_to_account=subscribe_to_account,
                                    subscribe_to_pnl=subscribe_to_pnl,
                                )

                            logger.info(
                                f"User {self.user_id}: Connection setup complete, "
                                f"starting indefinite streaming..."
                            )

                    except TimeoutError:
                        self.connection_state = "error"
                        logger.error(
                            f"User {self.user_id}: DXLink connection timeout after "
                            f"{DXLINK_CONNECTION_TIMEOUT}s. This often indicates an invalid session token "
                            f"or a network issue."
                        )
                        self.is_streaming = False
                        raise  # Re-raise to exit the streamer context

                    # Listeners run indefinitely WITHOUT timeout
                    listeners = [
                        self._listen_quotes(),
                        self._listen_trades(),
                        self._listen_summary(),
                        self._listen_greeks(),
                    ]
                    if alert_streamer:
                        listeners.append(self._listen_orders())

                    logger.info(
                        f"User {self.user_id}: 🎧 Starting {len(listeners)} listeners "
                        f"for indefinite streaming"
                    )
                    results = await asyncio.gather(*listeners, return_exceptions=True)

                    first_exception: BaseException | None = None
                    for result in results:
                        if isinstance(result, BaseException):
                            if isinstance(result, asyncio.CancelledError):
                                logger.info(f"User {self.user_id}: Listener cancelled: {result}")
                                continue

                            logger.error(
                                f"User {self.user_id}: Listener error: {result}",
                                exc_info=(
                                    type(result),
                                    result,
                                    result.__traceback__,
                                ),
                            )
                            if not first_exception:
                                first_exception = result

                    if first_exception:
                        self.connection_state = "error"
                        raise first_exception

            except ConnectionClosedOK:
                # Normal websocket closure - user disconnected or streamer closed cleanly
                logger.info(f"User {self.user_id}: DXLink connection closed normally")
                self.connection_state = "disconnected"
                self.is_streaming = False
            except Exception as e:
                # Check if OAuth related error FIRST
                if await self._is_oauth_error(e):
                    await self._handle_oauth_error(e)
                    raise  # Re-raise to exit the streamer context
                self.connection_state = "error"
                logger.error(
                    f"User {self.user_id}: An unexpected error occurred during "
                    f"DXLink streaming: {e}",
                    exc_info=True,
                )
                self.is_streaming = False

        except ConnectionClosedOK:
            # Normal websocket closure at outer level
            logger.info(f"User {self.user_id}: DXLink connection closed normally")
        except Exception as e:
            # Already handled OAuth errors above, this catches other exceptions
            if not await self._is_oauth_error(e):
                # Normal error handling for non-OAuth errors
                self.connection_state = "error"
                logger.error(
                    f"User {self.user_id}: Streaming error in _run_streaming: {e}", exc_info=True
                )
        finally:
            # Clean up our connection state
            self.connection_state = "disconnected"
            self.is_streaming = False
            self._reset_data_flags()

            self.context.data_streamer = None
            if self.context.account_streamer:
                try:
                    await self.context.account_streamer.close()
                except Exception as e:
                    logger.error(f"User {self.user_id}: Error closing AlertStreamer: {e}")
                finally:
                    self.context.account_streamer = None
            logger.info(f"User {self.user_id}: Streaming stopped.")

    async def _listen_stream(self, event_type, handler, label: str):
        streamer = self.context.data_streamer
        if not streamer:
            return

        async for event in streamer.listen(event_type):
            try:
                await handler(event)
            except asyncio.CancelledError:
                # Propagate cancellation so stop_streaming() can unwind cleanly
                raise
            except Exception as e:
                logger.error(f"Error processing {label}: {e}", exc_info=True)

    async def _listen_quotes(self):
        await self._listen_stream(Quote, self._handle_quote_event, "quote")

    async def _listen_trades(self):
        await self._listen_stream(Trade, self._handle_trade_event, "trade")

    async def _listen_summary(self):
        await self._listen_stream(Summary, self._handle_summary_event, "summary")

    async def _listen_greeks(self):
        await self._listen_stream(Greeks, self._handle_greeks_event, "greeks")

    async def _handle_quote_event(self, quote):
        if not self.has_received_data:
            self.has_received_data = True
            from django.utils import timezone

            self.last_quote_received = timezone.now()

        key = CacheManager.quote(quote.event_symbol)
        existing_quote = cache.get(key) or {}
        payload = build_quote_payload(quote, existing_quote)

        await enhanced_cache.set(key, payload, ttl=QUOTE_CACHE_TTL)
        self.subscription_manager.signal_data_received(quote.event_symbol)

        if is_option_symbol(quote.event_symbol):
            bid_price = payload.get("bid")
            ask_price = payload.get("ask")
            logger.debug(
                f"User {self.user_id}: Option quote: {quote.event_symbol} "
                f"bid={bid_price}, ask={ask_price}"
            )

        await self._broadcast("quote_update", payload)

    async def _handle_trade_event(self, trade):
        quote_key = CacheManager.quote(trade.event_symbol)
        existing_quote = cache.get(quote_key) or {}
        payload = build_trade_payload(trade, existing_quote)

        await enhanced_cache.set(quote_key, payload, ttl=QUOTE_CACHE_TTL)
        self.subscription_manager.signal_data_received(trade.event_symbol)

    async def _handle_summary_event(self, summary):
        quote_key = CacheManager.quote(summary.event_symbol)
        existing_quote = cache.get(quote_key) or {}
        payload = build_summary_payload(summary, existing_quote)

        await enhanced_cache.set(quote_key, payload, ttl=SUMMARY_CACHE_TTL)
        await self._broadcast(
            "summary_update",
            {"symbol": summary.event_symbol, "prev_day_close": payload.get("previous_close")},
        )

    async def _handle_greeks_event(self, greeks):
        key = CacheManager.dxfeed_greeks(greeks.event_symbol)
        data = {
            "symbol": greeks.event_symbol,
            "theoretical_price": safe_float(greeks.price),
            "delta": safe_float(greeks.delta),
            "gamma": safe_float(greeks.gamma),
            "theta": safe_float(greeks.theta),
            "vega": safe_float(greeks.vega),
            "rho": safe_float(greeks.rho),
            "updated_at": format_timestamp(greeks.event_time),
        }

        await enhanced_cache.set(key, data, ttl=GREEKS_CACHE_TTL)
        logger.debug(
            f"User {self.user_id}: Greeks: {greeks.event_symbol} "
            f"delta={data['delta']}, gamma={data['gamma']}, theo={data['theoretical_price']}"
        )

        asyncio.create_task(self._persist_greeks_limited(greeks))

    async def _persist_greeks_limited(self, greeks_event):
        """Throttle persistence tasks so they cannot exhaust the event loop."""
        await self._greeks_persist_semaphore.acquire()
        try:
            await self._persist_greeks(greeks_event)
        finally:
            self._greeks_persist_semaphore.release()

    async def _persist_greeks(self, greeks_event):
        """Persist Greeks data to HistoricalGreeks model (fire-and-forget)."""
        try:
            # Parse OCC symbol to extract components
            # Greeks event_symbol is in streamer format, need to convert back to OCC
            from decimal import Decimal

            from services.sdk.symbol_conversion import streamer_to_occ_fixed

            # Convert streamer symbol back to OCC format for parsing
            # Uses workaround for SDK bug that produces 22-char symbols for certain strikes
            try:
                occ_symbol = streamer_to_occ_fixed(greeks_event.event_symbol)
            except Exception:
                # If conversion fails, event_symbol might already be OCC format
                occ_symbol = greeks_event.event_symbol

            # Parse the OCC symbol
            parsed = parse_occ_symbol(occ_symbol)

            # Convert timestamp (milliseconds since epoch) to datetime
            # Use current time if event_time is invalid (0 or None)
            from datetime import datetime

            if greeks_event.event_time and greeks_event.event_time > 0:
                timestamp = datetime.fromtimestamp(greeks_event.event_time / 1000, tz=UTC)
            else:
                timestamp = datetime.now(tz=UTC)

            # Round timestamp to 1-second resolution (deduplication strategy)
            timestamp = timestamp.replace(microsecond=0)

            # Persist using aupdate_or_create (upsert pattern)
            await HistoricalGreeks.objects.aupdate_or_create(
                option_symbol=occ_symbol,
                timestamp=timestamp,
                defaults={
                    "underlying_symbol": parsed["underlying"],
                    "delta": (
                        Decimal(str(greeks_event.delta)) if greeks_event.delta else Decimal("0")
                    ),
                    "gamma": (
                        Decimal(str(greeks_event.gamma)) if greeks_event.gamma else Decimal("0")
                    ),
                    "theta": (
                        Decimal(str(greeks_event.theta)) if greeks_event.theta else Decimal("0")
                    ),
                    "vega": Decimal(str(greeks_event.vega)) if greeks_event.vega else Decimal("0"),
                    "rho": (
                        Decimal(str(greeks_event.rho))
                        if hasattr(greeks_event, "rho") and greeks_event.rho
                        else None
                    ),
                    "implied_volatility": (
                        Decimal(str(greeks_event.volatility))
                        if greeks_event.volatility
                        else Decimal("0")
                    ),
                    "strike": parsed["strike"],
                    "expiration_date": parsed["expiration"],
                    "option_type": parsed["option_type"],
                },
            )
            logger.debug(f"User {self.user_id}: Persisted Greeks for {occ_symbol} at {timestamp}")
        except Exception as e:
            logger.error(
                f"User {self.user_id}: Error persisting Greeks for {greeks_event.event_symbol}: {e}"
            )

    async def _start_position_metrics_updates(self):
        """
        Unified metrics update service - broadcasts balance, Greeks, and P&L every 30 seconds.

        Follows site-wide data flow pattern:
        1. Read from Redis cache (populated by DXLinkStreamer/AlertStreamer)
        2. Calculate metrics using service layer (no duplication)
        3. Broadcast via WebSocket for real-time UI updates
        4. Database persistence handled by Celery task (trading.tasks.batch_sync_data_task)
        """
        logger.info(f"User {self.user_id}: Starting unified position metrics update service")

        # Update loop
        while self.is_streaming:
            try:
                # Delegate to metrics calculator helper
                update_data = await self.metrics_calculator.calculate_unified_metrics()

                if update_data:
                    await self._broadcast("position_metrics_update", update_data)
                    balance_info = ""
                    if "balance" in update_data:
                        balance_info = f", balance ${update_data['balance']['balance']:,.2f}"
                    pos_count = len(update_data.get("positions", []))
                    logger.debug(
                        f"User {self.user_id}: Broadcasted metrics - {pos_count} positions{balance_info}"
                    )

            except Exception as e:
                logger.error(
                    f"User {self.user_id}: Position metrics update service error: {e}",
                    exc_info=True,
                )

            # Update every interval (unified)
            await asyncio.sleep(METRICS_UPDATE_INTERVAL)

    async def _listen_orders(self):
        """Listen for order events from AlertStreamer."""
        alert_streamer = self.context.account_streamer
        if not alert_streamer:
            logger.warning(f"User {self.user_id}: No AlertStreamer available for order listening")
            return

        try:
            from tastytrade.order import PlacedOrder

            logger.info(f"User {self.user_id}: Starting AlertStreamer order listener")

            async for order in alert_streamer.listen(PlacedOrder):
                # Delegate to order processor helper
                await self.order_processor.handle_order_event(order)

        except Exception as e:
            logger.error(f"User {self.user_id}: Error in order listener: {e}", exc_info=True)

    async def _broadcast(self, message_type: str, data: dict):
        """Broadcasts a message to the user's data group."""
        await self.channel_layer.group_send(self.data_group_name, {"type": message_type, **data})

    async def start_order_monitoring(self):
        """Order monitoring is handled by AlertStreamer in real-time - no action needed."""
        logger.info(
            f"User {self.user_id}: Order monitoring via AlertStreamer (real-time updates active)"
        )

    async def stop_order_monitoring(self):
        """Order monitoring cleanup is handled by AlertStreamer shutdown."""
        logger.info(f"User {self.user_id}: Order monitoring will stop with AlertStreamer shutdown")

    async def _is_oauth_error(self, error) -> bool:
        """Detect OAuth/authentication failures."""
        error_str = str(error).lower()
        oauth_indicators = [
            "unauthorized",
            "401",
            "authentication failed",
            "token expired",
            "invalid token",
            "session expired",
            "oauth",
        ]
        return any(indicator in error_str for indicator in oauth_indicators)

    async def _handle_oauth_error(self, error):
        """Handle OAuth expiration by notifying clients."""
        logger.warning(f"User {self.user_id}: OAuth error detected, notifying client: {error}")

        # Broadcast OAuth error to client
        await self._broadcast(
            "oauth_error",
            {
                "type": "oauth_error",
                "error": "Authentication expired",
                "action_required": "reconnect_broker",
                "message": "Your broker connection has expired. Please reconnect in Settings.",
                "timestamp": time.time() * 1000,
            },
        )

        # Mark streaming as stopped
        self.is_streaming = False
        self.connection_state = "oauth_expired"

    async def notify_oauth_restored(self):
        """Notify clients that OAuth has been restored."""
        logger.info(f"User {self.user_id}: OAuth restored, notifying client")

        # Broadcast OAuth restored to client
        await self._broadcast(
            "oauth_restored",
            {
                "type": "oauth_restored",
                "message": "Broker connection restored successfully.",
                "timestamp": time.time() * 1000,
            },
        )

        # Reset connection state
        self.connection_state = "disconnected"  # Ready for fresh connection


class GlobalStreamManager:
    """
    Simple global manager for all user streams.
    In-memory singleton - no Redis coordination.
    """

    _instance: Optional["GlobalStreamManager"] = None
    _user_managers: dict[int, UserStreamManager] = {}
    _last_activity: dict[int, datetime] = {}
    _lock = asyncio.Lock()
    _cleanup_tasks: dict[int, asyncio.Task] = {}  # Track cleanup tasks for grace period

    # Activity tracking settings (from streaming.constants)
    INACTIVITY_TIMEOUT_SECONDS = INACTIVITY_TIMEOUT_SECONDS
    CLEANUP_TIMEOUT_SECONDS = CLEANUP_TIMEOUT_SECONDS
    CLEANUP_GRACE_PERIOD = STREAMING_CLEANUP_GRACE_PERIOD

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_user_manager(cls, user_id: int) -> UserStreamManager:
        """Get or create UserStreamManager for user."""
        async with cls._lock:
            # Cancel any pending cleanup if user is back
            if user_id in cls._cleanup_tasks:
                cls._cleanup_tasks[user_id].cancel()
                del cls._cleanup_tasks[user_id]
                logger.info(f"User {user_id}: Cancelled pending cleanup, " f"user reconnected")

            if user_id not in cls._user_managers:
                cls._user_managers[user_id] = UserStreamManager(user_id)
                logger.info(f"Created UserStreamManager for user {user_id}")

            # Mark as active whenever accessed
            cls._last_activity[user_id] = datetime.now(UTC)
            return cls._user_managers[user_id]

    @classmethod
    async def remove_user_manager(cls, user_id: int) -> None:
        """Remove UserStreamManager when no more connections."""
        async with cls._lock:
            if user_id in cls._user_managers:
                manager = cls._user_managers[user_id]
                await manager.stop_streaming()
                del cls._user_managers[user_id]
                cls._last_activity.pop(user_id, None)
                logger.info(f"Removed UserStreamManager for user {user_id}")

    @classmethod
    async def record_activity(cls, user_id: int) -> None:
        """Record user activity from heartbeat."""
        async with cls._lock:
            if user_id in cls._user_managers:
                cls._last_activity[user_id] = datetime.now(UTC)

    @classmethod
    async def schedule_cleanup(cls, user_id: int) -> None:
        """Schedule cleanup after grace period if no reconnections."""
        async with cls._lock:
            # Cancel any existing cleanup timer
            if user_id in cls._cleanup_tasks:
                cls._cleanup_tasks[user_id].cancel()

            # Schedule new cleanup
            cleanup_task = asyncio.create_task(cls._delayed_cleanup(user_id))
            cls._cleanup_tasks[user_id] = cleanup_task

            logger.info(f"User {user_id}: Cleanup scheduled in " f"{cls.CLEANUP_GRACE_PERIOD}s")

    @classmethod
    async def _delayed_cleanup(cls, user_id: int) -> None:
        """Clean up user manager after grace period."""
        try:
            # Wait for grace period
            await asyncio.sleep(cls.CLEANUP_GRACE_PERIOD)

            manager_to_cleanup: UserStreamManager | None = None

            async with cls._lock:
                manager = cls._user_managers.get(user_id)
                if not manager:
                    cls._cleanup_tasks.pop(user_id, None)
                    return

                if manager.context.reference_count > 0:
                    logger.info(
                        f"User {user_id}: Cleanup cancelled, user reconnected (ref_count="
                        f"{manager.context.reference_count})"
                    )
                    cls._cleanup_tasks.pop(user_id, None)
                    return

                manager_to_cleanup = manager

            logger.info(f"User {user_id}: Performing cleanup after grace period")
            await manager_to_cleanup.stop_streaming()

            async with cls._lock:
                if cls._user_managers.get(user_id) is manager_to_cleanup:
                    del cls._user_managers[user_id]
                cls._cleanup_tasks.pop(user_id, None)

        except asyncio.CancelledError:
            logger.info(f"User {user_id}: Cleanup cancelled")
        except Exception as e:
            logger.error(f"User {user_id}: Error during cleanup: {e}", exc_info=True)

    @classmethod
    def get_stats(cls) -> dict:
        """Get streaming statistics."""
        return {
            "active_users": len(cls._user_managers),
            "pending_cleanups": len(cls._cleanup_tasks),
            "managers": {
                user_id: {
                    "ref_count": manager.context.reference_count,
                    "channels": len(manager.context.connected_channels),
                    "is_streaming": manager.is_streaming,
                }
                for user_id, manager in cls._user_managers.items()
            },
        }

    @classmethod
    async def get_last_activity(cls, user_id: int) -> datetime | None:
        """Get the last activity timestamp for a user."""
        async with cls._lock:
            return cls._last_activity.get(user_id)

    @classmethod
    async def cleanup_inactive_managers(cls) -> None:
        """Remove streamers for inactive users."""
        async with cls._lock:
            current_time = datetime.now(UTC)
            users_to_remove = []

            for user_id in list(cls._user_managers.keys()):
                last_activity = cls._last_activity.get(user_id)
                if last_activity:
                    inactive_duration = (current_time - last_activity).total_seconds()
                    if inactive_duration > cls.CLEANUP_TIMEOUT_SECONDS:
                        users_to_remove.append(user_id)
                        logger.info(f"Scheduling removal of inactive streamer for user {user_id}")

            for user_id in users_to_remove:
                manager = cls._user_managers[user_id]
                await manager.stop_streaming()
                del cls._user_managers[user_id]
                cls._last_activity.pop(user_id, None)
                logger.info(f"Removed inactive streamer for user {user_id}")
