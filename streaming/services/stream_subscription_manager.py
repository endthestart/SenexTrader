"""
Stream Subscription Manager - Manages symbol subscriptions and lifecycle.

This helper encapsulates subscription state management and streamer interactions,
following the stateless helper pattern from Phase 5.1a (OrderEventProcessor).

Responsibility:
- Manage subscribed symbols set and timestamps
- Handle subscription cleanup and lifecycle
- Enforce subscription limits
- Coordinate with DXLinkStreamer for subscriptions

Design Principles (from phase-5-boundary-validation.md):
- Encapsulates subscription state
- No circular dependencies (receives streamer as parameter)
- Clear separation of concerns (state vs. streaming logic)
"""

import asyncio
from datetime import UTC, datetime

from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Greeks, Quote, Summary, Trade

from services.core.logging import get_logger
from streaming.constants import (
    CHANNEL_RACE_DELAY,
    GREEKS_REFRESH_INTERVAL,
    MAX_SUBSCRIPTIONS,
    QUOTE_REFRESH_INTERVAL,
    SUBSCRIPTION_CLEANUP_SECONDS,
    SUBSCRIPTION_DELAY,
    SUMMARY_REFRESH_INTERVAL,
    UNDERLYING_QUOTE_REFRESH_INTERVAL,
)

logger = get_logger(__name__)


