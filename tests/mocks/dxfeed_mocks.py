"""
Mock classes for DXFeed streaming components.

These mocks simulate the behavior of DXFeed streaming for testing purposes,
providing realistic market data without requiring actual connections.
"""

import asyncio
import contextlib
import random
import time
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock


class MockDXFeedEvent:
    """Base class for all DXFeed event mocks."""

    def __init__(self, event_symbol: str, event_time: int | None = None):
        self.event_symbol = event_symbol
        self.event_time = event_time or int(time.time() * 1000)  # milliseconds


class MockQuote(MockDXFeedEvent):
    """Mock DXFeed Quote event."""

    def __init__(
        self,
        event_symbol: str,
        bid_price: float | None = None,
        ask_price: float | None = None,
        last_price: float | None = None,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.last_price = last_price


class MockTrade(MockDXFeedEvent):
    """Mock DXFeed Trade event."""

    def __init__(
        self,
        event_symbol: str,
        price: float,
        size: int = 100,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.price = price
        self.size = size
        self.time = event_time or self.event_time


class MockGreeks(MockDXFeedEvent):
    """Mock DXFeed Greeks event."""

    def __init__(
        self,
        event_symbol: str,
        delta: float | None = None,
        gamma: float | None = None,
        theta: float | None = None,
        vega: float | None = None,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega


class MockTheoPrice(MockDXFeedEvent):
    """Mock DXFeed TheoPrice event."""

    def __init__(
        self,
        event_symbol: str,
        theoretical_price: float | None = None,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.theoretical_price = theoretical_price


class MockSummary(MockDXFeedEvent):
    """Mock DXFeed Summary event."""

    def __init__(
        self,
        event_symbol: str,
        volatility: float | None = None,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.volatility = volatility


class MockUnderlying(MockDXFeedEvent):
    """Mock DXFeed Underlying event."""

    def __init__(
        self,
        event_symbol: str,
        price: float | None = None,
        reference_price: float | None = None,
        event_time: int | None = None,
    ):
        super().__init__(event_symbol, event_time)
        self.price = price
        self.reference_price = reference_price


class MockMarketDataGenerator:
    """Generates realistic market data for testing."""

    def __init__(self):
        # Base prices for common symbols
        self.base_prices = {
            "SPY": 450.0,
            "AAPL": 175.0,
            "MSFT": 350.0,
            "TSLA": 200.0,
            "SPY 240119C00460000": 2.50,  # Example option
            "SPY 240119P00440000": 1.75,  # Example option
        }

        # Volatility for different symbols
        self.volatilities = {
            "SPY": 0.20,
            "AAPL": 0.35,
            "MSFT": 0.30,
            "TSLA": 0.60,
            "SPY 240119C00460000": 0.25,
            "SPY 240119P00440000": 0.25,
        }

        # Current prices (will be modified as market moves)
        self.current_prices = self.base_prices.copy()

    def get_realistic_price(self, symbol: str) -> float:
        """Generate a realistic price based on random walk."""
        if symbol not in self.current_prices:
            # For unknown symbols, create a reasonable base price
            if "C" in symbol or "P" in symbol:  # Options
                self.current_prices[symbol] = random.uniform(0.50, 10.0)
            else:  # Stocks
                self.current_prices[symbol] = random.uniform(50.0, 500.0)

        base_price = self.current_prices[symbol]
        volatility = self.volatilities.get(symbol, 0.30)

        # Random walk with drift
        change_percent = random.gauss(0, volatility / 100)  # Small random changes
        new_price = base_price * (1 + change_percent)

        # Ensure price doesn't go negative
        new_price = max(new_price, 0.01)

        self.current_prices[symbol] = new_price
        return round(new_price, 2)

    def get_bid_ask_spread(self, price: float, symbol: str) -> tuple[float, float]:
        """Generate realistic bid/ask spread."""
        if "C" in symbol or "P" in symbol:  # Options have wider spreads
            spread_percent = random.uniform(0.02, 0.10)  # 2-10% spread
        else:  # Stocks have tighter spreads
            spread_percent = random.uniform(0.001, 0.005)  # 0.1-0.5% spread

        spread = price * spread_percent
        bid = price - spread / 2
        ask = price + spread / 2

        return round(max(bid, 0.01), 2), round(ask, 2)

    def get_option_greeks(self, symbol: str) -> dict[str, float]:
        """Generate realistic option Greeks."""
        if "C" not in symbol and "P" not in symbol:
            return {}  # Not an option

        # Simple mock Greeks based on whether it's a call or put
        is_call = "C" in symbol

        return {
            "delta": (random.uniform(0.2, 0.8) if is_call else random.uniform(-0.8, -0.2)),
            "gamma": random.uniform(0.01, 0.1),
            "theta": random.uniform(-0.1, -0.01),
            "vega": random.uniform(0.05, 0.3),
        }


class MockDXLinkStreamer:
    """Mock DXFeed streamer that simulates real streaming behavior."""

    def __init__(self, session, reconnect_fn=None, disconnect_fn=None):
        self.session = session
        self.reconnect_fn = reconnect_fn
        self.disconnect_fn = disconnect_fn
        self.closed = False
        self._subscriptions: dict[type, set[str]] = {}
        self._listeners: dict[type, list[asyncio.Queue]] = {}
        self._streaming_tasks: set[asyncio.Task] = set()
        self._data_generator = MockMarketDataGenerator()
        self._running = False

    async def subscribe(self, event_type: type, symbols: list[str]) -> None:
        """Subscribe to events for specific symbols."""
        if self.closed:
            raise RuntimeError("Streamer is closed")

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = set()

        self._subscriptions[event_type].update(symbols)

        # If we have listeners for this event type, start generating data
        if event_type in self._listeners and not self._running:
            self._start_data_generation()

    async def unsubscribe(self, event_type: type, symbols: list[str]) -> None:
        """Unsubscribe from events for specific symbols."""
        if event_type in self._subscriptions:
            self._subscriptions[event_type].difference_update(symbols)

    async def listen(self, event_type: type) -> AsyncGenerator[Any, None]:
        """Listen for events of a specific type."""
        if self.closed:
            return

        # Create a queue for this listener
        queue = asyncio.Queue(maxsize=1000)

        if event_type not in self._listeners:
            self._listeners[event_type] = []

        self._listeners[event_type].append(queue)

        # Start generating data if we have subscriptions
        if self._subscriptions.get(event_type):
            self._start_data_generation()

        try:
            while not self.closed:
                try:
                    # Wait for data with timeout to allow checking closed status
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue  # Check if closed and continue listening
        finally:
            # Remove this listener
            if event_type in self._listeners:
                with contextlib.suppress(ValueError):
                    self._listeners[event_type].remove(queue)

    def _start_data_generation(self):
        """Start generating mock market data."""
        if self._running:
            return

        self._running = True

        # Create tasks for different types of events
        loop = asyncio.get_running_loop()

        for event_type in self._listeners:
            if self._subscriptions.get(event_type):
                task = loop.create_task(self._generate_events(event_type))
                self._streaming_tasks.add(task)
                task.add_done_callback(self._streaming_tasks.discard)

    async def _generate_events(self, event_type: type):
        """Generate mock events for a specific type."""
        while not self.closed and event_type in self._subscriptions:
            symbols = list(self._subscriptions[event_type])
            if not symbols:
                await asyncio.sleep(0.1)
                continue

            # Generate events for random symbols
            for symbol in random.sample(symbols, min(len(symbols), 3)):
                await self._generate_single_event(event_type, symbol)

            # Wait before next batch (simulate realistic update frequency)
            if event_type == MockTrade:
                await asyncio.sleep(random.uniform(0.1, 0.5))  # Trades more frequent
            elif event_type == MockQuote:
                await asyncio.sleep(random.uniform(0.2, 1.0))  # Quotes frequent
            else:
                await asyncio.sleep(random.uniform(1.0, 3.0))  # Other events less frequent

    async def _generate_single_event(self, event_type: type, symbol: str):
        """Generate a single mock event."""
        if event_type not in self._listeners:
            return

        event = None

        if event_type == MockQuote:
            price = self._data_generator.get_realistic_price(symbol)
            bid, ask = self._data_generator.get_bid_ask_spread(price, symbol)
            event = MockQuote(symbol, bid_price=bid, ask_price=ask, last_price=price)

        elif event_type == MockTrade:
            price = self._data_generator.get_realistic_price(symbol)
            size = random.randint(1, 1000)
            event = MockTrade(symbol, price=price, size=size)

        elif event_type == MockGreeks:
            greeks = self._data_generator.get_option_greeks(symbol)
            if greeks:  # Only for options
                event = MockGreeks(symbol, **greeks)

        elif event_type == MockTheoPrice:
            price = self._data_generator.get_realistic_price(symbol)
            # Theoretical price is usually close to market price
            theo_price = price * random.uniform(0.98, 1.02)
            event = MockTheoPrice(symbol, theoretical_price=theo_price)

        elif event_type == MockSummary:
            volatility = random.uniform(0.1, 1.0)
            event = MockSummary(symbol, volatility=volatility)

        elif event_type == MockUnderlying:
            price = self._data_generator.get_realistic_price(symbol)
            ref_price = price * random.uniform(0.99, 1.01)
            event = MockUnderlying(symbol, price=price, reference_price=ref_price)

        if event:
            # Send to all listeners of this type
            for queue in self._listeners[event_type]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Skip if queue is full (simulate dropped events)
                    pass

    async def close(self) -> None:
        """Close the streamer."""
        self.closed = True
        self._running = False

        # Cancel all streaming tasks
        for task in list(self._streaming_tasks):
            task.cancel()

        # Wait for tasks to complete
        if self._streaming_tasks:
            await asyncio.gather(*self._streaming_tasks, return_exceptions=True)

        self._streaming_tasks.clear()
        self._subscriptions.clear()
        self._listeners.clear()


class MockTastyTradeSession:
    """Mock TastyTrade session for testing."""

    def __init__(self, account_number: str = "TEST123456"):
        self.account_number = account_number
        self.is_valid = True

    def __getattr__(self, name):
        # Return a mock for any attribute access
        return MagicMock()


# Factory functions for easy test setup
def create_mock_dxlink_streamer(session=None, symbols=None):
    """Create a mock DXLinkStreamer with optional pre-configured symbols."""
    if session is None:
        session = MockTastyTradeSession()

    streamer = MockDXLinkStreamer(session)

    if symbols:
        # Pre-subscribe to symbols for immediate testing
        loop = asyncio.get_event_loop()
        for event_type in [MockQuote, MockTrade, MockGreeks, MockTheoPrice]:
            loop.run_until_complete(streamer.subscribe(event_type, symbols))

    return streamer


def create_mock_session(account_number: str = "TEST123456"):
    """Create a mock TastyTrade session."""
    return MockTastyTradeSession(account_number)


# Patch utilities for test cases
class DXFeedMockPatcher:
    """Context manager for patching DXFeed imports in tests."""

    def __init__(self):
        self.patches = []

    def __enter__(self):
        # Patch the DXFeed imports
        from unittest.mock import MagicMock, patch

        # Create a mock module for tastytrade.dxfeed
        mock_dxfeed = MagicMock()
        mock_dxfeed.Quote = MockQuote
        mock_dxfeed.Trade = MockTrade
        mock_dxfeed.Greeks = MockGreeks
        mock_dxfeed.TheoPrice = MockTheoPrice
        mock_dxfeed.Summary = MockSummary
        mock_dxfeed.Underlying = MockUnderlying

        # Patch the DXLinkStreamer
        mock_tastytrade = MagicMock()
        mock_tastytrade.DXLinkStreamer = MockDXLinkStreamer
        mock_tastytrade.dxfeed = mock_dxfeed

        # Apply patches
        dxfeed_patch = patch.dict(
            "sys.modules",
            {"tastytrade.dxfeed": mock_dxfeed, "tastytrade": mock_tastytrade},
        )

        self.patches.append(dxfeed_patch)
        dxfeed_patch.start()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for patch in reversed(self.patches):
            patch.stop()


# Pytest fixtures (if using pytest)
try:
    import pytest

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
    def mock_market_data():
        """Pytest fixture providing realistic market data generator."""
        return MockMarketDataGenerator()

except ImportError:
    # pytest not available, skip fixtures
    pass
