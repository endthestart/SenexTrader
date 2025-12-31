"""
Tests for TransactionImporter.link_transactions_to_positions.

Tests enhanced transaction linking including:
1. Opening order matching (original behavior)
2. Profit target order matching
3. DTE automation order matching
4. Symbol-based matching fallback
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

import pytest

from services.orders.transactions import TransactionImporter


@pytest.fixture
def mock_user():
    """Create mock user."""
    user = MagicMock()
    user.id = 1
    return user


@pytest.fixture
def mock_account():
    """Create mock trading account."""
    account = MagicMock()
    account.account_number = "5WT12345"
    return account


@pytest.fixture
def importer():
    """Create TransactionImporter instance."""
    return TransactionImporter()


class TestLinkByOpeningOrderId:
    """Tests for opening_order_id matching."""

    @pytest.mark.asyncio
    async def test_link_by_opening_order_id(self, importer, mock_user, mock_account):
        """Test linking transaction by opening_order_id."""
        # Create mock transaction
        mock_tx = MagicMock()
        mock_tx.order_id = 123456
        mock_tx.transaction_id = "tx_001"
        mock_tx.action = "Sell to Open"
        mock_tx.asave = AsyncMock()

        # Create mock position with matching opening_order_id
        mock_position = MagicMock()
        mock_position.id = 1
        mock_position.opening_order_id = "123456"

        with (
            patch.object(
                importer,
                "_get_unlinked_transactions",
                return_value=[mock_tx],
            ),
            patch.object(
                importer,
                "_build_order_id_caches",
                return_value=({}, {}),
            ),
            patch(
                "services.orders.transactions.Position.objects"
            ) as mock_position_objects,
            patch(
                "services.orders.transactions.TastyTradeTransaction.objects"
            ) as mock_tx_objects,
        ):
            # Setup position query mock
            mock_position_objects.filter.return_value.afirst = AsyncMock(
                return_value=mock_position
            )
            mock_tx_objects.filter.return_value.acount = AsyncMock(return_value=5)

            result = await importer.link_transactions_to_positions(
                mock_user, mock_account
            )

        assert result["linked"] == 1
        assert result["linked_by_opening"] == 1
        assert mock_tx.related_position == mock_position
        mock_tx.asave.assert_called_once()


class TestLinkByProfitTargetOrderId:
    """Tests for profit_target order matching."""

    @pytest.mark.asyncio
    async def test_link_by_profit_target_order_id(self, importer, mock_user):
        """Test linking transaction by profit_target_details order_id."""
        # Create mock transaction for profit target fill
        mock_tx = MagicMock()
        mock_tx.order_id = 789012
        mock_tx.transaction_id = "tx_002"
        mock_tx.action = "Buy to Close"
        mock_tx.asave = AsyncMock()

        # Create mock position with profit target
        mock_position = MagicMock()
        mock_position.id = 2
        mock_position.profit_target_details = {
            "put_spread": {"order_id": 789012, "percent": 50}
        }
        mock_position.metadata = {}

        with (
            patch.object(
                importer,
                "_get_unlinked_transactions",
                return_value=[mock_tx],
            ),
            patch.object(
                importer,
                "_build_order_id_caches",
                return_value=({"789012": mock_position}, {}),
            ),
            patch(
                "services.orders.transactions.Position.objects"
            ) as mock_position_objects,
            patch(
                "services.orders.transactions.TastyTradeTransaction.objects"
            ) as mock_tx_objects,
        ):
            # Return None for opening_order_id lookup
            mock_position_objects.filter.return_value.afirst = AsyncMock(
                return_value=None
            )
            mock_tx_objects.filter.return_value.acount = AsyncMock(return_value=5)

            result = await importer.link_transactions_to_positions(mock_user)

        assert result["linked"] == 1
        assert result["linked_by_profit_target"] == 1
        assert mock_tx.related_position == mock_position


class TestLinkByDteOrderId:
    """Tests for DTE automation order matching."""

    @pytest.mark.asyncio
    async def test_link_by_dte_automation_order_id(self, importer, mock_user):
        """Test linking transaction by metadata.dte_automation.order_id."""
        # Create mock transaction for DTE close
        mock_tx = MagicMock()
        mock_tx.order_id = 345678
        mock_tx.transaction_id = "tx_003"
        mock_tx.action = "Buy to Close"
        mock_tx.asave = AsyncMock()

        # Create mock position with DTE automation
        mock_position = MagicMock()
        mock_position.id = 3
        mock_position.profit_target_details = {}
        mock_position.metadata = {
            "dte_automation": {
                "order_id": 345678,
                "dte": 7,
            }
        }

        with (
            patch.object(
                importer,
                "_get_unlinked_transactions",
                return_value=[mock_tx],
            ),
            patch.object(
                importer,
                "_build_order_id_caches",
                return_value=({}, {"345678": mock_position}),
            ),
            patch(
                "services.orders.transactions.Position.objects"
            ) as mock_position_objects,
            patch(
                "services.orders.transactions.TastyTradeTransaction.objects"
            ) as mock_tx_objects,
        ):
            mock_position_objects.filter.return_value.afirst = AsyncMock(
                return_value=None
            )
            mock_tx_objects.filter.return_value.acount = AsyncMock(return_value=5)

            result = await importer.link_transactions_to_positions(mock_user)

        assert result["linked"] == 1
        assert result["linked_by_dte"] == 1
        assert mock_tx.related_position == mock_position


class TestLinkBySymbol:
    """Tests for symbol-based matching fallback."""

    @pytest.mark.asyncio
    async def test_match_by_symbol_closing_transaction(self, importer, mock_user):
        """Test symbol-based matching for external close transaction."""
        # Create mock closing transaction
        mock_tx = MagicMock()
        mock_tx.order_id = 999999  # Unrecognized order
        mock_tx.transaction_id = "tx_004"
        mock_tx.action = "Buy to Close"
        mock_tx.symbol = "QQQ   251219P00616000"
        mock_tx.underlying_symbol = "QQQ"
        mock_tx.executed_at = timezone.now()

        # Create mock position with matching leg
        mock_position = MagicMock()
        mock_position.id = 4
        mock_position.symbol = "QQQ"
        mock_position.lifecycle_state = "open_full"
        mock_position.opened_at = timezone.now() - timedelta(days=5)
        mock_position.metadata = {
            "legs": [
                {"symbol": "QQQ   251219P00616000", "action": "Sell to Open"},
                {"symbol": "QQQ   251219P00613000", "action": "Buy to Open"},
            ]
        }

        # Mock async iterator for positions
        async def mock_position_iter():
            yield mock_position

        with (
            patch(
                "services.orders.transactions.Position.objects"
            ) as mock_position_objects,
        ):
            # Setup filter to return async iterator
            mock_filter = MagicMock()
            mock_filter.__aiter__ = lambda self: mock_position_iter()
            mock_position_objects.filter.return_value = mock_filter

            result = await importer._match_by_symbol(mock_tx, mock_user, None)

        assert result == mock_position

    @pytest.mark.asyncio
    async def test_match_by_symbol_skips_opening_transaction(self, importer, mock_user):
        """Test that symbol matching only works for closing transactions."""
        # Create mock opening transaction
        mock_tx = MagicMock()
        mock_tx.action = "Sell to Open"  # Not a closing action
        mock_tx.symbol = "QQQ   251219P00616000"

        result = await importer._match_by_symbol(mock_tx, mock_user, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_match_by_symbol_skips_without_symbol(self, importer, mock_user):
        """Test that symbol matching skips transactions without symbol."""
        mock_tx = MagicMock()
        mock_tx.action = "Buy to Close"
        mock_tx.symbol = None

        result = await importer._match_by_symbol(mock_tx, mock_user, None)

        assert result is None


class TestBuildOrderIdCaches:
    """Tests for _build_order_id_caches helper."""

    @pytest.mark.asyncio
    async def test_build_caches_from_positions(self, importer, mock_user):
        """Test building order ID caches from positions."""
        # Create mock positions
        pos1 = MagicMock()
        pos1.profit_target_details = {
            "put_spread": {"order_id": "111"},
            "call_spread": {"order_id": "222"},
        }
        pos1.metadata = {}

        pos2 = MagicMock()
        pos2.profit_target_details = {}
        pos2.metadata = {
            "dte_automation": {"order_id": "333"}
        }

        # Mock async iterator
        async def mock_position_iter():
            yield pos1
            yield pos2

        with patch(
            "services.orders.transactions.Position.objects"
        ) as mock_position_objects:
            mock_filter = MagicMock()
            mock_filter.__aiter__ = lambda self: mock_position_iter()
            mock_position_objects.filter.return_value = mock_filter

            pt_map, dte_map = await importer._build_order_id_caches(mock_user, None)

        assert "111" in pt_map
        assert "222" in pt_map
        assert pt_map["111"] == pos1
        assert pt_map["222"] == pos1
        assert "333" in dte_map
        assert dte_map["333"] == pos2


class TestResultReporting:
    """Tests for linking result metrics."""

    @pytest.mark.asyncio
    async def test_reports_all_link_types(self, importer, mock_user):
        """Test that all link types are tracked in results."""
        with (
            patch.object(
                importer,
                "_get_unlinked_transactions",
                return_value=[],
            ),
            patch.object(
                importer,
                "_build_order_id_caches",
                return_value=({}, {}),
            ),
            patch(
                "services.orders.transactions.TastyTradeTransaction.objects"
            ) as mock_tx_objects,
        ):
            mock_tx_objects.filter.return_value.acount = AsyncMock(return_value=10)

            result = await importer.link_transactions_to_positions(mock_user)

        # Verify all keys are present
        assert "linked" in result
        assert "not_found" in result
        assert "already_linked" in result
        assert "linked_by_opening" in result
        assert "linked_by_profit_target" in result
        assert "linked_by_dte" in result
        assert "linked_by_symbol" in result
        assert result["already_linked"] == 10
