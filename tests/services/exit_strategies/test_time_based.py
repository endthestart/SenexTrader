"""Tests for TimeBasedExit strategy."""

from datetime import timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from django.utils import timezone

import pytest

from services.exit_strategies.time_based import TimeBasedExit

# Use the same timezone as the implementation to avoid date boundary issues
ET_TIMEZONE = ZoneInfo("America/New_York")


def get_today_et():
    """Get today's date in ET timezone (consistent with TimeBasedExit._get_dte)."""
    return timezone.now().astimezone(ET_TIMEZONE).date()


@pytest.mark.asyncio
class TestTimeBasedExit:
    """Test TimeBasedExit strategy."""

    async def test_min_dte_triggered(self):
        """Test exit when DTE falls below minimum."""
        # Create strategy with 7 DTE minimum
        strategy = TimeBasedExit(min_dte=7)

        # Create mock position with 5 DTE (below minimum)
        position = Mock()
        position.id = 1
        # 5 days from today in ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=5)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now() - timedelta(days=10)

        # Evaluate
        result = await strategy.evaluate(position)

        # Should trigger exit (5 < 7)
        assert result.should_exit is True
        assert "DTE 5 < minimum 7" in result.reason
        assert result.metadata["current_dte"] == 5
        assert result.metadata["min_dte"] == 7

    async def test_min_dte_not_triggered(self):
        """Test no exit when DTE above minimum."""
        strategy = TimeBasedExit(min_dte=7)

        position = Mock()
        position.id = 1
        # 10 days from today in ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=10)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now() - timedelta(days=5)

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (10 >= 7)
        assert result.should_exit is False
        assert "DTE 10 >= minimum 7" in result.reason
        assert result.metadata["current_dte"] == 10

    async def test_max_dte_triggered(self):
        """Test exit when DTE exceeds maximum."""
        strategy = TimeBasedExit(max_dte=45)

        position = Mock()
        position.id = 1
        # 60 days from today in ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=60)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now()

        result = await strategy.evaluate(position)

        # Should trigger exit (60 > 45)
        assert result.should_exit is True
        assert "DTE 60 > maximum 45" in result.reason
        assert result.metadata["max_dte"] == 45

    async def test_max_dte_not_triggered(self):
        """Test no exit when DTE below maximum."""
        strategy = TimeBasedExit(max_dte=45)

        position = Mock()
        position.id = 1
        # 30 days from today in ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=30)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        position.opened_at = timezone.now()

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (30 <= 45)
        assert result.should_exit is False
        assert "DTE 30 <= maximum 45" in result.reason

    async def test_min_holding_days_not_met(self):
        """Test no exit when minimum holding period not met."""
        strategy = TimeBasedExit(min_holding_days=30)

        position = Mock()
        position.id = 1
        position.opened_at = timezone.now() - timedelta(days=20)
        position.metadata = {}

        result = await strategy.evaluate(position)

        # Should NOT exit (only held 20 days, need 30)
        assert result.should_exit is False
        assert "Holding 20 days < minimum 30" in result.reason
        assert result.metadata["holding_days"] == 20
        assert result.metadata["min_holding_days"] == 30

    async def test_min_holding_days_met(self):
        """Test when minimum holding period is met (but doesn't trigger exit)."""
        strategy = TimeBasedExit(min_holding_days=30)

        position = Mock()
        position.id = 1
        position.opened_at = timezone.now() - timedelta(days=35)
        position.metadata = {}

        result = await strategy.evaluate(position)

        # Should NOT exit (min_holding is a hold condition, not exit condition)
        assert result.should_exit is False
        assert "Holding 35 days >= minimum 30" in result.reason

    async def test_max_holding_days_triggered(self):
        """Test exit when maximum holding period exceeded."""
        strategy = TimeBasedExit(max_holding_days=60)

        position = Mock()
        position.id = 1
        position.opened_at = timezone.now() - timedelta(days=65)
        position.metadata = {}

        result = await strategy.evaluate(position)

        # Should trigger exit (held 65 days > 60 max)
        assert result.should_exit is True
        assert "Holding 65 days > maximum 60" in result.reason
        assert result.metadata["holding_days"] == 65
        assert result.metadata["max_holding_days"] == 60

    async def test_max_holding_days_not_triggered(self):
        """Test no exit when holding period below maximum."""
        strategy = TimeBasedExit(max_holding_days=60)

        position = Mock()
        position.id = 1
        position.opened_at = timezone.now() - timedelta(days=45)
        position.metadata = {}

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (45 <= 60)
        assert result.should_exit is False
        assert "Holding 45 days <= maximum 60" in result.reason

    async def test_multiple_criteria_all_met(self):
        """Test exit when multiple time criteria met."""
        # Min DTE 7, max holding 60 days
        strategy = TimeBasedExit(min_dte=7, max_holding_days=60)

        position = Mock()
        position.id = 1
        # 5 DTE (triggers min_dte) - use ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=5)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        # 65 days held (triggers max_holding)
        position.opened_at = timezone.now() - timedelta(days=65)

        result = await strategy.evaluate(position)

        # Should exit (both conditions trigger)
        assert result.should_exit is True
        assert "DTE 5 < minimum 7" in result.reason
        assert "Holding 65 days > maximum 60" in result.reason

    async def test_multiple_criteria_one_met(self):
        """Test exit when one of multiple criteria met."""
        strategy = TimeBasedExit(min_dte=7, max_holding_days=60)

        position = Mock()
        position.id = 1
        # 5 DTE (triggers min_dte) - use ET timezone
        today_et = get_today_et()
        future_date = (today_et + timedelta(days=5)).strftime("%Y-%m-%d")
        position.metadata = {"expiration_date": future_date}
        # 30 days held (does NOT trigger max_holding)
        position.opened_at = timezone.now() - timedelta(days=30)

        result = await strategy.evaluate(position)

        # Should exit (one condition triggers)
        assert result.should_exit is True
        assert "DTE 5 < minimum 7" in result.reason

    async def test_no_expiration_date(self):
        """Test handling when expiration_date not in metadata."""
        strategy = TimeBasedExit(min_dte=7)

        position = Mock()
        position.id = 1
        position.metadata = {}  # No expiration_date
        position.opened_at = timezone.now()

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "DTE not available" in result.reason

    async def test_no_opened_at(self):
        """Test handling when opened_at is None."""
        strategy = TimeBasedExit(min_holding_days=30)

        position = Mock()
        position.id = 1
        position.metadata = {}
        position.opened_at = None

        result = await strategy.evaluate(position)

        # Should NOT trigger exit
        assert result.should_exit is False
        assert "Holding period not available" in result.reason

    async def test_invalid_expiration_date_format(self):
        """Test handling of invalid expiration date format."""
        strategy = TimeBasedExit(min_dte=7)

        position = Mock()
        position.id = 1
        position.metadata = {"expiration_date": "invalid-date"}
        position.opened_at = timezone.now()

        result = await strategy.evaluate(position)

        # Should NOT trigger exit (can't parse date)
        assert result.should_exit is False
        assert "DTE not available" in result.reason

    def test_no_criteria_specified(self):
        """Test validation when no time criteria provided."""
        with pytest.raises(ValueError, match="At least one time criterion"):
            TimeBasedExit()

    def test_invalid_min_dte(self):
        """Test validation of min_dte parameter."""
        with pytest.raises(ValueError, match="min_dte must be non-negative"):
            TimeBasedExit(min_dte=-5)

    def test_invalid_max_dte(self):
        """Test validation of max_dte parameter."""
        with pytest.raises(ValueError, match="max_dte must be non-negative"):
            TimeBasedExit(max_dte=-5)

    def test_invalid_dte_range(self):
        """Test validation of DTE range (min > max)."""
        with pytest.raises(ValueError, match="min_dte .* must be <= max_dte"):
            TimeBasedExit(min_dte=30, max_dte=7)

    def test_invalid_min_holding_days(self):
        """Test validation of min_holding_days parameter."""
        with pytest.raises(ValueError, match="min_holding_days must be non-negative"):
            TimeBasedExit(min_holding_days=-10)

    def test_invalid_max_holding_days(self):
        """Test validation of max_holding_days parameter."""
        with pytest.raises(ValueError, match="max_holding_days must be non-negative"):
            TimeBasedExit(max_holding_days=-10)

    def test_invalid_holding_days_range(self):
        """Test validation of holding days range (min > max)."""
        with pytest.raises(ValueError, match="min_holding_days .* must be <= max_holding_days"):
            TimeBasedExit(min_holding_days=60, max_holding_days=30)

    def test_get_name_single_criterion(self):
        """Test name generation with single criterion."""
        strategy = TimeBasedExit(min_dte=7)
        assert strategy.get_name() == "DTE < 7"

        strategy = TimeBasedExit(max_dte=45)
        assert strategy.get_name() == "DTE > 45"

        strategy = TimeBasedExit(min_holding_days=30)
        assert strategy.get_name() == "Hold >= 30d"

        strategy = TimeBasedExit(max_holding_days=60)
        assert strategy.get_name() == "Hold <= 60d"

    def test_get_name_multiple_criteria(self):
        """Test name generation with multiple criteria."""
        strategy = TimeBasedExit(min_dte=7, max_holding_days=60)
        assert "DTE < 7" in strategy.get_name()
        assert "Hold <= 60d" in strategy.get_name()
        assert " AND " in strategy.get_name()
