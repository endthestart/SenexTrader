"""Tests for the run_automated_trade management command."""

from unittest.mock import AsyncMock, patch

from django.core.management import CommandError, call_command
from django.utils import timezone

import pytest

from accounts.models import TradingAccount
from trading.models import Position, Trade


@pytest.fixture
def trading_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="cliuser",
        email="cli@example.com",
        password="secret123",
    )
    account = TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="CLI123",
        is_active=True,
        is_primary=True,
    )
    # Use property setter which automatically saves to preferences
    account.is_automated_trading_enabled = True
    return user


pytestmark = [pytest.mark.django_db(transaction=True)]


def test_command_single_user_success(trading_user, capsys):
    with patch(
        "trading.management.commands.run_automated_trade.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "success", "suggestion_id": 1, "position_id": 2, "symbol": "SPY"},
    ) as mock_process:
        call_command("run_automated_trade", "--user", trading_user.email)

    out = capsys.readouterr().out
    assert "Success!" in out
    mock_process.assert_called_once()


def test_command_dry_run_skips_execution(trading_user, capsys):
    with patch(
        "trading.management.commands.run_automated_trade.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
    ) as mock_process:
        call_command("run_automated_trade", "--user", trading_user.email, "--dry-run")

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    mock_process.assert_not_called()


def _create_trade(user, status):
    account = TradingAccount.objects.get(user=user)
    position = Position.objects.create(
        user=user,
        trading_account=account,
        strategy_type="senex_trident",
        symbol="SPY",
        lifecycle_state="open_full",
    )
    return Trade.objects.create(
        user=user,
        position=position,
        trading_account=account,
        broker_order_id=f"ORD-{status}-{timezone.now().timestamp()}",
        trade_type="open",
        order_legs=[],
        quantity=1,
        status=status,
    )


def test_command_allows_retry_after_cancelled_trade(trading_user, capsys):
    _create_trade(trading_user, status="cancelled")

    with patch(
        "trading.management.commands.run_automated_trade.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "success", "suggestion_id": 2, "position_id": 5, "symbol": "QQQ"},
    ) as mock_process:
        call_command("run_automated_trade", "--user", trading_user.email)

    out = capsys.readouterr().out
    assert "Success!" in out
    mock_process.assert_called_once()


def test_command_all_eligible_users(trading_user, django_user_model, capsys):
    second_user = django_user_model.objects.create_user(
        username="cliuser2",
        email="cli2@example.com",
        password="secret123",
    )
    account = TradingAccount.objects.create(
        user=second_user,
        connection_type="TASTYTRADE",
        account_number="CLI456",
        is_active=True,
        is_primary=True,
    )
    # Use property setter which automatically saves to preferences
    account.is_automated_trading_enabled = True

    with patch(
        "trading.management.commands.run_automated_trade.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        side_effect=[
            {"status": "success", "suggestion_id": 1, "position_id": 1, "symbol": "SPY"},
            {"status": "skipped", "reason": "market_unavailable"},
        ],
    ) as mock_process:
        call_command("run_automated_trade", "--all")

    out = capsys.readouterr().out
    assert "SUMMARY" in out
    assert mock_process.call_count == 2


def test_command_user_not_found():
    with pytest.raises(CommandError) as excinfo:
        call_command("run_automated_trade", "--user", "missing@example.com")

    assert "not found" in str(excinfo.value)


def test_command_ineligible_user(trading_user, capsys):
    account = TradingAccount.objects.get(user=trading_user)
    account.is_active = False
    account.save(update_fields=["is_active"])

    with patch(
        "trading.management.commands.run_automated_trade.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
    ) as mock_process:
        call_command("run_automated_trade", "--user", trading_user.email)

    out = capsys.readouterr().out
    assert "not eligible" in out
    mock_process.assert_not_called()
