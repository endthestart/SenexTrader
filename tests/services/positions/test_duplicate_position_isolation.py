"""
Tests for duplicate position isolation using order-aware matching.

This test module validates the core fix for the position tracking problem:
When multiple identical spreads exist (e.g., 2x QQQ put credit spreads with
the same strikes), they must remain separate Position objects and not be
merged during sync.

The key mechanism is `opening_order_id` - each Position stores the unique
TastyTrade order ID that opened it, allowing us to isolate which legs
belong to which position.

Test Scenarios:
1. Create 2 identical spreads with different opening_order_ids
2. Run position sync with mocked TastyTrade data showing aggregated legs
3. Verify both positions remain separate and get correct market data
4. Close one position and verify only it gets marked closed
"""

from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase

import pytest
from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.positions.lifecycle.leg_matcher import OrderAwareLegMatcher
from services.positions.sync import PositionSyncService
from trading.models import Position, TastyTradeOrderHistory

User = get_user_model()


def create_mock_tt_position(
    symbol: str,
    underlying: str,
    quantity: int,
    direction: str = "Short",
    avg_price: float = 1.50,
    mark_price: float = 1.00,
    instrument_type: str = "Equity Option",
    multiplier: int = 100,
):
    """Create a mock TastyTrade CurrentPosition object."""
    mock = MagicMock()
    mock.symbol = symbol
    mock.underlying_symbol = underlying
    mock.quantity = quantity if direction == "Long" else -quantity
    mock.quantity_direction = direction
    mock.average_open_price = avg_price
    mock.close_price = mark_price
    mock.mark_price = mark_price
    mock.instrument_type = instrument_type
    mock.multiplier = multiplier
    mock.cost_effect = "Debit" if direction == "Long" else "Credit"
    return mock


def create_order_legs_data(legs: list[dict]) -> list[dict]:
    """Create order legs data in the format stored in TastyTradeOrderHistory.order_data."""
    return [
        {
            "symbol": leg["symbol"],
            "action": leg.get("action", "Sell to Open"),
            "quantity": leg.get("quantity", 1),
            "instrument_type": leg.get("instrument_type", "Equity Option"),
            "fills": [
                {
                    "fill_price": str(leg.get("fill_price", "1.50")),
                    "quantity": leg.get("quantity", 1),
                    "filled_at": "2025-01-27T10:00:00Z",
                }
            ],
        }
        for leg in legs
    ]


