"""
Tests for OCC symbol utility functions.

This module tests the centralized OCC (Options Clearing Corporation) symbol
generation, parsing, and validation functionality.
"""

from datetime import date
from decimal import Decimal

import pytest

from services.core.exceptions import InvalidOptionTypeError, InvalidSymbolFormatError
from services.sdk.instruments import (
    build_occ_symbol,
    parse_occ_symbol,
    validate_occ_symbol,
)


class TestBuildOCCSymbol:
    """Test build_occ_symbol function."""

    def test_build_occ_symbol_basic_put(self):
        """Test basic OCC symbol generation for a put option."""
        symbol = build_occ_symbol("SPY", date(2025, 11, 7), Decimal("591.00"), "P")
        assert symbol == "SPY   251107P00591000"

    def test_build_occ_symbol_basic_call(self):
        """Test basic OCC symbol generation for a call option."""
        symbol = build_occ_symbol("AAPL", date(2024, 12, 20), Decimal("175.50"), "C")
        assert symbol == "AAPL  241220C00175500"

    def test_build_occ_symbol_short_ticker(self):
        """Test OCC symbol with short underlying ticker (1-5 chars)."""
        # 1 char
        symbol = build_occ_symbol("A", date(2025, 1, 17), Decimal("100.00"), "P")
        assert symbol == "A     250117P00100000"
        assert len(symbol) == 21  # Total length is always 21

        # 3 chars
        symbol = build_occ_symbol("AMD", date(2025, 1, 17), Decimal("150.00"), "C")
        assert symbol == "AMD   250117C00150000"

    def test_build_occ_symbol_six_char_ticker(self):
        """Test OCC symbol with 6-character underlying ticker."""
        symbol = build_occ_symbol(
            "GOOGL", date(2025, 3, 21), Decimal("140.00"), "C"  # 5 chars - should be padded
        )
        # Should be 'GOOGL ' (GOOGL + 1 space)
        assert symbol[:6] == "GOOGL "
        assert symbol == "GOOGL 250321C00140000"

    def test_build_occ_symbol_fractional_strike(self):
        """Test OCC symbol with fractional strike prices."""
        # Strike with .50
        symbol = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("580.50"), "P")
        assert symbol == "SPY   250117P00580500"

        # Strike with .25
        symbol = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("580.25"), "C")
        assert symbol == "SPY   250117C00580250"

        # Strike with .75
        symbol = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("580.75"), "P")
        assert symbol == "SPY   250117P00580750"

    def test_build_occ_symbol_high_strike(self):
        """Test OCC symbol with very high strike prices."""
        symbol = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("9999.99"), "C")
        assert symbol == "SPY   250117C09999990"

    def test_build_occ_symbol_low_strike(self):
        """Test OCC symbol with very low strike prices."""
        symbol = build_occ_symbol("AMD", date(2025, 1, 17), Decimal("1.00"), "P")
        assert symbol == "AMD   250117P00001000"

        symbol = build_occ_symbol("AMD", date(2025, 1, 17), Decimal("0.50"), "P")
        assert symbol == "AMD   250117P00000500"

    def test_build_occ_symbol_expiration_formats(self):
        """Test OCC symbol with various expiration dates."""
        # Beginning of year
        symbol = build_occ_symbol("SPY", date(2025, 1, 3), Decimal("590.00"), "P")
        assert symbol == "SPY   250103P00590000"

        # End of year
        symbol = build_occ_symbol("SPY", date(2025, 12, 31), Decimal("590.00"), "C")
        assert symbol == "SPY   251231C00590000"

        # Leap year
        symbol = build_occ_symbol("SPY", date(2024, 2, 29), Decimal("590.00"), "P")
        assert symbol == "SPY   240229P00590000"

    def test_build_occ_symbol_invalid_strike_none(self):
        """Test that None strike raises TypeError."""
        with pytest.raises(TypeError):
            build_occ_symbol("SPY", date(2025, 1, 17), None, "P")

    def test_build_occ_symbol_invalid_option_type(self):
        """Test that invalid option type raises InvalidOptionTypeError."""
        with pytest.raises(InvalidOptionTypeError):
            build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "X")

        with pytest.raises(InvalidOptionTypeError):
            build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "call")

    def test_build_occ_symbol_case_sensitivity(self):
        """Test that option type must be uppercase 'C' or 'P'."""
        # Uppercase works
        symbol_upper_p = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "P")
        assert "P" in symbol_upper_p

        symbol_upper_c = build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "C")
        assert "C" in symbol_upper_c

        # Lowercase should fail
        with pytest.raises(InvalidOptionTypeError):
            build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "p")

        with pytest.raises(InvalidOptionTypeError):
            build_occ_symbol("SPY", date(2025, 1, 17), Decimal("590.00"), "c")