class StreamSubscriptionManager:
    """Manages streaming subscriptions for symbols with lifecycle control."""

    MAX_SUBSCRIPTIONS = MAX_SUBSCRIPTIONS  # Prevent runaway growth

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.subscribed_symbols: set[str] = set()
        self.subscription_timestamps: dict[str, datetime] = {}
        self.pending_symbol_events: dict[str, asyncio.Event] = {}  # First data arrival tracking
        # OCC to streamer symbol mapping for option symbols
        self.occ_to_streamer: dict[str, str] = {}

    def cleanup_old_subscriptions(self) -> int:
        """
        Remove subscriptions older than 1 hour. Returns count removed.

        Returns:
            int: Number of subscriptions removed
        """
        if not self.subscription_timestamps:
            return 0

        current_time = datetime.now(UTC)
        expired = [
            symbol
            for symbol, ts in self.subscription_timestamps.items()
            if (current_time - ts).total_seconds() > SUBSCRIPTION_CLEANUP_SECONDS
        ]

        for symbol in expired:
            self.subscribed_symbols.discard(symbol)
            self.subscription_timestamps.pop(symbol, None)

        if expired:
            logger.info(f"User {self.user_id}: Cleaned up {len(expired)} expired subscriptions")

        return len(expired)

    def enforce_subscription_limits(self, new_symbols_count: int) -> None:
        """
        Enforce subscription limits by removing oldest if necessary.

        Args:
            new_symbols_count: Number of new symbols about to be added
        """
        current_count = len(self.subscribed_symbols)
        future_count = current_count + new_symbols_count

        if future_count <= self.MAX_SUBSCRIPTIONS:
            return

        # Need to make room - remove oldest subscriptions
        to_remove = future_count - self.MAX_SUBSCRIPTIONS
        oldest = sorted(self.subscription_timestamps.items(), key=lambda x: x[1])[:to_remove]

        for symbol, _ in oldest:
            self.subscribed_symbols.discard(symbol)
            self.subscription_timestamps.pop(symbol, None)

        logger.warning(
            f"User {self.user_id}: Subscription limit reached. "
            f"Removed {to_remove} oldest subscriptions. "
            f"Current: {len(self.subscribed_symbols)}/{self.MAX_SUBSCRIPTIONS}"
        )

    async def subscribe_to_new_symbols(
        self,
        streamer: DXLinkStreamer | None,
        symbols: list[str],
        is_streaming: bool,
    ) -> None:
        """
        Subscribe to a list of symbols if streamer is active.

        Args:
            streamer: DXLinkStreamer instance (or None if not active)
            symbols: List of symbols to subscribe to
            is_streaming: Whether streaming is currently active
        """
        logger.info(f"User {self.user_id}: 🔔 SUBSCRIBE REQUEST - symbols: {symbols}")
        logger.info(
            f"User {self.user_id}: 🔔 Current streaming status: {is_streaming}, "
            f"streamer exists: {streamer is not None}, streamer type: {type(streamer).__name__ if streamer else 'None'}"
        )

        if not is_streaming or not streamer:
            logger.warning(
                f"User {self.user_id}: ❌ Cannot subscribe, streamer not active "
                f"(streaming: {is_streaming}, streamer: {streamer is not None})"
            )
            return

        logger.info(f"User {self.user_id}: ✅ Proceeding with subscription (checks passed)")

        # Step 1: Cleanup old subscriptions
        self.cleanup_old_subscriptions()

        # Step 2: Convert symbols to streamer format for consistent keying
        # CRITICAL: Store everything keyed by streamer symbol to match what listeners receive
        streamer_symbols_map = {}  # streamer_symbol -> occ_symbol
        for symbol in symbols:
            streamer_symbol = self.to_streamer_symbol(symbol)
            streamer_symbols_map[streamer_symbol] = symbol

        # Step 3: Get new symbols (using streamer format for comparison)
        new_streamer_symbols = [
            s for s in streamer_symbols_map if s not in self.subscribed_symbols
        ]
        if not new_streamer_symbols:
            logger.info(f"User {self.user_id}: ✅ All symbols already subscribed")
            return

        self.enforce_subscription_limits(len(new_streamer_symbols))

        # Step 4: Subscribe to new symbols with timestamps and events
        # Use STREAMER symbol as key for all tracking (matches quote.event_symbol, trade.event_symbol)
        current_time = datetime.now(UTC)
        new_occ_symbols = []
        for streamer_symbol in new_streamer_symbols:
            occ_symbol = streamer_symbols_map[streamer_symbol]
            new_occ_symbols.append(occ_symbol)

            # Store using STREAMER symbol as key (matches what listeners receive from DXFeed)
            self.subscribed_symbols.add(streamer_symbol)
            self.subscription_timestamps[streamer_symbol] = current_time
            self.pending_symbol_events[streamer_symbol] = asyncio.Event()
            logger.debug(
                f"User {self.user_id}: 📍 Created pending event for {streamer_symbol} (OCC: {occ_symbol})"
            )

        logger.info(f"User {self.user_id}: 🔔 Subscribing to NEW symbols: {new_occ_symbols}")
        logger.info(
            f"User {self.user_id}: 🔔 Total subscriptions: "
            f"{len(self.subscribed_symbols)}/{self.MAX_SUBSCRIPTIONS}"
        )
        await self._subscribe_symbols_to_streamer(streamer, new_occ_symbols)

    async def _subscribe_symbols_to_streamer(
        self, streamer: DXLinkStreamer, symbols: list[str]
    ) -> None:
        """
        Subscribe symbols to DXLinkStreamer (Quote, Trade, Summary, Greeks).

        Args:
            streamer: DXLinkStreamer instance
            symbols: List of symbols to subscribe (OCC format)
        """
        if not symbols:
            return

        # Separate option symbols (contain spaces) from underlying symbols
        option_symbols = [s for s in symbols if " " in s]
        underlying_symbols = [s for s in symbols if " " not in s]

        # Subscribe to options with Greeks
        if option_symbols:
            await self._subscribe_option_symbols(streamer, option_symbols)

        # Subscribe to underlying symbols (SPY, QQQ, etc)
        if underlying_symbols:
            await self._subscribe_underlying_symbols(streamer, underlying_symbols)

        # Note: subscribed_symbols already updated in subscribe_to_new_symbols() with streamer format

    async def _subscribe_option_symbols(
        self, streamer: DXLinkStreamer, option_symbols: list[str]
    ) -> None:
        """
        Subscribe option symbols with Greeks to DXLinkStreamer.

        Args:
            streamer: DXLinkStreamer instance
            option_symbols: List of option symbols (OCC format with spaces)
        """
        logger.info(
            f"User {self.user_id}: 🎯 OPTION SYMBOLS DETECTED - "
            f"Converting OCC to streamer format"
        )

        # Convert OCC symbols to streamer symbols for DXFeed
        from tastytrade.instruments import Option

        streamer_symbols = []
        for occ_symbol in option_symbols:
            try:
                streamer_symbol = Option.occ_to_streamer_symbol(occ_symbol)
                streamer_symbols.append(streamer_symbol)
                self.occ_to_streamer[occ_symbol] = streamer_symbol
                logger.info(f"User {self.user_id}: ✅ Converted {occ_symbol} -> {streamer_symbol}")
            except Exception as e:
                logger.error(f"User {self.user_id}: ❌ Failed to convert symbol {occ_symbol}: {e}")
                # Fall back to original symbol if conversion fails
                streamer_symbols.append(occ_symbol)
                self.occ_to_streamer[occ_symbol] = occ_symbol
                logger.warning(
                    f"User {self.user_id}: ⚠️ Using original symbol as fallback: {occ_symbol}"
                )

        logger.info(
            f"User {self.user_id}: 🎯 About to subscribe to DXFeed with "
            f"streamer symbols: {streamer_symbols}"
        )

        # Subscribe with streamer symbols
        try:
            logger.info(
                f"User {self.user_id}: 🎯 DEBUG - Calling streamer.subscribe(Quote, {streamer_symbols}, refresh_interval={QUOTE_REFRESH_INTERVAL})"
            )
            await streamer.subscribe(
                Quote, streamer_symbols, refresh_interval=QUOTE_REFRESH_INTERVAL
            )
            logger.info(
                f"User {self.user_id}: ✅ Subscribed to Quote events for "
                f"{len(streamer_symbols)} symbols"
            )

            # Add small delay to prevent channel race condition
            await asyncio.sleep(SUBSCRIPTION_DELAY)

            await streamer.subscribe(
                Greeks, streamer_symbols, refresh_interval=GREEKS_REFRESH_INTERVAL
            )
            logger.info(
                f"User {self.user_id}: ✅ Subscribed to Greeks events for "
                f"{len(streamer_symbols)} symbols"
            )
        except Exception as e:
            logger.error(
                f"User {self.user_id}: ❌ Error subscribing to option Greeks: {e}",
                exc_info=True,
            )
            # Don't re-raise - continue with underlying symbols

        logger.info(
            f"User {self.user_id}: 🎉 SUBSCRIPTION COMPLETE - "
            f"Quote and Greeks for {len(streamer_symbols)} option symbols"
        )

    async def _subscribe_underlying_symbols(
        self, streamer: DXLinkStreamer, underlying_symbols: list[str]
    ) -> None:
        """
        Subscribe underlying symbols to DXLinkStreamer (Quote, Trade, Summary).

        Args:
            streamer: DXLinkStreamer instance
            underlying_symbols: List of underlying symbols (e.g. SPY, QQQ)
        """
        try:
            logger.info(
                f"User {self.user_id}: 🎯 DEBUG - Calling streamer.subscribe(Quote, {underlying_symbols}, refresh_interval={UNDERLYING_QUOTE_REFRESH_INTERVAL})"
            )
            await streamer.subscribe(
                Quote, underlying_symbols, refresh_interval=UNDERLYING_QUOTE_REFRESH_INTERVAL
            )
            await asyncio.sleep(CHANNEL_RACE_DELAY)  # Prevent channel race condition

            logger.info(
                f"User {self.user_id}: 🎯 DEBUG - Calling streamer.subscribe(Trade, {underlying_symbols})"
            )
            await streamer.subscribe(Trade, underlying_symbols)
            await asyncio.sleep(CHANNEL_RACE_DELAY)  # Prevent channel race condition

            logger.info(
                f"User {self.user_id}: 🎯 DEBUG - Calling streamer.subscribe(Summary, {underlying_symbols}, refresh_interval={SUMMARY_REFRESH_INTERVAL})"
            )
            await streamer.subscribe(
                Summary, underlying_symbols, refresh_interval=SUMMARY_REFRESH_INTERVAL
            )
            logger.info(
                f"User {self.user_id}: Subscribed to all events for "
                f"{len(underlying_symbols)} underlying symbols."
            )
        except Exception as e:
            # Handle connection closed errors gracefully
            error_str = str(e).lower()
            if "connectionclosed" in error_str or "websocket" in error_str:
                logger.warning(
                    f"User {self.user_id}: ⚠️ WebSocket connection closed during subscription: {e}. "
                    f"This is normal if the connection was closed by the client or server."
                )
            else:
                logger.error(
                    f"User {self.user_id}: ❌ Error subscribing to underlying symbols: {e}",
                    exc_info=True,
                )
            # Don't re-raise - connection state will be handled by stream manager

    def to_streamer_symbol(self, symbol: str) -> str:
        """
        Convert OCC option symbol to streamer format if needed.

        Args:
            symbol: OCC symbol (with spaces) or underlying symbol

        Returns:
            str: Streamer format symbol
        """
        if " " not in symbol:
            return symbol  # Not an option, return as-is

        # Check cache first
        if symbol in self.occ_to_streamer:
            return self.occ_to_streamer[symbol]

        try:
            from tastytrade.instruments import Option

            streamer_symbol = Option.occ_to_streamer_symbol(symbol)
            # Handle expired options (SDK returns empty string)
            if not streamer_symbol:
                logger.debug(
                    f"User {self.user_id}: Symbol {symbol} could not be converted (likely expired)"
                )
                self.occ_to_streamer[symbol] = symbol
                return symbol
            self.occ_to_streamer[symbol] = streamer_symbol
            logger.debug(f"User {self.user_id}: Converted {symbol} -> {streamer_symbol}")
            return streamer_symbol
        except Exception as e:
            logger.warning(f"User {self.user_id}: Failed to convert {symbol}: {e}")
            return symbol  # Fall back to original

    def get_symbol_mapping(self, symbols: list[str]) -> dict[str, str]:
        """
        Get mapping from OCC symbols to DXFeed streamer symbols.

        Args:
            symbols: List of OCC symbols

        Returns:
            dict: Mapping of OCC symbol -> DXFeed symbol
        """
        mapping = {}
        for symbol in symbols:
            streamer_symbol = self.to_streamer_symbol(symbol)
            mapping[symbol] = streamer_symbol
        return mapping

    def get_pending_event(self, symbol: str) -> asyncio.Event | None:
        """
        Get pending event for symbol (for first data arrival tracking).

        Args:
            symbol: Symbol to check

        Returns:
            asyncio.Event: Event to wait on, or None if not pending
        """
        return self.pending_symbol_events.get(symbol)

    def signal_data_received(self, symbol: str) -> None:
        """
        Signal that first data has been received for a symbol.

        Args:
            symbol: Symbol that received data
        """
        if symbol in self.pending_symbol_events:
            self.pending_symbol_events[symbol].set()
            logger.info(f"User {self.user_id}: ✅ First data received for {symbol}")
            self.pending_symbol_events.pop(symbol)

    def remove_pending_event(self, symbol: str) -> None:
        """
        Remove pending event for symbol after data received.

        Args:
            symbol: Symbol to cleanup
        """
        self.pending_symbol_events.pop(symbol, None)
