"""Unit tests for the ProfitCalculator lifecycle helper."""

from decimal import Decimal

from django.contrib.auth import get_user_model

import pytest

from accounts.models import TradingAccount
from services.positions.lifecycle.profit_calculator import ProfitCalculator
from trading.models import Position, Trade

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="calc_test@example.com", username="calc_user", password="testpass123"
    )


@pytest.fixture
def account(user):
    return TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="ACCT123",
        is_primary=True,
        is_active=True,
    )


@pytest.fixture
def position(user, account):
    return Position.objects.create(
        user=user,
        trading_account=account,
        strategy_type="senex_trident",
        symbol="SPY",
        quantity=2,
        lifecycle_state="open_full",
        avg_price=Decimal("2.50"),
        opening_price_effect="Credit",  # Must match PriceEffect.CREDIT.value
    )


@pytest.fixture
def calculator():
    return ProfitCalculator()


@pytest.mark.django_db
class TestProfitCalculator:
    def test_calculate_trade_pnl_credit_position(self, calculator, position, account, user):
        trade = Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="close1",
            trade_type="close",
            order_legs=[],
            quantity=1,  # Quantity stored as positive in our system
            status="filled",
            executed_price=Decimal("1.00"),
        )

        pnl = calculator.calculate_trade_pnl(trade)
        assert pnl == Decimal("150.00")  # (2.50 - 1.00) * 100

    def test_calculate_trade_pnl_debit_position(self, calculator, account, user):
        debit_position = Position.objects.create(
            user=user,
            trading_account=account,
            strategy_type="senex_trident",
            symbol="QQQ",
            quantity=1,
            lifecycle_state="open_full",
            avg_price=Decimal("1.20"),
            opening_price_effect="Debit",  # Must match PriceEffect.DEBIT.value
        )
        trade = Trade.objects.create(
            user=user,
            position=debit_position,
            trading_account=account,
            broker_order_id="close2",
            trade_type="close",
            order_legs=[],
            quantity=1,  # Quantity stored as positive in our system
            status="filled",
            executed_price=Decimal("1.45"),
        )

        pnl = calculator.calculate_trade_pnl(trade)
        assert pnl == Decimal("25.00")  # (1.45 - 1.20) * 100

    def test_calculate_position_realized_aggregates_trades(
        self, calculator, position, account, user
    ):
        Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="open1",
            trade_type="open",
            order_legs=[],
            quantity=2,
            status="filled",
        )
        Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="close_realized",
            trade_type="close",
            order_legs=[],
            quantity=1,  # Quantity stored as positive in our system
            status="filled",
            realized_pnl=Decimal("120.00"),
        )
        Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="close_calc",
            trade_type="close",
            order_legs=[],
            quantity=1,  # Quantity stored as positive in our system
            status="filled",
            executed_price=Decimal("1.10"),
        )
        # Non-filled trade should be ignored
        Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="close_pending",
            trade_type="close",
            order_legs=[],
            quantity=1,
            status="pending",
            executed_price=Decimal("1.30"),
        )

        realised = calculator.calculate_position_realized(position)
        # Realized trade contributes 120, calculated trade: (2.5 - 1.1) * 100 = 140
        assert realised == Decimal("260.00")

    def test_calculate_position_unrealized_defaults_to_zero(self, calculator, position):
        position.unrealized_pnl = None
        assert calculator.calculate_position_unrealized(position) == Decimal("0.00")

    def test_calculate_position_unrealized_quantizes(self, calculator, position):
        position.unrealized_pnl = Decimal("42.345")
        assert calculator.calculate_position_unrealized(position) == Decimal("42.35")

    def test_calculate_position_breakdown_combines_values(
        self, calculator, position, account, user
    ):
        Trade.objects.create(
            user=user,
            position=position,
            trading_account=account,
            broker_order_id="close3",
            trade_type="close",
            order_legs=[],
            quantity=1,  # Quantity stored as positive in our system
            status="filled",
            executed_price=Decimal("1.20"),
        )
        position.unrealized_pnl = Decimal("15.111")

        breakdown = calculator.calculate_position_breakdown(position)
        assert breakdown.realized == Decimal("130.00")  # (2.5 - 1.2) * 100
        assert breakdown.unrealized == Decimal("15.11")
