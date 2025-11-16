"""
Tests for MarketDataService - Epic 27 Task 013 Regression Tests.

Tests to ensure volatility data quality fixes prevent future regressions.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

import pytest

from services.market_data.service import MarketDataService
from trading.models import MarketMetricsHistory


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_zero_iv_persisted_correctly():
    """
    Regression test: Ensure IV=0.0 is treated as valid data.

    Epic 27 Task 013 Issue 1: Previously, truthy checks skipped 0.0 values, causing:
    - Database rows not persisted
    - TypeError: float() argument must be a string or a real number, not 'NoneType'

    This test ensures zero IV (valid in low-volatility environments) is persisted correctly.
    """
    # Clear cache to avoid pollution from previous test runs
    cache.clear()

    # Mock TastyTrade metrics with zero IV (very low volatility environment)
    class MockMetrics:
        tos_implied_volatility_index_rank = 0.0  # 0% IV Rank (SDK returns 0-1 scale)
        implied_volatility_percentile = 0.0  # 0% IV Percentile (SDK returns 0-1 scale)
        implied_volatility_30_day = 0.0  # 0% Current IV (SDK returns percentage: 0.0 = 0%)
        historical_volatility_30_day = 5.0  # SDK returns percentage format (5.0 = 5%)

    # Mock the API response
    mock_session = AsyncMock()
    mock_get_metrics = AsyncMock(return_value=[MockMetrics()])

    # Create service with mocked user
    user = MagicMock()
    user.id = 1
    service = MarketDataService(user=user)

    # Mock the session and API call
    service._get_session = AsyncMock(return_value=mock_session)

    # Patch the SDK function at the correct import location
    with patch("tastytrade.metrics.a_get_market_metrics", mock_get_metrics):
        # Fetch metrics (should not raise TypeError)
        result = await service.get_market_metrics("SPY")

        # Verify result has zero values (not None)
        assert result is not None, "Should return data for zero IV"
        assert result["iv_rank"] == 0.0, "IV Rank should be 0.0, not None"
        assert result["iv_percentile"] == 0.0, "IV Percentile should be 0.0, not None"
        assert result["iv_30_day"] == 0.0, "IV 30-day should be 0.0, not None"
        assert (
            result["hv_30_day"] == 5.0
        ), "HV 30-day should be 5.0 (SDK percentage format), not None"

        # Verify data was persisted to database (use timezone.now() like the service does)
        today = timezone.now().date()
        metrics = await MarketMetricsHistory.objects.aget(symbol="SPY", date=today)

        assert metrics.iv_rank == Decimal("0.0"), "IV Rank should persist as 0, not NULL"
        assert metrics.iv_percentile == Decimal(
            "0.0"
        ), "IV Percentile should persist as 0, not NULL"
        assert metrics.iv_30_day == Decimal("0.0"), "IV 30-day should persist as 0, not NULL"
        assert metrics.hv_30_day == Decimal(
            "5.0"
        ), "HV 30-day should persist as 5.0 (SDK percentage format), not NULL"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_none_iv_not_persisted():
    """
    Ensure NULL from API (missing data) is NOT persisted.

    When TastyTrade API returns None (no data available), we should skip persistence
    rather than creating incomplete records.
    """
    # Clear cache to avoid pollution
    cache.clear()

    # Mock TastyTrade metrics with None values (missing data)
    class MockMetrics:
        tos_implied_volatility_index_rank = None
        implied_volatility_percentile = None
        implied_volatility_30_day = None
        historical_volatility_30_day = None

    # Mock the API response
    mock_session = AsyncMock()
    mock_get_metrics = AsyncMock(return_value=[MockMetrics()])

    # Create service with mocked user
    user = MagicMock()
    user.id = 1
    service = MarketDataService(user=user)

    # Mock the session and API call
    service._get_session = AsyncMock(return_value=mock_session)

    # Patch the SDK function at the correct import location
    with patch("tastytrade.metrics.a_get_market_metrics", mock_get_metrics):
        # Fetch metrics (should return data dict with None values)
        result = await service.get_market_metrics("TEST")

        # Verify result has None values
        assert result is not None, "Should return dict even with None values"
        assert result["iv_rank"] is None, "IV Rank should be None"
        assert result["iv_percentile"] is None, "IV Percentile should be None"
        assert result["iv_30_day"] is None, "IV 30-day should be None"

        # Verify no row was created (essential fields are None, so persistence skipped)
        today = timezone.now().date()
        exists = await MarketMetricsHistory.objects.filter(symbol="TEST", date=today).aexists()
        assert not exists, "Should not persist when all essential fields are None"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_historical_volatility_extracted():
    """
    Epic 27 Task 013 Issue 2: Verify HV field is extracted from SDK.

    Ensures historical_volatility_30_day is fetched from TastyTrade API
    and persisted to database (was previously NULL permanently).
    """
    # Clear cache to avoid pollution
    cache.clear()

    # Mock TastyTrade metrics with HV data
    class MockMetrics:
        tos_implied_volatility_index_rank = 0.45  # 45% IV Rank (SDK returns 0-1 scale)
        implied_volatility_percentile = 0.50  # 50% IV Percentile (SDK returns 0-1 scale)
        implied_volatility_30_day = 28.0  # SDK returns percentage format (28.0 = 28%)
        historical_volatility_30_day = 22.0  # SDK returns percentage format (22.0 = 22%)

    # Mock the API response
    mock_session = AsyncMock()
    mock_get_metrics = AsyncMock(return_value=[MockMetrics()])

    # Create service with mocked user
    user = MagicMock()
    user.id = 1
    service = MarketDataService(user=user)

    # Mock the session and API call
    service._get_session = AsyncMock(return_value=mock_session)

    # Patch the SDK function at the correct import location
    with patch("tastytrade.metrics.a_get_market_metrics", mock_get_metrics):
        # Fetch metrics (use different symbol to avoid cache collision with test 1)
        result = await service.get_market_metrics("QQQ")

        # Verify HV field is in result
        assert result is not None
        assert "hv_30_day" in result, "HV field should be in result dict"
        assert result["hv_30_day"] == 22.0, "HV should be 22.0 (SDK percentage format)"
        assert result["iv_30_day"] == 28.0, "IV should be 28.0 (SDK percentage format)"

        # Verify HV was persisted to database (use timezone.now() like the service does)
        today = timezone.now().date()
        metrics = await MarketMetricsHistory.objects.aget(symbol="QQQ", date=today)

        assert metrics.hv_30_day is not None, "HV should not be NULL in database"
        assert metrics.hv_30_day == Decimal(
            "22.0"
        ), "HV should persist as 22.0 (SDK percentage format)"
