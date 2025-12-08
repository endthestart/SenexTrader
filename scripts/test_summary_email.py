#!/usr/bin/env python
"""
Test script to simulate daily summary email generation.
This helps identify issues with email sending in production.
"""
import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from services.notifications.email import EmailService
from trading.models import Trade

User = get_user_model()


def test_summary_email():
    """Test the daily summary email generation logic."""

    print("=" * 80)
    print("TESTING DAILY SUMMARY EMAIL GENERATION")
    print("=" * 80)

    # Check email service initialization
    print("\n1. Testing EmailService initialization...")
    try:
        email_service = EmailService()
        print("   PASS: EmailService initialized")
        print(f"   PASS: Default from email: {email_service.default_from_email}")
    except Exception as e:
        print(f"   FAIL: Failed to initialize EmailService: {e}")
        return

    # Check for users with summary preference
    print("\n2. Checking for users with 'summary' email preference...")
    users_wanting_summaries = User.objects.filter(email_preference="summary")
    print(f"   Found {users_wanting_summaries.count()} user(s) with summary preference:")

    if users_wanting_summaries.count() == 0:
        print("   ⚠ No users with 'summary' preference found!")
        print("   Creating test user...")
        test_user = User.objects.filter(email="test@example.com").first()
        if not test_user:
            test_user = User.objects.create_user(
                username="testuser",
                email="test@example.com",
                password="testpass123",
                first_name="Test",
                last_name="User",
                email_preference="summary",
            )
            print(f"   PASS: Created test user: {test_user.email}")
        else:
            test_user.email_preference = "summary"
            test_user.save()
            print(f"   PASS: Updated existing user: {test_user.email}")
        users_wanting_summaries = [test_user]
    else:
        for user in users_wanting_summaries:
            print(f"     - {user.email} (active: {user.is_active})")

    # Check for today's trades
    print("\n3. Checking for today's trade activity...")
    today = timezone.now().date()
    print(f"   Looking for trades on: {today}")

    for user in users_wanting_summaries:
        print(f"\n   User: {user.email}")

        # Get today's trades for this user
        todays_trades = Trade.objects.filter(user=user, submitted_at__date=today).select_related(
            "position"
        )

        print(f"     Total trades today: {todays_trades.count()}")

        # Categorize trades
        new_positions = todays_trades.filter(trade_type="open", status="filled")
        profit_targets = todays_trades.filter(trade_type="close", status="filled")
        cancelled = todays_trades.filter(status__in=["cancelled", "rejected", "expired"])

        print(f"     - New positions (open/filled): {new_positions.count()}")
        print(f"     - Profit targets (close/filled): {profit_targets.count()}")
        print(f"     - Cancelled/rejected/expired: {cancelled.count()}")

        # Check if user would be skipped (no activity)
        has_activity = new_positions.exists() or profit_targets.exists() or cancelled.exists()

        if not has_activity:
            print("     ⚠ User would be SKIPPED (no activity today)")
            print("     Note: In production, this user won't receive an email")

            # Show recent trades for context
            recent_trades = Trade.objects.filter(user=user).order_by("-submitted_at")[:5]
            if recent_trades.exists():
                print("     Recent trades (last 5):")
                for trade in recent_trades:
                    print(
                        f"       - {trade.submitted_at.date()}: {trade.trade_type} {trade.status}"
                    )
        else:
            print("     PASS: User HAS ACTIVITY - would receive email")

    # Test email building and sending
    print("\n4. Testing email building and sending...")

    for user in users_wanting_summaries:
        todays_trades = Trade.objects.filter(user=user, submitted_at__date=today).select_related(
            "position"
        )

        new_positions = todays_trades.filter(trade_type="open", status="filled")
        profit_targets = todays_trades.filter(trade_type="close", status="filled")
        cancelled = todays_trades.filter(status__in=["cancelled", "rejected", "expired"])

        # Skip users with no activity (same as task logic)
        if not (new_positions.exists() or profit_targets.exists() or cancelled.exists()):
            print(f"   Skipping {user.email} (no activity)")
            continue

        # Build email content (same logic as task)
        email_body = f"Daily Trading Summary - {today.strftime('%B %d, %Y')}\n\n"

        # New positions section
        if new_positions.exists():
            email_body += f"NEW POSITIONS OPENED ({new_positions.count()})\n"
            for trade in new_positions:
                credit = trade.credit_received or trade.executed_price or "N/A"
                email_body += (
                    f"  • {trade.position.symbol} {trade.position.strategy_type} "
                    f"@ ${credit} credit\n"
                )
            email_body += "\n"

        # Profit targets section
        if profit_targets.exists():
            email_body += f"💰 PROFIT TARGETS FILLED ({profit_targets.count()})\n"
            for trade in profit_targets:
                profit = trade.credit_received or trade.executed_price or "N/A"
                email_body += f"  • {trade.position.symbol} closed @ ${profit}\n"
            email_body += "\n"

        # Cancelled/rejected section
        if cancelled.exists():
            email_body += f"CANCELLED/REJECTED ({cancelled.count()})\n"
            for trade in cancelled:
                email_body += f"  • {trade.position.symbol} - {trade.status}\n"
            email_body += "\n"

        email_body += f"\nView full details in your dashboard at {settings.APP_BASE_URL}"

        print(f"\n   Email content for {user.email}:")
        print("   " + "-" * 70)
        print("   " + email_body.replace("\n", "\n   "))
        print("   " + "-" * 70)

        # Try to send email
        print(f"\n   Attempting to send email to {user.email}...")
        try:
            success = email_service.send_email(
                subject=f"Daily Trading Summary - {today.strftime('%b %d')}",
                body=email_body,
                recipient=user.email,
                fail_silently=False,  # Don't suppress errors for testing
            )
            if success:
                print("   PASS: Email sent successfully!")
            else:
                print("   FAIL: Email send returned False")
        except Exception as e:
            print(f"   FAIL: Email send failed with exception: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

    # Summary of findings
    print("\nKEY FINDINGS:")
    print(f"1. Users with 'summary' preference: {users_wanting_summaries.count()}")
    print(f"2. Email backend: {settings.EMAIL_BACKEND}")

    users_with_activity = sum(
        1
        for user in users_wanting_summaries
        if Trade.objects.filter(
            user=user,
            submitted_at__date=today,
            status__in=["filled", "cancelled", "rejected", "expired"],
        ).exists()
    )
    print(f"3. Users with activity today: {users_with_activity}")

    if users_with_activity == 0:
        print("\n⚠ ISSUE IDENTIFIED:")
        print("   No users have trade activity today, so NO emails would be sent.")
        print("   The task is working as designed - it only sends emails when there's activity.")
        print("\n   SOLUTION:")
        print("   - This is by design - summaries are only sent when there's trading activity")
        print("   - To test in production, create a trade on the current day")
        print("   - Or check if trades are being created but with wrong dates")


if __name__ == "__main__":
    test_summary_email()
