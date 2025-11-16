#!/usr/bin/env python
"""
Test daily suggestions email generation.
Generates sample emails showing what users will receive.
"""

import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")
django.setup()

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from services.market_data.analysis import MarketConditionReport

User = get_user_model()


class MockSuggestion:
    """Mock suggestion object for testing."""

    def __init__(self, idx=1):
        self.id = 1000 + idx
        self.underlying_symbol = "SPY"
        self.expiration_date = date.today() + timedelta(days=35)
        self.short_put_strike = None
        self.long_put_strike = None
        self.short_call_strike = None
        self.long_call_strike = None
        self.put_spread_quantity = 1
        self.call_spread_quantity = 0
        self.total_credit = Decimal("0")
        self.total_mid_credit = Decimal("0")
        self.max_risk = Decimal("0")


def print_email_example(title, subject, body):
    """Print formatted email example."""
    print("=" * 80)
    print(f"{title}")
    print("=" * 80)
    print()
    print(f"SUBJECT: {subject}")
    print()
    print("EMAIL BODY:")
    print("-" * 80)
    print(body)
    print("-" * 80)
    print()


def main():
    user = User.objects.filter(is_active=True).first()
    if not user:
        print("No active users found. Create a user first.")
        return

    print("\n" + "=" * 80)
    print("DAILY SUGGESTIONS EMAIL - TEST OUTPUT")
    print("=" * 80)
    print()

    # Example 1: Multiple suggestions (success case)
    mock_report = MarketConditionReport(
        current_price=458.50,
        open_price=456.00,
        iv_rank=42.5,
        current_iv=0.15,
        macd_signal="bullish",
        bollinger_position="within_bands",
        is_range_bound=True,
        rsi=58.5,
        trend_strength="moderate",
        market_stress_level=35.0,
        support_level=455.00,
        resistance_level=462.00,
        data_available=True,
        is_data_stale=False,
        last_update=timezone.now(),
        no_trade_reasons=[],
    )

    # Create 2 mock suggestions (only credit spreads - Senex has dedicated system)
    bull_put = MockSuggestion(1)
    bull_put.short_put_strike = Decimal("445.00")
    bull_put.long_put_strike = Decimal("440.00")
    bull_put.total_mid_credit = Decimal("185.00")
    bull_put.max_risk = Decimal("500.00")

    bear_call = MockSuggestion(2)
    bear_call.short_call_strike = Decimal("472.00")
    bear_call.long_call_strike = Decimal("477.00")
    bear_call.total_mid_credit = Decimal("165.00")
    bear_call.max_risk = Decimal("500.00")

    suggestions_list = [("bull_put_spread", bull_put, {}), ("bear_call_spread", bear_call, {})]

    global_context = {
        "type": "suggestions",
        "market_report": mock_report,
        "all_scores": {"bull_put_spread": {"score": 75.5}, "bear_call_spread": {"score": 52.0}},
    }

    subject, body = _build_suggestion_email(
        user, suggestions_list, global_context, "http://localhost:8000"
    )

    print_email_example("EXAMPLE 1: Two Strategy Recommendations", subject, body)

    # Example 2: No trades (low scores)
    global_context_low = {
        "type": "low_scores",
        "market_report": mock_report,
        "all_scores": {"bull_put_spread": {"score": 28.0}, "bear_call_spread": {"score": 25.0}},
        "best_score": 28.0,
    }

    subject2, body2 = _build_suggestion_email(user, [], global_context_low, "http://localhost:8000")

    print_email_example("EXAMPLE 2: No Trades (Low Scores)", subject2, body2)

    # Example 3: User at 100% risk utilization (Epic 24 Task 006 fix)
    # This scenario demonstrates that suggestions are generated regardless of risk budget
    print("=" * 80)
    print("EXAMPLE 3: User at 100% Risk Utilization (Task 006 Fix)")
    print("=" * 80)
    print()
    print("NOTE: Before Task 006 fix, users at 100% risk received 'No Suitable Trade' emails.")
    print("After Task 006 fix, suggestion_mode=True bypasses risk checks, so users receive")
    print("educational suggestions with full market analysis even at max risk utilization.")
    print()
    print("The email format is identical to Example 1, demonstrating that users now")
    print("receive value-added daily emails regardless of their risk budget status.")
    print()
    print("To verify the fix works:")
    print(
        "  1. Run integration test: pytest tests/test_strategy_selector.py::TestStrategySelector::test_suggestion_mode_bypasses_risk_at_100_percent"
    )
    print(
        "  2. Run integration test: pytest tests/test_strategy_selector.py::TestStrategySelector::test_multi_strategy_suggestions_at_max_risk"
    )
    print()
    print("The key difference is INTERNAL only:")
    print("  - suggestion_mode=False (execution): Risk check blocks at 100% risk")
    print("  - suggestion_mode=True (suggestions): Risk check bypassed for educational value")
    print()

    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
