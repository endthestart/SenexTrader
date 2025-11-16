"""
Tests for order builder utility functions.

This module tests the centralized order leg building functionality for
opening and closing spread positions.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from tastytrade.order import InstrumentType, Leg, OrderAction

from services.orders.spec import OrderLeg
from services.orders.utils.order_builder_utils import (
    build_closing_spread_legs,
    build_opening_spread_legs,
    build_senex_trident_legs,
)


class TestBuildClosingSpreadLegs:
    """Test build_closing_spread_legs function."""

    def test_close_put_spread_basic(self):
        """Test closing a basic put spread."""
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "put_spread_1",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=1,
        )

        assert len(legs) == 2
        assert all(isinstance(leg, OrderLeg) for leg in legs)

        # First leg: Buy to close short put
        assert legs[0].action == "buy_to_close"
        assert legs[0].quantity == 1
        assert legs[0].instrument_type == "equity_option"
        assert "P00590000" in legs[0].symbol  # Strike 590 put

        # Second leg: Sell to close long put
        assert legs[1].action == "sell_to_close"
        assert legs[1].quantity == 1
        assert "P00585000" in legs[1].symbol  # Strike 585 put

    def test_close_put_spread_multiple_quantity(self):
        """Test closing multiple put spread contracts."""
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "put_spread_2",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=2,  # Close 2 contracts
        )

        assert len(legs) == 2
        assert legs[0].quantity == 2
        assert legs[1].quantity == 2

    def test_close_call_spread_basic(self):
        """Test closing a basic call spread."""
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "call_spread",
            {"short_call": Decimal("595"), "long_call": Decimal("600")},
            quantity=1,
        )

        assert len(legs) == 2

        # First leg: Buy to close short call
        assert legs[0].action == "buy_to_close"
        assert legs[0].quantity == 1
        assert "C00595000" in legs[0].symbol  # Strike 595 call

        # Second leg: Sell to close long call
        assert legs[1].action == "sell_to_close"
        assert legs[1].quantity == 1
        assert "C00600000" in legs[1].symbol  # Strike 600 call

    def test_close_spread_missing_strikes(self):
        """Test that missing strikes return empty list."""
        # Missing long_put
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "put_spread_1",
            {"short_put": Decimal("590")},  # No long_put
            quantity=1,
        )
        assert legs == []

        # Missing short_call
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "call_spread",
            {"long_call": Decimal("600")},  # No short_call
            quantity=1,
        )
        assert legs == []

    def test_close_spread_fractional_strikes(self):
        """Test closing spreads with fractional strikes."""
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "put_spread_1",
            {"short_put": Decimal("590.50"), "long_put": Decimal("585.50")},
            quantity=1,
        )

        assert "P00590500" in legs[0].symbol
        assert "P00585500" in legs[1].symbol


class TestBuildOpeningSpreadLegs:
    """Test build_opening_spread_legs function."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        return AsyncMock()

    @pytest.fixture
    def mock_instruments(self):
        """Create mock instrument objects."""

        def create_mock_instrument(symbol):
            mock = MagicMock()
            mock.symbol = symbol
            return mock

        return create_mock_instrument

    @pytest.mark.asyncio
    async def test_open_put_spread_basic(self, mock_session, mock_instruments, monkeypatch):
        """Test opening a basic put spread."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),  # Short put
                mock_instruments("SPY   251107P00585000"),  # Long put
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "put_spread",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=1,
        )

        assert len(legs) == 2
        assert all(isinstance(leg, Leg) for leg in legs)

        # First leg: Sell to open short put
        assert legs[0].action == OrderAction.SELL_TO_OPEN
        assert legs[0].quantity == 1
        assert legs[0].instrument_type == InstrumentType.EQUITY_OPTION
        assert "P00590000" in legs[0].symbol

        # Second leg: Buy to open long put
        assert legs[1].action == OrderAction.BUY_TO_OPEN
        assert legs[1].quantity == 1
        assert "P00585000" in legs[1].symbol

    @pytest.mark.asyncio
    async def test_open_call_spread_basic(self, mock_session, mock_instruments, monkeypatch):
        """Test opening a basic call spread."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107C00595000"),  # Short call
                mock_instruments("SPY   251107C00600000"),  # Long call
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "call_spread",
            {"short_call": Decimal("595"), "long_call": Decimal("600")},
            quantity=1,
        )

        assert len(legs) == 2

        # First leg: Sell to open short call
        assert legs[0].action == OrderAction.SELL_TO_OPEN
        assert "C00595000" in legs[0].symbol

        # Second leg: Buy to open long call
        assert legs[1].action == OrderAction.BUY_TO_OPEN
        assert "C00600000" in legs[1].symbol

    @pytest.mark.asyncio
    async def test_open_spread_multiple_quantity(self, mock_session, mock_instruments, monkeypatch):
        """Test opening multiple spread contracts."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107P00585000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "put_spread",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=3,
        )

        assert legs[0].quantity == 3
        assert legs[1].quantity == 3

    @pytest.mark.asyncio
    async def test_open_iron_condor(self, mock_session, mock_instruments, monkeypatch):
        """Test opening an iron condor."""

        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00585000"),
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107C00595000"),
                mock_instruments("SPY   251107C00600000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "iron_condor",
            {
                "long_put": Decimal("585"),
                "short_put": Decimal("590"),
                "short_call": Decimal("595"),
                "long_call": Decimal("600"),
            },
            quantity=1,
        )

        assert len(legs) == 4
        assert legs[0].action == OrderAction.BUY_TO_OPEN
        assert legs[1].action == OrderAction.SELL_TO_OPEN
        assert legs[2].action == OrderAction.SELL_TO_OPEN
        assert legs[3].action == OrderAction.BUY_TO_OPEN

    @pytest.mark.asyncio
    async def test_open_iron_butterfly(self, mock_session, mock_instruments, monkeypatch):
        """Test opening an iron butterfly."""

        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00585000"),
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107C00590000"),
                mock_instruments("SPY   251107C00595000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "iron_butterfly",
            {
                "long_put": Decimal("585"),
                "short_put": Decimal("590"),
                "short_call": Decimal("590"),
                "long_call": Decimal("595"),
            },
            quantity=1,
        )

        assert len(legs) == 4

    @pytest.mark.asyncio
    async def test_open_straddle(self, mock_session, mock_instruments, monkeypatch):
        """Test opening a straddle."""

        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107C00590000"),
                mock_instruments("SPY   251107P00590000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "straddle",
            {"strike": Decimal("590")},
            quantity=1,
        )

        assert len(legs) == 2
        assert all(leg.action == OrderAction.BUY_TO_OPEN for leg in legs)

    @pytest.mark.asyncio
    async def test_open_strangle(self, mock_session, mock_instruments, monkeypatch):
        """Test opening a strangle."""

        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00585000"),
                mock_instruments("SPY   251107C00595000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "strangle",
            {"put_strike": Decimal("585"), "call_strike": Decimal("595")},
            quantity=1,
        )

        assert len(legs) == 2
        assert all(leg.action == OrderAction.BUY_TO_OPEN for leg in legs)

    @pytest.mark.asyncio
    async def test_open_call_backspread(self, mock_session, mock_instruments, monkeypatch):
        """Test opening a call backspread."""

        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107C00590000"),
                mock_instruments("SPY   251107C00595000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "call_backspread",
            {"short_call": Decimal("590"), "long_call": Decimal("595")},
            quantity=1,
        )

        assert len(legs) == 2
        assert legs[0].action == OrderAction.SELL_TO_OPEN
        assert legs[0].quantity == 1
        assert legs[1].action == OrderAction.BUY_TO_OPEN
        assert legs[1].quantity == 2


class TestBuildSenexTridentLegs:
    """Test build_senex_trident_legs function."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        return AsyncMock()

    @pytest.fixture
    def mock_instruments(self):
        """Create mock instrument objects."""

        def create_mock_instrument(symbol):
            mock = MagicMock()
            mock.symbol = symbol
            return mock

        return create_mock_instrument

    @pytest.mark.asyncio
    async def test_senex_trident_puts_only(self, mock_session, mock_instruments, monkeypatch):
        """Test Senex Trident with put spreads only (no call spread)."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107P00585000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_senex_trident_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            put_strikes={"short_put": Decimal("590"), "long_put": Decimal("585")},
            call_strikes=None,
            put_quantity=2,
            call_quantity=1,
        )

        # Should have 2 legs for put spread (short + long) x quantity 2
        assert len(legs) == 2
        assert all(isinstance(leg, Leg) for leg in legs)
        assert legs[0].quantity == 2  # Put spread quantity
        assert legs[1].quantity == 2

    @pytest.mark.asyncio
    async def test_senex_trident_full_iron_condor(
        self, mock_session, mock_instruments, monkeypatch
    ):
        """Test Senex Trident with both put and call spreads (Iron Condor)."""

        # Mock the get_option_instruments_bulk function - called twice (puts then calls)
        async def mock_get_instruments(session, specs):
            # Return instruments based on the specs passed (put or call)
            if len(specs) == 2 and specs[0].get("option_type") == "P":
                # Put spread
                return [
                    mock_instruments("SPY   251107P00590000"),  # Short put
                    mock_instruments("SPY   251107P00585000"),  # Long put
                ]
            if len(specs) == 2 and specs[0].get("option_type") == "C":
                # Call spread
                return [
                    mock_instruments("SPY   251107C00595000"),  # Short call
                    mock_instruments("SPY   251107C00600000"),  # Long call
                ]
            return []

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_senex_trident_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            put_strikes={"short_put": Decimal("590"), "long_put": Decimal("585")},
            call_strikes={"short_call": Decimal("595"), "long_call": Decimal("600")},
            put_quantity=2,
            call_quantity=1,
        )

        # Should have 4 legs: 2 for put spread + 2 for call spread
        assert len(legs) == 4

        # First 2 legs are put spread (quantity 2)
        assert legs[0].quantity == 2
        assert legs[1].quantity == 2
        assert "P" in legs[0].symbol
        assert "P" in legs[1].symbol

        # Last 2 legs are call spread (quantity 1)
        assert legs[2].quantity == 1
        assert legs[3].quantity == 1
        assert "C" in legs[2].symbol
        assert "C" in legs[3].symbol

    @pytest.mark.asyncio
    async def test_senex_trident_default_quantities(
        self, mock_session, mock_instruments, monkeypatch
    ):
        """Test Senex Trident with default quantities."""

        # Mock the get_option_instruments_bulk function - called twice (puts then calls)
        async def mock_get_instruments(session, specs):
            # Return instruments based on the specs passed (put or call)
            if len(specs) == 2 and specs[0].get("option_type") == "P":
                return [
                    mock_instruments("SPY   251107P00590000"),
                    mock_instruments("SPY   251107P00585000"),
                ]
            if len(specs) == 2 and specs[0].get("option_type") == "C":
                return [
                    mock_instruments("SPY   251107C00595000"),
                    mock_instruments("SPY   251107C00600000"),
                ]
            return []

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_senex_trident_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            put_strikes={"short_put": Decimal("590"), "long_put": Decimal("585")},
            call_strikes={"short_call": Decimal("595"), "long_call": Decimal("600")},
            # Default: put_quantity=2, call_quantity=1
        )

        assert len(legs) == 4
        # Default put quantity is 2
        assert legs[0].quantity == 2
        assert legs[1].quantity == 2
        # Default call quantity is 1
        assert legs[2].quantity == 1
        assert legs[3].quantity == 1

    @pytest.mark.asyncio
    async def test_senex_trident_action_types(self, mock_session, mock_instruments, monkeypatch):
        """Test that Senex Trident generates correct action types."""

        # Mock the get_option_instruments_bulk function - called twice (puts then calls)
        async def mock_get_instruments(session, specs):
            # Return instruments based on the specs passed (put or call)
            if len(specs) == 2 and specs[0].get("option_type") == "P":
                return [
                    mock_instruments("SPY   251107P00590000"),
                    mock_instruments("SPY   251107P00585000"),
                ]
            if len(specs) == 2 and specs[0].get("option_type") == "C":
                return [
                    mock_instruments("SPY   251107C00595000"),
                    mock_instruments("SPY   251107C00600000"),
                ]
            return []

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_senex_trident_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            put_strikes={"short_put": Decimal("590"), "long_put": Decimal("585")},
            call_strikes={"short_call": Decimal("595"), "long_call": Decimal("600")},
            put_quantity=2,
            call_quantity=1,
        )

        # Short legs should be sell_to_open
        short_legs = [leg for leg in legs if leg.action == OrderAction.SELL_TO_OPEN]
        assert len(short_legs) == 2  # Short put + short call

        # Long legs should be buy_to_open
        long_legs = [leg for leg in legs if leg.action == OrderAction.BUY_TO_OPEN]
        assert len(long_legs) == 2  # Long put + long call


class TestOrderLegFormat:
    """Test that order legs have correct format."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        return AsyncMock()

    @pytest.fixture
    def mock_instruments(self):
        """Create mock instrument objects."""

        def create_mock_instrument(symbol):
            mock = MagicMock()
            mock.symbol = symbol
            return mock

        return create_mock_instrument

    def test_closing_leg_format(self):
        """Test that closing legs return OrderLeg objects."""
        legs = build_closing_spread_legs(
            "SPY",
            date(2025, 11, 7),
            "put_spread_1",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=1,
        )

        for leg in legs:
            assert isinstance(leg, OrderLeg)
            assert hasattr(leg, "instrument_type")
            assert hasattr(leg, "symbol")
            assert hasattr(leg, "action")
            assert hasattr(leg, "quantity")

    @pytest.mark.asyncio
    async def test_opening_leg_format(self, mock_session, mock_instruments, monkeypatch):
        """Test that opening legs return SDK Leg objects."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107P00585000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "put_spread",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=1,
        )

        for leg in legs:
            assert isinstance(leg, Leg)
            assert hasattr(leg, "instrument_type")
            assert hasattr(leg, "symbol")
            assert hasattr(leg, "action")
            assert hasattr(leg, "quantity")

    @pytest.mark.asyncio
    async def test_senex_trident_leg_format(self, mock_session, mock_instruments, monkeypatch):
        """Test that Senex Trident legs return SDK Leg objects."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107P00585000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_senex_trident_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            put_strikes={"short_put": Decimal("590"), "long_put": Decimal("585")},
            call_strikes=None,
            put_quantity=2,
        )

        for leg in legs:
            assert isinstance(leg, Leg)
            assert hasattr(leg, "instrument_type")
            assert hasattr(leg, "symbol")
            assert hasattr(leg, "action")
            assert hasattr(leg, "quantity")


