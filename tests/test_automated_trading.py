"""Tests for automated trading service and Celery task."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

import pytest

from accounts.models import TradingAccount
from trading.models import StrategyConfiguration
from trading.services.automated_trading_service import AutomatedTradingService
from trading.tasks import automated_daily_trade_cycle

User = get_user_model()


@pytest.mark.django_db
class AutomatedDailyTradeCycleTest(TestCase):
    """Verify Celery task delegates to service layer appropriately."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="secret123"
        )
        account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="ACC123",
            is_active=True,
            is_primary=True,
        )
        # Use the property setter to update via the model's mechanism
        account.is_automated_trading_enabled = True

    @patch(
        "trading.services.automated_trading_service.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "success"},
    )
    def test_success_counts_processed(self, mock_process_account):
        result = automated_daily_trade_cycle()

        assert result == {"processed": 1, "succeeded": 1, "failed": 0, "skipped": 0}
        assert mock_process_account.call_count == 1

    @patch(
        "trading.services.automated_trading_service.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "skipped", "reason": "trade_exists_today"},
    )
    def test_skipped_user_reported(self, mock_process_account):
        result = automated_daily_trade_cycle()

        assert result == {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 1}
        assert mock_process_account.call_count == 1

    @patch(
        "trading.services.automated_trading_service.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "failed", "reason": "boom"},
    )
    def test_failure_counts(self, mock_process_account):
        result = automated_daily_trade_cycle()

        assert result == {"processed": 0, "succeeded": 0, "failed": 1, "skipped": 0}
        assert mock_process_account.call_count == 1

    @patch(
        "trading.services.automated_trading_service.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        return_value={"status": "success"},
    )
    def test_disabled_account_not_processed(self, mock_process_account):
        account = TradingAccount.objects.get(user=self.user)
        # The setter automatically saves to preferences
        account.is_automated_trading_enabled = False

        automated_daily_trade_cycle()

        mock_process_account.assert_not_called()

    @patch(
        "trading.services.automated_trading_service.AutomatedTradingService.a_process_account",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    )
    def test_service_exception_treated_as_failure(self, mock_process_account):
        result = automated_daily_trade_cycle()

        assert result == {"processed": 0, "succeeded": 0, "failed": 1, "skipped": 0}
        assert mock_process_account.call_count == 1


