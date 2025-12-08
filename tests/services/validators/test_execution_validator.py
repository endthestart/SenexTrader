"""Unit tests for ExecutionValidator."""

from decimal import Decimal
from unittest.mock import Mock

from services.execution.validators.execution_validator import ExecutionValidator


class TestValidateCustomCredit:
    """Test ExecutionValidator.validate_custom_credit method."""

    def test_none_input_returns_none_none(self):
        """Test that None input returns (None, None)."""
        credit, error = ExecutionValidator.validate_custom_credit(None)
        assert credit is None
        assert error is None

    def test_valid_credit_string(self):
        """Test valid credit as string."""
        credit, error = ExecutionValidator.validate_custom_credit("5.50")
        assert credit == Decimal("5.50")
        assert error is None

    def test_valid_credit_decimal(self):
        """Test valid credit as Decimal."""
        credit, error = ExecutionValidator.validate_custom_credit(Decimal("10.00"))
        assert credit == Decimal("10.00")
        assert error is None

    def test_valid_credit_integer(self):
        """Test valid credit as integer."""
        credit, error = ExecutionValidator.validate_custom_credit(5)
        assert credit == Decimal("5")
        assert error is None

    def test_valid_credit_float(self):
        """Test valid credit as float."""
        credit, error = ExecutionValidator.validate_custom_credit(7.25)
        assert credit == Decimal("7.25")
        assert error is None

    def test_valid_credit_max_value(self):
        """Test credit at maximum allowed value ($100.00)."""
        credit, error = ExecutionValidator.validate_custom_credit("100.00")
        assert credit == Decimal("100.00")
        assert error is None

    def test_valid_credit_min_value(self):
        """Test credit at minimum allowed value (just above $0)."""
        credit, error = ExecutionValidator.validate_custom_credit("0.01")
        assert credit == Decimal("0.01")
        assert error is None

    def test_invalid_format_string(self):
        """Test invalid format - non-numeric string."""
        credit, error = ExecutionValidator.validate_custom_credit("abc")
        assert credit is None
        assert error == "Invalid credit format. Must be a valid number."

    def test_invalid_format_special_chars(self):
        """Test invalid format - special characters."""
        credit, error = ExecutionValidator.validate_custom_credit("$5.00")
        assert credit is None
        assert error == "Invalid credit format. Must be a valid number."

    def test_invalid_format_empty_string(self):
        """Test invalid format - empty string."""
        credit, error = ExecutionValidator.validate_custom_credit("")
        assert credit is None
        assert error == "Invalid credit format. Must be a valid number."

    def test_negative_credit(self):
        """Test negative credit value."""
        credit, error = ExecutionValidator.validate_custom_credit("-5.00")
        assert credit is None
        assert error == "Credit must be positive (greater than $0.00)."

    def test_zero_credit(self):
        """Test zero credit value."""
        credit, error = ExecutionValidator.validate_custom_credit("0.00")
        assert credit is None
        assert error == "Credit must be positive (greater than $0.00)."

    def test_exceeds_maximum(self):
        """Test credit exceeds maximum ($100.00)."""
        credit, error = ExecutionValidator.validate_custom_credit("100.01")
        assert credit is None
        assert error == "Credit must not exceed $100.00."

    def test_exceeds_maximum_large_value(self):
        """Test credit far exceeds maximum."""
        credit, error = ExecutionValidator.validate_custom_credit("500.00")
        assert credit is None
        assert error == "Credit must not exceed $100.00."

    def test_too_many_decimal_places_three(self):
        """Test too many decimal places - 3 places."""
        credit, error = ExecutionValidator.validate_custom_credit("5.123")
        assert credit is None
        assert error == "Credit must have at most 2 decimal places."

    def test_too_many_decimal_places_four(self):
        """Test too many decimal places - 4 places."""
        credit, error = ExecutionValidator.validate_custom_credit("10.1234")
        assert credit is None
        assert error == "Credit must have at most 2 decimal places."

    def test_valid_one_decimal_place(self):
        """Test valid credit with 1 decimal place."""
        credit, error = ExecutionValidator.validate_custom_credit("5.5")
        assert credit == Decimal("5.5")
        assert error is None

    def test_valid_no_decimal_places(self):
        """Test valid credit with no decimal places."""
        credit, error = ExecutionValidator.validate_custom_credit("5")
        assert credit == Decimal("5")
        assert error is None


