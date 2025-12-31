"""Tests for strategy composition."""

from datetime import date
from decimal import Decimal

import pytest

from services.orders.spec import OrderLeg
from services.strategies.core.legs import StrategyLeg
from services.strategies.core.primitives import OptionContract
from services.strategies.core.strategy import StrategyComposition
from services.strategies.core.types import OptionType, PriceEffect, Side

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def spy_put_580() -> OptionContract:
    """SPY $580 put."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.PUT,
        strike=Decimal("580.00"),
        expiration=date(2025, 1, 17),
    )


@pytest.fixture
def spy_put_575() -> OptionContract:
    """SPY $575 put."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.PUT,
        strike=Decimal("575.00"),
        expiration=date(2025, 1, 17),
    )


@pytest.fixture
def spy_call_600() -> OptionContract:
    """SPY $600 call."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.CALL,
        strike=Decimal("600.00"),
        expiration=date(2025, 1, 17),
    )


@pytest.fixture
def spy_call_605() -> OptionContract:
    """SPY $605 call."""
    return OptionContract(
        symbol="SPY",
        option_type=OptionType.CALL,
        strike=Decimal("605.00"),
        expiration=date(2025, 1, 17),
    )


@pytest.fixture
def bull_put_spread(spy_put_580, spy_put_575) -> StrategyComposition:
    """Bull put spread: sell $580 put, buy $575 put ($5 wide)."""
    return StrategyComposition(
        legs=[
            StrategyLeg(contract=spy_put_580, side=Side.SHORT, quantity=1),
            StrategyLeg(contract=spy_put_575, side=Side.LONG, quantity=1),
        ]
    )


@pytest.fixture
def bear_call_spread(spy_call_600, spy_call_605) -> StrategyComposition:
    """Bear call spread: sell $600 call, buy $605 call ($5 wide)."""
    return StrategyComposition(
        legs=[
            StrategyLeg(contract=spy_call_600, side=Side.SHORT, quantity=1),
            StrategyLeg(contract=spy_call_605, side=Side.LONG, quantity=1),
        ]
    )


@pytest.fixture
def iron_condor(spy_put_580, spy_put_575, spy_call_600, spy_call_605) -> StrategyComposition:
    """Iron condor: bull put spread + bear call spread."""
    return StrategyComposition(
        legs=[
            # Put spread
            StrategyLeg(contract=spy_put_580, side=Side.SHORT, quantity=1),
            StrategyLeg(contract=spy_put_575, side=Side.LONG, quantity=1),
            # Call spread
            StrategyLeg(contract=spy_call_600, side=Side.SHORT, quantity=1),
            StrategyLeg(contract=spy_call_605, side=Side.LONG, quantity=1),
        ]
    )


# =============================================================================
# Creation Tests
# =============================================================================


class TestStrategyCompositionCreation:
    """Test StrategyComposition creation and validation."""

    def test_create_single_leg(self, spy_put_580):
        """Test creating a single-leg strategy."""
        leg = StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1)
        strategy = StrategyComposition(legs=[leg])
        assert strategy.leg_count == 1

    def test_create_multi_leg(self, bull_put_spread):
        """Test creating a multi-leg strategy."""
        assert bull_put_spread.leg_count == 2

    def test_empty_legs_raises_error(self):
        """Test that empty legs raises ValueError."""
        with pytest.raises(ValueError, match="at least one leg"):
            StrategyComposition(legs=[])

    def test_mismatched_underlyings_raises_error(self, spy_put_580):
        """Test that mismatched underlyings raises ValueError."""
        qqq_put = OptionContract(
            symbol="QQQ",
            option_type=OptionType.PUT,
            strike=Decimal("500.00"),
            expiration=date(2025, 1, 17),
        )
        with pytest.raises(ValueError, match="same underlying"):
            StrategyComposition(
                legs=[
                    StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                    StrategyLeg(contract=qqq_put, side=Side.LONG, quantity=1),
                ]
            )

    def test_legs_converted_to_tuple(self, spy_put_580, spy_put_575):
        """Test that legs list is converted to immutable tuple."""
        legs_list = [
            StrategyLeg(contract=spy_put_580, side=Side.SHORT, quantity=1),
            StrategyLeg(contract=spy_put_575, side=Side.LONG, quantity=1),
        ]
        strategy = StrategyComposition(legs=legs_list)
        assert isinstance(strategy.legs, tuple)

    def test_immutability(self, bull_put_spread):
        """Test that strategy is immutable."""
        with pytest.raises(AttributeError):
            bull_put_spread.legs = ()


# =============================================================================
# Property Tests
# =============================================================================


class TestStrategyProperties:
    """Test StrategyComposition property accessors."""

    def test_underlying(self, bull_put_spread):
        """Test underlying property."""
        assert bull_put_spread.underlying == "SPY"

    def test_expiration(self, bull_put_spread):
        """Test expiration property."""
        assert bull_put_spread.expiration == date(2025, 1, 17)

    def test_expirations_single(self, bull_put_spread):
        """Test expirations for single-expiration strategy."""
        assert bull_put_spread.expirations == {date(2025, 1, 17)}

    def test_expirations_calendar_spread(self, spy_call_600):
        """Test expirations for calendar spread."""
        near_call = spy_call_600
        far_call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("600.00"),
            expiration=date(2025, 2, 21),  # Different expiration
        )
        calendar = StrategyComposition(
            legs=[
                StrategyLeg(contract=near_call, side=Side.SHORT, quantity=1),
                StrategyLeg(contract=far_call, side=Side.LONG, quantity=1),
            ]
        )
        assert calendar.expirations == {date(2025, 1, 17), date(2025, 2, 21)}
        assert calendar.is_multi_expiration is True
        assert calendar.expiration == date(2025, 1, 17)  # Nearest

    def test_is_multi_expiration_false(self, bull_put_spread):
        """Test is_multi_expiration for single expiration."""
        assert bull_put_spread.is_multi_expiration is False


# =============================================================================
# Net Premium Tests
# =============================================================================


class TestNetPremium:
    """Test net premium calculation."""

    def test_credit_spread_net_premium(self, bull_put_spread, spy_put_580, spy_put_575):
        """Test net premium for credit spread."""
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),  # Short: receive
            spy_put_575.occ_symbol: Decimal("2.00"),  # Long: pay
        }
        net = bull_put_spread.net_premium(premiums)
        assert net == Decimal("1.00")  # $3 received - $2 paid = $1 credit

    def test_debit_spread_net_premium(self, spy_put_580, spy_put_575):
        """Test net premium for debit spread (long higher strike put)."""
        debit_spread = StrategyComposition(
            legs=[
                StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.SHORT, quantity=1),
            ]
        )
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),  # Long: pay
            spy_put_575.occ_symbol: Decimal("2.00"),  # Short: receive
        }
        net = debit_spread.net_premium(premiums)
        assert net == Decimal("-1.00")  # $2 received - $3 paid = $1 debit

    def test_iron_condor_net_premium(
        self, iron_condor, spy_put_580, spy_put_575, spy_call_600, spy_call_605
    ):
        """Test net premium for iron condor."""
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),  # Short put
            spy_put_575.occ_symbol: Decimal("2.00"),  # Long put
            spy_call_600.occ_symbol: Decimal("2.50"),  # Short call
            spy_call_605.occ_symbol: Decimal("1.50"),  # Long call
        }
        net = iron_condor.net_premium(premiums)
        # Put spread: $3 - $2 = $1 credit
        # Call spread: $2.50 - $1.50 = $1 credit
        # Total: $2 credit
        assert net == Decimal("2.00")

    def test_price_effect_credit(self, bull_put_spread, spy_put_580, spy_put_575):
        """Test price effect for credit strategy."""
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),
            spy_put_575.occ_symbol: Decimal("2.00"),
        }
        assert bull_put_spread.price_effect(premiums) == PriceEffect.CREDIT

    def test_price_effect_debit(self, spy_put_580, spy_put_575):
        """Test price effect for debit strategy."""
        debit_spread = StrategyComposition(
            legs=[
                StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.SHORT, quantity=1),
            ]
        )
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),
            spy_put_575.occ_symbol: Decimal("2.00"),
        }
        assert debit_spread.price_effect(premiums) == PriceEffect.DEBIT


# =============================================================================
# Spread Width Tests
# =============================================================================


class TestSpreadWidth:
    """Test spread width calculations."""

    def test_single_spread_width(self, bull_put_spread):
        """Test spread width for simple vertical spread."""
        widths = bull_put_spread.spread_widths()
        assert widths == [Decimal("5.00")]
        assert bull_put_spread.max_spread_width() == Decimal("5.00")

    def test_iron_condor_symmetric_widths(self, iron_condor):
        """Test spread widths for symmetric iron condor."""
        widths = iron_condor.spread_widths()
        assert len(widths) == 2
        assert all(w == Decimal("5.00") for w in widths)
        assert iron_condor.max_spread_width() == Decimal("5.00")

    def test_asymmetric_iron_condor(self, spy_put_575, spy_call_600):
        """Test spread widths for asymmetric iron condor."""
        # Put side: $5 wide
        put_short = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        # Call side: $3 wide
        call_long = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("603.00"),
            expiration=date(2025, 1, 17),
        )
        asymmetric_ic = StrategyComposition(
            legs=[
                StrategyLeg(contract=put_short, side=Side.SHORT, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_call_600, side=Side.SHORT, quantity=1),
                StrategyLeg(contract=call_long, side=Side.LONG, quantity=1),
            ]
        )
        widths = asymmetric_ic.spread_widths()
        assert Decimal("5.00") in widths  # Put side
        assert Decimal("3.00") in widths  # Call side
        # Max width should be the larger one
        assert asymmetric_ic.max_spread_width() == Decimal("5.00")

    def test_single_leg_no_width(self, spy_put_580):
        """Test that single leg has no spread width."""
        single_leg = StrategyComposition(
            legs=[StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1)]
        )
        assert single_leg.spread_widths() == []
        assert single_leg.max_spread_width() is None


# =============================================================================
# Risk/Reward Tests
# =============================================================================


class TestRiskReward:
    """Test max risk and max profit calculations."""

    def test_credit_spread_max_risk(self, bull_put_spread):
        """Test max risk for credit spread."""
        net_credit = Decimal("1.00")  # $1 credit
        max_risk = bull_put_spread.max_risk(net_credit)
        # Max risk = (width - credit) * 100 = ($5 - $1) * 100 = $400
        assert max_risk == Decimal("400.00")

    def test_credit_spread_max_profit(self, bull_put_spread):
        """Test max profit for credit spread."""
        net_credit = Decimal("1.00")
        max_profit = bull_put_spread.max_profit(net_credit)
        # Max profit = credit * 100 = $1 * 100 = $100
        assert max_profit == Decimal("100.00")

    def test_debit_spread_max_risk(self, spy_put_580, spy_put_575):
        """Test max risk for debit spread."""
        debit_spread = StrategyComposition(
            legs=[
                StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.SHORT, quantity=1),
            ]
        )
        net_debit = Decimal("-1.00")  # $1 debit (negative)
        max_risk = debit_spread.max_risk(net_debit)
        # Max risk = debit * 100 = $1 * 100 = $100
        assert max_risk == Decimal("100.00")

    def test_debit_spread_max_profit(self, spy_put_580, spy_put_575):
        """Test max profit for debit spread."""
        debit_spread = StrategyComposition(
            legs=[
                StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.SHORT, quantity=1),
            ]
        )
        net_debit = Decimal("-1.00")
        max_profit = debit_spread.max_profit(net_debit)
        # Max profit = (width - debit) * 100 = ($5 - $1) * 100 = $400
        assert max_profit == Decimal("400.00")

    def test_asymmetric_max_risk_uses_larger_width(self, spy_put_575, spy_call_600):
        """Test that asymmetric spreads use larger width for max risk."""
        # Put side: $5 wide, Call side: $3 wide
        put_short = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        call_long = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("603.00"),
            expiration=date(2025, 1, 17),
        )
        asymmetric_ic = StrategyComposition(
            legs=[
                StrategyLeg(contract=put_short, side=Side.SHORT, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_call_600, side=Side.SHORT, quantity=1),
                StrategyLeg(contract=call_long, side=Side.LONG, quantity=1),
            ]
        )
        net_credit = Decimal("2.00")
        max_risk = asymmetric_ic.max_risk(net_credit)
        # Max risk = (max_width - credit) * 100 = ($5 - $2) * 100 = $300
        assert max_risk == Decimal("300.00")

    def test_long_option_max_risk(self, spy_put_580):
        """Test max risk for single long option."""
        long_put = StrategyComposition(
            legs=[StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1)]
        )
        net_debit = Decimal("-2.50")  # Paid $2.50
        max_risk = long_put.max_risk(net_debit)
        # Max risk = premium paid * 100 = $2.50 * 100 = $250
        assert max_risk == Decimal("250.00")


# =============================================================================
# Order Conversion Tests
# =============================================================================


class TestOrderConversion:
    """Test conversion to order legs."""

    def test_to_order_legs_opening(self, bull_put_spread):
        """Test converting to opening order legs."""
        order_legs = bull_put_spread.to_order_legs(opening=True)
        assert len(order_legs) == 2
        assert all(isinstance(leg, OrderLeg) for leg in order_legs)

        # Check actions
        actions = {leg.action for leg in order_legs}
        assert "sell_to_open" in actions  # Short leg
        assert "buy_to_open" in actions  # Long leg

    def test_to_order_legs_closing(self, bull_put_spread):
        """Test converting to closing order legs."""
        order_legs = bull_put_spread.to_order_legs(opening=False)
        actions = {leg.action for leg in order_legs}
        assert "buy_to_close" in actions  # Close short
        assert "sell_to_close" in actions  # Close long

    def test_occ_symbols(self, bull_put_spread, spy_put_580, spy_put_575):
        """Test getting OCC symbols."""
        symbols = bull_put_spread.occ_symbols()
        assert len(symbols) == 2
        assert spy_put_580.occ_symbol in symbols
        assert spy_put_575.occ_symbol in symbols


# =============================================================================
# Filtering Tests
# =============================================================================


class TestLegFiltering:
    """Test leg filtering methods."""

    def test_long_legs(self, iron_condor):
        """Test filtering long legs."""
        long_legs = iron_condor.long_legs()
        assert len(long_legs) == 2
        assert all(leg.is_long for leg in long_legs)

    def test_short_legs(self, iron_condor):
        """Test filtering short legs."""
        short_legs = iron_condor.short_legs()
        assert len(short_legs) == 2
        assert all(leg.is_short for leg in short_legs)

    def test_put_legs(self, iron_condor):
        """Test filtering put legs."""
        put_legs = iron_condor.put_legs()
        assert len(put_legs) == 2
        assert all(leg.contract.option_type == OptionType.PUT for leg in put_legs)

    def test_call_legs(self, iron_condor):
        """Test filtering call legs."""
        call_legs = iron_condor.call_legs()
        assert len(call_legs) == 2
        assert all(leg.contract.option_type == OptionType.CALL for leg in call_legs)

    def test_total_quantity(self, iron_condor):
        """Test total quantity calculation."""
        assert iron_condor.total_quantity() == 4


# =============================================================================
# Closing Composition Tests
# =============================================================================


class TestClosingComposition:
    """Test closing composition generation."""

    def test_closing_reverses_sides(self, bull_put_spread):
        """Test that closing composition reverses all sides."""
        closing = bull_put_spread.closing_composition()
        assert closing.leg_count == bull_put_spread.leg_count

        # Original short becomes long, original long becomes short
        original_short = [leg for leg in bull_put_spread.legs if leg.is_short][0]
        closing_short_contract = [
            leg for leg in closing.legs
            if leg.contract == original_short.contract
        ][0]
        assert closing_short_contract.is_long

    def test_closing_preserves_contracts(self, bull_put_spread):
        """Test that closing preserves contracts."""
        closing = bull_put_spread.closing_composition()
        original_contracts = {leg.contract for leg in bull_put_spread.legs}
        closing_contracts = {leg.contract for leg in closing.legs}
        assert original_contracts == closing_contracts


# =============================================================================
# Credit/Debit Helper Tests
# =============================================================================


class TestCreditDebitHelpers:
    """Test credit/debit classification helpers."""

    def test_is_credit_strategy(self, bull_put_spread, spy_put_580, spy_put_575):
        """Test is_credit_strategy helper."""
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),
            spy_put_575.occ_symbol: Decimal("2.00"),
        }
        assert bull_put_spread.is_credit_strategy(premiums) is True
        assert bull_put_spread.is_debit_strategy(premiums) is False

    def test_is_debit_strategy(self, spy_put_580, spy_put_575):
        """Test is_debit_strategy helper."""
        debit_spread = StrategyComposition(
            legs=[
                StrategyLeg(contract=spy_put_580, side=Side.LONG, quantity=1),
                StrategyLeg(contract=spy_put_575, side=Side.SHORT, quantity=1),
            ]
        )
        premiums = {
            spy_put_580.occ_symbol: Decimal("3.00"),
            spy_put_575.occ_symbol: Decimal("2.00"),
        }
        assert debit_spread.is_debit_strategy(premiums) is True
        assert debit_spread.is_credit_strategy(premiums) is False
