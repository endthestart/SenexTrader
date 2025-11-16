"""
Tests for DTE Manager bug fixes - ensuring proper closing order behavior
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

import pytest

from accounts.models import TradingAccount
from services.positions.lifecycle.dte_manager import DTEManager
from trading.models import Position


@pytest.mark.asyncio
class TestDTEManagerFixes:
    """Test suite for DTE manager critical bug fixes"""

    @pytest.fixture
    async def setup(self):
        """Setup test fixtures"""
        # Create mock user and account
        self.user = MagicMock()
        self.user.id = 1

        self.account = MagicMock(spec=TradingAccount)
        self.account.account_number = "TEST123"

        # Create test position at 7 DTE
        self.position = MagicMock(spec=Position)
        self.position.id = 1
        self.position.symbol = "SPY"
        self.position.strategy_type = "senex_trident"
        self.position.avg_price = Decimal("1.00")  # Sold for $1.00 credit
        self.position.spread_width = Decimal("3.00")  # $3 wide spread
        self.position.opening_price_effect = "Credit"
        self.position.lifecycle_state = "active"
        self.position.trading_account = self.account
        self.position.metadata = {
            "expiration": (timezone.now() + timedelta(days=7)).isoformat(),
            "strikes": {
                "short_put_1": 550,
                "long_put_1": 545,
                "short_put_2": 540,
                "long_put_2": 535,
                "short_call": 580,
                "long_call": 585,
            },
            "dte_automation": {},
        }
        self.position.profit_target_details = {
            "put_spread_1": {"order_id": "123456", "status": "filled", "target_price": "0.40"},
            "put_spread_2": {"order_id": "234567", "status": "filled", "target_price": "0.60"},
            "call_spread": {"order_id": "410555945", "target_price": "1.00", "percent": 50},
        }
        self.position.asave = AsyncMock()

        # Mock services
        self.order_service = AsyncMock()
        self.cancellation_service = AsyncMock()

        self.manager = DTEManager(
            user=self.user,
            order_service=self.order_service,
            cancellation_service=self.cancellation_service,
        )

    @pytest.mark.asyncio
    async def test_dte_close_creates_trade_before_order(self, setup):
        """Verify DTE close creates Trade with trade_type='close' BEFORE submitting order"""
        # This prevents creating new positions

        # Mock order submission to return an order ID
        self.order_service.execute_order_spec.return_value = "NEW_ORDER_123"

        # Mock Trade.objects.acreate
        with patch("trading.models.Trade.objects.acreate") as mock_create_trade:
            mock_trade = MagicMock()
            mock_create_trade.return_value = mock_trade

            # Execute DTE close
            result = await self.manager.close_position_at_dte(self.position, 7)

            # Verify Trade was created with correct attributes
            mock_create_trade.assert_called_once()
            trade_kwargs = mock_create_trade.call_args.kwargs

            assert trade_kwargs["trade_type"] == "close"  # CRITICAL: Must be 'close'
            assert trade_kwargs["position"] == self.position
            assert trade_kwargs["lifecycle_event"] == "dte_close"
            assert trade_kwargs["status"] == "pending"
            assert "pending_dte_close_" in trade_kwargs["broker_order_id"]  # Temp ID

            # Verify Trade was updated with real order ID after submission
            assert mock_trade.broker_order_id == "NEW_ORDER_123"
            assert mock_trade.status == "submitted"

    @pytest.mark.asyncio
    async def test_dte_close_price_above_profit_targets(self, setup):
        """Verify closing price is always >= 110% of highest profit target"""
        # Position sold at $1.00, profit target at $1.00
        # At 7 DTE: Should close at max($1.40, $1.10) = $1.40

        # Expected: 70% of max loss ($2.00) = $1.40
        # But must be >= 110% of profit target ($1.00) = $1.10
        # So final price should be $1.40

        cancelled_targets = {
            "call_spread": {
                "order_id": "410555945",
                "original_target_price": "1.00",
                "original_percent": 50,
            }
        }

        limit_price, order_type, price_effect = self.manager._determine_close_parameters(
            self.position, 7, cancelled_targets
        )

        # At 7 DTE, for credit spread: 70% of max_loss = 70% of $2.00 = $1.40
        assert limit_price >= Decimal("1.40")
        assert order_type == "LIMIT"
        assert price_effect == "Debit"  # Paying to close credit spread

    @pytest.mark.asyncio
    async def test_dte_close_cancels_only_unfilled_profit_targets(self, setup):
        """Verify only unfilled profit targets are cancelled, not filled ones"""

        # Mock the cancellation service
        self.cancellation_service.cancel_trade.return_value = True

        # Mock _cancel_child_order_at_broker
        with patch.object(
            self.manager, "_cancel_child_order_at_broker", AsyncMock(return_value=True)
        ), patch.object(self.manager, "_update_profit_target_status", AsyncMock()):

            cancelled_targets = await self.manager._cancel_open_trades(self.position)

            # Should only cancel the call_spread (410555945), not the filled put spreads
            assert "call_spread" in cancelled_targets
            assert cancelled_targets["call_spread"]["order_id"] == "410555945"
            assert "put_spread_1" not in cancelled_targets  # Already filled
            assert "put_spread_2" not in cancelled_targets  # Already filled

    @pytest.mark.asyncio
    async def test_dte_escalation_percentages(self, setup):
        """Test progressive escalation of closing prices as DTE decreases"""

        # Test escalation for credit spread (sold at $1.00 on $3 spread)
        # Max loss = $3.00 - $1.00 = $2.00

        test_cases = [
            (7, Decimal("1.40")),  # 70% of $2.00
            (6, Decimal("1.80")),  # 90% of $2.00
            (5, Decimal("2.20")),  # 110% of $2.00 (accept small loss)
            (4, Decimal("2.60")),  # 130% of $2.00 (accept moderate loss)
            (3, Decimal("0")),  # MARKET order
        ]

        for dte, expected_price in test_cases:
            limit_price, order_type, _ = self.manager._determine_close_parameters(
                self.position, dte
            )

            if dte == 3:
                assert order_type == "MARKET"
            else:
                assert (
                    limit_price == expected_price
                ), f"DTE {dte}: expected ${expected_price}, got ${limit_price}"
                assert order_type == "LIMIT"

    @pytest.mark.asyncio
    async def test_tracks_cancelled_profit_targets_in_metadata(self, setup):
        """Verify cancelled profit targets are tracked in position.metadata"""

        self.order_service.execute_order_spec.return_value = "CLOSE_ORDER_123"

        with patch("trading.models.Trade.objects.acreate", AsyncMock()):
            with patch.object(self.manager, "_cancel_open_trades") as mock_cancel:
                mock_cancel.return_value = {
                    "call_spread": {
                        "order_id": "410555945",
                        "original_target_price": "1.00",
                        "cancelled_at": timezone.now().isoformat(),
                        "reason": "dte_replacement_7",
                    }
                }

                result = await self.manager.close_position_at_dte(self.position, 7)

                # Verify metadata was updated
                assert self.position.asave.called
                metadata = self.position.metadata
                assert "dte_automation" in metadata
                assert "cancelled_profit_targets" in metadata["dte_automation"]
                assert "call_spread" in metadata["dte_automation"]["cancelled_profit_targets"]

    @pytest.mark.asyncio
    async def test_no_new_position_created(self, setup):
        """Ensure no new Position record is created during DTE close"""

        # Mock Position.objects to ensure no new positions are created
        with patch("trading.models.Position.objects") as mock_position_objects:
            mock_position_objects.acreate = AsyncMock()

            # Mock Trade creation
            with patch("trading.models.Trade.objects.acreate", AsyncMock()):
                self.order_service.execute_order_spec.return_value = "CLOSE_ORDER_123"

                result = await self.manager.close_position_at_dte(self.position, 7)

                # Verify NO new Position was created
                mock_position_objects.acreate.assert_not_called()

                # Verify existing position state was updated
                assert self.position.lifecycle_state == "closing"

    @pytest.mark.asyncio
    async def test_price_calculation_with_zero_avg_price(self, setup):
        """Test pricing calculation when position.avg_price is 0 or None"""

        # This might be the cause of the $0.10 bug
        self.position.avg_price = None  # Or 0

        limit_price, order_type, _ = self.manager._determine_close_parameters(self.position, 7)

        # With avg_price=0, max_loss = $3.00 - $0 = $3.00
        # At 7 DTE: 70% of $3.00 = $2.10
        assert limit_price == Decimal("2.10")

        # Test with avg_price = 0
        self.position.avg_price = Decimal("0")
        limit_price, order_type, _ = self.manager._determine_close_parameters(self.position, 7)
        assert limit_price == Decimal("2.10")

    @pytest.mark.asyncio
    async def test_debit_spread_closing_logic(self, setup):
        """Test closing logic for debit spreads (opposite of credit spreads)"""

        # Setup debit spread position
        self.position.opening_price_effect = "Debit"
        self.position.avg_price = Decimal("2.00")  # Paid $2.00

        # For debit spread at 7 DTE: accept 30% of max value
        # Max value = $3.00, so accept $0.90
        limit_price, order_type, price_effect = self.manager._determine_close_parameters(
            self.position, 7
        )

        assert limit_price == Decimal("0.90")
        assert price_effect == "Credit"  # Receiving credit to close debit spread
