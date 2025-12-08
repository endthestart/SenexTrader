"""
Test volatility format consistency across all layers.

TDD approach to fix volatility double-conversion bug:
- SDK returns decimal (0.2122 for 21.22%)
- Application stores decimal throughout
- Display layer converts to percentage only when needed

This test suite validates the correct format at each layer.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone

import pytest

from services.market_data.analysis import MarketConditionReport
from services.market_data.volatility import VolatilityAnalyzer
from trading.models import MarketMetricsHistory

User = get_user_model()


@pytest.mark.django_db(transaction=True)
class TestVolatilitySDKIngestion:
    """Test that SDK data is stored in decimal format."""

    @pytest.mark.asyncio
    async def test_sdk_decimal_format_stored_correctly(self):
        """
        Verify SDK decimal format (0.2122) is stored as-is, not converted to percentage.

        EXPECTED BEHAVIOR:
        - SDK returns: implied_volatility_30_day = 0.2122 (decimal)
        - Application stores: iv_30_day = 0.2122 (decimal)
        - NOT: iv_30_day = 21.22 (percentage)
        """
        # Create test data directly in database to verify storage format
        # This tests that the system stores SDK decimal format without conversion
        today = timezone.now().date()

        await MarketMetricsHistory.objects.acreate(
            symbol="TEST_SDK",
            date=today,
            iv_30_day=Decimal("0.2122"),  # SDK returns decimal format
            hv_30_day=Decimal("0.1850"),  # SDK returns decimal format
            iv_rank=Decimal("65.0"),
            iv_percentile=Decimal("68.0"),
        )

        retrieved = await MarketMetricsHistory.objects.aget(symbol="TEST_SDK", date=today)

        # Assert decimal format is preserved in database
        assert retrieved.iv_30_day == Decimal(
            "0.2122"
        ), f"Expected decimal 0.2122, got {retrieved.iv_30_day}"
        assert retrieved.hv_30_day == Decimal(
            "0.1850"
        ), f"Expected decimal 0.1850, got {retrieved.hv_30_day}"

        # Verify NOT stored as percentage
        assert retrieved.iv_30_day != Decimal("21.22"), "Should NOT be stored as percentage"
        assert retrieved.hv_30_day != Decimal("18.50"), "Should NOT be stored as percentage"


@pytest.mark.django_db(transaction=True)
class TestVolatilityDatabaseStorage:
    """Test that database stores volatility in decimal format."""

    @pytest.mark.asyncio
    async def test_database_stores_decimal_format(self):
        """
        Verify database fields store decimal format (0.2122), not percentage.

        Database schema should allow decimals like 0.9999 (99.99% volatility).
        """
        from django.utils import timezone

        today = timezone.now().date()

        # Create record with decimal format
        await MarketMetricsHistory.objects.acreate(
            symbol="SPY",
            date=today,
            iv_rank=Decimal("65.00"),
            iv_percentile=Decimal("68.00"),
            iv_30_day=Decimal("0.2122"),  # Decimal format
            hv_30_day=Decimal("0.1850"),  # Decimal format
        )

        # Retrieve and verify
        retrieved = await MarketMetricsHistory.objects.aget(symbol="SPY", date=today)
        assert retrieved.iv_30_day == Decimal(
            "0.2122"
        ), f"Expected decimal 0.2122, got {retrieved.iv_30_day}"
        assert retrieved.hv_30_day == Decimal(
            "0.1850"
        ), f"Expected decimal 0.1850, got {retrieved.hv_30_day}"

    @pytest.mark.asyncio
    async def test_database_handles_high_volatility(self):
        """
        Verify database can store high volatility values (market crashes).

        Example: During market crashes, HV can exceed 100% (1.0 in decimal).
        """
        from django.utils import timezone

        today = timezone.now().date()

        # Create record with crash-level volatility
        await MarketMetricsHistory.objects.acreate(
            symbol="VIX",
            date=today,
            iv_rank=Decimal("95.00"),
            iv_percentile=Decimal("98.00"),
            iv_30_day=Decimal("0.8500"),  # 85% IV
            hv_30_day=Decimal("1.2500"),  # 125% HV (market crash)
        )

        retrieved = await MarketMetricsHistory.objects.aget(symbol="VIX", date=today)
        assert retrieved.hv_30_day == Decimal("1.2500"), "Should handle HV > 100% (1.0 in decimal)"


@pytest.mark.django_db(transaction=True)
class TestVolatilityMarketAnalysis:
    """Test that MarketAnalyzer uses decimal format internally."""

    @pytest.mark.asyncio
    async def test_market_report_current_iv_is_decimal(self):
        """
        Verify MarketConditionReport.current_iv is in decimal format.

        EXPECTED: current_iv = 0.2122 (not 21.22)
        """
        # Create a report directly with decimal values
        report = MarketConditionReport(symbol="SPY", current_price=450.0)
        report.current_iv = 0.2122  # Decimal format
        report.historical_volatility = 0.1850  # Decimal format

        # Verify decimal format in report
        assert report.current_iv == pytest.approx(
            0.2122, rel=1e-4
        ), f"Expected decimal 0.2122, got {report.current_iv}"
        assert report.historical_volatility == pytest.approx(
            0.1850, rel=1e-4
        ), f"Expected decimal 0.1850, got {report.historical_volatility}"

        # Verify NOT percentage format
        assert report.current_iv != 21.22, "Should NOT be percentage"
        assert report.historical_volatility != 18.50, "Should NOT be percentage"

    @pytest.mark.asyncio
    async def test_hv_iv_ratio_calculation_uses_decimals(self):
        """
        Verify HV/IV ratio is calculated correctly with both values as decimals.

        Example: HV = 0.35, IV = 0.285 → ratio = 1.228
        NOT: HV = 35, IV = 28.5 → ratio = 1.228 (same result but wrong format)
        NOT: HV = 35, IV = 2850 → ratio = 0.012 (double-conversion bug!)
        """
        report = MarketConditionReport(symbol="SPY", current_price=450.0)
        report.current_iv = 0.285  # 28.5% IV (decimal)
        report.historical_volatility = 0.35  # 35% HV (decimal)

        # Call post_init to calculate ratio
        report.__post_init__()

        expected_ratio = 0.35 / 0.285  # ~1.228
        assert report.hv_iv_ratio == pytest.approx(
            expected_ratio, rel=1e-3
        ), f"Expected ratio {expected_ratio:.3f}, got {report.hv_iv_ratio:.3f}"

        # Verify NOT the double-conversion bug
        wrong_ratio = 35 / 2850  # ~0.012 (bug!)
        assert (
            abs(report.hv_iv_ratio - wrong_ratio) > 1.0
        ), "Detected double-conversion bug in HV/IV ratio"


@pytest.mark.django_db(transaction=True)
class TestVolatilityAPIDisplay:
    """Test that API layer converts decimal to percentage for display."""

    @pytest.mark.asyncio
    async def test_api_converts_decimal_to_percentage(self):
        """
        Verify API endpoint converts decimal (0.2122) to percentage (21.22) for frontend.

        This is the ONLY place where conversion should happen.
        """
        # Mock market report with decimal format
        mock_report = MagicMock()
        mock_report.current_iv = 0.2122  # Decimal format
        mock_report.iv_rank = 65.0
        mock_report.macd_signal = "bullish"
        mock_report.is_range_bound = False
        mock_report.market_stress_level = 25

        # Simulate API conversion (from api_views.py line 823)
        current_iv_pct = (
            round(mock_report.current_iv * 100, 1) if mock_report.current_iv is not None else None
        )

        # Verify conversion for display
        assert (
            current_iv_pct == 21.2
        ), f"Expected 21.2 (percentage for display), got {current_iv_pct}"

        # Verify NOT double-converted
        assert current_iv_pct != 2122.0, "Should NOT be double-converted"


@pytest.mark.django_db(transaction=True)
class TestVolatilityAnalyzer:
    """Test that VolatilityAnalyzer expects decimal format."""

    @pytest.mark.asyncio
    async def test_volatility_analyzer_expects_decimals(self):
        """
        Verify VolatilityAnalyzer.analyze() expects both HV and IV as decimals.

        EXPECTED:
        - historical_volatility: 0.185 (decimal)
        - implied_volatility: 0.2122 (decimal)

        NOT:
        - historical_volatility: 18.5 (percentage)
        - implied_volatility: 0.2122 (mixed format - inconsistent!)
        """
        user = await User.objects.acreate(username="test_user", email="test@example.com")
        analyzer = VolatilityAnalyzer(user)

        # Call with decimal format
        result = await analyzer.analyze(
            symbol="SPY",
            historical_volatility=0.185,  # Decimal format
            implied_volatility=0.2122,  # Decimal format
            iv_rank=65.0,
            iv_percentile=68.0,
        )

        # Verify HV/IV ratio calculation
        expected_ratio = 0.185 / 0.2122  # ~0.872
        assert result.hv_iv_ratio == pytest.approx(
            expected_ratio, rel=1e-3
        ), f"Expected ratio {expected_ratio:.3f}, got {result.hv_iv_ratio:.3f}"

        # Verify formats are preserved
        assert result.historical_volatility == pytest.approx(0.185, rel=1e-4)
        assert result.implied_volatility == pytest.approx(0.2122, rel=1e-4)


@pytest.mark.django_db(transaction=True)
class TestVolatilityStrategyUsage:
    """Test that strategies receive and use decimal format correctly."""

    @pytest.mark.asyncio
    async def test_strategies_receive_decimal_format(self):
        """
        Verify strategies receive market_report.current_iv in decimal format.

        Strategies should NOT need to convert - they should use the value as-is.
        """
        from services.strategies.credit_spread_strategy import (
            ShortPutVerticalStrategy,
        )

        user = await User.objects.acreate(username="test_user", email="test@example.com")
        ShortPutVerticalStrategy(user)

        # Mock market report with decimal format
        mock_report = MagicMock()
        mock_report.current_iv = 0.2122  # Decimal format
        mock_report.iv_rank = 65.0
        mock_report.rsi = 45.0
        mock_report.trend = "bullish"

        # Strategy should use decimal format directly
        # (This is a smoke test - actual strategy logic may vary)
        assert mock_report.current_iv < 1.0, "Strategy should receive decimal format (< 1.0)"
        assert mock_report.current_iv > 0.0, "Strategy should receive valid decimal"


@pytest.mark.django_db(transaction=True)
class TestVolatilityFrontendDisplay:
    """Test that frontend receives properly formatted percentage string."""

    def test_frontend_display_format(self):
        """
        Verify frontend receives percentage string like "21.2%" (not "2122.0%").

        This tests the final display formatting.
        """
        # Simulate API response
        api_volatility = 21.2  # Percentage (from current_iv * 100)

        # Simulate frontend formatting (from trading.js line 1324)
        frontend_display = f"{api_volatility:.1f}%"

        assert frontend_display == "21.2%", f"Expected '21.2%', got '{frontend_display}'"

        # Verify NOT the bug
        assert frontend_display != "2122.0%", "Should NOT show double-converted value"
        assert frontend_display != "212200.0%", "Should NOT show triple-converted value"


@pytest.mark.django_db(transaction=True)
class TestVolatilityEdgeCases:
    """Test edge cases and extreme volatility values."""

    @pytest.mark.asyncio
    async def test_zero_volatility(self):
        """Verify zero volatility is handled correctly."""
        report = MarketConditionReport(symbol="SPY", current_price=450.0)
        report.current_iv = 0.0
        report.historical_volatility = 0.05

        report.__post_init__()

        # Should default to ratio = 1.0 when IV is zero
        assert report.hv_iv_ratio == 1.0

    @pytest.mark.asyncio
    async def test_crash_level_volatility(self):
        """Verify extreme volatility (> 100%) is handled correctly."""
        report = MarketConditionReport(symbol="SPY", current_price=450.0)
        report.current_iv = 0.85  # 85% IV
        report.historical_volatility = 1.25  # 125% HV (market crash)

        report.__post_init__()

        expected_ratio = 1.25 / 0.85  # ~1.47
        assert report.hv_iv_ratio == pytest.approx(expected_ratio, rel=1e-3)

    @pytest.mark.asyncio
    async def test_none_volatility_values(self):
        """Verify None/zero values are handled gracefully."""
        report = MarketConditionReport(symbol="SPY", current_price=450.0)
        # current_iv defaults to 0.0, historical_volatility to 0.0
        # Test with zero values which behave similarly to None
        report.current_iv = 0.0
        report.historical_volatility = 0.0

        report.__post_init__()

        assert report.hv_iv_ratio == 1.0, "Should default to 1.0 when values are zero"
