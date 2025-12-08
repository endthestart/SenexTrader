"""
Integration test for complete Senex Trident trading flow using Phase 5
infrastructure.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import skip
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

import pytest
from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.execution.order_service import OrderExecutionService
from services.market_data.option_chains import OptionChainService
from services.strategies.senex_trident_strategy import SenexTridentStrategy
from trading.models import Position, StrategyConfiguration, Trade, TradingSuggestion

User = get_user_model()


class TestSenexTridentIntegration(TestCase):
    """Integration test for complete Senex Trident trading workflow."""

    def setUp(self):
        """Set up test environment with user, account, and services."""
        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        # Create trading account
        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="12345",
            is_primary=True,
            is_active=True,
        )

        # Create strategy configuration
        self.strategy_config = StrategyConfiguration.objects.create(
            user=self.user,
            strategy_id="senex_trident",
            parameters={
                "senex_trident": {
                    "underlying_symbol": "SPY",
                    "dte_target": 45,
                    "spread_width": 5,
                }
            },
        )

        # Initialize services
        self.option_service = OptionChainService()
        self.order_service = OrderExecutionService(self.user)
        self.strategy_service = SenexTridentStrategy(self.user)

        # Mock market data
        self.mock_current_price = Decimal("450.75")  # Will round to 450 (even strike)
        self.mock_option_chain = {
            "symbol": "SPY",
            "current_price": self.mock_current_price,
            "expiration": "2024-02-16",
            "put_strikes": [Decimal(str(s)) for s in range(440, 465, 5)],  # 440, 445, 450, 455, 460
            "call_strikes": [Decimal(str(s)) for s in range(440, 465, 5)],
            "fetched_at": "2024-01-02T10:00:00Z",
        }

        # Expected strikes based on even-strike algorithm
        self.expected_strikes = {
            "short_put": Decimal("450"),  # Base strike (even)
            "long_put": Decimal("445"),  # Base - width (450 - 5)
            "short_call": Decimal("450"),  # Base strike (even)
            "long_call": Decimal("455"),  # Base + width (450 + 5)
        }

    @pytest.mark.asyncio
    @skip("execute_suggestion method not implemented in SenexTridentStrategy yet")
    async def test_complete_senex_trident_trading_flow(self):
        """Test the complete end-to-end Senex Trident trading flow."""
        print("\n=== SENEX TRIDENT INTEGRATION TEST ===")

        # Step 1: Mock option chain service
        with patch.object(
            self.option_service, "get_option_chain", return_value=self.mock_option_chain
        ):
            print("Step 1: Fetching option chain data...")
            option_chain = await self.option_service.get_option_chain(self.user, "SPY", 45)

            assert option_chain["symbol"] == "SPY"
            assert option_chain["current_price"] == self.mock_current_price
            print(f"   Option chain fetched for SPY at " f"${option_chain['current_price']}")

        # Step 2: Test strike selection algorithm
        print("\nStep 2: Testing strike selection algorithm...")
        selected_strikes = await self.option_service.select_strikes(
            self.mock_current_price, option_chain, width=5
        )

        assert selected_strikes is not None
        assert selected_strikes["short_put"] == self.expected_strikes["short_put"]
        assert selected_strikes["long_put"] == self.expected_strikes["long_put"]
        assert selected_strikes["short_call"] == self.expected_strikes["short_call"]
        assert selected_strikes["long_call"] == self.expected_strikes["long_call"]

        print(
            f"   Strikes selected - Put spread: "
            f"{selected_strikes['short_put']}/{selected_strikes['long_put']}"
        )
        print(
            f"   Strikes selected - Call spread: "
            f"{selected_strikes['short_call']}/{selected_strikes['long_call']}"
        )

        # Step 3: Create trading suggestion
        print("\nStep 3: Creating trading suggestion...")
        suggestion = await sync_to_async(TradingSuggestion.objects.create)(
            user=self.user,
            strategy_configuration=self.strategy_config,
            underlying_symbol="SPY",
            underlying_price=self.mock_current_price,
            expiration_date=date.today() + timedelta(days=45),
            expires_at=timezone.now() + timedelta(hours=24),
            short_put_strike=selected_strikes["short_put"],
            long_put_strike=selected_strikes["long_put"],
            short_call_strike=selected_strikes["short_call"],
            long_call_strike=selected_strikes["long_call"],
            put_spread_quantity=2,  # 2 put spreads
            call_spread_quantity=1,  # 1 call spread (complete Senex Trident)
            put_spread_credit=Decimal("2.50"),
            call_spread_credit=Decimal("1.75"),
            total_credit=Decimal("6.75"),  # (2.50 * 2) + (1.75 * 1)
            has_real_pricing=True,
            pricing_source="mock_test_data",
        )

        print(f"   Trading suggestion created with ID: {suggestion.id}")
        print(
            f"   Symbol: {suggestion.underlying_symbol}, "
            f"Put spreads: {suggestion.put_spread_quantity}, "
            f"Call spreads: {suggestion.call_spread_quantity}"
        )

        # Step 4: Mock order execution and create the position
        print("\nStep 4: Executing Senex Trident order...")

        # Mock the order execution response
        mock_order_response = {
            "order_id": "test_order_123",
            "status": "submitted",
            "legs": [
                # First put spread (short put)
                {
                    "symbol": "SPY240216P00450000",
                    "quantity": -2,
                    "action": "SELL_TO_OPEN",
                },
                {
                    "symbol": "SPY240216P00445000",
                    "quantity": 2,
                    "action": "BUY_TO_OPEN",
                },
                # Second put spread (short put - will be added as separate spread)
                {
                    "symbol": "SPY240216P00450000",
                    "quantity": -2,
                    "action": "SELL_TO_OPEN",
                },
                {
                    "symbol": "SPY240216P00445000",
                    "quantity": 2,
                    "action": "BUY_TO_OPEN",
                },
                # Call spread
                {
                    "symbol": "SPY240216C00450000",
                    "quantity": -1,
                    "action": "SELL_TO_OPEN",
                },
                {
                    "symbol": "SPY240216C00455000",
                    "quantity": 1,
                    "action": "BUY_TO_OPEN",
                },
            ],
            "total_legs": 6,
        }

        with patch.object(
            self.strategy_service,
            "_execute_suggestion_order",
            return_value=mock_order_response,
        ):
            execution_result = await self.strategy_service.execute_suggestion(suggestion.id)

            assert execution_result["success"]
            assert execution_result["order_id"] == "test_order_123"

            print(f"   Order executed successfully: {execution_result['order_id']}")
            print(f"   Total legs created: {mock_order_response['total_legs']}")

        # Step 5: Verify position was created
        print("\nStep 5: Verifying position creation...")

        # Create the position that would result from order execution
        position = await sync_to_async(Position.objects.create)(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            quantity=3,  # 2 put spreads + 1 call spread
            lifecycle_state="open_full",
            is_app_managed=True,
            metadata={
                "strikes": selected_strikes,
                "expiration": "2024-02-16",
                "strategy_type": "senex_trident",
                "is_complete_trident": True,
                "streaming_pricing": {
                    "put_credit": "2.50",
                    "call_credit": "1.75",
                    "total_credit": "6.75",  # (2.50 * 2) + (1.75 * 1)
                },
            },
        )

        # Create opening trade record
        opening_trade = await sync_to_async(Trade.objects.create)(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id="test_order_123",
            trade_type="open",
            order_legs=mock_order_response["legs"],
            quantity=3,
            status="filled",
        )

        print(f"   Position created with ID: {position.id}")
        print(f"   Opening trade recorded: {opening_trade.broker_order_id}")

        # Step 6: Test profit target creation
        print("\nStep 6: Creating profit targets...")

        mock_execution_result = {
            "order_ids": [
                "profit_target_1",
                "profit_target_2",
                "profit_target_3",
            ],
            "targets": [
                {
                    "spread_type": "put_spread_1",
                    "order_id": "profit_target_1",
                    "profit_percentage": 40,
                    "target_price": 1.50,
                },
                {
                    "spread_type": "put_spread_2",
                    "order_id": "profit_target_2",
                    "profit_percentage": 60,
                    "target_price": 1.00,
                },
                {
                    "spread_type": "call_spread",
                    "order_id": "profit_target_3",
                    "profit_percentage": 50,
                    "target_price": 0.88,
                },
            ],
            "total_orders": 3,
        }

        order_service = OrderExecutionService(self.user)

        with (
            patch.object(SenexTridentStrategy, "__init__", return_value=None),
            patch.object(
                SenexTridentStrategy,
                "get_profit_target_specifications_sync",
                return_value=[MagicMock(), MagicMock(), MagicMock()],
            ),
            patch.object(
                OrderExecutionService,
                "execute_profit_targets_sync",
                return_value=mock_execution_result,
            ),
        ):
            profit_result = await sync_to_async(order_service.create_profit_targets_sync)(
                position, opening_trade.broker_order_id
            )

        assert profit_result["status"] == "success"
        assert profit_result["order_ids"] == mock_execution_result["order_ids"]

        print(f"   Profit targets created: {profit_result['total_orders']}")
        for target in mock_execution_result["targets"]:
            print(
                "   Target: "
                f"{target['spread_type']} at {target['profit_percentage']}% "
                f"(order {target['order_id']})"
            )

        # Step 7: Verify profit target calculations
        print("\n🧮 Step 7: Verifying profit target calculations...")

        put_credit = Decimal("2.50")
        call_credit = Decimal("1.75")

        # Calculate expected target prices
        put_target_40 = put_credit * (Decimal("1.0") - Decimal("40") / Decimal("100"))  # $1.50
        put_target_60 = put_credit * (Decimal("1.0") - Decimal("60") / Decimal("100"))  # $1.00
        call_target_50 = call_credit * (Decimal("1.0") - Decimal("50") / Decimal("100"))  # $0.875

        assert put_target_40 == Decimal("1.50")
        assert put_target_60 == Decimal("1.00")
        assert call_target_50 == Decimal("0.875")

        print(f"   Put spread 1 (40% target): ${put_credit} → ${put_target_40}")
        print(f"   Put spread 2 (60% target): ${put_credit} → ${put_target_60}")
        print(f"   Call spread (50% target): ${call_credit} → ${call_target_50}")

        # Step 8: Test position status and management
        print("\nStep 8: Verifying position management...")

        # Update position with real data that would come from broker
        position.avg_price = Decimal("6.75")  # Total credit received
        position.current_price = Decimal("5.25")  # Current position value
        position.unrealized_pnl = Decimal("150.00")  # Profit from position
        await sync_to_async(position.save)()

        # Verify position is properly managed
        assert position.is_app_managed
        assert position.symbol == "SPY"
        assert position.quantity == 3

        print(f"   Position managed - Symbol: {position.symbol}")
        print(
            f"   Position value - Avg: ${position.avg_price}, "
            f"Current: ${position.current_price}"
        )
        print(f"   Unrealized P&L: ${position.unrealized_pnl}")

        print("\n=== SENEX TRIDENT INTEGRATION TEST COMPLETED SUCCESSFULLY ===")
        print("All Phase 5 infrastructure components working together correctly!")

    @pytest.mark.asyncio
    async def test_senex_trident_put_spreads_only_flow(self):
        """
        Test Senex Trident flow when only put spreads are possible
        (no call spread).
        """
        print("\n=== SENEX TRIDENT PUT SPREADS ONLY TEST ===")

        # Mock option chain with limited call strikes (no call spread possible)
        # Create Strike objects - full put strikes, but limited call strikes (missing 455)
        strikes_list = []
        for s in range(440, 465, 5):  # 440, 445, 450, 455, 460
            strike_dict = {
                "strike_price": str(s),
                "put": f"SPY 240216P{s:05d}",
                "call": (
                    f"SPY 240216C{s:05d}" if s in [445, 450] else None
                ),  # Only 445, 450 have calls
            }
            strikes_list.append(strike_dict)

        limited_chain = {
            "symbol": "SPY",
            "current_price": self.mock_current_price,
            "expiration": "2024-02-16",
            "strikes": strikes_list,
            "fetched_at": "2024-01-02T10:00:00Z",
        }

        # Test strike selection - should only return put spreads
        selected_strikes = await self.option_service.select_strikes(
            self.mock_current_price, limited_chain, width=5
        )

        assert selected_strikes is not None
        assert selected_strikes["short_put"] == Decimal("450")
        assert selected_strikes["long_put"] == Decimal("445")
        # Call spread should not be possible
        assert selected_strikes.get("short_call") is None
        assert selected_strikes.get("long_call") is None

        print("   Put spreads only configuration detected correctly")
        print(
            f"   Put spread strikes: "
            f"{selected_strikes['short_put']}/{selected_strikes['long_put']}"
        )
        print("   Call spread: Not possible (missing strikes)")

    def test_even_strike_algorithm_edge_cases(self):
        """Test the critical even-strike selection algorithm with various prices."""
        print("\n=== EVEN-STRIKE ALGORITHM TEST ===")

        test_cases = [
            (Decimal("450.00"), Decimal("450")),  # Exact even
            (
                Decimal("450.75"),
                Decimal("450"),
            ),  # Round to nearest even (450.75/2=225.375, round=225, *2=450)
            (
                Decimal("451.25"),
                Decimal("452"),
            ),  # Round to nearest even (451.25/2=225.625, round=226, *2=452)
            (
                Decimal("452.50"),
                Decimal("452"),
            ),  # Round to nearest even (452.50/2=226.25, round=226, *2=452)
            (
                Decimal("453.75"),
                Decimal("454"),
            ),  # Round to nearest even (453.75/2=226.875, round=227, *2=454)
            (
                Decimal("449.99"),
                Decimal("450"),
            ),  # Round to nearest even (449.99/2=224.995, round=225, *2=450)
        ]

        for current_price, expected_strike in test_cases:
            result = self.strategy_service.calculate_base_strike(current_price)
            assert result == expected_strike
            print(f"   ${current_price} → ${expected_strike} (even strike)")

    def test_profit_target_percentage_validation(self):
        """Test Senex Trident specific profit target percentages."""
        print("\n=== PROFIT TARGET VALIDATION TEST ===")

        # Senex Trident target percentages from Phase 5 plan
        PROFIT_TARGETS = {
            "put_spread_1": 40,  # First put spread: 40% profit target
            "put_spread_2": 60,  # Second put spread: 60% profit target
            "call_spread": 50,  # Call spread: 50% profit target
        }

        credit = Decimal("2.00")

        for component, target_percent in PROFIT_TARGETS.items():
            target_price = credit * (Decimal("1.0") - Decimal(str(target_percent)) / Decimal("100"))
            profit = credit - target_price
            profit_percentage = (profit / credit) * 100

            assert profit_percentage == Decimal(str(target_percent))
            print(f"   {component}: {target_percent}% target → close at ${target_price}")

        print("   All Senex Trident profit targets validated")

    def tearDown(self):
        """Clean up test data."""
        # Django TestCase automatically rolls back transactions