@pytest.mark.django_db(transaction=True)
class TestAutomatedTradingService:
    """Unit tests for asynchronous service methods."""

    @pytest.fixture(autouse=True)
    def default_user(self, django_user_model):
        self.user = django_user_model.objects.create_user(
            username="auto", email="auto@example.com", password="secret123"
        )
        self.account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="ACC999",
            is_active=True,
            is_primary=True,
        )
        # Use the property setter to update via the model's mechanism
        self.account.is_automated_trading_enabled = True
        # Refresh to pick up the preference
        self.account.refresh_from_db()

        StrategyConfiguration.objects.get_or_create(
            user=self.user,
            strategy_id="senex_trident",
            defaults={"is_active": True},
        )

    @pytest.mark.asyncio
    async def test_a_process_account_skips_existing_trade(self):
        """Test that the service skips processing when a trade already exists.

        We mock the Trade.objects.filter query to simulate an existing trade
        because async DB access in tests can have transaction isolation issues.
        """
        with (
            patch(
                "trading.services.automated_trading_service.is_market_open_now",
                return_value=True,
            ),
            patch(
                "trading.services.automated_trading_service.Trade.objects.filter"
            ) as mock_filter,
        ):
            # Make the filter chain return exists() = True
            mock_filter.return_value.exclude.return_value.exists.return_value = True

            service = AutomatedTradingService()
            result = await service.a_process_account(self.account)

        assert result["status"] == "skipped"
        assert result["reason"] == "trade_exists_today"

    @pytest.mark.asyncio
    async def test_a_process_account_handles_no_suggestion(self):
        with (
            patch(
                "trading.services.automated_trading_service.is_market_open_now",
                return_value=True,
            ),
            patch.object(
                AutomatedTradingService,
                "a_generate_suggestion",
                AsyncMock(return_value=None),
            ),
        ):
            service = AutomatedTradingService()
            result = await service.a_process_account(self.account)

        assert result == {
            "status": "skipped",
            "reason": "unsuitable_market_conditions",
        }

    @pytest.mark.asyncio
    async def test_a_process_account_success(self):
        suggestion = MagicMock()
        suggestion.id = 10
        suggestion.underlying_symbol = "SPY"

        mock_position = MagicMock()
        mock_position.id = 55

        with (
            patch(
                "trading.services.automated_trading_service.is_market_open_now",
                return_value=True,
            ),
            patch.object(
                AutomatedTradingService,
                "a_generate_suggestion",
                AsyncMock(return_value=suggestion),
            ),
            patch(
                "trading.services.automated_trading_service.RiskValidationService.validate_trade_risk",
                AsyncMock(return_value={"valid": True}),
            ),
            patch(
                "trading.services.automated_trading_service.OrderExecutionService"
            ) as mock_order_service,
            patch.object(AutomatedTradingService, "send_notification") as mock_notify,
            patch.object(
                AutomatedTradingService, "_calculate_automation_credit", return_value=None
            ),
        ):
            mock_order_service.return_value.execute_suggestion_async = AsyncMock(
                return_value=mock_position
            )

            service = AutomatedTradingService()
            result = await service.a_process_account(self.account)

        assert result == {
            "status": "success",
            "suggestion_id": 10,
            "position_id": 55,
            "symbol": "SPY",
        }
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_process_account_execution_failure(self):
        suggestion = MagicMock()
        suggestion.id = 11
        suggestion.underlying_symbol = "QQQ"

        with (
            patch(
                "trading.services.automated_trading_service.is_market_open_now",
                return_value=True,
            ),
            patch.object(
                AutomatedTradingService,
                "a_generate_suggestion",
                AsyncMock(return_value=suggestion),
            ),
            patch(
                "trading.services.automated_trading_service.RiskValidationService.validate_trade_risk",
                AsyncMock(return_value={"valid": True}),
            ),
            patch(
                "trading.services.automated_trading_service.OrderExecutionService"
            ) as mock_order_service,
            patch.object(
                AutomatedTradingService, "_calculate_automation_credit", return_value=None
            ),
        ):
            mock_order_service.return_value.execute_suggestion_async = AsyncMock(return_value=None)

            service = AutomatedTradingService()
            result = await service.a_process_account(self.account)

        assert result["status"] == "failed"
        assert result["reason"] == "execution_failed"

    @pytest.mark.asyncio
    async def test_a_generate_suggestion_marks_automated(self):
        mock_manager = AsyncMock()
        mock_manager.ensure_streaming_for_automation.return_value = True

        mock_suggestion = MagicMock()
        mock_suggestion.id = 77
        mock_suggestion.status = "pending"
        mock_suggestion.save = MagicMock()
        mock_manager.a_process_suggestion_request.return_value = mock_suggestion

        mock_context = {
            "config_id": 1,
            "market_snapshot": {},
            "current_price": Decimal("450.00"),
            "spread_width": 5,
            "strikes": {
                "short_put": Decimal("445"),
                "long_put": Decimal("440"),
                "short_call": Decimal("455"),
                "long_call": Decimal("460"),
            },
            "occ_bundle": {
                "underlying": "SPY",
                "expiration": timezone.now().date().isoformat(),
                "legs": {},
            },
        }

        with (
            patch(
                "streaming.services.stream_manager.GlobalStreamManager.get_user_manager",
                AsyncMock(return_value=mock_manager),
            ),
            patch(
                "trading.services.automated_trading_service.SenexTridentStrategy"
            ) as mock_strategy,
        ):
            # Make a_prepare_suggestion_context return an awaitable
            mock_strategy.return_value.a_prepare_suggestion_context = AsyncMock(
                return_value=mock_context
            )

            service = AutomatedTradingService()
            suggestion = await service.a_generate_suggestion(self.user)

        assert suggestion is mock_suggestion
        assert mock_manager.a_process_suggestion_request.call_args[0][0]["is_automated"] is True

    @pytest.mark.asyncio
    async def test_a_process_account_risk_validation_failure(self):
        suggestion = MagicMock()
        suggestion.id = 88
        suggestion.underlying_symbol = "DIA"

        with (
            patch(
                "trading.services.automated_trading_service.is_market_open_now",
                return_value=True,
            ),
            patch.object(
                AutomatedTradingService,
                "a_generate_suggestion",
                AsyncMock(return_value=suggestion),
            ),
            patch(
                "trading.services.automated_trading_service.RiskValidationService.validate_trade_risk",
                AsyncMock(return_value={"valid": False, "message": "Too risky"}),
            ),
        ):
            service = AutomatedTradingService()
            result = await service.a_process_account(self.account)

        assert result["status"] == "skipped"
        assert result["reason"] == "risk_validation_failed"

    def test_calculate_automation_credit_respects_offset(self):
        service = AutomatedTradingService()
        account = self.account
        account.automated_entry_offset_cents = 4

        suggestion = MagicMock()
        suggestion.total_mid_credit = Decimal("4.03")
        suggestion.total_credit = Decimal("3.96")
        suggestion.price_effect = "credit"

        credit = service._calculate_automation_credit(account, suggestion)

        assert float(credit) == pytest.approx(3.99)

    def test_automated_trading_small_offset_doesnt_hit_floor(self):
        """
        Test normal automation with small offset - floor doesn't trigger.

        This is the typical case with user's 2¢ offset setting.
        With mid=$4.00, offset=2¢, natural=$3.60, the floor doesn't activate.
        """
        service = AutomatedTradingService()
        account = self.account
        account.automated_entry_offset_cents = 2

        suggestion = MagicMock()
        suggestion.id = 123
        suggestion.total_mid_credit = Decimal("4.00")
        suggestion.total_credit = Decimal("3.60")  # Natural credit ~40¢ lower
        suggestion.price_effect = "credit"

        credit = service._calculate_automation_credit(account, suggestion)

        # Should be mid - offset = $4.00 - $0.02 = $3.98
        # Floor at $3.60 should NOT trigger because $3.98 > $3.60
        assert credit == Decimal("3.98")
        assert credit > Decimal("3.60")  # Didn't hit floor

    def test_automated_trading_large_offset_hits_floor(self):
        """
        Test large offset triggers floor safety mechanism.

        With offset=50¢ and narrow spread, floor prevents absurdly low submission.
        """
        service = AutomatedTradingService()
        account = self.account
        account.automated_entry_offset_cents = 50  # Unusually large

        suggestion = MagicMock()
        suggestion.id = 124
        suggestion.total_mid_credit = Decimal("1.00")
        suggestion.total_credit = Decimal("0.80")  # Natural credit 20¢ lower
        suggestion.price_effect = "credit"

        credit = service._calculate_automation_credit(account, suggestion)

        # Without floor: $1.00 - $0.50 = $0.50
        # With floor: max($0.50, $0.80) = $0.80
        assert credit == Decimal("0.80")  # Floored at natural credit

    def test_automated_trading_debit_adds_offset_no_floor(self):
        """
        Test debit orders ADD offset (pay more to ensure fill) with no floor.

        Verifies asymmetry is correct: buying adds offset, selling subtracts.
        No floor needed for debits - we're already paying above mid.
        """
        service = AutomatedTradingService()
        account = self.account
        account.automated_entry_offset_cents = 5

        suggestion = MagicMock()
        suggestion.id = 125
        suggestion.total_mid_credit = Decimal("2.00")
        suggestion.total_credit = Decimal("1.85")  # Not used for debits
        suggestion.price_effect = "debit"

        credit = service._calculate_automation_credit(account, suggestion)

        # Should be mid + offset = $2.00 + $0.05 = $2.05
        # No floor for debits
        assert credit == Decimal("2.05")

    def test_automation_fails_when_mid_credit_unavailable(self):
        """
        Test automation rejects orders with missing mid-credit (real data or fail).

        Verifies fail-fast principle: no fallbacks to conservative pricing.
        """
        service = AutomatedTradingService()
        account = self.account
        account.automated_entry_offset_cents = 2

        suggestion = MagicMock()
        suggestion.id = 126
        suggestion.total_mid_credit = None  # Missing streaming data
        suggestion.total_credit = Decimal("3.60")
        suggestion.price_effect = "credit"

        credit = service._calculate_automation_credit(account, suggestion)

        # Should return None (fail) instead of falling back to total_credit
        assert credit is None
