"""Tests for position synchronization service (Phase 5F)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

import pytest
from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.positions.sync import PositionSyncService
from trading.models import Position

User = get_user_model()


@pytest.mark.django_db
class TestPositionSyncService(TestCase):
    """Test position import and classification logic."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="12345",
            is_primary=True,
            is_active=True,
        )

        self.sync_service = PositionSyncService()

    @pytest.mark.asyncio
    async def test_sync_all_positions_success(self):
        """Test successful position synchronization."""
        # Mock TastyTrade API responses (raw positions from API)
        mock_raw_position1 = MagicMock()
        mock_raw_position1.underlying_symbol = "SPY"
        mock_raw_position1.symbol = "SPY"
        mock_raw_position1.instrument_type = "Equity"
        mock_raw_position1.quantity = 100
        mock_raw_position1.quantity_direction = "Long"
        mock_raw_position1.average_open_price = 450.25
        mock_raw_position1.close_price = 451.00
        mock_raw_position1.mark_price = 451.00
        mock_raw_position1.multiplier = 1
        mock_raw_position1.cost_effect = "Debit"

        mock_raw_position2 = MagicMock()
        mock_raw_position2.underlying_symbol = "QQQ"
        mock_raw_position2.symbol = "QQQ   240119P00460000"
        mock_raw_position2.instrument_type = "Equity Option"
        mock_raw_position2.quantity = -2
        mock_raw_position2.quantity_direction = "Short"
        mock_raw_position2.average_open_price = 2.50
        mock_raw_position2.close_price = 2.00
        mock_raw_position2.mark_price = 2.00
        mock_raw_position2.multiplier = 100
        mock_raw_position2.cost_effect = "Credit"

        # Mock TastyTrade Account and session
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(
            return_value=[mock_raw_position1, mock_raw_position2]
        )

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            result = await self.sync_service.sync_all_positions(self.user)

        # Verify results
        assert result["success"]
        assert result["imported"] == 2
        assert result["updated"] == 0

        # Verify positions were created
        positions = await sync_to_async(list)(Position.objects.filter(user=self.user))
        assert len(positions) == 2

        # Verify position data
        spy_stock = await sync_to_async(Position.objects.get)(user=self.user, symbol="SPY")
        assert spy_stock.symbol == "SPY"
        assert spy_stock.quantity == 100
        assert spy_stock.avg_price == Decimal("450.25")
        assert not spy_stock.is_app_managed  # Imported positions are external

        qqq_option = await sync_to_async(Position.objects.get)(user=self.user, symbol="QQQ")
        assert qqq_option.symbol == "QQQ"
        assert qqq_option.quantity == 2
        assert not qqq_option.is_app_managed

    @pytest.mark.asyncio
    async def test_sync_existing_position_update(self):
        """Test updating an existing position."""
        # Create existing position
        existing_position = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="external",
            symbol="SPY",
            quantity=50,
            avg_price=Decimal("445.00"),
            is_app_managed=False,
        )

        # Mock updated position data (raw TastyTrade format)
        mock_raw_position = MagicMock()
        mock_raw_position.underlying_symbol = "SPY"
        mock_raw_position.symbol = "SPY"
        mock_raw_position.instrument_type = "Equity"
        mock_raw_position.quantity = 75  # Changed quantity
        mock_raw_position.quantity_direction = "Long"
        mock_raw_position.average_open_price = 448.50  # Changed price
        mock_raw_position.close_price = 450.00
        mock_raw_position.mark_price = 450.00
        mock_raw_position.multiplier = 1
        mock_raw_position.cost_effect = "Debit"

        # Mock TastyTrade Account and session
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(return_value=[mock_raw_position])

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            result = await self.sync_service.sync_all_positions(self.user)

        # Verify update occurred
        assert result["success"]
        assert result["imported"] == 0
        assert result["updated"] == 1

        # Verify position was updated
        updated_position = await sync_to_async(Position.objects.get)(id=existing_position.id)
        # Quantity should be updated for external positions
        assert updated_position.unrealized_pnl == Decimal("112.50")  # (450.00 - 448.50) * 75

    def test_categorize_position_external(self):
        """Test position categorization logic."""
        mock_position = {
            "id": "pos_1",
            "symbol": "SPY",
            "quantity": 100,
            "position_type": "stock",
        }

        # All imported positions should be categorized as external
        import asyncio

        is_app_managed = asyncio.run(self.sync_service._categorize_position(mock_position))
        assert not is_app_managed

    def test_safe_decimal_conversion(self):
        """Test safe decimal conversion utility."""
        # Test valid conversions
        assert self.sync_service._safe_decimal("123.45") == Decimal("123.45")
        assert self.sync_service._safe_decimal(123.45) == Decimal("123.45")
        assert self.sync_service._safe_decimal(100) == Decimal("100")

        # Test None
        assert self.sync_service._safe_decimal(None) is None

        # Test invalid values
        assert self.sync_service._safe_decimal("invalid") is None
        assert self.sync_service._safe_decimal("") is None

    @pytest.mark.asyncio
    async def test_sync_no_account(self):
        """Test sync when user has no primary account."""
        user_no_account = await sync_to_async(User.objects.create_user)(
            email="noacccount@example.com", username="noaccount", password="testpass123"
        )

        result = await self.sync_service.sync_all_positions(user_no_account)
        assert "error" in result
        assert "No primary trading account" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_api_error_handling(self):
        """Test handling of API errors during sync."""
        mock_session = AsyncMock()

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", side_effect=Exception("API Error")),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            result = await self.sync_service.sync_all_positions(self.user)

        assert "error" in result
        assert "API Error" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_tastytrade_positions_empty(self):
        """Test handling of empty position list from API."""
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(return_value=[])

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            result = await self.sync_service.sync_all_positions(self.user)

        assert result["success"]
        assert result["positions_found"] == 0
        assert result["imported"] == 0
        assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_sync_positions_requests_live_marks(self):
        """Test that position sync requests live market prices with include_marks=True.

        This is a critical regression test to prevent the $0.00 unrealized P&L bug
        that occurred when mark_price was None due to missing include_marks parameter.
        """
        from unittest.mock import AsyncMock, MagicMock

        from tastytrade import Account

        # Mock session and account
        mock_session = MagicMock()
        mock_tt_account = AsyncMock()
        mock_tt_account.a_get_positions = AsyncMock(return_value=[])

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch.object(Account, "a_get", return_value=mock_tt_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            await self.sync_service.sync_all_positions(self.user)

            # CRITICAL: Verify include_marks=True was passed to API
            mock_tt_account.a_get_positions.assert_called_once()
            call_args = mock_tt_account.a_get_positions.call_args

            # Check if include_marks=True in kwargs
            assert (
                call_args.kwargs.get("include_marks") is True
            ), "Position sync must request live marks to prevent $0.00 P&L bug"

    @pytest.mark.asyncio
    async def test_unrealized_pnl_uses_mark_price(self):
        """Test that unrealized P&L calculation uses mark_price when available.

        When mark_price is provided by API, P&L should reflect actual market value,
        not show $0.00 when close_price equals average_open_price (stale data).
        """
        # Mock position with mark_price different from average
        mock_raw_position = MagicMock()
        mock_raw_position.underlying_symbol = "SPY"
        mock_raw_position.symbol = "SPY   241220P00450000"
        mock_raw_position.instrument_type = "Equity Option"
        mock_raw_position.quantity = 1
        mock_raw_position.quantity_direction = "Long"
        mock_raw_position.average_open_price = 10.00
        mock_raw_position.close_price = 10.00  # Stale (equals average)
        mock_raw_position.mark_price = 8.50  # Live market price (should use this)
        mock_raw_position.multiplier = 100
        mock_raw_position.cost_effect = "Debit"

        # Mock TastyTrade Account and session
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(return_value=[mock_raw_position])

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            result = await self.sync_service.sync_all_positions(self.user)

        assert result["success"]

        # Get the created position
        position = await sync_to_async(Position.objects.get)(user=self.user, symbol="SPY")

        # P&L should be calculated from mark_price, not $0.00
        # For long position: (8.50 - 10.00) * 1 * 100 = -$150.00 loss
        assert position.unrealized_pnl != Decimal(
            "0.00"
        ), "Unrealized P&L should use mark_price, not stale close_price"
        assert position.unrealized_pnl == Decimal(
            "-150.00"
        ), f"Expected -$150 loss but got {position.unrealized_pnl}"

    @pytest.mark.asyncio
    async def test_position_sync_broadcasts_completion(self):
        """Test that WebSocket broadcast occurs after successful position sync."""
        # Mock position data (raw TastyTrade format)
        mock_raw_position = MagicMock()
        mock_raw_position.underlying_symbol = "QQQ"
        mock_raw_position.symbol = "QQQ   241220C00400000"
        mock_raw_position.instrument_type = "Equity Option"
        mock_raw_position.quantity = 1
        mock_raw_position.quantity_direction = "Short"
        mock_raw_position.average_open_price = 5.00
        mock_raw_position.close_price = 4.50
        mock_raw_position.mark_price = 4.50
        mock_raw_position.multiplier = 100
        mock_raw_position.cost_effect = "Credit"

        # Mock TastyTrade Account and session
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(return_value=[mock_raw_position])

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
            patch(
                "streaming.services.stream_manager.GlobalStreamManager.get_user_manager"
            ) as mock_get_manager,
        ):
            # Mock stream manager and broadcast
            mock_stream_manager = AsyncMock()
            mock_get_manager.return_value = mock_stream_manager

            result = await self.sync_service.sync_all_positions(self.user)

            assert result["success"]

            # Verify broadcast was called
            mock_stream_manager._broadcast.assert_called_once()

            # Verify message type and data
            call_args = mock_stream_manager._broadcast.call_args
            message_type = call_args[0][0]
            message_data = call_args[0][1]

            assert message_type == "position_sync_complete"
            assert "positions_updated" in message_data
            assert "positions_imported" in message_data
            assert "timestamp" in message_data

    @pytest.mark.asyncio
    async def test_no_synchronous_operations_in_async_context(self):
        """Test that position sync completes without SynchronousOnlyOperation errors.

        This is a regression test for the @transaction.atomic bug that was fixed
        by restructuring _reconcile_profit_target_fills to use @sync_to_async.
        """
        # Mock position data (raw TastyTrade format)
        mock_raw_position = MagicMock()
        mock_raw_position.underlying_symbol = "SPY"
        mock_raw_position.symbol = "SPY   241220C00450000"
        mock_raw_position.instrument_type = "Equity Option"
        mock_raw_position.quantity = 1
        mock_raw_position.quantity_direction = "Long"
        mock_raw_position.average_open_price = 5.00
        mock_raw_position.close_price = 5.50
        mock_raw_position.mark_price = 5.50
        mock_raw_position.multiplier = 100
        mock_raw_position.cost_effect = "Debit"

        # Mock TastyTrade Account and session
        mock_session = AsyncMock()
        mock_account = AsyncMock()
        mock_account.a_get_positions = AsyncMock(return_value=[mock_raw_position])

        # Mock order history service
        mock_order_service = AsyncMock()
        mock_order_service.sync_order_history = AsyncMock(return_value={"orders_synced": 0})
        self.sync_service.order_history_service = mock_order_service

        with (
            patch("services.data_access.get_oauth_session", return_value=mock_session),
            patch("tastytrade.Account.a_get", return_value=mock_account),
            patch.object(
                self.sync_service,
                "_get_primary_account",
                return_value=self.trading_account,
            ),
        ):
            # Should complete without raising SynchronousOnlyOperation
            result = await self.sync_service.sync_all_positions(self.user)

            assert result["success"]
            assert result["imported"] == 1

    @pytest.mark.asyncio
    async def test_profit_target_reconciliation_with_transaction(self):
        """Test profit target reconciliation maintains transaction atomicity.

        When profit targets are filled, the position update should occur within
        a transaction. If any part fails, the entire update should roll back.
        """
        from django.utils import timezone

        from trading.models import CachedOrder

        # Create a position with profit targets
        position = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="SPY",
            quantity=2,
            avg_price=Decimal("10.00"),
            is_app_managed=True,
            lifecycle_state="open_full",
            profit_targets_created=True,
            profit_target_details={
                "pt_25": {
                    "order_id": "ORDER-PT-25",
                    "contracts": 1,
                    "original_credit": 10.00,
                }
            },
            metadata={
                "original_quantity": 2,
            },
        )

        # Create a filled profit target order with proper structure
        await sync_to_async(CachedOrder.objects.create)(
            broker_order_id="ORDER-PT-25",
            user=self.user,
            trading_account=self.trading_account,
            underlying_symbol="SPY",
            order_type="Limit",
            status="Filled",
            price_effect="Debit",
            filled_at=timezone.now(),
            order_data={
                "legs": [
                    {
                        "symbol": "SPY   241220C00450000",
                        "quantity": "1",
                        "action": "Buy to Close",
                    }
                ],
                "fills": [
                    {
                        "price": "5.00",  # Closed for $5, opened for $10, profit = $5 * 100
                    }
                ],
            },
        )

        # Call reconcile method
        await self.sync_service._reconcile_profit_target_fills(position, self.trading_account)

        # Verify position was updated correctly
        await sync_to_async(position.refresh_from_db)()

        # Position should now show partial close
        assert position.quantity == 1  # Reduced from 2 to 1
        assert position.lifecycle_state == "open_partial"

        # Profit target should be marked as filled
        assert position.profit_target_details.get("pt_25", {}).get("status") == "filled"
