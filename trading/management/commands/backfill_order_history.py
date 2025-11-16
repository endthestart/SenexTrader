"""
Management command to backfill order history cache and correct position data.

This command:
1. Syncs order history from TastyTrade for all open positions
2. Reconstructs position data from cached orders
3. Corrects number_of_spreads and quantity fields where needed
4. Reports on discrepancies found and corrections made
"""

from django.contrib.auth import get_user_model

from accounts.models import TradingAccount
from services.core.logging import get_logger
from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from services.orders.history import OrderHistoryService
from trading.models import Position

User = get_user_model()
logger = get_logger(__name__)


class Command(AsyncCommand):
    help = "Backfill order history cache and correct position data from orders"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=False)
        parser.add_argument(
            "--position-id",
            type=int,
            help="Backfill for specific position ID only",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=60,
            help="Number of days back to fetch order history (default: 60)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Dry run mode - report discrepancies but don't save corrections",
        )
        parser.add_argument(
            "--app-managed-only",
            action="store_true",
            help="Only process app-managed positions",
        )

    async def async_handle(self, *args, **options):
        position_id = options.get("position_id")
        days_back = options.get("days_back", 60)
        dry_run = options.get("dry_run", False)
        app_managed_only = options.get("app_managed_only", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be saved"))

        # Get positions to process
        positions_query = Position.objects.filter(
            lifecycle_state__in=["open_full", "open_partial"]
        ).select_related("user", "trading_account")

        if position_id:
            try:
                positions = [
                    Position.objects.select_related("user", "trading_account").get(id=position_id)
                ]
                self.stdout.write(f"Processing single position {position_id}")
            except Position.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Position with ID {position_id} does not exist")
                )
                return
        else:
            # Get user using utility function if provided
            user = await aget_user_from_options(
                options, require_user=False, allow_superuser_fallback=False
            )
            if user:
                positions = list(positions_query.filter(user=user))
                self.stdout.write(
                    f"Processing {len(positions)} open positions for user {user.email}"
                )
            elif app_managed_only:
                positions = list(positions_query.filter(is_app_managed=True))
                self.stdout.write(
                    f"Processing {len(positions)} app-managed open positions for all users"
                )
            else:
                positions = list(positions_query)
                self.stdout.write(f"Processing {len(positions)} open positions for all users")

        if not positions:
            self.stdout.write(self.style.WARNING("No positions found to process"))
            return

        # Run async backfill
        service = OrderHistoryService()
        await self._async_backfill(service, positions, days_back, dry_run)

    async def _async_backfill(
        self,
        service: OrderHistoryService,
        positions: list[Position],
        days_back: int,
        dry_run: bool,
    ):
        """Async method to backfill order history and correct positions."""
        accounts_processed = set()
        positions_checked = 0
        positions_corrected = 0
        discrepancies = []

        # Group positions by account to avoid duplicate syncs
        positions_by_account = {}
        for position in positions:
            account_id = position.trading_account_id
            if account_id not in positions_by_account:
                positions_by_account[account_id] = []
            positions_by_account[account_id].append(position)

        # Process each account
        for account_id, account_positions in positions_by_account.items():
            try:
                account = await TradingAccount.objects.select_related("user").aget(id=account_id)

                # Sync order history for this account if not done yet
                if account_id not in accounts_processed:
                    self.stdout.write(
                        f"\nSyncing order history for account {account.account_number}..."
                    )
                    result = await service.sync_order_history(account, days_back=days_back)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Synced {result['orders_synced']} orders "
                            f"({result['new_orders']} new, {result['updated_orders']} updated)"
                        )
                    )
                    accounts_processed.add(account_id)

                # Process positions for this account
                self.stdout.write(
                    f"\nProcessing {len(account_positions)} positions for account "
                    f"{account.account_number}..."
                )

                for position in account_positions:
                    positions_checked += 1

                    # Reconstruct from cached orders
                    corrected_data = await service.reconstruct_position_from_orders(position)

                    if not corrected_data:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Position {position.id} ({position.symbol}): "
                                "No cached orders found"
                            )
                        )
                        continue

                    # Check for discrepancies
                    has_discrepancy = False
                    changes = []

                    if "number_of_spreads" in corrected_data:
                        old_spreads = position.number_of_spreads
                        new_spreads = corrected_data["number_of_spreads"]
                        if old_spreads != new_spreads:
                            has_discrepancy = True
                            changes.append(f"spreads: {old_spreads} -> {new_spreads}")
                            position.number_of_spreads = new_spreads

                    if "quantity" in corrected_data:
                        old_qty = position.quantity
                        new_qty = corrected_data["quantity"]
                        if old_qty != new_qty:
                            has_discrepancy = True
                            changes.append(f"quantity: {old_qty} -> {new_qty}")
                            position.quantity = new_qty

                    if has_discrepancy:
                        positions_corrected += 1
                        discrepancies.append(
                            {
                                "position_id": position.id,
                                "symbol": position.symbol,
                                "strategy": position.strategy_type,
                                "changes": changes,
                            }
                        )

                        self.stdout.write(
                            self.style.WARNING(
                                f"  Position {position.id} ({position.symbol}): "
                                f"DISCREPANCY - {', '.join(changes)}"
                            )
                        )

                        # Update metadata with corrected info
                        if "metadata" in corrected_data:
                            existing_metadata = position.metadata or {}
                            existing_metadata.update(corrected_data["metadata"])
                            position.metadata = existing_metadata

                        # Save if not dry run
                        if not dry_run:
                            await position.asave()
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"    Position {position.id} corrected and saved"
                                )
                            )
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"    Position {position.id} correction skipped (dry run)"
                                )
                            )
                    else:
                        self.stdout.write(f"  Position {position.id} ({position.symbol}): OK")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing account {account_id}: {e}"))
                logger.error(
                    f"Error in backfill for account {account_id}: {e}",
                    exc_info=True,
                )

        # Print summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("BACKFILL SUMMARY:")
        self.stdout.write(f"  Accounts processed: {len(accounts_processed)}")
        self.stdout.write(f"  Positions checked: {positions_checked}")
        self.stdout.write(f"  Positions with discrepancies: {positions_corrected}")
        self.stdout.write("=" * 70)

        if discrepancies:
            self.stdout.write("\nDISCREPANCIES FOUND:")
            for disc in discrepancies:
                self.stdout.write(
                    f"  Position {disc['position_id']} ({disc['symbol']}, "
                    f"{disc['strategy']}): {', '.join(disc['changes'])}"
                )
            self.stdout.write("")

        if dry_run and positions_corrected > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: {positions_corrected} positions would be corrected. "
                    "Run without --dry-run to apply corrections."
                )
            )
        elif positions_corrected > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nBackfill complete! {positions_corrected} positions corrected."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\nBackfill complete! All positions have correct data.")
            )
