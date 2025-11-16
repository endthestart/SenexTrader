"""Tests for the DTE monitoring Celery task."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model

import pytest

from accounts.models import TradingAccount, TradingAccountPreferences
from trading.models import Position
from trading.tasks import _async_monitor_positions_for_dte

User = get_user_model()


@pytest.fixture
def automated_user(db):
    """Create user with automated trading account."""
    user = User.objects.create_user(
        email="auto@example.com", username="auto_user", password="testpass123"
    )
    account = TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="AUT123",
        is_primary=True,
        is_active=True,
    )
    TradingAccountPreferences.objects.create(
        account=account,
        is_automated_trading_enabled=True,
    )
    return user


@pytest.fixture
def manual_user(db):
    """Create user with manual trading account."""
    user = User.objects.create_user(
        email="manual@example.com", username="manual_user", password="testpass123"
    )
    TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="MAN123",
        is_primary=True,
        is_active=True,
        is_automated_trading_enabled=False,
    )
    return user


@pytest.fixture
def automated_position(automated_user):
    """Create position for automated trading account."""
    account = TradingAccount.objects.get(user=automated_user)
    expiration = date.today() + timedelta(days=5)
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
        user=automated_user,
        trading_account=account,
        strategy_type="senex_trident",
        symbol="SPY",
        quantity=3,
        lifecycle_state="open_full",
        avg_price=Decimal("2.40"),
        metadata=metadata,
    )


@pytest.fixture
def manual_position(manual_user):
    """Create position for manual trading account."""
    account = TradingAccount.objects.get(user=manual_user)
    expiration = date.today() + timedelta(days=2)
    metadata = {
        "expiration": expiration.isoformat(),
        "strikes": {
            "short_put": "380",
            "long_put": "375",
        },
    }
    return Position.objects.create(
        user=manual_user,
        trading_account=account,
        strategy_type="bull_put_spread",
        symbol="QQQ",
        quantity=2,
        lifecycle_state="open_full",
        avg_price=Decimal("1.50"),
        metadata=metadata,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_async_monitor_positions_closes_positions(automated_position):
    """Test that DTE monitoring closes positions for automated accounts."""
    with patch("trading.tasks.DTEManager") as manager_cls:
        manager_instance = manager_cls.return_value
        manager_instance.calculate_current_dte.return_value = 3
        manager_instance.get_dte_threshold.return_value = 5
        manager_instance.close_position_at_dte = AsyncMock(return_value=True)

        result = await _async_monitor_positions_for_dte()

    assert result == {"status": "success", "evaluated": 1, "closed": 1, "notified": 0}
    manager_instance.close_position_at_dte.assert_awaited_once_with(automated_position, 3)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_async_monitor_positions_respects_manual_accounts(manual_position):
    """Test that DTE monitoring sends notifications for manual accounts."""
    with patch("trading.tasks.DTEManager") as manager_cls:
        manager_instance = manager_cls.return_value
        manager_instance.calculate_current_dte.return_value = 2
        manager_instance.get_dte_threshold.return_value = 7
        manager_instance.notify_manual_action = AsyncMock()

        result = await _async_monitor_positions_for_dte()

    assert result == {"status": "success", "evaluated": 1, "closed": 0, "notified": 1}
    manager_instance.notify_manual_action.assert_awaited_once_with(manual_position, 2)
