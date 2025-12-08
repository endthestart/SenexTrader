"""
Management command to test TastyTrade SDK net_positions parameter behavior.
"""

from django.contrib.auth import get_user_model

from tastytrade import Account

from services.core.data_access import get_oauth_session, get_primary_tastytrade_account
from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options

User = get_user_model()


class Command(AsyncCommand):
    help = "Test TastyTrade SDK net_positions=True vs False behavior"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)

    async def async_handle(self, *args, **options):
        """Async implementation."""
        self.stdout.write("=" * 80)
        self.stdout.write("Testing TastyTrade SDK net_positions parameter")
        self.stdout.write("=" * 80)

        # Get user from options
        user = await aget_user_from_options(options, require_user=True)
        self.stdout.write(f"\nUsing user: {user.username} (ID: {user.id})")

        # Get account
        account = await get_primary_tastytrade_account(user)
        if not account:
            self.stdout.write(self.style.ERROR("No primary TastyTrade account found"))
            return

        self.stdout.write(f"Account: {account.account_number}")

        # Get session
        session = await get_oauth_session(user)
        if not session:
            self.stdout.write(self.style.ERROR("Unable to get OAuth session"))
            return

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("Fetching positions with net_positions=False (individual legs)")
        self.stdout.write("=" * 80)

        tt_account = await Account.a_get(session, account.account_number)
        raw_positions = await tt_account.a_get_positions(session, net_positions=False)

        self.stdout.write(f"\nTotal positions returned: {len(raw_positions)}")

        if raw_positions:
            self.stdout.write("\nFirst 3 positions (individual legs):")
            for i, pos in enumerate(raw_positions[:3], 1):
                self.stdout.write(f"\n  Position {i}:")
                self.stdout.write(f"    symbol: {pos.symbol}")
                self.stdout.write(f"    underlying_symbol: {pos.underlying_symbol}")
                self.stdout.write(f"    instrument_type: {pos.instrument_type}")
                self.stdout.write(f"    quantity: {pos.quantity}")
                self.stdout.write(f"    quantity_direction: {pos.quantity_direction}")
                self.stdout.write(f"    average_open_price: {pos.average_open_price}")
                self.stdout.write(f"    close_price: {pos.close_price}")
                self.stdout.write(f"    multiplier: {pos.multiplier}")

        # Group by underlying to see structure
        by_underlying = {}
        for pos in raw_positions:
            underlying = pos.underlying_symbol
            if underlying not in by_underlying:
                by_underlying[underlying] = []
            by_underlying[underlying].append(pos)

        self.stdout.write("\n\nPositions grouped by underlying symbol:")
        for underlying, positions in by_underlying.items():
            self.stdout.write(f"  {underlying}: {len(positions)} legs")

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("Fetching positions with net_positions=True (SDK grouping)")
        self.stdout.write("=" * 80)

        net_positions = await tt_account.a_get_positions(session, net_positions=True)

        self.stdout.write(f"\nTotal positions returned: {len(net_positions)}")

        if net_positions:
            self.stdout.write("\nFirst 3 positions (netted/grouped):")
            for i, pos in enumerate(net_positions[:3], 1):
                self.stdout.write(f"\n  Position {i}:")
                self.stdout.write(f"    symbol: {pos.symbol}")
                self.stdout.write(f"    underlying_symbol: {pos.underlying_symbol}")
                self.stdout.write(f"    instrument_type: {pos.instrument_type}")
                self.stdout.write(f"    quantity: {pos.quantity}")
                self.stdout.write(f"    quantity_direction: {pos.quantity_direction}")
                self.stdout.write(f"    average_open_price: {pos.average_open_price}")
                self.stdout.write(f"    close_price: {pos.close_price}")
                self.stdout.write(f"    multiplier: {pos.multiplier}")
                # Check for P&L fields
                if hasattr(pos, "realized_day_gain"):
                    self.stdout.write(f"    realized_day_gain: {pos.realized_day_gain}")
                if hasattr(pos, "realized_today"):
                    self.stdout.write(f"    realized_today: {pos.realized_today}")

        # Compare counts
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("COMPARISON RESULTS")
        self.stdout.write("=" * 80)
        self.stdout.write(f"net_positions=False: {len(raw_positions)} positions")
        self.stdout.write(f"net_positions=True:  {len(net_positions)} positions")
        self.stdout.write(
            f"Difference:          {len(raw_positions) - len(net_positions)} positions"
        )

        if len(net_positions) < len(raw_positions):
            self.stdout.write(
                self.style.SUCCESS(
                    "\n[OK] SDK DOES group/net positions (fewer returned with net_positions=True)"
                )
            )
            self.stdout.write("  This means we can replace custom grouping logic.")
        elif len(net_positions) == len(raw_positions):
            self.stdout.write(self.style.WARNING("\n[FAIL] SDK DOES NOT group positions (same count)"))
            self.stdout.write("  We may still need custom grouping logic.")
        else:
            self.stdout.write(
                self.style.ERROR("\n? Unexpected: More positions with net_positions=True")
            )

        self.stdout.write("\n" + "=" * 80)
