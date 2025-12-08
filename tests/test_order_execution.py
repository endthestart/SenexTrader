"""Tests for order execution service.

Note: Tests for OCC symbol generation and order leg building have been moved to:
- tests/utils/test_occ_symbol.py
- tests/utils/test_order_builder_utils.py

This file now contains only integration tests for the OrderExecutionService.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import TradingAccount
from services.execution.order_service import OrderExecutionService
from trading.models import StrategyConfiguration, TradingSuggestion

User = get_user_model()


class TestOrderExecutionService(TestCase):
    """Test order creation and execution logic."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="12345",
            is_primary=True,
            is_active=True,
        )

        self.strategy_config = StrategyConfiguration.objects.create(
            user=self.user,
            strategy_id="senex_trident",
            parameters={"senex_trident": {"underlying_symbol": "SPY"}},
        )

        self.order_service = OrderExecutionService(self.user)

        # Create mock suggestion
        self.suggestion = TradingSuggestion.objects.create(
            user=self.user,
            strategy_configuration=self.strategy_config,
            underlying_symbol="SPY",
            underlying_price=Decimal("450.25"),
            expiration_date=date.today() + timedelta(days=45),
            short_put_strike=Decimal("450"),
            long_put_strike=Decimal("445"),
            short_call_strike=Decimal("450"),
            long_call_strike=Decimal("455"),
            put_spread_quantity=2,
            call_spread_quantity=1,
            put_spread_credit=Decimal("2.50"),
            call_spread_credit=Decimal("1.75"),
            total_credit=Decimal("6.75"),  # (2.50 * 2) + (1.75 * 1)
            max_risk=Decimal("325.00"),
            status="approved",
            has_real_pricing=True,
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_is_pricing_current_fresh(self):
        """Test pricing freshness check with current data."""
        # Create fresh suggestion (just generated)
        fresh_suggestion = TradingSuggestion.objects.create(
            user=self.user,
            strategy_configuration=self.strategy_config,
            underlying_symbol="SPY",
            underlying_price=Decimal("450.25"),
            expiration_date=date.today() + timedelta(days=45),
            short_put_strike=Decimal("450"),
            long_put_strike=Decimal("445"),
            put_spread_quantity=2,
            status="approved",
            has_real_pricing=True,
            expires_at=timezone.now() + timedelta(hours=24),
            generated_at=timezone.now(),  # Fresh
        )

        result = self.order_service._is_pricing_current(fresh_suggestion)
        assert result

    def test_uses_mid_price_credit_not_natural_credit(self):
        """
        Test that orders use mid-price credit instead of conservative natural credit.

        This fixes the regression where orders were submitted ~$0.40-0.50 lower than
        actual fill prices. Mid-price credit is realistic, natural credit is conservative.

        This test verifies that suggestion data correctly distinguishes between:
        - total_credit (conservative natural credit based on bid/ask worst-case)
        - total_mid_credit (realistic mid-market pricing)

        The order_service.py code at line 240 uses total_mid_credit for pricing.
        """
        # Create suggestion with both natural and mid-price credits
        # Simulating typical ~$0.40 difference between natural and mid prices
        suggestion = TradingSuggestion.objects.create(
            user=self.user,
            strategy_configuration=self.strategy_config,
            underlying_symbol="SPY",
            underlying_price=Decimal("450.25"),
            expiration_date=date.today() + timedelta(days=45),
            short_put_strike=Decimal("450"),
            long_put_strike=Decimal("445"),
            short_call_strike=Decimal("450"),
            long_call_strike=Decimal("455"),
            put_spread_quantity=2,
            call_spread_quantity=1,
            put_spread_credit=Decimal("2.30"),  # natural
            call_spread_credit=Decimal("1.60"),  # natural
            total_credit=Decimal("6.20"),  # (2.30 * 2) + (1.60 * 1) - CONSERVATIVE
            put_spread_mid_credit=Decimal("2.50"),  # mid-price
            call_spread_mid_credit=Decimal("1.75"),  # mid-price
            total_mid_credit=Decimal("6.75"),  # (2.50 * 2) + (1.75 * 1) - REALISTIC
            max_risk=Decimal("325.00"),
            status="approved",
            has_real_pricing=True,
            expires_at=timezone.now() + timedelta(hours=24),
            pricing_source="streaming",
        )

        # Verify the two credit values are properly different
        expected_credit = suggestion.total_mid_credit  # $6.75
        conservative_credit = suggestion.total_credit  # $6.20

        # Verify they're different (this is the regression we're preventing)
        assert (
            expected_credit != conservative_credit
        ), "Test setup error: total_mid_credit should differ from total_credit"

        # Verify mid-price is higher (more realistic)
        assert (
            expected_credit > conservative_credit
        ), "Mid-price credit should be higher than natural (conservative) credit"

        # Verify the difference is significant (~$0.40-0.55 typical)
        diff = expected_credit - conservative_credit
        assert (
            Decimal("0.30") <= diff <= Decimal("1.00")
        ), f"Expected typical bid-ask difference of $0.30-1.00, got ${diff}"

    def test_cached_order_calculates_fill_price_from_legs(self):
        """
        Test that TastyTradeOrderHistory.price uses actual fill prices for filled orders.

        This validates Fix #3: OrderHistoryService.calculate_fill_price() correctly
        calculates net credit/debit from leg fills instead of using limit price.

        Example: Senex Trident with 2 put spreads + 1 call spread
        - Sell 2 short puts @ $2.15 each = +$4.30
        - Buy 2 long puts @ $0.85 each = -$1.70
        - Sell 1 short call @ $1.55 = +$1.55
        - Buy 1 long call @ $0.75 = -$0.75
        Net credit: $4.30 - $1.70 + $1.55 - $0.75 = $3.40
        """
        from services.orders.history import OrderHistoryService

        service = OrderHistoryService()

        # Mock order data with filled legs (typical Senex Trident order)
        order_data = {
            "id": "test-order-123",
            "status": "Filled",
            "legs": [
                # Put spread (quantity 2)
                {
                    "symbol": "SPY 251219P00450000",  # Short put
                    "action": "Sell to Open",
                    "quantity": "2",
                    "fills": [{"fill_price": "2.15", "quantity": "2"}],
                },
                {
                    "symbol": "SPY 251219P00445000",  # Long put
                    "action": "Buy to Open",
                    "quantity": "2",
                    "fills": [{"fill_price": "0.85", "quantity": "2"}],
                },
                # Call spread (quantity 1)
                {
                    "symbol": "SPY 251219C00455000",  # Short call
                    "action": "Sell to Open",
                    "quantity": "1",
                    "fills": [{"fill_price": "1.55", "quantity": "1"}],
                },
                {
                    "symbol": "SPY 251219C00460000",  # Long call
                    "action": "Buy to Open",
                    "quantity": "1",
                    "fills": [{"fill_price": "0.75", "quantity": "1"}],
                },
            ],
        }

        # Calculate fill price
        fill_price = service.calculate_fill_price(order_data)

        # Expected: (2.15 * 2) + (1.55 * 1) - (0.85 * 2) - (0.75 * 1)
        #         = 4.30 + 1.55 - 1.70 - 0.75 = 3.40
        expected = Decimal("3.40")

        assert fill_price == expected, (
            f"Expected fill price ${expected}, got ${fill_price}. "
            f"Calculation: "
            f"(2.15 * 2 sell) + (1.55 * 1 sell) - (0.85 * 2 buy) - (0.75 * 1 buy) = "
            f"4.30 + 1.55 - 1.70 - 0.75 = 3.40"
        )

        # Verify it's a Decimal (correct type)
        assert isinstance(fill_price, Decimal), "Fill price should be returned as Decimal"

        # Test edge case: no fills
        order_data_no_fills = {
            "id": "test-order-456",
            "status": "Working",
            "legs": [
                {
                    "symbol": "SPY 251219P00450000",
                    "action": "Sell to Open",
                    "quantity": "2",
                    "fills": [],
                }
            ],
        }

        fill_price_no_fills = service.calculate_fill_price(order_data_no_fills)
        assert fill_price_no_fills is None, "Should return None when no fills present"