class TestIntegrationWithOCCSymbol:
    """Test integration with OCC symbol generation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        return AsyncMock()

    @pytest.fixture
    def mock_instruments(self):
        """Create mock instrument objects."""

        def create_mock_instrument(symbol):
            mock = MagicMock()
            mock.symbol = symbol
            return mock

        return create_mock_instrument

    @pytest.mark.asyncio
    async def test_generated_symbols_valid_format(
        self, mock_session, mock_instruments, monkeypatch
    ):
        """Test that generated OCC symbols follow correct format."""

        # Mock the get_option_instruments_bulk function
        async def mock_get_instruments(session, specs):
            return [
                mock_instruments("SPY   251107P00590000"),
                mock_instruments("SPY   251107P00585000"),
            ]

        monkeypatch.setattr(
            "services.sdk.instruments.get_option_instruments_bulk", mock_get_instruments
        )

        legs = await build_opening_spread_legs(
            mock_session,
            "SPY",
            date(2025, 11, 7),
            "put_spread",
            {"short_put": Decimal("590"), "long_put": Decimal("585")},
            quantity=1,
        )

        for leg in legs:
            symbol = leg.symbol
            # Should be 21 characters: 6 (ticker) + 6 (date) + 1 (type) + 8 (strike)
            assert len(symbol) == 21
            # Should contain the underlying
            assert "SPY" in symbol
            # Should contain the option type
            assert "P" in symbol
            # Should be properly formatted
            assert symbol[:6].strip() == "SPY"
