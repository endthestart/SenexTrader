"""
Tests for Earnings Calendar Service - Epic 22 Task 016

Verifies:
- Upcoming earnings detection
- Days until earnings calculation
- Danger window detection (7 days)
- Target window detection (1-3 days)
- Strategy-specific recommendations
"""

from datetime import date, timedelta

import pytest

from services.market_data.earnings import EarningsCalendar, EarningsInfo


@pytest.mark.asyncio
async def test_earnings_within_danger_window():
    """Test earnings within 7-day danger window"""
    calendar = EarningsCalendar()

    today = date.today()
    earnings_date = today + timedelta(days=5)

    metrics = {"earnings": {"expected_report_date": earnings_date.isoformat()}}

    info = await calendar.get_earnings_info("AAPL", metrics)

    assert info.has_upcoming_earnings is True
    assert info.days_until_earnings == 5
    assert info.is_within_danger_window is True
    assert info.recommendation == "avoid"


@pytest.mark.asyncio
async def test_earnings_target_window():
    """Test earnings in 1-3 day target window for vol plays"""
    calendar = EarningsCalendar()

    today = date.today()
    earnings_date = today + timedelta(days=2)

    metrics = {"earnings": {"expected_report_date": earnings_date.isoformat()}}

    info = await calendar.get_earnings_info("AAPL", metrics)

    assert info.days_until_earnings == 2
    assert info.is_within_danger_window is True  # Within 7 days
    assert info.recommendation == "target"


@pytest.mark.asyncio
async def test_no_upcoming_earnings():
    """Test symbol with no upcoming earnings"""
    calendar = EarningsCalendar()

    metrics = {}

    info = await calendar.get_earnings_info("AAPL", metrics)

    assert info.has_upcoming_earnings is False
    assert info.days_until_earnings is None
    assert info.is_within_danger_window is False
    assert info.recommendation == "neutral"


@pytest.mark.asyncio
async def test_earnings_far_away():
    """Test earnings more than 7 days away (neutral)"""
    calendar = EarningsCalendar()

    today = date.today()
    earnings_date = today + timedelta(days=15)

    metrics = {"earnings": {"expected_report_date": earnings_date.isoformat()}}

    info = await calendar.get_earnings_info("AAPL", metrics)

    assert info.has_upcoming_earnings is True
    assert info.days_until_earnings == 15
    assert info.is_within_danger_window is False
    assert info.recommendation == "neutral"


@pytest.mark.asyncio
async def test_should_avoid_earnings_iron_condor():
    """Iron condor should avoid earnings"""
    calendar = EarningsCalendar()

    earnings_info = EarningsInfo(
        symbol="AAPL",
        has_upcoming_earnings=True,
        earnings_date=date.today() + timedelta(days=5),
        days_until_earnings=5,
        is_within_danger_window=True,
        recommendation="avoid",
    )

    should_avoid, reason = calendar.should_avoid_earnings(earnings_info, "short_iron_condor")

    assert should_avoid is True
    assert "AVOID" in reason


@pytest.mark.asyncio
async def test_should_target_earnings_straddle():
    """Long straddle should target earnings"""
    calendar = EarningsCalendar()

    earnings_info = EarningsInfo(
        symbol="AAPL",
        has_upcoming_earnings=True,
        earnings_date=date.today() + timedelta(days=2),
        days_until_earnings=2,
        is_within_danger_window=True,
        recommendation="target",
    )

    should_avoid, reason = calendar.should_avoid_earnings(earnings_info, "long_straddle")

    assert should_avoid is False
    assert "Perfect timing" in reason


@pytest.mark.asyncio
async def test_should_avoid_earnings_senex_trident():
    """Senex Trident should avoid earnings"""
    calendar = EarningsCalendar()

    earnings_info = EarningsInfo(
        symbol="SPY",
        has_upcoming_earnings=True,
        earnings_date=date.today() + timedelta(days=3),
        days_until_earnings=3,
        is_within_danger_window=True,
        recommendation="target",  # 1-3 days = target, but Senex avoids
    )

    should_avoid, reason = calendar.should_avoid_earnings(earnings_info, "senex_trident")

    assert should_avoid is True
    assert "AVOID" in reason


@pytest.mark.asyncio
async def test_straddle_rejects_far_earnings():
    """Long straddle rejects earnings too far away"""
    calendar = EarningsCalendar()

    earnings_info = EarningsInfo(
        symbol="AAPL",
        has_upcoming_earnings=True,
        earnings_date=date.today() + timedelta(days=10),
        days_until_earnings=10,
        is_within_danger_window=False,
        recommendation="neutral",
    )

    should_avoid, reason = calendar.should_avoid_earnings(earnings_info, "long_straddle")

    assert should_avoid is True
    assert "Too far from earnings" in reason


@pytest.mark.asyncio
async def test_no_earnings_no_impact():
    """No earnings means no avoidance"""
    calendar = EarningsCalendar()

    earnings_info = EarningsInfo(
        symbol="SPY",
        has_upcoming_earnings=False,
        earnings_date=None,
        days_until_earnings=None,
        is_within_danger_window=False,
        recommendation="neutral",
    )

    should_avoid, reason = calendar.should_avoid_earnings(earnings_info, "short_iron_condor")

    assert should_avoid is False
    assert "No upcoming earnings" in reason