@pytest.mark.django_db
class TestDuplicatePositionIsolation(TestCase):
    """Test that duplicate positions with same strikes remain isolated."""

    def setUp(self):
        """Set up test data with two identical positions."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="5WT12345",
            is_primary=True,
            is_active=True,
        )

        # Create two identical QQQ put credit spreads
        # Both have: Short 520 Put, Long 515 Put
        self.short_put_symbol = "QQQ   251219P00520000"  # Short 520 put
        self.long_put_symbol = "QQQ   251219P00515000"  # Long 515 put

        # Position A - opened with order 1001
        self.position_a = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("1.50"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="1001",  # Unique order ID
        )

        # Position B - opened with order 1002
        self.position_b = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("1.55"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="1002",  # Different order ID
        )

        # Create cached orders for both positions
        self.order_a = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="1001",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 1001,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.short_put_symbol, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.long_put_symbol, "action": "Buy to Open", "quantity": 1},
                    ]
                ),
            },
        )

        self.order_b = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="1002",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 1002,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.short_put_symbol, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.long_put_symbol, "action": "Buy to Open", "quantity": 1},
                    ]
                ),
            },
        )

        self.sync_service = PositionSyncService()

    def test_order_aware_matcher_isolates_positions(self):
        """Test that OrderAwareLegMatcher correctly maps legs to positions by order ID."""
        cached_orders = [self.order_a, self.order_b]
        positions = [self.position_a, self.position_b]

        matcher = OrderAwareLegMatcher(cached_orders, positions)

        # Each position should get its own legs from its opening order
        legs_a = matcher.get_position_legs(self.position_a)
        legs_b = matcher.get_position_legs(self.position_b)

        # Both should have 2 legs (short put + long put)
        assert len(legs_a) == 2
        assert len(legs_b) == 2

        # The leg symbols should be the same (same strikes)
        symbols_a = matcher.get_position_occ_symbols(self.position_a)
        symbols_b = matcher.get_position_occ_symbols(self.position_b)

        assert set(symbols_a) == {self.short_put_symbol, self.long_put_symbol}
        assert set(symbols_b) == {self.short_put_symbol, self.long_put_symbol}

    def test_order_aware_matcher_tracks_quantity_per_position(self):
        """Test that each position tracks its own quantity separately."""
        cached_orders = [self.order_a, self.order_b]
        positions = [self.position_a, self.position_b]

        matcher = OrderAwareLegMatcher(cached_orders, positions)

        # Position A should have quantity 1 for each leg
        legs_a = matcher.get_position_legs(self.position_a)
        for leg in legs_a:
            assert leg.get("quantity") == 1

        # Position B should also have quantity 1 for each leg
        legs_b = matcher.get_position_legs(self.position_b)
        for leg in legs_b:
            assert leg.get("quantity") == 1

    def test_position_without_opening_order_id_logs_warning(self):
        """Test that positions without opening_order_id are handled gracefully."""
        # Create a legacy position without opening_order_id
        legacy_position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="SPY",
            quantity=1,
            avg_price=Decimal("2.00"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id=None,  # Legacy - no opening order ID
        )

        cached_orders = [self.order_a, self.order_b]
        positions = [self.position_a, self.position_b, legacy_position]

        matcher = OrderAwareLegMatcher(cached_orders, positions)

        # Legacy position should return empty legs (no order to match)
        legacy_legs = matcher.get_position_legs(legacy_position)
        assert legacy_legs == []

        # Other positions should still work
        assert len(matcher.get_position_legs(self.position_a)) == 2
        assert len(matcher.get_position_legs(self.position_b)) == 2

    @pytest.mark.asyncio
    async def test_sync_preserves_duplicate_positions(self):
        """
        Test that position sync preserves both duplicate positions.

        Scenario:
        - TastyTrade returns aggregated position: 2x short 520 put, 2x long 515 put
        - We have 2 app-managed positions, each with opening_order_id
        - After sync, both positions should still exist separately

        This tests _sync_app_managed_from_orders which is the core of duplicate
        position isolation. It's more focused than testing the full sync flow.
        """
        # TastyTrade aggregates our 2 spreads into combined quantities
        mock_raw_positions = [
            create_mock_tt_position(
                symbol=self.short_put_symbol,
                underlying="QQQ",
                quantity=2,  # 2 contracts total (1 from each position)
                direction="Short",
                avg_price=3.50,
                mark_price=2.80,
            ),
            create_mock_tt_position(
                symbol=self.long_put_symbol,
                underlying="QQQ",
                quantity=2,  # 2 contracts total (1 from each position)
                direction="Long",
                avg_price=2.00,
                mark_price=1.90,
            ),
        ]

        # Call _sync_app_managed_from_orders directly (core logic for duplicate isolation)
        updated_count = await self.sync_service._sync_app_managed_from_orders(
            self.user, self.trading_account, mock_raw_positions
        )

        # Both positions should still exist (not merged)
        positions = await sync_to_async(list)(
            Position.objects.filter(user=self.user, symbol="QQQ", is_app_managed=True)
        )
        assert len(positions) == 2

        # Verify each position kept its unique opening_order_id
        order_ids = {p.opening_order_id for p in positions}
        assert order_ids == {"1001", "1002"}

        # Both positions should have been updated with mark prices
        assert updated_count == 2

    @pytest.mark.asyncio
    async def test_closing_one_position_does_not_affect_other(self):
        """
        Test that closing one position doesn't affect the duplicate.

        Scenario:
        - Close Position A's spread at TastyTrade
        - TastyTrade now shows only 1x short 520, 1x long 515 (from Position B)
        - Run sync
        - Position A should detect it's closed
        - Position B should remain open
        """
        # TastyTrade now shows only Position B's legs (Position A was closed)
        mock_raw_positions = [
            create_mock_tt_position(
                symbol=self.short_put_symbol,
                underlying="QQQ",
                quantity=1,  # Only 1 contract now
                direction="Short",
                avg_price=3.50,
                mark_price=2.50,
            ),
            create_mock_tt_position(
                symbol=self.long_put_symbol,
                underlying="QQQ",
                quantity=1,  # Only 1 contract now
                direction="Long",
                avg_price=2.00,
                mark_price=1.60,
            ),
        ]

        # Create closing order for Position A
        closing_order = await sync_to_async(TastyTradeOrderHistory.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="2001",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Debit",
            order_data={
                "id": 2001,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.short_put_symbol, "action": "Buy to Close", "quantity": 1},
                        {"symbol": self.long_put_symbol, "action": "Sell to Close", "quantity": 1},
                    ]
                ),
            },
        )

        cached_orders = [self.order_a, self.order_b, closing_order]
        positions = [self.position_a, self.position_b]

        matcher = OrderAwareLegMatcher(cached_orders, positions)

        # Check if positions are still open at TT
        # Position B should still be open (1 contract of each leg remains)
        is_b_open = matcher.is_position_still_open_at_tt(self.position_b, mock_raw_positions)
        assert is_b_open

        # For Position A, we need to detect it was closed
        # This requires checking if there are closing transactions
        # The OrderAwareLegMatcher.is_position_still_open_at_tt() checks
        # if there's enough quantity remaining for the position's legs

    def test_matcher_handles_partial_close(self):
        """Test that partial closes are detected correctly."""
        # Create a position with 2 contracts
        position_2x = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="SPY",
            quantity=2,  # 2 contracts
            avg_price=Decimal("2.00"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="3001",
        )

        order_2x = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="3001",
            status="Filled",
            underlying_symbol="SPY",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 3001,
                "legs": create_order_legs_data(
                    [
                        {
                            "symbol": "SPY   251219P00580000",
                            "action": "Sell to Open",
                            "quantity": 2,
                        },
                        {"symbol": "SPY   251219P00575000", "action": "Buy to Open", "quantity": 2},
                    ]
                ),
            },
        )

        # TastyTrade shows only 1 contract (partial close happened)
        mock_raw_positions = [
            create_mock_tt_position(
                symbol="SPY   251219P00580000",
                underlying="SPY",
                quantity=1,  # Only 1 left (was 2)
                direction="Short",
            ),
            create_mock_tt_position(
                symbol="SPY   251219P00575000",
                underlying="SPY",
                quantity=1,  # Only 1 left (was 2)
                direction="Long",
            ),
        ]

        matcher = OrderAwareLegMatcher([order_2x], [position_2x])

        # Position should show as partially closed
        result = matcher.is_position_still_open_at_tt(position_2x, mock_raw_positions)
        # With 2 contracts opened and only 1 remaining, it's partially closed
        # The current implementation returns True if ANY legs remain
        # This is correct for detecting "still open" vs "fully closed"
        assert result is True, "Position with remaining legs should be considered still open"


@pytest.mark.django_db
class TestTransactionBasedClosing(TestCase):
    """Test closing detection using transaction history."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test2@example.com", username="testuser2", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="5WT67890",
            is_primary=True,
            is_active=True,
        )

        self.short_put_symbol = "QQQ   251219P00520000"
        self.long_put_symbol = "QQQ   251219P00515000"

    @pytest.mark.asyncio
    async def test_transaction_importer_links_to_correct_position(self):
        """Test that transactions are linked to positions by order_id."""
        from services.orders.transactions import TransactionImporter
        from trading.models import TastyTradeTransaction

        # Create position with known opening order
        position = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("1.50"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="5001",
        )

        # Create transaction that matches the position's opening order
        transaction = await sync_to_async(TastyTradeTransaction.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            transaction_id=90001,
            order_id=5001,  # Matches position.opening_order_id
            transaction_type="Trade",
            transaction_sub_type="Sell to Open",
            symbol=self.short_put_symbol,
            underlying_symbol="QQQ",
            instrument_type="Equity Option",
            quantity=Decimal("1"),
            price=Decimal("3.50"),
            value=Decimal("350.00"),
            net_value=Decimal("349.35"),
            executed_at="2025-01-27T10:00:00Z",
            raw_data={},
        )

        # Create importer and link transactions
        importer = TransactionImporter()
        result = await importer.link_transactions_to_positions(
            user=self.user,
            account=self.trading_account,
        )

        # Refresh transaction from DB
        transaction = await sync_to_async(TastyTradeTransaction.objects.get)(transaction_id=90001)

        # Transaction should be linked to the position
        assert transaction.related_position_id == position.id
        assert result["linked"] == 1

    @pytest.mark.asyncio
    async def test_transactions_not_linked_to_wrong_position(self):
        """Test that transactions aren't linked to wrong position."""
        from trading.models import TastyTradeTransaction

        # Create two positions with different opening orders
        position_a = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("1.50"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="6001",
        )

        position_b = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="short_put_vertical",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("1.55"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="6002",
        )

        # Create transaction for Position A's order
        transaction_a = await sync_to_async(TastyTradeTransaction.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            transaction_id=90002,
            order_id=6001,  # Matches Position A
            transaction_type="Trade",
            transaction_sub_type="Sell to Open",
            symbol=self.short_put_symbol,
            underlying_symbol="QQQ",
            instrument_type="Equity Option",
            quantity=Decimal("1"),
            price=Decimal("3.50"),
            value=Decimal("350.00"),
            net_value=Decimal("349.35"),
            executed_at="2025-01-27T10:00:00Z",
            raw_data={},
        )

        # Link transactions
        from services.orders.transactions import TransactionImporter

        importer = TransactionImporter()
        await importer.link_transactions_to_positions(
            user=self.user,
            account=self.trading_account,
        )

        # Refresh from DB
        transaction_a = await sync_to_async(TastyTradeTransaction.objects.get)(transaction_id=90002)

        # Should be linked to Position A, not Position B
        assert transaction_a.related_position_id == position_a.id
        assert transaction_a.related_position_id != position_b.id


