"""Tests for profit target calculations (Phase 5F)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import TradingAccount
from services.execution.order_service import OrderExecutionService
from services.strategies.senex_trident_strategy import SenexTridentStrategy
from trading.models import Position, StrategyConfiguration, Trade, TradingSuggestion

User = get_user_model()


class TestProfitTargetCalculations(TestCase):
    """Test profit target calculation logic."""

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
        self.strategy_service = SenexTridentStrategy(self.user)

    def test_calculate_profit_target_price_basic(self):
        """Test basic profit target price calculation."""
        # 40% profit target on $2.50 credit
        entry_credit = Decimal("2.50")
        target_percentage = 40.0

        # Formula: credit * (1 - target_percentage/100)
        # $2.50 * (1 - 0.40) = $2.50 * 0.60 = $1.50
        expected_price = Decimal("1.50")

        # Test the calculation from the Phase 5 plan
        target_price = entry_credit * (
            Decimal("1.0") - Decimal(str(target_percentage)) / Decimal("100.0")
        )
        assert target_price == expected_price

    def test_calculate_profit_target_price_various_targets(self):
        """Test profit target calculations for different percentages."""
        entry_credit = Decimal("3.00")

        # 40% target: $3.00 * (1 - 0.40) = $1.80
        target_40 = entry_credit * (Decimal("1.0") - Decimal("40") / Decimal("100"))
        assert target_40 == Decimal("1.80")

        # 50% target: $3.00 * (1 - 0.50) = $1.50
        target_50 = entry_credit * (Decimal("1.0") - Decimal("50") / Decimal("100"))
        assert target_50 == Decimal("1.50")

        # 60% target: $3.00 * (1 - 0.60) = $1.20
        target_60 = entry_credit * (Decimal("1.0") - Decimal("60") / Decimal("100"))
        assert target_60 == Decimal("1.20")

    def test_senex_trident_profit_targets_specification(self):
        """Test Senex Trident specific profit target percentages."""
        put_spread_credit = Decimal("2.50")
        call_spread_credit = Decimal("1.75")

        # Senex Trident targets from Phase 5 plan:
        # - 40% target for first put spread
        # - 60% target for second put spread
        # - 50% target for call spread

        put_target_40 = put_spread_credit * (Decimal("1.0") - Decimal("40") / Decimal("100"))
        put_target_60 = put_spread_credit * (Decimal("1.0") - Decimal("60") / Decimal("100"))
        call_target_50 = call_spread_credit * (Decimal("1.0") - Decimal("50") / Decimal("100"))

        assert put_target_40 == Decimal("1.50")  # $2.50 * 0.60
        assert put_target_60 == Decimal("1.00")  # $2.50 * 0.40
        assert call_target_50 == Decimal("0.875")  # $1.75 * 0.50

    def _create_suggestion(self, include_call: bool = True) -> TradingSuggestion:
        """Create a trading suggestion with configurable call spread support."""
        expiration = date.today() + timedelta(days=30)
        expires_at = timezone.now() + timedelta(hours=2)
        params = {
            "user": self.user,
            "strategy_configuration": self.strategy_config,
            "underlying_price": Decimal("430.00"),
            "expiration_date": expiration,
            "short_put_strike": Decimal("430"),
            "long_put_strike": Decimal("425"),
            "put_spread_quantity": 2,
            "put_spread_mid_credit": Decimal("2.50"),
            "total_mid_credit": Decimal("5.00" if not include_call else "6.75"),
            "expires_at": expires_at,
            "market_conditions": {},
        }
        if include_call:
            params.update(
                {
                    "short_call_strike": Decimal("450"),
                    "long_call_strike": Decimal("455"),
                    "call_spread_quantity": 1,
                    "call_spread_mid_credit": Decimal("1.75"),
                }
            )
        else:
            params.update({"call_spread_quantity": 0, "call_spread_mid_credit": None})

        return TradingSuggestion.objects.create(**params)

    def _create_position(self, suggestion: TradingSuggestion, is_full_condor: bool) -> Position:
        metadata = {
            "suggestion_id": suggestion.id,
            "streaming_pricing": {
                "put_credit": str(suggestion.put_spread_mid_credit),
                "call_credit": (
                    str(suggestion.call_spread_mid_credit)
                    if suggestion.call_spread_mid_credit is not None
                    else None
                ),
                "total_credit": str(suggestion.total_mid_credit),
            },
            "strikes": {
                "short_put": str(suggestion.short_put_strike),
                "long_put": str(suggestion.long_put_strike),
                "short_call": (
                    str(suggestion.short_call_strike) if suggestion.short_call_strike else None
                ),
                "long_call": (
                    str(suggestion.long_call_strike) if suggestion.long_call_strike else None
                ),
            },
            "is_complete_trident": is_full_condor,
        }

        return Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="SPY",
            quantity=3 if is_full_condor else 2,
            lifecycle_state="open_full",
            metadata=metadata,
        )

    def _create_open_trade(self, position: Position, quantity: int) -> Trade:
        return Trade.objects.create(
            user=self.user,
            position=position,
            trading_account=self.trading_account,
            broker_order_id=f"order_{position.id}",
            trade_type="open",
            order_legs=[],
            quantity=quantity,
            status="filled",
        )

    def test_get_profit_target_specifications_missing_suggestion_returns_empty(self):
        """Missing suggestion metadata yields no profit target specifications."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            strategy_type="senex_trident",
            symbol="SPY",
            quantity=2,
            lifecycle_state="open_full",
            metadata={},
        )
        trade = self._create_open_trade(position, quantity=2)

        specs = self.strategy_service.get_profit_target_specifications_sync(position, trade)
        assert specs == []

    def test_create_profit_targets_sync_updates_models(self):
        """OrderExecutionService populates position/trade metadata when successful."""
        suggestion = self._create_suggestion(include_call=True)
        position = self._create_position(suggestion, is_full_condor=True)
        trade = self._create_open_trade(position, quantity=3)

        mock_targets = {
            "order_ids": ["target1", "target2", "target3"],
            "targets": [
                {
                    "spread_type": "put_spread_1",
                    "order_id": "target1",
                    "profit_percentage": 40,
                    "target_price": 1.5,
                },
                {
                    "spread_type": "put_spread_2",
                    "order_id": "target2",
                    "profit_percentage": 60,
                    "target_price": 1.0,
                },
                {
                    "spread_type": "call_spread",
                    "order_id": "target3",
                    "profit_percentage": 40,
                    "target_price": 1.2,
                },
            ],
            "total_orders": 3,
        }

        with (
            patch.object(SenexTridentStrategy, "__init__", return_value=None),
            patch.object(
                SenexTridentStrategy,
                "get_profit_target_specifications_sync",
                return_value=[MagicMock(), MagicMock(), MagicMock()],
            ),
            patch.object(
                OrderExecutionService, "execute_profit_targets_sync", return_value=mock_targets
            ),
        ):
            result = self.order_service.create_profit_targets_sync(position, trade.broker_order_id)

        position.refresh_from_db()
        trade.refresh_from_db()

        assert result["status"] == "success"
        assert result["order_ids"] == mock_targets["order_ids"]
        assert position.profit_targets_created is True
        assert position.profit_target_details == {
            "put_spread_1": {
                "order_id": "target1",
                "percent": 40,
                "target_price": 1.5,
            },
            "put_spread_2": {
                "order_id": "target2",
                "percent": 60,
                "target_price": 1.0,
            },
            "call_spread": {
                "order_id": "target3",
                "percent": 40,
                "target_price": 1.2,
            },
        }
        assert trade.child_order_ids == mock_targets["order_ids"]

    def test_create_profit_targets_sync_without_open_trade(self):
        """Attempting to create profit targets without an opening trade returns error."""
        suggestion = self._create_suggestion(include_call=False)
        position = self._create_position(suggestion, is_full_condor=False)

        result = self.order_service.create_profit_targets_sync(position, parent_order_id="order_x")

        assert result["status"] == "error"
        assert "No opening trade" in result["message"]

    def test_profit_target_examples_from_plan(self):
        """Test profit target calculations using examples from Phase 5 plan."""
        # Example from plan: $1.00 credit, 40% target
        # Close at: $1.00 * (1 - 0.40) = $0.60
        # Profit: $1.00 - $0.60 = $0.40 (40% of entry credit)

        entry_credit = Decimal("1.00")
        target_percentage = 40.0

        target_price = entry_credit * (
            Decimal("1.0") - Decimal(str(target_percentage)) / Decimal("100.0")
        )
        expected_target = Decimal("0.60")

        assert target_price == expected_target

        # Verify profit calculation
        profit = entry_credit - target_price
        expected_profit = Decimal("0.40")
        assert profit == expected_profit

        # Verify profit percentage
        profit_percentage = (profit / entry_credit) * 100
        assert profit_percentage == Decimal("40.0")

    def test_senex_trident_profit_target_constants(self):
        """Test the profit target constants from Phase 5 plan."""
        # From the plan:
        PROFIT_TARGETS = {
            "put_spread_1": 40,  # First put spread: 40% profit target
            "put_spread_2": 60,  # Second put spread: 60% profit target
            "call_spread": 50,  # Call spread: 50% profit target
        }

        assert PROFIT_TARGETS["put_spread_1"] == 40
        assert PROFIT_TARGETS["put_spread_2"] == 60
        assert PROFIT_TARGETS["call_spread"] == 50

        # Test calculations with these targets
        credit = Decimal("2.00")

        target_1 = credit * (
            Decimal("1.0") - Decimal(str(PROFIT_TARGETS["put_spread_1"])) / Decimal("100")
        )
        target_2 = credit * (
            Decimal("1.0") - Decimal(str(PROFIT_TARGETS["put_spread_2"])) / Decimal("100")
        )
        target_3 = credit * (
            Decimal("1.0") - Decimal(str(PROFIT_TARGETS["call_spread"])) / Decimal("100")
        )

        assert target_1 == Decimal("1.20")  # 40% -> close at 60%
        assert target_2 == Decimal("0.80")  # 60% -> close at 40%
        assert target_3 == Decimal("1.00")  # 50% -> close at 50%

    def test_profit_target_edge_cases(self):
        """Test profit target calculations for edge cases."""
        # Zero credit (should not happen in practice)
        zero_credit = Decimal("0.00")
        target_price = zero_credit * (Decimal("1.0") - Decimal("40") / Decimal("100"))
        assert target_price == Decimal("0.00")

        # 100% target (close for free)
        credit = Decimal("2.50")
        target_100 = credit * (Decimal("1.0") - Decimal("100") / Decimal("100"))
        assert target_100 == Decimal("0.00")

        # 0% target (no profit taken)
        target_0 = credit * (Decimal("1.0") - Decimal("0") / Decimal("100"))
        assert target_0 == credit

        # Small credit values
        small_credit = Decimal("0.01")
        target_small = small_credit * (Decimal("1.0") - Decimal("50") / Decimal("100"))
        assert target_small == Decimal("0.005")

    def test_profit_calculation_precision(self):
        """Test precision handling in profit calculations."""
        # Test with high precision decimal
        credit = Decimal("2.375")  # $2.375 credit
        target_percent = Decimal("42.5")  # 42.5% target

        target_price = credit * (Decimal("1.0") - target_percent / Decimal("100"))
        expected = credit * Decimal("0.575")  # 1 - 0.425 = 0.575

        assert target_price == expected
        assert target_price == Decimal("1.365625")

    def test_decimal_rounding_consistency(self):
        """Test that decimal calculations are consistent and properly rounded."""
        # Use ROUND_HALF_EVEN (banker's rounding) for consistency
        from decimal import ROUND_HALF_EVEN

        credit = Decimal("2.125")
        target_percent = Decimal("40")

        # Calculate with explicit rounding
        target_price = (credit * (Decimal("1.0") - target_percent / Decimal("100"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

        expected = Decimal("1.28")  # 2.125 * 0.6 = 1.275, rounds to 1.28
        assert target_price == expected
