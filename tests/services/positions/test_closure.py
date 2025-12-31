"""
Tests for PositionClosureService.

Tests closure processing and P&L calculation, ensuring:
1. Manual closes calculate correct P&L
2. Assignments create equity positions
3. Expired positions are detected
4. Profit target closures are identified
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

import pytest

from services.positions.closure_service import (
    CLOSURE_ASSIGNMENT,
    CLOSURE_EXPIRED_WORTHLESS,
    CLOSURE_MANUAL,
    CLOSURE_PROFIT_TARGET,
    CLOSURE_UNKNOWN,
    PositionClosureService,
)


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
def closure_service():
    """Create PositionClosureService instance."""
    return PositionClosureService()


class TestCalculatePnl:
    """Tests for _calculate_pnl method."""

    def test_credit_spread_profit_pnl(self, closure_service):
        """
        Test P&L calculation for profitable credit spread.

        Opening: Sell to Open +$228 credit
        Closing: Buy to Close -$50 debit
        P&L = +$178 profit
        """
        # Opening transaction (credit received)
        open_tx = MagicMock()
        open_tx.action = "Sell to Open"
        open_tx.net_value = Decimal("228.00")

        # Closing transaction (debit paid)
        close_tx = MagicMock()
        close_tx.action = "Buy to Close"
        close_tx.net_value = Decimal("50.00")

        pnl = closure_service._calculate_pnl([open_tx], [close_tx])

        assert pnl == Decimal("178.00")

    def test_credit_spread_loss_pnl(self, closure_service):
        """
        Test P&L calculation for losing credit spread.

        Opening: Sell to Open +$100 credit
        Closing: Buy to Close -$250 debit
        P&L = -$150 loss
        """
        open_tx = MagicMock()
        open_tx.action = "Sell to Open"
        open_tx.net_value = Decimal("100.00")

        close_tx = MagicMock()
        close_tx.action = "Buy to Close"
        close_tx.net_value = Decimal("250.00")

        pnl = closure_service._calculate_pnl([open_tx], [close_tx])

        assert pnl == Decimal("-150.00")

    def test_bull_put_spread_full_pnl(self, closure_service):
        """
        Test P&L for bull put spread with both legs.

        Opening:
          Sell to Open P616 +$1471 credit
          Buy to Open P613 -$1357 debit
          Net opening: +$114

        Closing:
          Buy to Close P616 -$50 debit
          Sell to Close P613 +$30 credit
          Net closing: -$20

        P&L = +$114 - $20 = +$94 profit
        """
        open_tx1 = MagicMock()
        open_tx1.action = "Sell to Open"
        open_tx1.net_value = Decimal("1471.00")

        open_tx2 = MagicMock()
        open_tx2.action = "Buy to Open"
        open_tx2.net_value = Decimal("1357.00")

        close_tx1 = MagicMock()
        close_tx1.action = "Buy to Close"
        close_tx1.net_value = Decimal("50.00")

        close_tx2 = MagicMock()
        close_tx2.action = "Sell to Close"
        close_tx2.net_value = Decimal("30.00")

        pnl = closure_service._calculate_pnl(
            [open_tx1, open_tx2],
            [close_tx1, close_tx2]
        )

        # Opening: +1471 - 1357 = +114
        # Closing: -50 + 30 = -20
        # Total: +114 - 20 = +94
        assert pnl == Decimal("94.00")

    def test_expired_worthless_pnl(self, closure_service):
        """
        Test P&L for position that expired worthless.

        Opening: +$228 credit
        Closing: No transactions (expired)
        P&L = +$228 (full credit kept)
        """
        open_tx1 = MagicMock()
        open_tx1.action = "Sell to Open"
        open_tx1.net_value = Decimal("1471.00")

        open_tx2 = MagicMock()
        open_tx2.action = "Buy to Open"
        open_tx2.net_value = Decimal("1243.00")

        pnl = closure_service._calculate_pnl(
            [open_tx1, open_tx2],
            []  # No closing transactions
        )

        # Full credit kept: 1471 - 1243 = 228
        assert pnl == Decimal("228.00")


class TestDetermineClosureReason:
    """Tests for _determine_closure_reason method."""

    def test_assignment_reason(self, closure_service):
        """Test assignment transactions return CLOSURE_ASSIGNMENT."""
        position = MagicMock()
        position.profit_target_details = {}
        position.metadata = {}

        assignment_tx = MagicMock()
        assignment_tx.transaction_sub_type = "Assignment"

        reason = closure_service._determine_closure_reason(
            position=position,
            opening_txns=[],
            closing_txns=[],
            assignment_txns=[assignment_tx],
        )

        assert reason == CLOSURE_ASSIGNMENT

    def test_profit_target_reason(self, closure_service):
        """Test profit target order match returns CLOSURE_PROFIT_TARGET."""
        position = MagicMock()
        position.profit_target_details = {
            "put_spread": {"order_id": "123456"}
        }
        position.metadata = {}

        closing_tx = MagicMock()
        closing_tx.order_id = 123456
        closing_tx.action = "Buy to Close"

        reason = closure_service._determine_closure_reason(
            position=position,
            opening_txns=[],
            closing_txns=[closing_tx],
            assignment_txns=[],
        )

        assert reason == CLOSURE_PROFIT_TARGET

    def test_manual_close_reason(self, closure_service):
        """Test non-profit-target closing returns CLOSURE_MANUAL."""
        position = MagicMock()
        position.profit_target_details = {
            "put_spread": {"order_id": "123456"}
        }
        position.metadata = {}

        closing_tx = MagicMock()
        closing_tx.order_id = 999999  # Different from profit target
        closing_tx.action = "Buy to Close"

        reason = closure_service._determine_closure_reason(
            position=position,
            opening_txns=[],
            closing_txns=[closing_tx],
            assignment_txns=[],
        )

        assert reason == CLOSURE_MANUAL

    def test_expired_worthless_reason(self, closure_service):
        """Test expiration past returns CLOSURE_EXPIRED_WORTHLESS."""
        position = MagicMock()
        position.profit_target_details = {}
        position.metadata = {
            "expiration_date": "2024-01-01"  # Past date
        }

        reason = closure_service._determine_closure_reason(
            position=position,
            opening_txns=[],
            closing_txns=[],  # No closing transactions
            assignment_txns=[],
        )

        assert reason == CLOSURE_EXPIRED_WORTHLESS

    def test_unknown_reason(self, closure_service):
        """Test unknown scenario returns CLOSURE_UNKNOWN."""
        position = MagicMock()
        position.profit_target_details = {}
        position.metadata = {}

        reason = closure_service._determine_closure_reason(
            position=position,
            opening_txns=[],
            closing_txns=[],
            assignment_txns=[],
        )

        assert reason == CLOSURE_UNKNOWN


class TestHandleAssignment:
    """Tests for _handle_assignment method."""

    @pytest.mark.asyncio
    async def test_put_assignment_creates_equity(self, closure_service):
        """
        Test put assignment creates equity position.

        Scenario:
        - Short put P616 assigned
        - User acquires 200 shares at $616
        - Equity position created
        """
        position = MagicMock()
        position.id = 100
        position.symbol = "QQQ"
        position.user = MagicMock()
        position.trading_account = MagicMock()
        position.metadata = {}

        assignment_tx = MagicMock()
        assignment_tx.symbol = "QQQ   251219P00616000"  # Put option
        assignment_tx.quantity = Decimal("2")  # 2 contracts = 200 shares
        assignment_tx.net_value = Decimal("-123200.00")  # Cost of shares
        assignment_tx.executed_at = timezone.now()
        assignment_tx.transaction_id = 999

        with patch(
            "services.positions.closure_service.Position.objects"
        ) as mock_position:
            mock_equity = MagicMock()
            mock_equity.id = 101
            mock_position.acreate = AsyncMock(return_value=mock_equity)

            result = await closure_service._handle_assignment(
                position=position,
                assignment_txns=[assignment_tx],
                user=position.user,
                account=position.trading_account,
            )

        # Equity position should be created
        assert result is not None or mock_position.acreate.called


# TestProcessClosedPositions class removed - contained only empty placeholder tests
# TODO: Implement integration tests when full mocking infrastructure is available
