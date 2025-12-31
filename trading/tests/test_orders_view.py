"""
Tests for the Orders view.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import TradingAccount
from trading.models import Position, Trade

User = get_user_model()


class OrdersViewTestCase(TestCase):
    """Test cases for the orders view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )
        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            account_number="TEST123",
            is_primary=True,
            connection_type="TASTYTRADE",
            is_active=True,
            access_token="test_token",
            refresh_token="test_refresh_token",
        )
        self.client.login(email="test@example.com", password="testpass123")

    def test_orders_view_loads(self):
        """Test that the orders view loads successfully."""
        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "trading/orders.html")
        assert "enriched_orders" in response.context
        assert "order_count" in response.context

    def test_orders_view_empty_state(self):
        """Test orders view with no active orders."""
        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.context["order_count"] == 0
        self.assertContains(response, "No Active Orders")

    def test_orders_view_with_active_order(self):
        """Test orders view displays active orders."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            strategy_type="senex_trident",
            is_app_managed=True,
            lifecycle_state="pending_entry",
        )

        Trade.objects.create(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id="TEST_ORDER_123",
            trade_type="open",
            quantity=1,
            status="live",
            order_legs=[{"symbol": "QQQ", "quantity": 1, "action": "BUY_TO_OPEN"}],
        )

        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.context["order_count"] == 1
        self.assertContains(response, "QQQ")
        self.assertContains(response, "Senex Trident")
        self.assertNotContains(response, "No Active Orders")

    def test_orders_view_filters_filled_orders(self):
        """Test that filled orders are not displayed."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            strategy_type="senex_trident",
            is_app_managed=True,
            lifecycle_state="open_full",
        )

        # Create a filled order (should not appear)
        Trade.objects.create(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id="FILLED_ORDER",
            trade_type="open",
            quantity=1,
            status="filled",
        )

        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.context["order_count"] == 0
        self.assertNotContains(response, "FILLED_ORDER")

    def test_orders_view_filters_unmanaged_positions(self):
        """Test that orders from unmanaged positions are not displayed."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="AAPL",
            strategy_type="manual",
            is_app_managed=False,
            lifecycle_state="open_full",
        )

        Trade.objects.create(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id="UNMANAGED_ORDER",
            trade_type="open",
            quantity=1,
            status="live",
        )

        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.context["order_count"] == 0
        self.assertNotContains(response, "UNMANAGED_ORDER")

    def test_orders_view_requires_login(self):
        """Test that orders view requires authentication."""
        self.client.logout()
        url = reverse("trading:orders")
        response = self.client.get(url)

        # Should redirect to login page
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_orders_view_enriches_option_legs(self):
        """Test that orders view enriches option leg data."""
        from datetime import date, timedelta

        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            strategy_type="senex_trident",
            is_app_managed=True,
            lifecycle_state="pending_entry",
        )

        # Create order with OCC-formatted option symbols
        expiration = (date.today() + timedelta(days=30)).strftime("%y%m%d")
        trade = Trade.objects.create(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id="TEST_OPTION_ORDER",
            trade_type="open",
            quantity=1,
            status="live",
            order_legs=[
                {
                    "symbol": f"SPY   {expiration}C00450000",
                    "quantity": 1,
                    "action": "SELL_TO_OPEN",
                    "instrument_type": "Equity Option",
                },
                {
                    "symbol": f"SPY   {expiration}C00455000",
                    "quantity": 1,
                    "action": "BUY_TO_OPEN",
                    "instrument_type": "Equity Option",
                },
            ],
        )

        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.status_code == 200
        enriched_orders = response.context["enriched_orders"]

        assert len(enriched_orders) == 1

        order_data = enriched_orders[0]
        assert order_data["order"].id == trade.id
        assert len(order_data["parsed_legs"]) == 2

        # Check first leg (sell 450 call)
        leg1 = order_data["parsed_legs"][0]
        assert leg1["underlying"] == "SPY"
        assert leg1["strike"] == 450.0
        assert leg1["option_type"] == "Call"
        assert leg1["action"] == "SELL_TO_OPEN"

        # Check second leg (buy 455 call)
        leg2 = order_data["parsed_legs"][1]
        assert leg2["underlying"] == "SPY"
        assert leg2["strike"] == 455.0
        assert leg2["option_type"] == "Call"
        assert leg2["action"] == "BUY_TO_OPEN"

        # Check DTE calculation
        assert order_data["dte"] is not None
        assert order_data["dte"] > 25  # Should be around 30 days
        assert order_data["dte"] < 35

    def test_orders_view_displays_profit_targets(self):
        """Test that profit target orders from TastyTradeOrderHistory are displayed."""
        from datetime import date, timedelta

        from trading.models import TastyTradeOrderHistory

        # Create an open position with profit target details
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            strategy_type="senex_trident",
            is_app_managed=True,
            lifecycle_state="open_full",
            profit_target_details={
                "call_spread": {
                    "order_id": "PT_ORDER_123",
                    "percent": 50,
                    "target_price": 1.25,
                }
            },
        )

        # Create a TastyTradeOrderHistory for the profit target
        expiration = (date.today() + timedelta(days=30)).strftime("%y%m%d")
        TastyTradeOrderHistory.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            broker_order_id="PT_ORDER_123",
            underlying_symbol="SPY",
            order_type="Limit",
            status="Live",
            price_effect="Credit",
            order_data={
                "legs": [
                    {
                        "symbol": f"SPY   {expiration}C00450000",
                        "quantity": 1,
                        "action": "BUY_TO_CLOSE",
                    },
                    {
                        "symbol": f"SPY   {expiration}C00455000",
                        "quantity": 1,
                        "action": "SELL_TO_CLOSE",
                    },
                ]
            },
        )

        url = reverse("trading:orders")
        response = self.client.get(url)

        assert response.status_code == 200
        enriched_orders = response.context["enriched_orders"]

        # Should have 1 profit target order
        assert len(enriched_orders) == 1

        order_data = enriched_orders[0]
        order = order_data["order"]

        # Check that it's marked as a profit target
        assert order.is_profit_target

        # Check basic order properties
        assert order.broker_order_id == "PT_ORDER_123"
        assert order.position.id == position.id
        assert order.get_trade_type_display() == "Profit Target"

        # Check that legs are parsed correctly
        assert len(order_data["parsed_legs"]) == 2

        # Verify HTML renders correctly (profit target should not have cancel button)
        self.assertContains(response, "Profit Target")
        self.assertContains(response, "N/A")  # Cancel button replaced with N/A
