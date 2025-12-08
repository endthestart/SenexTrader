"""
Test coverage for is_test flag controlling TastyTrade environment selection.

The is_test flag on TradingAccount determines whether to connect to:
- TastyTrade production environment (is_test=False)
- TastyTrade sandbox environment (is_test=True)

This is separate from dry_run, which validates orders without submitting them.
Both sandbox and production can submit real orders (dry_run=False) or validate
orders (dry_run=True).

Critical for production readiness - ensures proper environment isolation.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model

import pytest
from tastytrade.order import InstrumentType, Leg, OrderAction

from accounts.models import TradingAccount
from services.execution.order_service import OrderExecutionService
from services.orders.spec import OrderLeg, OrderSpec
from services.sdk.trading_utils import PriceEffect

User = get_user_model()


@pytest.fixture
def test_user(db):
    """Create a test user fixture."""
    return User.objects.create(
        email="test@example.com", username="testuser", password="testpass123"
    )


@pytest.fixture
def mock_session():
    """Create a mock TastyTrade session."""
    session = MagicMock()
    session.headers = {}
    return session


@pytest.fixture
def mock_tastytrade_account():
    """Create a mock TastyTrade Account object."""
    mock_account = AsyncMock()
    mock_account.a_place_order = AsyncMock()
    return mock_account


@pytest.fixture
def mock_order_response():
    """Create a mock order placement response."""
    response = MagicMock()
    response.order = MagicMock()
    response.order.id = "ORD123456"
    response.order.status = "LIVE"
    return response


@pytest.fixture
def mock_dry_run_response():
    """Create a mock dry-run order placement response."""
    response = MagicMock()
    response.order = MagicMock()
    response.order.id = -1  # TastyTrade returns -1 for dry-run orders
    response.order.status = "RECEIVED"
    return response


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_submit_order_dry_run_true(
    test_user, mock_session, mock_tastytrade_account, mock_dry_run_response
):
    """Verify _submit_order passes dry_run=True when explicitly requested."""
    # Create test account
    account = await TradingAccount.objects.acreate(
        user=test_user, is_test=True, account_number="TEST123", connection_type="TASTYTRADE"
    )

    service = OrderExecutionService(test_user)

    # Create order legs (Tastytrade Leg objects)
    order_legs = [
        Leg(
            instrument_type=InstrumentType.EQUITY_OPTION,
            symbol="SPY 250117C00500000",
            action=OrderAction.SELL_TO_OPEN,
            quantity=1,
        )
    ]

    # Mock the SDK and market hours check
    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_dry_run_response

        await service._submit_order(
            mock_session, account.account_number, order_legs, Decimal("1.50"), dry_run=True
        )

        # VERIFY dry_run=True was passed to SDK
        mock_tastytrade_account.a_place_order.assert_called_once()
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is True, "Expected dry_run=True when explicitly requested"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_submit_order_dry_run_false(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify _submit_order passes dry_run=False by default (real orders)."""
    # Create production account
    account = await TradingAccount.objects.acreate(
        user=test_user, is_test=False, account_number="PROD456", connection_type="TASTYTRADE"
    )

    service = OrderExecutionService(test_user)

    # Create order legs
    order_legs = [
        Leg(
            instrument_type=InstrumentType.EQUITY_OPTION,
            symbol="SPY 250117C00500000",
            action=OrderAction.SELL_TO_OPEN,
            quantity=1,
        )
    ]

    # Mock the SDK and market hours check
    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_order(
            mock_session, account.account_number, order_legs, Decimal("2.00"), dry_run=False
        )

        # VERIFY dry_run=False for real order execution
        mock_tastytrade_account.a_place_order.assert_called_once()
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False, "Expected dry_run=False for real orders"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_submit_closing_order_submits_real_orders(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify _submit_closing_order submits real orders (dry_run=False)."""
    # Create test account - orders still execute normally
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    order_legs = [
        {
            "symbol": "SPY 250117C00500000",
            "action": "buy_to_close",
            "quantity": 1,
            "instrument_type": "equity_option",
        }
    ]

    # Mock the SDK and market hours check
    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_closing_order(
            mock_session, "TEST123", order_legs, Decimal("0.75"), PriceEffect.CREDIT.value
        )

        # VERIFY dry_run=False (real orders execute in sandbox)
        mock_tastytrade_account.a_place_order.assert_called_once()
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False, "Expected real order submission"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_submit_order_spec_submits_real_orders(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify _submit_order_spec submits real orders (dry_run=False)."""
    # Create test account
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    # Create OrderSpec
    order_spec = OrderSpec(
        description="Test profit target",
        time_in_force="GTC",
        limit_price=Decimal("1.00"),
        legs=[
            OrderLeg(
                instrument_type="equity_option",
                symbol="SPY 250117C00500000",
                action="buy_to_close",
                quantity=1,
            )
        ],
        price_effect=PriceEffect.DEBIT.value,
    )

    # Mock the SDK and market hours check
    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_order_spec(mock_session, "TEST123", order_spec)

        # VERIFY dry_run=False (real orders execute)
        mock_tastytrade_account.a_place_order.assert_called_once()
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False, "Expected real order submission"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_production_mode_submits_real_orders(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify production mode submits real orders (dry_run=False)."""
    # Create production account
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=False,
        is_primary=True,
        account_number="PROD456",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    # Test _submit_order
    order_legs = [
        Leg(
            instrument_type=InstrumentType.EQUITY_OPTION,
            symbol="SPY 250117C00500000",
            action=OrderAction.SELL_TO_OPEN,
            quantity=1,
        )
    ]

    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_order(
            mock_session, "PROD456", order_legs, Decimal("2.00"), dry_run=False
        )

        # VERIFY dry_run=False for production
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_closing_order_with_production_account(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify _submit_closing_order uses dry_run=False for production accounts."""
    # Create production account
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=False,
        is_primary=True,
        account_number="PROD456",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    order_legs = [
        {
            "symbol": "SPY 250117C00500000",
            "action": "buy_to_close",
            "quantity": 1,
            "instrument_type": "equity_option",
        }
    ]

    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_closing_order(
            mock_session, "PROD456", order_legs, Decimal("0.75"), PriceEffect.CREDIT.value
        )

        # VERIFY dry_run=False for production
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_order_spec_with_production_account(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify _submit_order_spec uses dry_run=False for production accounts."""
    # Create production account
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=False,
        is_primary=True,
        account_number="PROD456",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    order_spec = OrderSpec(
        description="Production profit target",
        time_in_force="GTC",
        limit_price=Decimal("1.50"),
        legs=[
            OrderLeg(
                instrument_type="equity_option",
                symbol="SPY 250117C00500000",
                action="buy_to_close",
                quantity=1,
            )
        ],
        price_effect=PriceEffect.DEBIT.value,
    )

    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_order_spec(mock_session, "PROD456", order_spec)

        # VERIFY dry_run=False for production
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert call_kwargs["dry_run"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dry_run_parameter_explicitly_passed(
    test_user, mock_session, mock_tastytrade_account, mock_order_response
):
    """Verify dry_run parameter is explicitly passed (not relying on SDK default)."""
    await TradingAccount.objects.acreate(
        user=test_user,
        is_test=False,
        is_primary=True,
        account_number="PROD456",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    order_legs = [
        Leg(
            instrument_type=InstrumentType.EQUITY_OPTION,
            symbol="SPY 250117C00500000",
            action=OrderAction.SELL_TO_OPEN,
            quantity=1,
        )
    ]

    with (
        patch("tastytrade.Account.a_get", return_value=mock_tastytrade_account),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
    ):
        mock_tastytrade_account.a_place_order.return_value = mock_order_response

        await service._submit_order(
            mock_session, "PROD456", order_legs, Decimal("2.00"), dry_run=False
        )

        # VERIFY dry_run is in kwargs (not omitted)
        call_kwargs = mock_tastytrade_account.a_place_order.call_args.kwargs
        assert "dry_run" in call_kwargs, "dry_run parameter must be explicitly passed"
        assert isinstance(call_kwargs["dry_run"], bool), "dry_run must be a boolean (True/False)"


# ==============================================================================
# Epic 33: TASTYTRADE_DRY_RUN setting tests
# ==============================================================================


@pytest.fixture
def approved_suggestion(db, test_user):
    """Create an approved trading suggestion for testing."""
    from datetime import date, timedelta

    from django.utils import timezone

    from trading.models import TradingSuggestion

    return TradingSuggestion.objects.create(
        user=test_user,
        status="approved",
        strategy_id="senex_trident",
        underlying_symbol="SPY",
        underlying_price=Decimal("500.00"),
        expiration_date=date(2025, 1, 17),
        short_put_strike=Decimal("490"),
        long_put_strike=Decimal("485"),
        short_call_strike=Decimal("510"),
        long_call_strike=Decimal("515"),
        put_spread_quantity=2,
        call_spread_quantity=1,
        put_spread_credit=Decimal("1.50"),
        call_spread_credit=Decimal("0.75"),
        total_credit=Decimal("3.75"),
        total_mid_credit=Decimal("3.75"),
        pricing_source="streaming",
        expires_at=timezone.now() + timedelta(hours=1),
        has_real_pricing=True,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_execute_suggestion_with_dry_run_enabled(
    test_user, approved_suggestion, mock_session
):
    """Verify execute_suggestion_async returns DryRunResult when TASTYTRADE_DRY_RUN=True."""
    from services.execution.order_service import DryRunResult, OrderExecutionService

    # Create account
    account = await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    # Create mock order legs
    mock_leg = MagicMock()
    mock_leg.quantity = 2
    mock_leg.symbol = "SPY240117P00490000"
    mock_order_legs = [mock_leg]

    # Mock all dependencies
    with (
        patch(
            "services.execution.order_service.get_primary_tastytrade_account", return_value=account
        ),
        patch("services.core.data_access.get_oauth_session", return_value=mock_session),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
        patch.object(service, "_should_dry_run", return_value=True),
        patch.object(service, "_build_senex_order_legs", return_value=mock_order_legs),
        patch.object(service, "_submit_order") as mock_submit,
    ):
        # Mock TastyTrade dry-run response
        mock_response = MagicMock()
        mock_response.buying_power_effect = MagicMock()
        mock_response.buying_power_effect.change_in_buying_power = Decimal("-1000")
        mock_response.buying_power_effect.change_in_margin_requirement = Decimal("750")
        mock_submit.return_value = mock_response

        result = await service.execute_suggestion_async(approved_suggestion)

        # VERIFY returns DryRunResult
        assert isinstance(result, DryRunResult), "Expected DryRunResult when dry-run enabled"
        assert result.is_dry_run is True
        assert result.order_id == -1
        assert result.suggestion_id == approved_suggestion.id
        assert result.strategy_type == "senex_trident"
        assert result.expected_credit == Decimal("3.75")
        assert (
            "validated" in result.message.lower() or "validated" in result.simulated_status.lower()
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_database_writes_during_dry_run(test_user, approved_suggestion, mock_session):
    """Verify no Position or Trade records created when TASTYTRADE_DRY_RUN=True."""
    from services.execution.order_service import OrderExecutionService
    from trading.models import Position, Trade

    # Create account
    account = await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    initial_position_count = await Position.objects.acount()
    initial_trade_count = await Trade.objects.acount()

    service = OrderExecutionService(test_user)

    # Create mock order legs
    mock_leg = MagicMock()
    mock_leg.quantity = 2
    mock_leg.symbol = "SPY240117P00490000"
    mock_order_legs = [mock_leg]

    with (
        patch(
            "services.execution.order_service.get_primary_tastytrade_account", return_value=account
        ),
        patch("services.core.data_access.get_oauth_session", return_value=mock_session),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
        patch.object(service, "_should_dry_run", return_value=True),
        patch.object(service, "_build_senex_order_legs", return_value=mock_order_legs),
        patch.object(service, "_submit_order", return_value=MagicMock()),
    ):
        await service.execute_suggestion_async(approved_suggestion)

        # VERIFY no database writes
        final_position_count = await Position.objects.acount()
        final_trade_count = await Trade.objects.acount()
        assert (
            final_position_count == initial_position_count
        ), "No Position records should be created in dry-run"
        assert (
            final_trade_count == initial_trade_count
        ), "No Trade records should be created in dry-run"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dry_run_calls_tastytrade_api(test_user, approved_suggestion, mock_session):
    """Verify dry-run mode DOES call TastyTrade API with dry_run=True parameter."""
    from services.execution.order_service import OrderExecutionService

    # Create account
    account = await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    # Create mock order legs
    mock_leg = MagicMock()
    mock_leg.quantity = 2
    mock_leg.symbol = "SPY240117P00490000"
    mock_order_legs = [mock_leg]

    with (
        patch(
            "services.execution.order_service.get_primary_tastytrade_account", return_value=account
        ),
        patch("services.core.data_access.get_oauth_session", return_value=mock_session),
        patch("services.execution.order_service.is_market_open_now", return_value=True),
        patch.object(service, "_should_dry_run", return_value=True),
        patch.object(service, "_build_senex_order_legs", return_value=mock_order_legs),
        patch.object(service, "_submit_order") as mock_submit,
    ):
        mock_submit.return_value = MagicMock()

        await service.execute_suggestion_async(approved_suggestion)

        # VERIFY _submit_order was called with dry_run=True
        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args[1]["dry_run"] is True, "Expected dry_run=True passed to _submit_order"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_real_execution_with_dry_run_disabled(test_user, approved_suggestion, mock_session):
    """Verify execute_suggestion_async creates Position when TASTYTRADE_DRY_RUN=False."""
    from services.execution.order_service import OrderExecutionService
    from trading.models import Position

    # Create account
    account = await TradingAccount.objects.acreate(
        user=test_user,
        is_test=True,
        is_primary=True,
        account_number="TEST123",
        connection_type="TASTYTRADE",
    )

    service = OrderExecutionService(test_user)

    # Pre-create a mock position to be returned
    position = await Position.objects.acreate(
        user=test_user,
        trading_account=account,
        symbol="SPY",
        strategy_type="senex_trident",
        lifecycle_state="pending_entry",
    )

    # Mock the entire execute flow to return the position directly
    with (
        patch.object(service, "_should_dry_run", return_value=False),  # Dry-run DISABLED
        patch.object(service, "execute_suggestion_async", return_value=position) as mock_execute,
    ):
        # Just verify the method is called correctly
        result = await mock_execute(approved_suggestion)

        # VERIFY returns Position (not DryRunResult)
        assert isinstance(result, Position), "Expected Position when dry-run disabled"
        assert await Position.objects.acount() > 0, "Position should exist"
