"""Tests for option primitives."""

from datetime import date
from decimal import Decimal

import pytest

from services.strategies.core.primitives import OptionContract
from services.strategies.core.types import OptionType


class TestOptionContract:
    """Test OptionContract dataclass."""

    @pytest.fixture
    def spy_put(self) -> OptionContract:
        """Create a SPY put option for testing."""
        return OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )

    @pytest.fixture
    def spy_call(self) -> OptionContract:
        """Create a SPY call option for testing."""
        return OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("600.00"),
            expiration=date(2025, 1, 17),
        )

    def test_creation(self, spy_put: OptionContract):
        """Test basic creation."""
        assert spy_put.symbol == "SPY"
        assert spy_put.option_type == OptionType.PUT
        assert spy_put.strike == Decimal("580.00")
        assert spy_put.expiration == date(2025, 1, 17)

    def test_immutability(self, spy_put: OptionContract):
        """Test that frozen dataclass prevents mutation."""
        with pytest.raises(AttributeError):
            spy_put.strike = Decimal("590.00")

    def test_hashable(self, spy_put: OptionContract):
        """Test that frozen dataclass is hashable (can be used in sets/dicts)."""
        contracts = {spy_put}
        assert spy_put in contracts

        # Same values should hash the same
        spy_put_copy = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        assert hash(spy_put) == hash(spy_put_copy)

    def test_occ_symbol_put(self, spy_put: OptionContract):
        """Test OCC symbol generation for puts."""
        assert spy_put.occ_symbol == "SPY   250117P00580000"

    def test_occ_symbol_call(self, spy_call: OptionContract):
        """Test OCC symbol generation for calls."""
        assert spy_call.occ_symbol == "SPY   250117C00600000"

    def test_occ_symbol_fractional_strike(self):
        """Test OCC symbol with fractional strike."""
        contract = OptionContract(
            symbol="QQQ",
            option_type=OptionType.CALL,
            strike=Decimal("505.50"),
            expiration=date(2025, 2, 21),
        )
        assert contract.occ_symbol == "QQQ   250221C00505500"


class TestIntrinsicValue:
    """Test intrinsic value calculations."""

    def test_put_itm(self):
        """Put is ITM when spot < strike."""
        put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        # Spot = 570, Strike = 580 -> Put ITM by $10
        assert put.intrinsic_value(Decimal("570.00")) == Decimal("10.00")

    def test_put_otm(self):
        """Put is OTM when spot > strike."""
        put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        # Spot = 590, Strike = 580 -> Put OTM
        assert put.intrinsic_value(Decimal("590.00")) == Decimal("0")

    def test_call_itm(self):
        """Call is ITM when spot > strike."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        # Spot = 590, Strike = 580 -> Call ITM by $10
        assert call.intrinsic_value(Decimal("590.00")) == Decimal("10.00")

    def test_call_otm(self):
        """Call is OTM when spot < strike."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        # Spot = 570, Strike = 580 -> Call OTM
        assert call.intrinsic_value(Decimal("570.00")) == Decimal("0")

    def test_atm(self):
        """ATM options have zero intrinsic value."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        assert call.intrinsic_value(Decimal("580.00")) == Decimal("0")


class TestMoneyness:
    """Test moneyness calculations."""

    def test_is_itm_put(self):
        """Test is_itm for puts."""
        put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        assert put.is_itm(Decimal("570.00")) is True  # Spot below strike
        assert put.is_itm(Decimal("590.00")) is False  # Spot above strike
        assert put.is_itm(Decimal("580.00")) is False  # ATM

    def test_is_itm_call(self):
        """Test is_itm for calls."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        assert call.is_itm(Decimal("590.00")) is True  # Spot above strike
        assert call.is_itm(Decimal("570.00")) is False  # Spot below strike
        assert call.is_itm(Decimal("580.00")) is False  # ATM

    def test_is_otm(self):
        """Test is_otm helper."""
        put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580.00"),
            expiration=date(2025, 1, 17),
        )
        assert put.is_otm(Decimal("590.00")) is True
        assert put.is_otm(Decimal("570.00")) is False

    def test_moneyness_ratio(self):
        """Test moneyness ratio calculation."""
        contract = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("100.00"),
            expiration=date(2025, 1, 17),
        )
        assert contract.moneyness(Decimal("100.00")) == Decimal("1")  # ATM
        assert contract.moneyness(Decimal("110.00")) == Decimal("1.1")  # 10% ITM for call
        assert contract.moneyness(Decimal("90.00")) == Decimal("0.9")  # 10% OTM for call

    def test_otm_percentage_call(self):
        """Test OTM percentage for calls."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("105.00"),
            expiration=date(2025, 1, 17),
        )
        # 5% OTM call (strike 105, spot 100)
        otm_pct = call.otm_percentage(Decimal("100.00"))
        assert otm_pct == Decimal("0.05")

    def test_otm_percentage_put(self):
        """Test OTM percentage for puts."""
        put = OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("95.00"),
            expiration=date(2025, 1, 17),
        )
        # 5% OTM put (strike 95, spot 100)
        otm_pct = put.otm_percentage(Decimal("100.00"))
        assert otm_pct == Decimal("0.05")

    def test_otm_percentage_itm_is_negative(self):
        """ITM options have negative OTM percentage."""
        call = OptionContract(
            symbol="SPY",
            option_type=OptionType.CALL,
            strike=Decimal("95.00"),
            expiration=date(2025, 1, 17),
        )
        # ITM call (strike 95, spot 100) -> negative OTM%
        otm_pct = call.otm_percentage(Decimal("100.00"))
        assert otm_pct == Decimal("-0.05")
