"""Tests for core type definitions."""

import json
from decimal import Decimal

from services.strategies.core.types import (
    Delta,
    Direction,
    OptionType,
    Premium,
    Quantity,
    Side,
    Strike,
    StrikeSelection,
)


class TestTypeAliases:
    """Test type aliases are properly defined."""

    def test_strike_is_decimal(self):
        strike: Strike = Decimal("585.00")
        assert isinstance(strike, Decimal)

    def test_premium_is_decimal(self):
        premium: Premium = Decimal("2.50")
        assert isinstance(premium, Decimal)

    def test_delta_is_float(self):
        delta: Delta = 0.30
        assert isinstance(delta, float)

    def test_quantity_is_int(self):
        qty: Quantity = 10
        assert isinstance(qty, int)


class TestDirection:
    """Test Direction enum."""

    def test_values(self):
        assert Direction.BULLISH.value == "bullish"
        assert Direction.BEARISH.value == "bearish"
        assert Direction.NEUTRAL.value == "neutral"

    def test_string_serialization(self):
        """Enums should serialize to strings for JSON."""
        assert str(Direction.BULLISH) == "Direction.BULLISH"
        assert Direction.BULLISH.value == "bullish"

    def test_json_serializable(self):
        """Enum values should be JSON serializable."""
        data = {"direction": Direction.BULLISH.value}
        json_str = json.dumps(data)
        assert '"bullish"' in json_str

    def test_from_string(self):
        """Should be able to reconstruct from string value."""
        assert Direction("bullish") == Direction.BULLISH
        assert Direction("bearish") == Direction.BEARISH


class TestOptionType:
    """Test OptionType enum."""

    def test_values(self):
        assert OptionType.CALL.value == "C"
        assert OptionType.PUT.value == "P"

    def test_full_name(self):
        assert OptionType.CALL.full_name == "Call"
        assert OptionType.PUT.full_name == "Put"

    def test_from_string(self):
        assert OptionType("C") == OptionType.CALL
        assert OptionType("P") == OptionType.PUT


class TestSide:
    """Test Side enum."""

    def test_values(self):
        assert Side.LONG.value == "long"
        assert Side.SHORT.value == "short"

    def test_multiplier(self):
        assert Side.LONG.multiplier == 1
        assert Side.SHORT.multiplier == -1

    def test_multiplier_in_calculation(self):
        """Multiplier should work for P&L calculations."""
        premium = Decimal("2.50")
        # Long position: negative cash flow (paid premium)
        long_cash = premium * Side.LONG.multiplier * -1  # Pay
        assert long_cash == Decimal("-2.50")
        # Short position: positive cash flow (received premium)
        short_cash = premium * Side.SHORT.multiplier * -1  # Receive
        assert short_cash == Decimal("2.50")


class TestStrikeSelection:
    """Test StrikeSelection enum."""

    def test_values(self):
        assert StrikeSelection.DELTA.value == "delta"
        assert StrikeSelection.OTM_PERCENT.value == "otm_pct"
        assert StrikeSelection.FIXED_WIDTH.value == "width"
        assert StrikeSelection.ATM_OFFSET.value == "atm"

    def test_all_methods_defined(self):
        """Ensure all expected selection methods exist."""
        methods = [m.value for m in StrikeSelection]
        assert "delta" in methods
        assert "otm_pct" in methods
        assert "width" in methods
        assert "atm" in methods
