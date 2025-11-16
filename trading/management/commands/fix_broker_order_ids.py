"""
Management command to backfill missing broker_order_ids from metadata or trades.

This fixes positions that were created without proper broker_order_ids population.
The broker_order_ids field is used by backfill_order_history to find opening orders.
"""

from django.core.management.base import BaseCommand

from services.core.logging import get_logger
from trading.models import Position, Trade

logger = get_logger(__name__)


class Command(BaseCommand):
    help = "Fix missing broker_order_ids by copying from metadata or trades"

    def add_arguments(self, parser):
        parser.add_argument(
            "--position-id",
            type=int,
            help="Fix specific position ID only",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Dry run mode - report what would be fixed but don't save",
        )
        parser.add_argument(
            "--app-managed-only",
            action="store_true",
            help="Only process app-managed positions",
        )

    def handle(self, *args, **options):
        position_id = options.get("position_id")
        dry_run = options.get("dry_run", False)
        app_managed_only = options.get("app_managed_only", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be saved"))

        # Get positions to process
        # Include all lifecycle states to fix historical positions too
        positions_query = Position.objects.all()

        if app_managed_only:
            positions_query = positions_query.filter(is_app_managed=True)

        if position_id:
            try:
                positions = [Position.objects.get(id=position_id)]
                self.stdout.write(f"Processing single position {position_id}")
            except Position.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Position with ID {position_id} does not exist")
                )
                return
        else:
            positions = list(positions_query)
            self.stdout.write(f"Processing {len(positions)} positions")

        if not positions:
            self.stdout.write(self.style.WARNING("No positions found to process"))
            return

        # Process each position
        positions_fixed = 0
        positions_checked = 0

        for position in positions:
            positions_checked += 1

            # Check if broker_order_ids is empty or missing
            if position.broker_order_ids and len(position.broker_order_ids) > 0:
                self.stdout.write(
                    f"  Position {position.id} ({position.symbol}): Already has broker_order_ids"
                )
                continue

            # Try to find broker_order_id from multiple sources
            order_id = None

            # Source 1: metadata.broker_response.order_id
            if position.metadata and "broker_response" in position.metadata:
                order_id = position.metadata["broker_response"].get("order_id")
                if order_id:
                    self.stdout.write(
                        f"  Position {position.id} ({position.symbol}): "
                        f"Found order_id in metadata.broker_response: {order_id}"
                    )

            # Source 2: First trade's broker_order_id
            if not order_id:
                first_trade = Trade.objects.filter(position=position, trade_type="open").first()
                if first_trade and first_trade.broker_order_id:
                    order_id = first_trade.broker_order_id
                    self.stdout.write(
                        f"  Position {position.id} ({position.symbol}): "
                        f"Found order_id from Trade: {order_id}"
                    )

            if order_id:
                positions_fixed += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  Position {position.id} ({position.symbol}): "
                        f"MISSING broker_order_ids - will set to [{order_id}]"
                    )
                )

                if not dry_run:
                    position.broker_order_ids = [order_id]
                    position.save(update_fields=["broker_order_ids"])
                    self.stdout.write(
                        self.style.SUCCESS(f"    Position {position.id} fixed and saved")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"    Position {position.id} fix skipped (dry run)")
                    )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Position {position.id} ({position.symbol}): "
                        "Could not find broker_order_id from any source"
                    )
                )

        # Print summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("FIX SUMMARY:")
        self.stdout.write(f"  Positions checked: {positions_checked}")
        self.stdout.write(f"  Positions fixed: {positions_fixed}")
        self.stdout.write("=" * 70)

        if dry_run and positions_fixed > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: {positions_fixed} positions would be fixed. "
                    "Run without --dry-run to apply fixes."
                )
            )
        elif positions_fixed > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\nFix complete! {positions_fixed} positions fixed.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo positions needed fixing."))
