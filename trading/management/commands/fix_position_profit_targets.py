"""
One-time fix command to handle Position 1's cancelled profit targets.
This addresses the specific bug where profit targets were created as credits instead of debits.
"""

import asyncio

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from services.execution.order_service import OrderExecutionService
from trading.models import Position, Trade

User = get_user_model()


class Command(BaseCommand):
    help = "Fix Position 1 profit targets that were cancelled due to credit/debit bug"

    def add_arguments(self, parser):
        parser.add_argument(
            "--position", type=int, default=1, help="Position ID to fix (default: 1)"
        )
        parser.add_argument(
            "--check-status",
            action="store_true",
            help="Check order status with TastyTrade before recreating",
        )

    def handle(self, *args, **options):
        """Handle the one-time fix."""
        position_id = options["position"]

        try:
            position = Position.objects.get(id=position_id)
            self.stdout.write(f"\n📍 Position {position_id} ({position.symbol})")
            self.stdout.write(
                f"   Status: profit_targets_created={position.profit_targets_created}"
            )

            # Find the opening trade
            opening_trade = Trade.objects.filter(position=position, trade_type="open").first()

            if not opening_trade:
                self.stdout.write(self.style.ERROR("❌ No opening trade found"))
                return

            self.stdout.write(f"   Opening Trade: {opening_trade.broker_order_id}")
            self.stdout.write(f"   Child Orders: {opening_trade.child_order_ids}")

            # Step 1: Clear the bad profit target data
            self.stdout.write("\n🧹 Step 1: Clearing cancelled profit target data...")

            if options.get("check_status"):
                # Optional: verify orders are actually cancelled
                cancelled_count = self._check_order_statuses(
                    position.user, opening_trade.child_order_ids
                )
                self.stdout.write(f"   Found {cancelled_count} cancelled/rejected orders")

            # Clear the position's profit target tracking
            position.profit_targets_created = False
            position.profit_target_details = {}
            position.save()
            self.stdout.write(self.style.SUCCESS("   ✅ Cleared position profit target fields"))

            # Clear the trade's child order references
            opening_trade.child_order_ids = []
            opening_trade.save()
            self.stdout.write(self.style.SUCCESS("   ✅ Cleared trade child_order_ids"))

            # Step 2: Create new profit targets
            self.stdout.write("\n🎯 Step 2: Creating new profit targets...")

            # Use the synchronous order service method
            service = OrderExecutionService(position.user)
            result = service.create_profit_targets_sync(position, opening_trade.broker_order_id)

            if result and result.get("status") == "success":
                # Update trade with new profit target order IDs
                new_order_ids = result.get("order_ids", [])
                opening_trade.child_order_ids = new_order_ids
                opening_trade.save()

                num_orders = result.get("total_orders", 0)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✅ Successfully created {num_orders} new profit targets:"
                    )
                )
                for target in result.get("targets", []):
                    self.stdout.write(
                        f"   - {target['spread_type']}: {target['profit_percentage']}% "
                        f"@ ${target.get('target_price', 'N/A')} → Order {target['order_id']}"
                    )

                # Show final state
                position.refresh_from_db()
                self.stdout.write("\n📊 Final State:")
                self.stdout.write(f"   profit_targets_created: {position.profit_targets_created}")
                self.stdout.write(f"   child_order_ids: {opening_trade.child_order_ids}")

            else:
                error_msg = result.get("message", "Unknown error") if result else "No result"
                self.stdout.write(
                    self.style.ERROR(f"❌ Failed to create profit targets: {error_msg}")
                )

        except Position.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Position {position_id} not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e!s}"))
            import traceback

            traceback.print_exc()

    def _check_order_statuses(self, user, order_ids):
        """Check if orders are cancelled/rejected (optional verification)."""
        if not order_ids:
            return 0

        cancelled_count = 0

        try:
            # Run async check in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            service = OrderExecutionService(user)

            for order_id in order_ids:
                try:
                    result = loop.run_until_complete(service.check_order_status(order_id))
                    status = result.get("status", "").upper()

                    self.stdout.write(f"   Order {order_id}: {status}")

                    if status in ["CANCELLED", "REJECTED", "CANCEL", "REJECT"]:
                        cancelled_count += 1
                except Exception as e:
                    self.stdout.write(f"   Order {order_id}: Could not check ({e})")

            loop.close()

        except Exception as e:
            self.stdout.write(f"   Warning: Could not check order statuses: {e}")

        return cancelled_count
