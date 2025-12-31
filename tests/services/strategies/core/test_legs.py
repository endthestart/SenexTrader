"""Tests for leg composition."""

from datetime import date
from decimal import Decimal

import pytest

from services.orders.spec import OrderLeg
from services.strategies.core.legs import StrategyLeg
from services.strategies.core.primitives import OptionContract
from services.strategies.core.types import OptionType, Side


@pytest.fixture
def spy_put_contract() -> OptionContract:
    """Create a SPY put option for testing."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.PUT,
        strike=Decimal("580.00"),
        expiration=date(2025, 1, 17),
    )


@pytest.fixture
def spy_call_contract() -> OptionContract:
    """Create a SPY call option for testing."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.CALL,
        strike=Decimal("600.00"),
        expiration=date(2025, 1, 17),
    )


class TestStrategyLegCreation:
    """Test StrategyLeg creation and validation."""

    def test_create_long_leg(self, spy_put_contract: OptionContract):
        """Test creating a long leg."""
        leg = StrategyLeg(
            contract=spy_put_contract,
            side=Side.LONG,
            quantity=1,
        )
        assert leg.contract == spy_put_contract
        assert leg.side == Side.LONG
        assert leg.quantity == 1

    def test_create_short_leg(self, spy_put_contract: OptionContract):
        """Test creating a short leg."""
        leg = StrategyLeg(
            contract=spy_put_contract,
            side=Side.SHORT,
            quantity=5,
        )
        assert leg.side == Side.SHORT
        assert leg.quantity == 5

    def test_quantity_must_be_positive(self, spy_put_contract: OptionContract):
        """Test that quantity must be positive."""
        with pytest.raises(ValueError, match="positive"):
            StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=0)

        with pytest.raises(ValueError, match="positive"):
            StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=-1)

    def test_immutability(self, spy_put_contract: OptionContract):
        """Test that leg is immutable."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        with pytest.raises(AttributeError):
            leg.quantity = 2

    def test_hashable(self, spy_put_contract: OptionContract):
        """Test that leg is hashable."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        legs = {leg}
        assert leg in legs


class TestStrategyLegProperties:
    """Test StrategyLeg property accessors."""

    def test_occ_symbol_delegation(self, spy_put_contract: OptionContract):
        """Test that occ_symbol delegates to contract."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        assert leg.occ_symbol == spy_put_contract.occ_symbol
        assert leg.occ_symbol == "SPY   250117P00580000"

    def test_is_long(self, spy_put_contract: OptionContract):
        """Test is_long property."""
        long_leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        short_leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)

        assert long_leg.is_long is True
        assert long_leg.is_short is False
        assert short_leg.is_long is False
        assert short_leg.is_short is True


class TestPremiumEffect:
    """Test premium calculation logic."""

    def test_long_leg_pays_premium(self, spy_put_contract: OptionContract):
        """Long positions pay premium (negative cash flow)."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        effect = leg.premium_effect(Decimal("2.50"))
        assert effect == Decimal("-2.50")

    def test_short_leg_receives_premium(self, spy_put_contract: OptionContract):
        """Short positions receive premium (positive cash flow)."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        effect = leg.premium_effect(Decimal("2.50"))
        assert effect == Decimal("2.50")

    def test_premium_scales_with_quantity(self, spy_put_contract: OptionContract):
        """Premium should scale with quantity."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=10)
        effect = leg.premium_effect(Decimal("1.00"))
        assert effect == Decimal("10.00")

    def test_credit_spread_premium_flow(
        self, spy_put_contract: OptionContract, spy_call_contract: OptionContract
    ):
        """Test premium flow for a credit spread (sell near, buy far)."""
        # Sell $580 put for $3.00
        short_leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        # Buy $575 put for $2.00 (would need different contract, using different strike)
        far_put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("575.00"),
            expiration=date(2025, 1, 17),
        )
        long_leg = StrategyLeg(contract=far_put, side=Side.LONG, quantity=1)

        short_premium = short_leg.premium_effect(Decimal("3.00"))
        long_premium = long_leg.premium_effect(Decimal("2.00"))
        net_credit = short_premium + long_premium

        assert short_premium == Decimal("3.00")  # Received
        assert long_premium == Decimal("-2.00")  # Paid
        assert net_credit == Decimal("1.00")  # Net credit


class TestMaxLoss:
    """Test max loss calculations."""

    def test_long_max_loss_is_premium(self, spy_put_contract: OptionContract):
        """Long option max loss is premium paid."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        max_loss = leg.max_loss_at_expiry(Decimal("2.50"))
        assert max_loss == Decimal("2.50")

    def test_long_max_loss_scales_with_quantity(self, spy_put_contract: OptionContract):
        """Long max loss scales with quantity."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=10)
        max_loss = leg.max_loss_at_expiry(Decimal("2.50"))
        assert max_loss == Decimal("25.00")

    def test_short_max_loss_requires_spread_context(
        self, spy_put_contract: OptionContract
    ):
        """Short options return 0 (need spread context for true max)."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        max_loss = leg.max_loss_at_expiry(Decimal("2.50"))
        assert max_loss == Decimal("0")


class TestOrderLegConversion:
    """Test conversion to OrderLeg."""

    def test_long_opening_order(self, spy_put_contract: OptionContract):
        """Long leg opening creates buy_to_open."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        order_leg = leg.to_order_leg(opening=True)

        assert isinstance(order_leg, OrderLeg)
        assert order_leg.action == "buy_to_open"
        assert order_leg.symbol == spy_put_contract.occ_symbol
        assert order_leg.quantity == 1
        assert order_leg.instrument_type == "equity_option"

    def test_short_opening_order(self, spy_put_contract: OptionContract):
        """Short leg opening creates sell_to_open."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        order_leg = leg.to_order_leg(opening=True)

        assert order_leg.action == "sell_to_open"

    def test_long_closing_order(self, spy_put_contract: OptionContract):
        """Long leg closing creates sell_to_close."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        order_leg = leg.to_order_leg(opening=False)

        assert order_leg.action == "sell_to_close"

    def test_short_closing_order(self, spy_put_contract: OptionContract):
        """Short leg closing creates buy_to_close."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        order_leg = leg.to_order_leg(opening=False)

        assert order_leg.action == "buy_to_close"

    def test_quantity_preserved(self, spy_put_contract: OptionContract):
        """Quantity should be preserved in conversion."""
        leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=5)
        order_leg = leg.to_order_leg(opening=True)

        assert order_leg.quantity == 5


class TestClosingLeg:
    """Test closing leg generation."""

    def test_closing_long_becomes_short(self, spy_put_contract: OptionContract):
        """Closing a long leg creates a short leg."""
        long_leg = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        closing = long_leg.closing_leg()

        assert closing.side == Side.SHORT
        assert closing.contract == long_leg.contract
        assert closing.quantity == long_leg.quantity

    def test_closing_short_becomes_long(self, spy_put_contract: OptionContract):
        """Closing a short leg creates a long leg."""
        short_leg = StrategyLeg(contract=spy_put_contract, side=Side.SHORT, quantity=1)
        closing = short_leg.closing_leg()

        assert closing.side == Side.LONG

    def test_double_closing_returns_original_side(
        self, spy_put_contract: OptionContract
    ):
        """Closing a closing leg returns original side."""
        original = StrategyLeg(contract=spy_put_contract, side=Side.LONG, quantity=1)
        closed = original.closing_leg()
        reopened = closed.closing_leg()

        assert reopened.side == original.side
