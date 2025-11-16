"""
Trading suggestion serialization utilities.

These utilities handle conversion of Django models and complex objects
for JSON serialization, particularly for WebSocket channel communication
and API responses.
"""

from datetime import date, datetime
from decimal import Decimal

from django.forms.models import model_to_dict

# Fields exposed to WebSocket/API clients (matches TradingSuggestion.to_dict contract)
EXPOSED_FIELDS = [
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
    "max_profit",
    "price_effect",
    "iv_rank",
    "is_near_bollinger_band",
    "is_range_bound",
    "market_stress_level",
    "status",
    "generated_at",
    "expires_at",
    "has_real_pricing",
]


class TradingSuggestionSerializer:
    """Handles serialization for trading suggestions across all strategies."""

    @staticmethod
    def serialize_for_channels(suggestion, decimal_format="string"):
        """
        Convert suggestion model to dict serializable for channels.
        Uses existing conversion utility following DRY principles.

        Args:
            suggestion: TradingSuggestion model instance
            decimal_format: 'string' or 'float' for Decimal conversion

        Returns:
            dict: Serializable representation for WebSocket channels
        """
        data = model_to_dict(suggestion, fields=EXPOSED_FIELDS)

        # Add legs data with DTE using the model's to_dict method
        suggestion_dict = suggestion.to_dict()
        if "legs" in suggestion_dict:
            data["legs"] = suggestion_dict["legs"]

        # Also include strategy_id which is needed for formatting
        data["strategy_id"] = suggestion.strategy_id

        return TradingSuggestionSerializer._convert_for_serialization(data, decimal_format)

    @staticmethod
    def convert_decimals_to_floats(obj):
        """
        Recursively converts Decimal objects to floats.
        Delegates to generic conversion method following DRY principles.

        Args:
            obj: Object to convert (dict, list, or primitive)

        Returns:
            Object with Decimals converted to floats
        """
        return TradingSuggestionSerializer._convert_for_serialization(obj, decimal_format="float")

    @staticmethod
    def _convert_for_serialization(obj, decimal_format="float"):
        """
        Recursively converts objects for serialization.
        Extends existing pattern to support multiple decimal formats and datetimes.

        Args:
            obj: Object to convert (dict, list, tuple, set, or primitive)
            decimal_format: 'float' or 'string' for Decimal conversion

        Returns:
            Object with all non-serializable types converted
        """
        if isinstance(obj, Decimal):
            return str(obj) if decimal_format == "string" else float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {
                k: TradingSuggestionSerializer._convert_for_serialization(v, decimal_format)
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple, set)):
            return [
                TradingSuggestionSerializer._convert_for_serialization(elem, decimal_format)
                for elem in obj
            ]
        return obj