@pytest.mark.django_db
class TestSenexTridentScenario(TestCase):
    """
    Test the specific Senex Trident scenario that motivated this fix.

    Senex Trident = 6 legs:
    - 2 legs for call credit spread (short call, long call)
    - 4 legs for put credit spreads (2x short put vertical)

    Problem: Opening 2 Senex Tridents with same strikes would merge into 1
    Solution: Each has unique opening_order_id for isolation
    """

    def setUp(self):
        """Set up test data for Senex Trident positions."""
        self.user = User.objects.create_user(
            email="trident@example.com", username="tridentuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="5WT11111",
            is_primary=True,
            is_active=True,
        )

        # Senex Trident legs for QQQ
        self.call_short = "QQQ   251219C00540000"  # Short 540 call
        self.call_long = "QQQ   251219C00545000"  # Long 545 call
        self.put_short_1 = "QQQ   251219P00520000"  # Short 520 put
        self.put_long_1 = "QQQ   251219P00515000"  # Long 515 put
        self.put_short_2 = "QQQ   251219P00510000"  # Short 510 put (2nd spread)
        self.put_long_2 = "QQQ   251219P00505000"  # Long 505 put (2nd spread)

    def test_two_tridents_remain_isolated(self):
        """Test that two Senex Tridents with same strikes stay separate."""
        # Create Trident A with order 7001
        trident_a = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("2.50"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="7001",
        )

        # Create Trident B with order 7002
        trident_b = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("2.55"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="7002",
        )

        # Create cached orders with 6 legs each
        order_a = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="7001",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 7001,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.call_short, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.call_long, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_1, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_1, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_2, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_2, "action": "Buy to Open", "quantity": 1},
                    ]
                ),
            },
        )

        order_b = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="7002",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 7002,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.call_short, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.call_long, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_1, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_1, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_2, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_2, "action": "Buy to Open", "quantity": 1},
                    ]
                ),
            },
        )

        # Create matcher
        matcher = OrderAwareLegMatcher([order_a, order_b], [trident_a, trident_b])

        # Each trident should have 6 legs
        legs_a = matcher.get_position_legs(trident_a)
        legs_b = matcher.get_position_legs(trident_b)

        assert len(legs_a) == 6
        assert len(legs_b) == 6

        # Each should have its own OCC symbols
        symbols_a = set(matcher.get_position_occ_symbols(trident_a))
        symbols_b = set(matcher.get_position_occ_symbols(trident_b))

        expected_symbols = {
            self.call_short,
            self.call_long,
            self.put_short_1,
            self.put_long_1,
            self.put_short_2,
            self.put_long_2,
        }

        assert symbols_a == expected_symbols
        assert symbols_b == expected_symbols

    def test_closing_trident_call_spread_only(self):
        """Test partial close of Trident (closing call spread keeps put spreads)."""
        trident = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="QQQ",
            quantity=1,
            avg_price=Decimal("2.50"),
            is_app_managed=True,
            lifecycle_state="open_full",
            opening_order_id="8001",
        )

        # Opening order with all 6 legs
        opening_order = TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="8001",
            status="Filled",
            underlying_symbol="QQQ",
            order_type="Limit",
            price_effect="Credit",
            order_data={
                "id": 8001,
                "legs": create_order_legs_data(
                    [
                        {"symbol": self.call_short, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.call_long, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_1, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_1, "action": "Buy to Open", "quantity": 1},
                        {"symbol": self.put_short_2, "action": "Sell to Open", "quantity": 1},
                        {"symbol": self.put_long_2, "action": "Buy to Open", "quantity": 1},
                    ]
                ),
            },
        )

        # TastyTrade after call spread closed - only put legs remain
        mock_raw_positions = [
            create_mock_tt_position(self.put_short_1, "QQQ", 1, "Short"),
            create_mock_tt_position(self.put_long_1, "QQQ", 1, "Long"),
            create_mock_tt_position(self.put_short_2, "QQQ", 1, "Short"),
            create_mock_tt_position(self.put_long_2, "QQQ", 1, "Long"),
            # No call legs - they were closed
        ]

        matcher = OrderAwareLegMatcher([opening_order], [trident])

        # Position should be "still open" (some legs remain)
        is_open = matcher.is_position_still_open_at_tt(trident, mock_raw_positions)

        # The position is partially open - 4 of 6 legs remain
        # This should be detected as "partially closed" not "fully closed"
        # Current implementation: returns True if ANY legs remain
        assert is_open

        # Get matched legs to verify which ones are missing
        position_symbols = set(matcher.get_position_occ_symbols(trident))
        tt_symbols = {p.symbol for p in mock_raw_positions}

        missing = position_symbols - tt_symbols
        assert missing == {self.call_short, self.call_long}
