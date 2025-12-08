"""Tests for the DTEManager lifecycle automation service."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model

import pytest

from accounts.models import TradingAccount
from services.orders.spec import OrderLeg
from services.positions.lifecycle.dte_manager import DTEManager
from trading.models import Position, Trade

User = get_user_model()


class TestDTEPricingCalculation:
    """Test the DTE closing price escalation logic.

    Credit spread formula: close_price = entry_price + (% × max_loss)
    Debit spread formula: close_price = entry_price × remaining_%
    """

    @pytest.fixture
    def credit_spread_position(self, db):
        """$3 wide credit spread with $1.50 credit received."""
        user = User.objects.create_user(
            email="dte_pricing@test.com", username="dte_pricing", password="test123"
        )
        account = TradingAccount.objects.create(
            user=user,
            connection_type="TASTYTRADE",
            account_number="PRICING123",
            is_primary=True,
            is_active=True,
        )
        return Position.objects.create(
            user=user,
            trading_account=account,
            strategy_type="bull_put_spread",
            symbol="QQQ",
            quantity=1,
            lifecycle_state="open_full",
            avg_price=Decimal("1.50"),  # Credit received
            spread_width=3,  # $3 wide
            opening_price_effect="Credit",
            metadata={
                "expiration": (date.today() + timedelta(days=7)).isoformat(),
                "strikes": {"short_put": "500", "long_put": "497"},
            },
        )

    @pytest.fixture
    def debit_spread_position(self, db):
        """$3 wide debit spread with $2.00 debit paid."""
        user = User.objects.create_user(
            email="dte_debit@test.com", username="dte_debit", password="test123"
        )
        account = TradingAccount.objects.create(
            user=user,
            connection_type="TASTYTRADE",
            account_number="DEBIT123",
            is_primary=True,
            is_active=True,
        )
        return Position.objects.create(
            user=user,
            trading_account=account,
            strategy_type="bear_put_spread",  # Debit spread
            symbol="QQQ",
            quantity=1,
            lifecycle_state="open_full",
            avg_price=Decimal("2.00"),  # Debit paid
            spread_width=3,  # $3 wide
            opening_price_effect="Debit",
            metadata={
                "expiration": (date.today() + timedelta(days=7)).isoformat(),
                "strikes": {"long_put": "500", "short_put": "497"},
            },
        )

    def test_credit_spread_dte_7_breakeven(self, credit_spread_position):
        """At DTE 7, credit spread should close at breakeven (entry price)."""
        manager = DTEManager(credit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            credit_spread_position, current_dte=7
        )

        # $1.50 credit received = $1.50 to close (breakeven)
        assert limit_price == Decimal("1.50")
        assert order_type == "LIMIT"

    def test_credit_spread_dte_6_70_percent_max_loss(self, credit_spread_position):
        """At DTE 6, credit spread should accept 70% of max loss."""
        manager = DTEManager(credit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            credit_spread_position, current_dte=6
        )

        # Max loss = $3.00 - $1.50 = $1.50
        # Close price = $1.50 + (0.70 × $1.50) = $2.55
        assert limit_price == Decimal("2.55")
        assert order_type == "LIMIT"

    def test_credit_spread_dte_5_80_percent_max_loss(self, credit_spread_position):
        """At DTE 5, credit spread should accept 80% of max loss."""
        manager = DTEManager(credit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            credit_spread_position, current_dte=5
        )

        # Close price = $1.50 + (0.80 × $1.50) = $2.70
        assert limit_price == Decimal("2.70")
        assert order_type == "LIMIT"

    def test_credit_spread_dte_4_90_percent_max_loss(self, credit_spread_position):
        """At DTE 4, credit spread should accept 90% of max loss."""
        manager = DTEManager(credit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            credit_spread_position, current_dte=4
        )

        # Close price = $1.50 + (0.90 × $1.50) = $2.85
        assert limit_price == Decimal("2.85")
        assert order_type == "LIMIT"

    def test_credit_spread_dte_3_full_spread_width(self, credit_spread_position):
        """At DTE ≤3, credit spread should pay full spread width."""
        manager = DTEManager(credit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            credit_spread_position, current_dte=3
        )

        # Full spread width = $3.00
        assert limit_price == Decimal("3.00")
        assert order_type == "LIMIT"

    def test_debit_spread_dte_7_breakeven(self, debit_spread_position):
        """At DTE 7, debit spread should close at breakeven (entry price)."""
        manager = DTEManager(debit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            debit_spread_position, current_dte=7
        )

        # $2.00 debit paid = $2.00 to close (breakeven)
        assert limit_price == Decimal("2.00")
        assert order_type == "LIMIT"

    def test_debit_spread_dte_6_70_percent_max_loss(self, debit_spread_position):
        """At DTE 6, debit spread should accept 70% of max loss.

        For debit spread: sell_price = entry_price - (% × max_loss)
        max_loss = entry_price (lose entire debit paid)
        """
        manager = DTEManager(debit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            debit_spread_position, current_dte=6
        )

        # Close price = $2.00 - (0.70 × $2.00) = $0.60
        assert limit_price == Decimal("0.60")
        assert order_type == "LIMIT"

    def test_debit_spread_dte_5_80_percent_max_loss(self, debit_spread_position):
        """At DTE 5, debit spread should accept 80% of max loss."""
        manager = DTEManager(debit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            debit_spread_position, current_dte=5
        )

        # Close price = $2.00 - (0.80 × $2.00) = $0.40
        assert limit_price == Decimal("0.40")
        assert order_type == "LIMIT"

    def test_debit_spread_dte_4_90_percent_max_loss(self, debit_spread_position):
        """At DTE 4, debit spread should accept 90% of max loss."""
        manager = DTEManager(debit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            debit_spread_position, current_dte=4
        )

        # Close price = $2.00 - (0.90 × $2.00) = $0.20
        assert limit_price == Decimal("0.20")
        assert order_type == "LIMIT"

    def test_debit_spread_dte_3_total_loss(self, debit_spread_position):
        """At DTE ≤3, debit spread should accept total loss ($0)."""
        manager = DTEManager(debit_spread_position.user)
        limit_price, order_type, price_effect = manager._determine_close_parameters(
            debit_spread_position, current_dte=3
        )

        # Accept $0 (total loss)
        assert limit_price == Decimal("0.00")
        assert order_type == "LIMIT"


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
    prefs, _created = TradingAccountPreferences.objects.get_or_create(account=account)
    prefs.is_automated_trading_enabled = True
    prefs.save(update_fields=["is_automated_trading_enabled"])
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


@pytest.mark.django_db(transaction=True)
class TestDTEManagerAutomation:
    @pytest.mark.asyncio
    async def test_close_position_at_dte_submits_order(self, position, manager, open_trade):

        with (
            patch.object(position, "asave", new=AsyncMock()),
            patch.object(manager, "_cancel_open_trades", new=AsyncMock(return_value=[])),
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
            patch.object(position, "asave", new=AsyncMock()),
            patch.object(manager, "_record_closing_trade", new=AsyncMock()),
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
                return_value=(Decimal("0.10"), "LIMIT", "debit"),
            ),
            patch.object(
                manager,
                "_cancel_open_trades",
                new=AsyncMock(return_value=[]),
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
        with patch(
            "services.positions.lifecycle.dte_manager.logger.warning"
        ) as mock_warning:
            await manager.notify_manual_action(position, current_dte=1)
        mock_warning.assert_called_once()
        assert "requires manual closure" in mock_warning.call_args[0][0]
