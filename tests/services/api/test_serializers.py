"""Tests for trading suggestion serializers."""

from datetime import date, datetime
from decimal import Decimal

from services.api.serializers import EXPOSED_FIELDS, TradingSuggestionSerializer


class TestConvertForSerialization:
    """Test _convert_for_serialization with various data types."""

    def test_decimal_to_float(self):
        """Test Decimal conversion to float."""
        result = TradingSuggestionSerializer._convert_for_serialization(
            Decimal("123.45"), decimal_format="float"
        )
        assert result == 123.45
        assert isinstance(result, float)

    def test_decimal_to_string(self):
        """Test Decimal conversion to string."""
        result = TradingSuggestionSerializer._convert_for_serialization(
            Decimal("123.45"), decimal_format="string"
        )
        assert result == "123.45"
        assert isinstance(result, str)

    def test_datetime_conversion(self):
        """Test datetime conversion to ISO format."""
        dt = datetime(2025, 1, 15, 10, 30, 45)
        result = TradingSuggestionSerializer._convert_for_serialization(dt)
        assert result == "2025-01-15T10:30:45"

    def test_date_conversion(self):
        """Test date conversion to ISO format."""
        d = date(2025, 1, 15)
        result = TradingSuggestionSerializer._convert_for_serialization(d)
        assert result == "2025-01-15"

    def test_dict_conversion(self):
        """Test recursive dict conversion."""
        data = {
            "price": Decimal("100.50"),
            "timestamp": datetime(2025, 1, 15, 10, 30),
            "symbol": "SPY",
        }
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="float"
        )
        assert result == {
            "price": 100.50,
            "timestamp": "2025-01-15T10:30:00",
            "symbol": "SPY",
        }

    def test_list_conversion(self):
        """Test list conversion."""
        data = [Decimal("100.50"), Decimal("200.75"), "text"]
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="float"
        )
        assert result == [100.50, 200.75, "text"]

    def test_tuple_conversion(self):
        """Test tuple conversion to list."""
        data = (Decimal("100.50"), Decimal("200.75"), "text")
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="float"
        )
        assert result == [100.50, 200.75, "text"]
        assert isinstance(result, list)

    def test_set_conversion(self):
        """Test set conversion to list."""
        data = {"text", "other"}
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="float"
        )
        assert isinstance(result, list)
        assert set(result) == {"text", "other"}

    def test_nested_tuple_in_dict(self):
        """Test nested tuple inside dict (regression test for JSONField data)."""
        data = {
            "strikes": (Decimal("100.00"), Decimal("105.00")),
            "prices": [Decimal("1.50"), Decimal("2.00")],
        }
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="string"
        )
        assert result == {
            "strikes": ["100.00", "105.00"],
            "prices": ["1.50", "2.00"],
        }

    def test_nested_decimals_in_tuple(self):
        """Test Decimals nested inside tuples are converted."""
        data = (
            {"price": Decimal("100.50")},
            [Decimal("200.75"), Decimal("300.25")],
        )
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="float"
        )
        assert result == [
            {"price": 100.50},
            [200.75, 300.25],
        ]

    def test_deeply_nested_structures(self):
        """Test deeply nested mixed structures."""
        data = {
            "level1": {
                "level2": [
                    {"decimals": (Decimal("1.0"), Decimal("2.0"))},
                    {"dates": [date(2025, 1, 1), datetime(2025, 1, 2, 12, 0)]},
                ]
            }
        }
        result = TradingSuggestionSerializer._convert_for_serialization(
            data, decimal_format="string"
        )
        assert result == {
            "level1": {
                "level2": [
                    {"decimals": ["1.0", "2.0"]},
                    {"dates": ["2025-01-01", "2025-01-02T12:00:00"]},
                ]
            }
        }

    def test_primitive_types_unchanged(self):
        """Test that primitive types pass through unchanged."""
        assert TradingSuggestionSerializer._convert_for_serialization("text") == "text"
        assert TradingSuggestionSerializer._convert_for_serialization(123) == 123
        assert TradingSuggestionSerializer._convert_for_serialization(123.45) == 123.45
        assert TradingSuggestionSerializer._convert_for_serialization(True) is True
        assert TradingSuggestionSerializer._convert_for_serialization(None) is None

    def test_empty_collections(self):
        """Test empty collections."""
        assert TradingSuggestionSerializer._convert_for_serialization([]) == []
        assert TradingSuggestionSerializer._convert_for_serialization(()) == []
        assert TradingSuggestionSerializer._convert_for_serialization(set()) == []
        assert TradingSuggestionSerializer._convert_for_serialization({}) == {}


class TestConvertDecimalsToFloats:
    """Test the convert_decimals_to_floats convenience method."""

    def test_delegates_to_convert_for_serialization(self):
        """Test that convert_decimals_to_floats uses float format."""
        data = {"price": Decimal("100.50")}
        result = TradingSuggestionSerializer.convert_decimals_to_floats(data)
        assert result == {"price": 100.50}
        assert isinstance(result["price"], float)


class TestExposedFields:
    """Test EXPOSED_FIELDS constant."""

    def test_exposed_fields_matches_to_dict_contract(self):
        """Verify EXPOSED_FIELDS matches the fields in TradingSuggestion.to_dict."""
        expected_fields = [
            "id",
            "underlying_symbol",
            "underlying_price",
            "expiration_date",
            "short_put_strike",
            "long_put_strike",
            "short_call_strike",
            "long_call_strike",
            "put_spread_quantity",
            "call_spread_quantity",
            "put_spread_credit",
            "call_spread_credit",
            "total_credit",
            "put_spread_mid_credit",
            "call_spread_mid_credit",
            "total_mid_credit",
            "max_risk",
            "iv_rank",
            "is_range_bound",
            "market_stress_level",
            "status",
        ]

        for field in expected_fields:
            assert field in EXPOSED_FIELDS, f"Expected field {field} not in EXPOSED_FIELDS"

    def test_exposed_fields_excludes_internal_fields(self):
        """Verify internal-only fields are NOT exposed."""
        internal_fields = [
            "generation_notes",
            "rejection_reason",
            "streaming_latency_ms",
            "pricing_source",
            "user",
            "strategy_configuration",
        ]

        for field in internal_fields:
            assert field not in EXPOSED_FIELDS, f"Internal field {field} should not be exposed"