class TestParseOCCSymbol:
    """Test parse_occ_symbol function."""

    def test_parse_occ_symbol_basic(self):
        """Test parsing a basic OCC symbol."""
        result = parse_occ_symbol("SPY   251107P00591000")
        assert result["underlying"] == "SPY"
        assert result["expiration"] == date(2025, 11, 7)
        assert result["strike"] == Decimal("591.00")
        assert result["option_type"] == "P"

    def test_parse_occ_symbol_call(self):
        """Test parsing a call OCC symbol."""
        result = parse_occ_symbol("AAPL  241220C00175500")
        assert result["underlying"] == "AAPL"
        assert result["expiration"] == date(2024, 12, 20)
        assert result["strike"] == Decimal("175.50")
        assert result["option_type"] == "C"

    def test_parse_occ_symbol_fractional_strikes(self):
        """Test parsing OCC symbols with fractional strikes."""
        result = parse_occ_symbol("SPY   250117P00580250")
        assert result["strike"] == Decimal("580.25")

        result = parse_occ_symbol("SPY   250117C00580750")
        assert result["strike"] == Decimal("580.75")

    def test_parse_occ_symbol_short_ticker(self):
        """Test parsing OCC symbol with short ticker."""
        result = parse_occ_symbol("A     250117P00100000")
        assert result["underlying"] == "A"

        result = parse_occ_symbol("AMD   250117C00150000")
        assert result["underlying"] == "AMD"

    def test_parse_occ_symbol_invalid_format(self):
        """Test that invalid OCC symbol format raises InvalidSymbolFormatError."""
        with pytest.raises(InvalidSymbolFormatError):
            parse_occ_symbol("INVALID")

        with pytest.raises(InvalidSymbolFormatError):
            parse_occ_symbol("SPY250117P00590000")  # Missing padding

        with pytest.raises(InvalidSymbolFormatError):  # Also invalid length
            parse_occ_symbol("SPY   25P00590000")  # Wrong expiration format

    def test_parse_occ_symbol_invalid_option_type(self):
        """Test parsing symbol with invalid option type (doesn't raise, just returns it)."""
        # Note: parse doesn't validate option type, just extracts it
        result = parse_occ_symbol("SPY   251107X00591000")
        assert result["option_type"] == "X"  # Just extracts whatever is there


class TestValidateOCCSymbol:
    """Test validate_occ_symbol function."""

    def test_validate_occ_symbol_valid(self):
        """Test validation of valid OCC symbols."""
        assert validate_occ_symbol("SPY   251107P00591000") is True
        assert validate_occ_symbol("AAPL  241220C00175500") is True
        assert validate_occ_symbol("A     250117P00100000") is True

    def test_validate_occ_symbol_invalid_length(self):
        """Test validation rejects symbols with incorrect length."""
        assert validate_occ_symbol("SPY251107P00591000") is False  # Too short
        assert validate_occ_symbol("SPY   251107P005910000") is False  # Too long

    def test_validate_occ_symbol_invalid_option_type(self):
        """Test validation with invalid option type (validation just checks format, not semantic validity)."""
        # Note: validate_occ_symbol only checks format, not if option type is semantically valid
        assert (
            validate_occ_symbol("SPY   251107X00591000") is True
        )  # Valid format, even if 'X' isn't valid

    def test_validate_occ_symbol_invalid_format(self):
        """Test validation rejects malformed symbols."""
        assert validate_occ_symbol("INVALID") is False
        assert validate_occ_symbol("") is False
        assert validate_occ_symbol("SPY   25P00590000") is False


class TestRoundTrip:
    """Test that build and parse are inverse operations."""

    def test_round_trip_put(self):
        """Test build then parse for put options."""
        original = {
            "underlying": "SPY",
            "expiration": date(2025, 11, 7),
            "strike": Decimal("591.00"),
            "option_type": "P",
        }

        symbol = build_occ_symbol(
            original["underlying"],
            original["expiration"],
            original["strike"],
            original["option_type"],
        )

        parsed = parse_occ_symbol(symbol)

        assert parsed["underlying"] == original["underlying"]
        assert parsed["expiration"] == original["expiration"]
        assert parsed["strike"] == original["strike"]
        assert parsed["option_type"] == original["option_type"]

    def test_round_trip_call(self):
        """Test build then parse for call options."""
        original = {
            "underlying": "AAPL",
            "expiration": date(2024, 12, 20),
            "strike": Decimal("175.50"),
            "option_type": "C",
        }

        symbol = build_occ_symbol(
            original["underlying"],
            original["expiration"],
            original["strike"],
            original["option_type"],
        )

        parsed = parse_occ_symbol(symbol)

        assert parsed["underlying"] == original["underlying"]
        assert parsed["expiration"] == original["expiration"]
        assert parsed["strike"] == original["strike"]
        assert parsed["option_type"] == original["option_type"]

    def test_round_trip_various_strikes(self):
        """Test round trip with various strike prices."""
        test_cases = [
            Decimal("1.00"),
            Decimal("10.50"),
            Decimal("100.25"),
            Decimal("1000.75"),
            Decimal("9999.99"),
        ]

        for strike in test_cases:
            symbol = build_occ_symbol("SPY", date(2025, 1, 17), strike, "P")
            parsed = parse_occ_symbol(symbol)
            assert parsed["strike"] == strike, f"Failed for strike {strike}"
