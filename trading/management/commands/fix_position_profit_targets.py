"""
Management command to recover missing/cancelled profit target orders with DTE awareness.

This command finds positions that need profit target recovery:
1. is_app_managed=True
2. lifecycle_state in ['open_full', 'open_partial']
3. profit_targets_created=True but no working order exists
4. OR DTE <= 7 and no DTE close order exists

For positions with DTE > 7: Recreates profit targets at user's configured %
For positions with DTE <= 7: Creates DTE close order instead

Usage:
    python manage.py fix_position_profit_targets --user EMAIL
    python manage.py fix_position_profit_targets --position 123
    python manage.py fix_position_profit_targets --all --dry-run
"""

from django.contrib.auth import get_user_model

from services.core.logging import get_logger
from services.execution.order_service import OrderExecutionService
from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options
from services.positions.lifecycle.dte_manager import DTEManager
from trading.models import Position, Trade

User = get_user_model()
logger = get_logger(__name__)


class Command(AsyncCommand):
    help = "Recover missing/cancelled profit target orders with DTE awareness"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)
        parser.add_argument(
            "--position",
            type=int,
            help="Specific position ID to fix",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process all users with positions needing recovery",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without executing",
        )
        parser.add_argument(
            "--check-status",
            action="store_true",
            help="Check order status with broker before recreating",
        )

    async def async_handle(self, *args, **options):
        """Handle the profit target recovery."""
        dry_run = options.get("dry_run", False)
        check_status = options.get("check_status", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))

        if options.get("position"):
            # Single position mode
            await self._fix_single_position(options["position"], dry_run, check_status)
        elif options.get("all"):
            # All users mode
            await self._fix_all_positions(dry_run, check_status)
        else:
            # Single user mode
            user = await aget_user_from_options(options, require_user=True)
            await self._fix_user_positions(user, dry_run, check_status)

    async def _fix_single_position(self, position_id: int, dry_run: bool, check_status: bool):
        """Fix a specific position."""
        try:
            position = await Position.objects.select_related("user", "trading_account").aget(
                id=position_id
            )
        except Position.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Position {position_id} not found"))
            return

        await self._process_position(position, dry_run, check_status)

    async def _fix_user_positions(self, user, dry_run: bool, check_status: bool):
        """Fix all positions for a specific user."""
        self.stdout.write(f"\nProcessing positions for user: {user.email}\n")

        positions = [
            pos
            async for pos in Position.objects.filter(
                user=user,
                is_app_managed=True,
                lifecycle_state__in=["open_full", "open_partial"],
            ).select_related("trading_account")
        ]

        if not positions:
            self.stdout.write(self.style.WARNING("No eligible positions found"))
            return

        self.stdout.write(f"Found {len(positions)} position(s) to check\n")

        stats = {"recovered": 0, "dte_closed": 0, "skipped": 0, "errors": 0}

        for position in positions:
            result = await self._process_position(position, dry_run, check_status)
            if result == "recovered":
                stats["recovered"] += 1
            elif result == "dte_closed":
                stats["dte_closed"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1

        self._print_summary(stats)

    async def _fix_all_positions(self, dry_run: bool, check_status: bool):
        """Fix positions for all users."""
        self.stdout.write("\nProcessing all positions needing recovery\n")

        positions = [
            pos
            async for pos in Position.objects.filter(
                is_app_managed=True,
                lifecycle_state__in=["open_full", "open_partial"],
            ).select_related("user", "trading_account")
        ]

        if not positions:
            self.stdout.write(self.style.WARNING("No eligible positions found"))
            return

        self.stdout.write(f"Found {len(positions)} position(s) to check\n")

        stats = {"recovered": 0, "dte_closed": 0, "skipped": 0, "errors": 0}

        for position in positions:
            result = await self._process_position(position, dry_run, check_status)
            if result == "recovered":
                stats["recovered"] += 1
            elif result == "dte_closed":
                stats["dte_closed"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1

        self._print_summary(stats)

    async def _process_position(
        self, position: Position, dry_run: bool, check_status: bool
    ) -> str:
        """
        Process a single position for profit target recovery.

        Returns:
            "recovered" - Profit targets were recreated
            "dte_closed" - DTE close order was placed
            "skipped" - No action needed
            "error" - An error occurred
        """
        self.stdout.write(f"\n{'─' * 60}")
        self.stdout.write(f"Position {position.id}: {position.symbol} ({position.strategy_type})")

        # Calculate current DTE
        dte_manager = DTEManager(position.user)
        current_dte = dte_manager.calculate_current_dte(position)
        dte_threshold = dte_manager.get_dte_threshold(position)

        if current_dte is None:
            self.stdout.write(self.style.WARNING("  Cannot calculate DTE - missing expiration"))
            return "error"

        self.stdout.write(f"  DTE: {current_dte} (threshold: {dte_threshold})")
        self.stdout.write(f"  profit_targets_created: {position.profit_targets_created}")

        # Get opening trade
        opening_trade = await Trade.objects.filter(
            position=position, trade_type="open"
        ).afirst()

        if not opening_trade:
            self.stdout.write(self.style.WARNING("  No opening trade found"))
            return "error"

        # Check if there are any working close orders
        existing_close_trade = await Trade.objects.filter(
            position=position,
            trade_type="close",
            status__in=["pending", "submitted", "routed", "live", "working"],
        ).afirst()

        if existing_close_trade:
            self.stdout.write(
                f"  Already has working close order: {existing_close_trade.broker_order_id}"
            )
            return "skipped"

        # Determine action based on DTE
        if current_dte <= dte_threshold:
            # DTE mode: Create DTE close order
            self.stdout.write(
                self.style.WARNING(f"  📅 DTE <= {dte_threshold} - DTE close mode")
            )
            return await self._create_dte_close(position, current_dte, dry_run)
        # Normal mode: Check if profit targets need recovery
        if not position.profit_targets_created:
            self.stdout.write("  Profit targets never created - creating now")
            return await self._recreate_profit_targets(
                position, opening_trade, dry_run, check_status
            )

        # Check if profit target orders still exist
        needs_recovery = await self._check_profit_target_status(
            position, opening_trade, check_status
        )

        if needs_recovery:
            self.stdout.write("  Profit targets need recovery")
            return await self._recreate_profit_targets(
                position, opening_trade, dry_run, check_status
            )
        self.stdout.write("  Profit targets are intact")
        return "skipped"

    async def _check_profit_target_status(
        self, position: Position, opening_trade: Trade, check_status: bool
    ) -> bool:
        """Check if profit targets need recovery."""
        child_order_ids = opening_trade.child_order_ids or []

        if not child_order_ids:
            # No child orders recorded - needs recovery
            return True

        if not check_status:
            # Assume orders exist if we have IDs
            return False

        # Check actual order status at broker
        self.stdout.write(f"  Checking {len(child_order_ids)} profit target order(s)...")

        order_service = OrderExecutionService(position.user)
        all_terminal = True

        for order_id in child_order_ids:
            try:
                status_data = await order_service.check_order_status(order_id)
                status = status_data.get("status", "").lower() if status_data else "unknown"

                if status in ["live", "working", "routed", "pending", "submitted"]:
                    self.stdout.write(f"    Order {order_id}: {status} (still working)")
                    all_terminal = False
                elif status == "filled":
                    self.stdout.write(f"    Order {order_id}: {status} (filled)")
                else:
                    self.stdout.write(f"    Order {order_id}: {status} (terminal)")
            except Exception as e:
                self.stdout.write(f"    Order {order_id}: error checking ({e})")

        # If all orders are terminal (cancelled/rejected/expired) but position still open,
        # we need to recover
        return all_terminal

    async def _recreate_profit_targets(
        self, position: Position, opening_trade: Trade, dry_run: bool, check_status: bool
    ) -> str:
        """Recreate profit targets for a position."""
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN] Would recreate profit targets"))
            return "recovered"

        try:
            # Clear existing profit target data
            position.profit_targets_created = False
            position.profit_target_details = {}
            await position.asave(update_fields=["profit_targets_created", "profit_target_details"])

            opening_trade.child_order_ids = []
            await opening_trade.asave(update_fields=["child_order_ids"])

            # Create new profit targets
            order_service = OrderExecutionService(position.user)
            result = order_service.create_profit_targets_sync(
                position, opening_trade.broker_order_id
            )

            if result and result.get("status") == "success":
                new_order_ids = result.get("order_ids", [])
                opening_trade.child_order_ids = new_order_ids
                await opening_trade.asave(update_fields=["child_order_ids"])

                num_orders = result.get("total_orders", 0)
                self.stdout.write(
                    self.style.SUCCESS(f"  Created {num_orders} profit target order(s)")
                )

                for target in result.get("targets", []):
                    self.stdout.write(
                        f"     - {target['spread_type']}: {target['profit_percentage']}% "
                        f"→ Order {target['order_id']}"
                    )

                return "recovered"
            error_msg = result.get("message", "Unknown error") if result else "No result"
            self.stdout.write(self.style.ERROR(f"  Failed: {error_msg}"))
            return "error"

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Error: {e}"))
            return "error"

    async def _create_dte_close(self, position: Position, current_dte: int, dry_run: bool) -> str:
        """Create a DTE close order for a position near expiration."""
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"  [DRY RUN] Would create DTE close order at DTE={current_dte}")
            )
            return "dte_closed"

        try:
            dte_manager = DTEManager(position.user)
            success = await dte_manager.close_position_at_dte(position, current_dte)

            if success:
                self.stdout.write(
                    self.style.SUCCESS(f"  DTE close order submitted at DTE={current_dte}")
                )
                return "dte_closed"
            self.stdout.write(self.style.WARNING("  DTE close not needed or already exists"))
            return "skipped"

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  DTE close failed: {e}"))
            return "error"

    def _print_summary(self, stats: dict):
        """Print summary statistics."""
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"Profit targets recovered: {stats['recovered']}")
        self.stdout.write(f"DTE close orders placed:  {stats['dte_closed']}")
        self.stdout.write(f"Skipped (no action):      {stats['skipped']}")
        self.stdout.write(f"Errors:                   {stats['errors']}")
        self.stdout.write(f"{'=' * 60}\n")

