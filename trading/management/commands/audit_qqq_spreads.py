"""
Audit QQQ spreads - compare TastyTrade (source of truth) to database.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from tastytrade import Account

from accounts.models import TradingAccount, User
from services.core.data_access import get_oauth_session_sync
from trading.models import Position


class Command(BaseCommand):
    help = "Audit QQQ spreads by comparing TastyTrade to database"

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 100)
        self.stdout.write("QQQ SPREAD AUDIT - TastyTrade vs Database")
        self.stdout.write("=" * 100 + "\n")

        # Get TastyTrade positions using SYNC methods
        user = User.objects.first()
        session = get_oauth_session_sync(user)

        tt_account_model = TradingAccount.objects.filter(user=user, is_primary=True).first()
        tt_account = Account.get(session, tt_account_model.account_number)

        tt_positions = tt_account.get_positions(session, underlying_symbols=["QQQ"])

        self.stdout.write("\n📊 TASTYTRADE POSITIONS (Source of Truth)")
        self.stdout.write("-" * 100)

        # Group by expiration
        by_exp = defaultdict(list)
        total_legs = 0

        for pos in tt_positions:
            occ = pos.symbol
            parts = occ.split()
            if len(parts) == 2:
                exp = parts[1][:6]
                by_exp[exp].append(
                    {
                        "symbol": occ,
                        "qty": pos.quantity,
                        "strike": int(parts[1][7:]) / 1000,
                        "type": parts[1][6],
                    }
                )
                total_legs += 1

        for exp in sorted(by_exp.keys()):
            self.stdout.write(f"\nExpiration: 20{exp[:2]}/{exp[2:4]}/{exp[4:6]}")
            legs = by_exp[exp]

            calls = [l for l in legs if l["type"] == "C"]
            puts = [l for l in legs if l["type"] == "P"]

            if calls:
                self.stdout.write(f"  CALLS ({len(calls)} legs):")
                for leg in sorted(calls, key=lambda x: x["strike"]):
                    self.stdout.write(f"    {leg['qty']:+3} x {leg['strike']} strike")

            if puts:
                self.stdout.write(f"  PUTS ({len(puts)} legs):")
                for leg in sorted(puts, key=lambda x: x["strike"]):
                    self.stdout.write(f"    {leg['qty']:+3} x {leg['strike']} strike")

        self.stdout.write(f"\nTOTAL OPTION LEGS IN TASTYTRADE: {total_legs}")

        # Get database positions
        self.stdout.write("\n\n📊 DATABASE POSITIONS")
        self.stdout.write("-" * 100)

        db_positions = Position.objects.filter(
            symbol="QQQ", lifecycle_state__in=["open_full", "open_partial"]
        ).order_by("id")

        total_db_spreads = 0
        total_db_open_spreads = 0

        for pos in db_positions:
            ptd = pos.profit_target_details or {}

            spreads_info = []
            for spread_type in ["call_spread", "put_spread_1", "put_spread_2"]:
                if spread_type in ptd:
                    status = ptd[spread_type].get("status", "active")
                    spreads_info.append(f"{spread_type}={status}")
                    total_db_spreads += 1
                    if status in ["active", "pending"]:
                        total_db_open_spreads += 1

            self.stdout.write(f"Position #{pos.id}: {', '.join(spreads_info)}")

        self.stdout.write(f"\nTOTAL SPREADS IN DATABASE: {total_db_spreads}")
        self.stdout.write(f"OPEN SPREADS IN DATABASE: {total_db_open_spreads}")

        # Summary
        self.stdout.write("\n\n📊 SUMMARY")
        self.stdout.write("=" * 100)
        self.stdout.write(f"TastyTrade option legs: {total_legs}")
        self.stdout.write(f"Database total spreads: {total_db_spreads}")
        self.stdout.write(f"Database open spreads:  {total_db_open_spreads}")
        self.stdout.write("\nNOTE: Senex Trident positions have overlapping legs.")
        self.stdout.write(
            "To properly count spreads, we need to trace each position's original structure."
        )
        self.stdout.write("=" * 100 + "\n")