class TestValidateSuggestionAccess:
    """Test ExecutionValidator.validate_suggestion_access method."""

    def test_valid_access(self):
        """Test valid suggestion access."""
        # Create mock objects
        user = Mock()
        suggestion = Mock()
        suggestion.user = user

        error = ExecutionValidator.validate_suggestion_access(suggestion, user)
        assert error is None

    def test_suggestion_not_found(self):
        """Test None suggestion returns error."""
        user = Mock()
        error = ExecutionValidator.validate_suggestion_access(None, user)
        assert error == "Suggestion not found or not in pending status"

    def test_access_denied_different_user(self):
        """Test access denied when suggestion belongs to different user."""
        user = Mock()
        other_user = Mock()
        suggestion = Mock()
        suggestion.user = other_user

        error = ExecutionValidator.validate_suggestion_access(suggestion, user)
        assert error == "Access denied to this suggestion"


class TestValidateSenexTridentStructure:
    """Test ExecutionValidator.validate_senex_trident_structure method."""

    def test_valid_senex_trident_with_call_spread(self):
        """Test valid Senex Trident structure with call spread."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is None

    def test_valid_senex_trident_without_call_spread(self):
        """Test valid Senex Trident structure without call spread."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 0
        suggestion.total_credit = Decimal("2.50")
        suggestion.put_spread_credit = Decimal("1.25")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is None

    def test_non_senex_trident_strategy_passes(self):
        """Test non-Senex strategies are not validated."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "bull_put_spread"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 1  # Would be invalid for Senex
        suggestion.call_spread_quantity = 0

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is None  # Should pass because it's not a Senex Trident

    def test_invalid_put_spread_quantity_zero(self):
        """Test invalid put_spread_quantity = 0."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 0
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "put_spread_quantity must be 2" in error
        assert "got 0" in error

    def test_invalid_put_spread_quantity_one(self):
        """Test invalid put_spread_quantity = 1 (the bug we're fixing)."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 1  # THE BUG
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "put_spread_quantity must be 2" in error
        assert "got 1" in error

    def test_invalid_put_spread_quantity_three(self):
        """Test invalid put_spread_quantity = 3."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 3
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "put_spread_quantity must be 2" in error
        assert "got 3" in error

    def test_invalid_call_spread_quantity_zero_when_present(self):
        """Test that call_spread_quantity = 0 or None is valid (no call spread)."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 0
        suggestion.total_credit = Decimal("2.50")
        suggestion.put_spread_credit = Decimal("1.25")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is None  # 0 is valid (no call spread)

    def test_invalid_call_spread_quantity_two(self):
        """Test invalid call_spread_quantity = 2."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 2
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "call_spread_quantity must be 1" in error
        assert "got 2" in error

    def test_invalid_total_credit_zero(self):
        """Test invalid total_credit = 0."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("0")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "total_credit must be positive" in error

    def test_invalid_total_credit_negative(self):
        """Test invalid total_credit = negative."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("-1.50")
        suggestion.put_spread_credit = Decimal("1.50")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "total_credit must be positive" in error

    def test_invalid_put_spread_credit_zero(self):
        """Test invalid put_spread_credit = 0."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = Decimal("0")

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "put_spread_credit must be positive" in error

    def test_invalid_put_spread_credit_none(self):
        """Test invalid put_spread_credit = None."""
        suggestion = Mock()
        strategy_config = Mock()
        strategy_config.strategy_id = "senex_trident"
        suggestion.strategy_id = strategy_config.strategy_id
        suggestion.put_spread_quantity = 2
        suggestion.call_spread_quantity = 1
        suggestion.total_credit = Decimal("3.50")
        suggestion.put_spread_credit = None

        error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        assert error is not None
        assert "put_spread_credit must be positive" in error
