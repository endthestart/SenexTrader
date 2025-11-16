"""Tests for the DTEManager lifecycle automation service."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model

import pytest

from accounts.models import TradingAccount
from services.orders.spec import OrderLeg
from services.positions.lifecycle.dte_manager import DTEManager
from trading.models import Position, Trade

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="dte@example.com", username="dte_user", password="testpass123"
    )


@pytest.fixture
def account(user):
    from accounts.models import TradingAccountPreferences

    account = TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="DTE123",
        is_primary=True,
        is_active=True,
    )
    TradingAccountPreferences.objects.create(
        account=account,
        is_automated_trading_enabled=True,
    )
    return account


@pytest.fixture
def position(user, account):
    expiration = date.today() + timedelta(days=6)
    metadata = {
        "expiration": expiration.isoformat(),
        "strikes": {
            "short_put": "430",
            "long_put": "425",
            "short_call": "450",
            "long_call": "455",
        },
    }
    return Position.objects.create(
        user=user,
        trading_account=account,
        strategy_type="senex_trident",
        symbol="SPY",
        quantity=3,
        lifecycle_state="open_full",
        avg_price=Decimal("2.40"),
        metadata=metadata,
    )


@pytest.fixture
def manager(user):
    return DTEManager(user)


@pytest.fixture
def open_trade(position):
    return Trade.objects.create(
        user=position.user,
        position=position,
        trading_account=position.trading_account,
        broker_order_id="open_dte",
        trade_type="open",
        order_legs=[],
        quantity=position.quantity,
        status="filled",
    )


class TestDTEManagerUtilities:
    def test_calculate_current_dte_handles_invalid_metadata(self, position, manager):
        position.metadata["expiration"] = "bad-date"
        assert manager.calculate_current_dte(position) is None

    def test_get_dte_threshold_prefers_metadata(self, position, manager):
        position.metadata.setdefault("dte_close", "10")
        assert manager.get_dte_threshold(position) == 10

    def test_get_dte_threshold_invalid_metadata(self, position, manager):
        position.metadata["dte_close"] = "invalid"
        assert manager.get_dte_threshold(position) == 7


@pytest.mark.django_db
class TestDTEManagerAutomation:
    @pytest.mark.asyncio
    async def test_close_position_at_dte_submits_order(self, position, manager, open_trade):

        with (
            patch.object(position, "asave", new=AsyncMock()),
            patch.object(manager, "_cancel_open_trades", new=AsyncMock()),
            patch.object(manager, "_record_closing_trade", new=AsyncMock()),
            patch.object(
                manager.order_service,
                "execute_order_spec",
                new=AsyncMock(return_value="CLOSE123"),
            ),
            patch.object(
                manager,
                "_build_closing_legs",
                return_value=[
                    OrderLeg(
                        instrument_type="equity_option",
                        symbol="SPY",
                        action="BUY_TO_CLOSE",
                        quantity=1,
                    )
                ],
            ),
            patch.object(
                manager,
                "_determine_close_parameters",
                return_value=(Decimal("0.25"), "LIMIT", "debit"),
            ),
        ):
            success = await manager.close_position_at_dte(position, current_dte=2)

        assert success is True
        assert position.lifecycle_state == "closing"
        assert position.metadata["dte_automation"]["order_id"] == "CLOSE123"
        assert position.metadata["dte_automation"]["dte"] == 2

    @pytest.mark.asyncio
    async def test_close_position_at_dte_missing_metadata(self, position, manager):
        position.metadata.pop("strikes")
        result = await manager.close_position_at_dte(position, current_dte=2)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_at_dte_no_order_id(self, position, manager):
        with (
            patch.object(manager, "_build_closing_legs", return_value=[MagicMock()]),
            patch.object(
                manager,
                "_determine_close_parameters",
                return_value=(Decimal("0.10"), "LIMIT", "debit"),
            ),
            patch.object(
                manager,
                "_cancel_open_trades",
                new=AsyncMock(),
            ),
            patch.object(
                manager.order_service,
                "execute_order_spec",
                new=AsyncMock(return_value=None),
            ),
        ):
            success = await manager.close_position_at_dte(position, current_dte=2)

        assert success is False

    @pytest.mark.asyncio
    async def test_notify_manual_action_logs_warning(self, position, manager, caplog):
        position.trading_account.is_automated_trading_enabled = False
        with patch("services.position_lifecycle.dte_manager.logger.warning") as mock_warning:
            await manager.notify_manual_action(position, current_dte=1)
        mock_warning.assert_called_once()
        assert "requires manual closure" in mock_warning.call_args[0][0]
