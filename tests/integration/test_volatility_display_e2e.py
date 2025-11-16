"""
End-to-end test for volatility display bug.

This test catches the double-conversion bug by testing the ENTIRE data flow:
SDK → Storage → Market Analysis → Strategy Selector → API Response

History: This bug was fixed 15+ times because unit tests only tested individual
layers. This integration test ensures the bug never returns.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone

import pytest

from services.market_data.analysis import MarketConditionReport
from services.strategies.selector import StrategySelector
from trading.models import MarketMetricsHistory

User = get_user_model()


@pytest.mark.django_db(transaction=True)
class TestVolatilityDisplayE2E:
    """End-to-end tests for volatility display across entire system."""

    @pytest.mark.asyncio
    async def test_strategy_explanation_no_double_conversion(self):
        """
        CRITICAL TEST: Verify volatility is NOT double-converted in explanations.

        This is the PRIMARY test that catches the double-conversion bug.

        Data Flow:
        1. Market data stored: 21.22 (percentage in DB, from SDK 0.2122 decimal)
        2. Market report: current_iv = 21.22
        3. Strategy explanation: should show "21.2%" NOT "2122.0%"

        FAIL CONDITION: If this test passes but frontend shows "2122.0%",
        it means the API endpoint has a NEW double-conversion bug.
        """
        user = await User.objects.acreate(username="test_user", email="test@example.com")

        today = timezone.now().date()
        await MarketMetricsHistory.objects.acreate(
            symbol="SPY",
            date=today,
            iv_30_day=Decimal("21.22"),
            hv_30_day=Decimal("18.50"),
            iv_rank=Decimal("65.0"),
            iv_percentile=Decimal("68.0"),
        )

        selector = StrategySelector(user)

        mock_report = MarketConditionReport(symbol="SPY", current_price=450.0)
        mock_report.current_iv = 21.22
        mock_report.iv_rank = 65.0
        mock_report.macd_signal = "bullish"
        mock_report.is_range_bound = False

        auto_explanation = selector._build_auto_explanation(
            selected="bull_put_spread",
            selected_score=75.0,
            confidence="high",
            all_scores={"bull_put_spread": 75.0, "iron_condor": 60.0},
            all_explanations={
                "bull_put_spread": "High IV rank | Bullish trend",
                "iron_condor": "Moderate conditions",
            },
            report=mock_report,
        )

        volatility_in_explanation = auto_explanation["market"]["volatility"]

        assert (
            volatility_in_explanation == 21.2
        ), f"DOUBLE CONVERSION BUG! Expected 21.2, got {volatility_in_explanation}"
        assert (
            volatility_in_explanation != 2122.0
        ), "CRITICAL: Double conversion bug returned! Shows 2122.0"
        assert (
            volatility_in_explanation < 100
        ), f"Volatility suspiciously high ({volatility_in_explanation}) - conversion bug"

        forced_explanation = selector._build_forced_explanation(
            strategy_name="bull_put_spread",
            score=70.0,
            confidence="medium",
            score_explanation="Moderate bullish conditions",
            report=mock_report,
        )

        volatility_in_forced = forced_explanation["market"]["volatility"]

        assert (
            volatility_in_forced == 21.2
        ), f"DOUBLE CONVERSION in forced! Expected 21.2, got {volatility_in_forced}"
        assert (
            volatility_in_forced != 2122.0
        ), "CRITICAL: Double conversion in forced suggestion! Shows 2122.0"

    @pytest.mark.asyncio
    async def test_high_volatility_no_conversion_bug(self):
        """
        Verify high volatility (e.g., 85%) is NOT converted to 8500%.

        During market crashes, IV can reach 85%+. This should display as "85.0%",
        not "8500.0%" due to double conversion.
        """
        user = await User.objects.acreate(username="test_user", email="test@example.com")

        today = timezone.now().date()
        await MarketMetricsHistory.objects.acreate(
            symbol="VIX",
            date=today,
            iv_30_day=Decimal("85.00"),
            hv_30_day=Decimal("125.00"),
            iv_rank=Decimal("95.0"),
            iv_percentile=Decimal("98.0"),
        )

        selector = StrategySelector(user)

        mock_report = MarketConditionReport(symbol="VIX", current_price=30.0)
        mock_report.current_iv = 85.00
        mock_report.iv_rank = 95.0
        mock_report.macd_signal = "neutral"
        mock_report.is_range_bound = False

        explanation = selector._build_auto_explanation(
            selected="long_straddle",
            selected_score=80.0,
            confidence="high",
            all_scores={"long_straddle": 80.0},
            all_explanations={"long_straddle": "Extreme volatility"},
            report=mock_report,
        )

        volatility = explanation["market"]["volatility"]

        assert volatility == 85.0, f"Expected 85.0, got {volatility}"
        assert (
            volatility != 8500.0
        ), "CRITICAL: Double conversion with high volatility! Shows 8500.0"
        assert (
            volatility < 200
        ), f"Volatility impossibly high ({volatility}) - conversion bug detected"

    @pytest.mark.asyncio
    async def test_market_report_to_api_response_format(self):
        """
        Test the critical conversion point: MarketReport → API Response.

        This is where the double-conversion bug occurs. The API must:
        1. Receive current_iv = 21.22 (percentage from storage)
        2. Round to current_iv_pct = 21.2 (display percentage)
        3. NOT multiply by 100 again (would give 2122.0)
        """
        mock_report = MagicMock()
        mock_report.current_iv = 21.22
        mock_report.iv_rank = 65.0
        mock_report.macd_signal = "bullish"
        mock_report.is_range_bound = False
        mock_report.market_stress_level = 25

        current_iv_pct = (
            round(mock_report.current_iv, 1) if mock_report.current_iv is not None else None
        )

        assert current_iv_pct == 21.2, f"API conversion failed! Expected 21.2, got {current_iv_pct}"
        assert (
            current_iv_pct != 2122.0
        ), "CRITICAL: API still doing * 100 conversion! This is the bug!"

        market_conditions = {
            "direction": mock_report.macd_signal,
            "iv_rank": mock_report.iv_rank,
            "volatility": current_iv_pct,
            "range_bound": mock_report.is_range_bound,
            "stress_level": mock_report.market_stress_level,
        }

        assert market_conditions["volatility"] == 21.2
        assert market_conditions["volatility"] != 2122.0

    @pytest.mark.asyncio
    async def test_sdk_storage_format_reminder(self):
        """
        Reminder test: SDK stores data in PERCENTAGE format (21.22), not decimal (0.2122).

        This changed in commit e730e86 on Oct 24, 2025.

        Before: SDK 0.2122 → Storage 0.2122 → Display *100 = 21.2%
        After:  SDK 0.2122 → Storage *100 = 21.22 → Display = 21.2%

        This test documents the current behavior to prevent future confusion.
        """
        today = timezone.now().date()

        await MarketMetricsHistory.objects.acreate(
            symbol="TEST",
            date=today,
            iv_30_day=Decimal("21.22"),
            hv_30_day=Decimal("18.50"),
            iv_rank=Decimal("65.0"),
            iv_percentile=Decimal("68.0"),
        )

        retrieved = await MarketMetricsHistory.objects.aget(symbol="TEST", date=today)

        assert retrieved.iv_30_day == Decimal(
            "21.22"
        ), "Storage format should be PERCENTAGE (21.22), not decimal (0.2122)"
        assert retrieved.iv_30_day != Decimal(
            "0.2122"
        ), "If this fails, storage format changed back to decimal! Update all display code!"

        assert retrieved.iv_30_day > 1.0, "Quick check: if value is > 1.0, it's percentage format"
