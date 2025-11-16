#!/usr/bin/env python
"""
Test Celery tasks locally to validate code paths and identify issues.

This script tests:
1. automated_daily_trade_cycle
2. generate_and_email_daily_suggestions
3. generate_trading_summary

Run with: python scripts/test_celery_tasks.py
"""
import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import TradingAccount
from services.core.logging import get_logger
from trading.models import Trade, Watchlist

logger = get_logger(__name__)
User = get_user_model()


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def check_prerequisites():
    """Check if basic prerequisites are met."""
    print_section("PREREQUISITES CHECK")

    issues = []

    # Check for users
    user_count = User.objects.filter(is_active=True).count()
    print(f"✓ Active users: {user_count}")
    if user_count == 0:
        issues.append("No active users found - create a user first")

    # Check for trading accounts
    account_count = TradingAccount.objects.filter(is_active=True).count()
    print(f"✓ Active trading accounts: {account_count}")

    # Check for Redis connection
    try:
        from django.conf import settings

        import redis

        redis_url = getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/1")
        r = redis.from_url(redis_url)
        r.ping()
        print(f"✓ Redis connection: OK ({redis_url})")
    except Exception as e:
        issues.append(f"Redis connection failed: {e}")
        print(f"✗ Redis connection: FAILED ({e})")

    # Check email backend
    from django.conf import settings

    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    print(f"✓ Email backend: {email_backend}")

    # Check TastyTrade settings
    tt_client_id = getattr(settings, "TASTYTRADE_CLIENT_ID", None)
    tt_dry_run = getattr(settings, "TASTYTRADE_DRY_RUN", True)
    print(f"✓ TastyTrade client ID: {'Set' if tt_client_id else 'NOT SET'}")
    print(f"✓ TastyTrade dry-run mode: {tt_dry_run}")

    if issues:
        print("\n⚠ ISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
        return False

    print("\n✓ All prerequisites met!")
    return True


def test_automated_daily_trade_cycle():
    """Test the automated daily trade cycle task."""
    print_section("TEST 1: AUTOMATED DAILY TRADE CYCLE")

    import asyncio

    from trading.tasks import _async_automated_daily_trade_cycle

    print("Checking eligible accounts...")
    eligible_accounts = TradingAccount.objects.filter(
        is_active=True, is_automated_trading_enabled=True, is_token_valid=True
    ).select_related("user")

    print(f"Found {eligible_accounts.count()} eligible accounts:")
    for account in eligible_accounts:
        print(f"  - {account.user.email} (account: {account.account_number})")

    if eligible_accounts.count() == 0:
        print("\n⚠ No eligible accounts found.")
        print("  Accounts need:")
        print("    - is_active=True")
        print("    - is_automated_trading_enabled=True")
        print("    - is_token_valid=True")
        print("\n  Skipping task execution (would skip in production too)")
        return

    print("\nAttempting to run task...")
    print("Note: This will attempt to connect to TastyTrade API")
    print("      (will use dry-run mode if configured)\n")

    try:
        # Run the async version directly
        result = asyncio.run(_async_automated_daily_trade_cycle())
        print("\n✓ Task completed successfully!")
        print(f"  Result: {result}")
    except Exception as e:
        print(f"\n✗ Task failed: {e}")
        import traceback

        traceback.print_exc()
        print("\nCommon issues:")
        print("  - Missing TastyTrade OAuth tokens")
        print("  - Invalid TastyTrade credentials")
        print("  - Network connectivity issues")
        print("  - Market closed (task checks market hours)")


def test_daily_suggestions():
    """Test the daily suggestions email task."""
    print_section("TEST 2: DAILY SUGGESTIONS EMAIL")

    import asyncio

    from trading.tasks import (
        _async_generate_and_email_daily_suggestions,
    )

    print("Checking eligible users...")
    eligible_users = User.objects.filter(is_active=True, email_daily_trade_suggestion=True).exclude(
        email_preference="none"
    )

    print(f"Found {eligible_users.count()} eligible users:")
    for user in eligible_users:
        watchlist_count = Watchlist.objects.filter(user=user).count()
        print(f"  - {user.email} (watchlist: {watchlist_count} symbols)")

    if eligible_users.count() == 0:
        print("\n⚠ No eligible users found.")
        print("  Users need:")
        print("    - is_active=True")
        print("    - email_daily_trade_suggestion=True")
        print("    - email_preference != 'none'")
        print("\n  Skipping task execution (would skip in production too)")
        return

    print("\nAttempting to run task...")
    print("Note: This will:")
    print("  - Start streaming for watchlist symbols")
    print("  - Generate strategy suggestions")
    print("  - Send emails (using configured email backend)\n")

    try:
        result = asyncio.run(_async_generate_and_email_daily_suggestions())
        print("\n✓ Task completed successfully!")
        print(f"  Result: {result}")
    except Exception as e:
        print(f"\n✗ Task failed: {e}")
        import traceback

        traceback.print_exc()
        print("\nCommon issues:")
        print("  - Redis not running (needed for streaming)")
        print("  - Missing TastyTrade credentials")
        print("  - Email backend misconfigured")
        print("  - Watchlist symbols invalid")


def test_daily_summary():
    """Test the daily trading summary task."""
    print_section("TEST 3: DAILY TRADING SUMMARY")

    from trading.tasks import generate_trading_summary

    print("Checking eligible users...")
    users_wanting_summaries = User.objects.filter(email_preference="summary")

    print(f"Found {users_wanting_summaries.count()} users with 'summary' preference:")
    for user in users_wanting_summaries:
        today = timezone.now().date()
        today_trades = Trade.objects.filter(user=user, submitted_at__date=today)
        print(f"  - {user.email} (trades today: {today_trades.count()})")

    if users_wanting_summaries.count() == 0:
        print("\n⚠ No users with 'summary' preference found.")
        print("  Users need: email_preference='summary'")
        print("\n  Skipping task execution (would skip in production too)")
        return

    print("\nChecking for today's activity...")
    today = timezone.now().date()
    users_with_activity = 0

    for user in users_wanting_summaries:
        todays_trades = Trade.objects.filter(user=user, submitted_at__date=today).select_related(
            "position"
        )

        new_positions = todays_trades.filter(trade_type="open", status="filled")
        profit_targets = todays_trades.filter(trade_type="close", status="filled")
        cancelled = todays_trades.filter(status__in=["cancelled", "rejected", "expired"])

        has_activity = new_positions.exists() or profit_targets.exists() or cancelled.exists()
        if has_activity:
            users_with_activity += 1
            print(f"  ✓ {user.email} has activity")
        else:
            print(f"  - {user.email} has no activity (would be skipped)")

    if users_with_activity == 0:
        print("\n⚠ No users have activity today.")
        print("  The task only sends emails when there's trading activity.")
        print("  This is expected behavior - no emails will be sent.")
        return

    print(f"\n{users_with_activity} user(s) would receive emails.")
    print("\nAttempting to run task...")
    print("Note: This will send emails using configured email backend\n")

    try:
        result = generate_trading_summary()
        print("\n✓ Task completed successfully!")
        print(f"  Result: {result}")
    except Exception as e:
        print(f"\n✗ Task failed: {e}")
        import traceback

        traceback.print_exc()
        print("\nCommon issues:")
        print("  - Email backend misconfigured")
        print("  - Missing APP_BASE_URL setting")


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("  CELERY TASKS LOCAL VALIDATION")
    print("=" * 80)
    print("\nThis script validates Celery task code paths without requiring")
    print("a full Celery worker setup. It tests the actual task functions.")
    print("\nNote: Some tasks may fail if prerequisites are missing.")
    print("      This is expected and helps identify configuration issues.\n")

    # Check prerequisites first
    if not check_prerequisites():
        print("\n⚠ Some prerequisites are missing. Tests may fail.")
        response = input("\nContinue anyway? (y/n): ")
        if response.lower() != "y":
            print("Exiting.")
            return

    # Run tests
    test_automated_daily_trade_cycle()
    test_daily_suggestions()
    test_daily_summary()

    print_section("VALIDATION COMPLETE")
    print("Review the output above for any issues.")
    print("\nNext steps:")
    print("  1. Fix any identified configuration issues")
    print("  2. Ensure Redis is running (for streaming tasks)")
    print("  3. Configure TastyTrade credentials if needed")
    print("  4. Set up email backend for email tasks")
    print("  5. Create test users/accounts with appropriate settings")


if __name__ == "__main__":
    main()
