"""
Tests for Dividend Schedule Service - Epic 22 Task 017

Verifies:
- Upcoming dividend detection
- Days until ex-div calculation
- Risk window detection (5 days)
- Assignment risk assessment
- Strategy-specific recommendations
"""

from datetime import date, timedelta

import pytest

from services.market_data.dividends import DividendInfo, DividendSchedule


@pytest.mark.asyncio
async def test_dividend_within_risk_window():
    """Test dividend within 5-day risk window"""
    schedule = DividendSchedule()

    today = date.today()
    ex_div_date = today + timedelta(days=3)

    metrics = {"dividend_ex_date": ex_div_date.isoformat()}

    info = await schedule.get_dividend_info("AAPL", metrics)

    assert info.has_upcoming_dividend is True
    assert info.days_until_ex_div == 3
    assert info.is_within_risk_window is True
    assert info.assignment_risk_level == "moderate"


@pytest.mark.asyncio
async def test_dividend_high_risk_window():
    """Test dividend in 0-2 day high risk window"""
    schedule = DividendSchedule()

    today = date.today()
    ex_div_date = today + timedelta(days=1)

    metrics = {"dividend_ex_date": ex_div_date.isoformat()}

    info = await schedule.get_dividend_info("AAPL", metrics)

    assert info.days_until_ex_div == 1
    assert info.is_within_risk_window is True
    assert info.assignment_risk_level == "high"


@pytest.mark.asyncio
async def test_no_upcoming_dividend():
    """Test symbol with no upcoming dividend"""
    schedule = DividendSchedule()

    metrics = {}

    info = await schedule.get_dividend_info("AAPL", metrics)

    assert info.has_upcoming_dividend is False
    assert info.days_until_ex_div is None
    assert info.is_within_risk_window is False
    assert info.assignment_risk_level == "low"


@pytest.mark.asyncio
async def test_dividend_far_away():
    """Test dividend more than 5 days away (low risk)"""
    schedule = DividendSchedule()

    today = date.today()
    next_div_date = today + timedelta(days=10)

    metrics = {"dividend_next_date": next_div_date.isoformat()}

    info = await schedule.get_dividend_info("AAPL", metrics)

    assert info.has_upcoming_dividend is True
    assert info.days_until_next_div == 10
    assert info.is_within_risk_window is False
    assert info.assignment_risk_level == "low"


@pytest.mark.asyncio
async def test_should_avoid_dividend_covered_call_high_risk():
    """Covered call should avoid high risk dividend"""
    schedule = DividendSchedule()

    dividend_info = DividendInfo(
        symbol="AAPL",
        has_upcoming_dividend=True,
        ex_dividend_date=date.today() + timedelta(days=1),
        dividend_next_date=None,
        days_until_ex_div=1,
        days_until_next_div=None,
        is_within_risk_window=True,
        assignment_risk_level="high",
    )

    should_avoid, reason = schedule.should_avoid_dividend(dividend_info, "covered_call")

    assert should_avoid is True
    assert "HIGH assignment risk" in reason


@pytest.mark.asyncio
async def test_should_avoid_dividend_bear_call_moderate_risk():
    """Bear call spread should avoid moderate risk dividend"""
    schedule = DividendSchedule()

    dividend_info = DividendInfo(
        symbol="AAPL",
        has_upcoming_dividend=True,
        ex_dividend_date=date.today() + timedelta(days=4),
        dividend_next_date=None,
        days_until_ex_div=4,
        days_until_next_div=None,
        is_within_risk_window=True,
        assignment_risk_level="moderate",
    )

    should_avoid, reason = schedule.should_avoid_dividend(dividend_info, "short_call_vertical")

    assert should_avoid is True
    assert "MODERATE assignment risk" in reason


@pytest.mark.asyncio
async def test_should_avoid_dividend_cash_secured_put():
    """Cash-secured put has moderate risk from dividends"""
    schedule = DividendSchedule()

    dividend_info = DividendInfo(
        symbol="AAPL",
        has_upcoming_dividend=True,
        ex_dividend_date=date.today() + timedelta(days=1),
        dividend_next_date=None,
        days_until_ex_div=1,
        days_until_next_div=None,
        is_within_risk_window=True,
        assignment_risk_level="high",
    )

    should_avoid, reason = schedule.should_avoid_dividend(dividend_info, "cash_secured_put")

    assert should_avoid is True
    assert "increased assignment risk" in reason


@pytest.mark.asyncio
async def test_no_dividend_no_impact():
    """No dividend means no avoidance"""
    schedule = DividendSchedule()

    dividend_info = DividendInfo(
        symbol="AAPL",
        has_upcoming_dividend=False,
        ex_dividend_date=None,
        dividend_next_date=None,
        days_until_ex_div=None,
        days_until_next_div=None,
        is_within_risk_window=False,
        assignment_risk_level="low",
    )

    should_avoid, reason = schedule.should_avoid_dividend(dividend_info, "covered_call")

    assert should_avoid is False
    assert "No upcoming dividend" in reason


@pytest.mark.asyncio
async def test_dividend_low_risk_acceptable():
    """Dividend far away is acceptable"""
    schedule = DividendSchedule()

    dividend_info = DividendInfo(
        symbol="AAPL",
        has_upcoming_dividend=True,
        ex_dividend_date=date.today() + timedelta(days=10),
        dividend_next_date=None,
        days_until_ex_div=10,
        days_until_next_div=None,
        is_within_risk_window=False,
        assignment_risk_level="low",
    )

    should_avoid, reason = schedule.should_avoid_dividend(dividend_info, "covered_call")

    assert should_avoid is False
    assert "acceptable" in reason
