"""
Tastytrade-cli inspired streaming utilities for elegant event collection.

This module provides clean patterns for collecting streaming events,
based on the proven patterns from tastytrade-cli.
"""

import asyncio
from typing import Any, TypeVar

from services.core.logging import get_logger

logger = get_logger(__name__)

# Type variable for generic event types
U = TypeVar("U")


async def listen_events[U](dxfeeds: list[str], event_class: type[U], streamer) -> dict[str, U]:
    """
    Collect events for all symbols before returning.

    This elegant pattern from tastytrade-cli allows collecting
    initial events for all symbols efficiently.

    Args:
        dxfeeds: List of symbol strings to subscribe to
        event_class: The event type (Quote, Greeks, Summary, etc.)
        streamer: DXLinkStreamer instance

    Returns:
        Dict mapping symbol -> event object

    Example:
        quotes = await listen_events(["SPY", "QQQ"], Quote, streamer)
        greeks = await listen_events(option_symbols, Greeks, streamer)
    """
    event_dict = {}

    try:
        # Subscribe to the event type for all symbols
        await streamer.subscribe(event_class, dxfeeds)

        # Listen for events until we have all symbols
        async for event in streamer.listen(event_class):
            event_dict[event.event_symbol] = event

            # Stop when we have events for all symbols
            if len(event_dict) == len(dxfeeds):
                break

    except Exception as e:
        logger.error(f"Error in listen_events for {event_class.__name__}: {e}", exc_info=True)

    return event_dict


async def collect_multiple_event_types(
    dxfeeds: list[str], event_types: list[type], streamer
) -> dict[str, dict[str, Any]]:
    """
    Collect multiple event types concurrently for efficiency.

    Inspired by tastytrade-cli's concurrent event collection pattern.

    Args:
        dxfeeds: List of symbol strings
        event_types: List of event classes to collect
        streamer: DXLinkStreamer instance

    Returns:
        Dict[symbol] -> Dict[event_type_name] -> event_object

    Example:
        events = await collect_multiple_event_types(
            ["SPY", "QQQ"],
            [Quote, Greeks],
            streamer
        )
        spy_quote = events["SPY"]["Quote"]
        spy_greeks = events["SPY"]["Greeks"]
    """
    # Create tasks for each event type
    tasks = [
        asyncio.create_task(listen_events(dxfeeds, event_type, streamer))
        for event_type in event_types
    ]

    try:
        # Wait for all event types to complete
        results = await asyncio.gather(*tasks)

        # Organize results by symbol
        symbol_events = {}
        for symbol in dxfeeds:
            symbol_events[symbol] = {}

        for event_type, event_dict in zip(event_types, results, strict=False):
            event_type_name = event_type.__name__
            for symbol, event in event_dict.items():
                if symbol not in symbol_events:
                    symbol_events[symbol] = {}
                symbol_events[symbol][event_type_name] = event

        return symbol_events

    except Exception as e:
        logger.error(f"Error collecting multiple event types: {e}", exc_info=True)
        return {}


async def wait_for_initial_data(
    symbols: list[str], event_class: type, streamer, timeout: int = 10
) -> bool:
    """
    Wait for initial data to be available for all symbols.

    Args:
        symbols: List of symbols to wait for
        event_class: Event type to check
        streamer: DXLinkStreamer instance
        timeout: Maximum seconds to wait

    Returns:
        True if all symbols have data, False if timeout
    """
    try:
        # Use listen_events with timeout
        events = await asyncio.wait_for(
            listen_events(symbols, event_class, streamer), timeout=timeout
        )

        # Check if we got events for all symbols
        return len(events) == len(symbols)

    except TimeoutError:
        logger.warning(f"Timeout waiting for {event_class.__name__} data for {symbols}")
        return False
    except Exception as e:
        logger.error(f"Error waiting for initial data: {e}", exc_info=True)
        return False


class StreamingEventCollector:
    """
    Higher-level collector for managing streaming event collection.

    Provides a clean interface for common streaming patterns.
    """

    def __init__(self, streamer):
        self.streamer = streamer
        self._active_subscriptions = set()

    async def subscribe_and_collect(
        self, symbols: list[str], event_types: list[type], timeout: int = 10
    ) -> dict[str, dict[str, Any]]:
        """
        Subscribe to multiple event types and collect initial data.

        Args:
            symbols: Symbols to subscribe to
            event_types: Event types to collect
            timeout: Timeout for initial collection

        Returns:
            Organized event data by symbol and type
        """
        try:
            # Track subscriptions
            for event_type in event_types:
                self._active_subscriptions.add((tuple(symbols), event_type))

            # Collect events with timeout
            return await asyncio.wait_for(
                collect_multiple_event_types(symbols, event_types, self.streamer), timeout=timeout
            )

        except TimeoutError:
            logger.warning(f"Timeout collecting events for {symbols}")
            return {}
        except Exception as e:
            logger.error(f"Error in subscribe_and_collect: {e}", exc_info=True)
            return {}

    async def get_quotes_and_greeks(
        self, option_symbols: list[str], timeout: int = 10
    ) -> dict[str, dict[str, Any]]:
        """
        Convenience method for getting quotes and Greeks for options.

        Common pattern for option analysis.
        """
        from tastytrade.dxfeed import Greeks, Quote

        return await self.subscribe_and_collect(option_symbols, [Quote, Greeks], timeout)

    def get_active_subscriptions(self) -> set:
        """Get currently active subscriptions for debugging."""
        return self._active_subscriptions.copy()
