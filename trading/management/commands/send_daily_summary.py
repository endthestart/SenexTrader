"""
Management command to send daily trading summary emails.
Usage: python manage.py send_daily_summary [--date YYYY-MM-DD]
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from services.notifications.email import EmailService
from trading.models import Trade

User = get_user_model()


class Command(BaseCommand):
    help = "Send daily trading summary emails for a specific date"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date to send summary for (YYYY-MM-DD). Defaults to yesterday.",
        )

    def handle(self, *args, **options):
        # Parse target date
        if options["date"]:
            try:
                target_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(
                    self.style.ERROR(f"Invalid date format: {options['date']}. Use YYYY-MM-DD")
                )
                return
        else:
            # Default to yesterday
            target_date = (timezone.now() - timedelta(days=1)).date()

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS(f"SENDING DAILY SUMMARY EMAIL FOR: {target_date}"))
        self.stdout.write("=" * 80)

        email_service = EmailService()

        # Get users who want daily summaries
        users_wanting_summaries = User.objects.filter(email_preference="summary")

        self.stdout.write(f"\nUsers with summary preference: {users_wanting_summaries.count()}")

        emails_sent = 0
        users_with_activity = 0

        for user in users_wanting_summaries:
            self.stdout.write(f"\n{self.style.WARNING(f'Processing user: {user.email}')}")

            # Get trades for target date
            todays_trades = Trade.objects.filter(
                user=user, submitted_at__date=target_date
            ).select_related("position")

            # Categorize trades
            new_positions = todays_trades.filter(trade_type="open", status="filled")
            profit_targets = todays_trades.filter(trade_type="close", status="filled")
            cancelled = todays_trades.filter(status__in=["cancelled", "rejected", "expired"])

            self.stdout.write(f"  Total trades: {todays_trades.count()}")
            self.stdout.write(f"  New positions: {new_positions.count()}")
            self.stdout.write(f"  Profit targets: {profit_targets.count()}")
            self.stdout.write(f"  Cancelled: {cancelled.count()}")

            # Skip users with no activity
            if not (new_positions.exists() or profit_targets.exists() or cancelled.exists()):
                self.stdout.write("  Skipping (no activity)")
                continue

            users_with_activity += 1

            # Build email content with enhanced details
            email_body = f"Daily Trading Summary - {target_date.strftime('%B %d, %Y')}\n\n"

            # New positions section with full details
            if new_positions.exists():
                email_body += f"NEW POSITIONS OPENED ({new_positions.count()})\n\n"
                for trade in new_positions:
                    pos = trade.position
                    credit = f"${trade.fill_price:.2f}" if trade.fill_price else "N/A"

                    email_body += f"  {pos.symbol} {pos.strategy_type.upper().replace('_', ' ')}\n"
                    email_body += f"  Credit Received: {credit}\n"
                    email_body += f"  Expiration: {pos.expiration_date.strftime('%b %d, %Y')}\n"

                    # Show legs
                    metadata = pos.strategy_metadata or {}
                    strikes = metadata.get("strikes", {})
                    if strikes:
                        email_body += "  Strikes:\n"
                        if "short_put" in strikes:
                            email_body += f"    Put Spread: ${strikes.get('long_put')}/${strikes.get('short_put')}\n"
                        if "short_call" in strikes:
                            email_body += f"    Call Spread: ${strikes.get('short_call')}/${strikes.get('long_call')}\n"

                    # Show profit targets
                    profit_target_trades = Trade.objects.filter(
                        position=pos, trade_type="close", status__in=["pending", "open"]
                    )
                    if profit_target_trades.exists():
                        email_body += "  Profit Targets Set:\n"
                        for pt in profit_target_trades:
                            email_body += f"    • {pt.lifecycle_event or 'Profit target'}\n"

                    email_body += "\n"

            # Profit targets section with details
            if profit_targets.exists():
                email_body += f"💰 PROFIT TARGETS FILLED ({profit_targets.count()})\n\n"
                for trade in profit_targets:
                    pos = trade.position
                    profit = f"${trade.fill_price:.2f}" if trade.fill_price else "N/A"

                    email_body += f"  {pos.symbol} {pos.strategy_type.upper().replace('_', ' ')}\n"
                    email_body += f"  Target Type: {trade.lifecycle_event or 'Profit target'}\n"
                    email_body += f"  Close Price: {profit}\n"

                    # Show P&L if available
                    if pos.current_value and pos.max_risk:
                        pnl = pos.current_value
                        pnl_pct = (pnl / abs(pos.max_risk)) * 100 if pos.max_risk else 0
                        email_body += f"  P&L: ${pnl:.2f} ({pnl_pct:.1f}%)\n"

                    email_body += "\n"

            # Cancelled/rejected section
            if cancelled.exists():
                email_body += f"CANCELLED/REJECTED ({cancelled.count()})\n"
                for trade in cancelled:
                    email_body += f"  • {trade.position.symbol} - {trade.status}\n"
                email_body += "\n"

            email_body += f"\nView full details in your dashboard at {settings.APP_BASE_URL}"

            # Print email content
            self.stdout.write("\n  Email content:")
            self.stdout.write("  " + "-" * 70)
            for line in email_body.split("\n"):
                self.stdout.write(f"  {line}")
            self.stdout.write("  " + "-" * 70)

            # Send email
            self.stdout.write(f"\n  Sending email to {user.email}...")
            try:
                success = email_service.send_email(
                    subject=f"Daily Trading Summary - {target_date.strftime('%b %d')}",
                    body=email_body,
                    recipient=user.email,
                    fail_silently=False,
                )
                if success:
                    emails_sent += 1
                    self.stdout.write(self.style.SUCCESS("  Email sent successfully!"))
                else:
                    self.stderr.write(self.style.ERROR("  Email send returned False"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Email send failed: {e}"))
                import traceback

                traceback.print_exc()

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY:"))
        self.stdout.write(f"  Users with activity: {users_with_activity}")
        self.stdout.write(f"  Emails sent: {emails_sent}")
        self.stdout.write("=" * 80)

        if emails_sent > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSuccessfully sent {emails_sent} email(s) for {target_date}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"\nNo emails sent (no users had activity on {target_date})")
            )
