"""
Management command to create profit targets for existing positions.
Uses synchronous execution for reliable Django management command compatibility.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.execution.order_service import OrderExecutionService
from services.management.utils import add_user_arguments, get_user_from_options
from trading.models import Position, Trade

User = get_user_model()


class Command(BaseCommand):
    help = "Create profit targets for open positions"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=False)
        parser.add_argument(
            "--position", type=int, help="Specific position ID to create profit targets for"
        )
        parser.add_argument(
            "--test",
            action="store_true",
            help="Test mode - simulate profit target creation without real orders",
        )
        parser.add_argument(
            "--check-fill",
            action="store_true",
            help="Check if opening order is filled before creating profit targets",
        )

    def handle(self, *args, **options):
        """Handle the command execution synchronously."""
        try:
            if options["position"]:
                # Handle specific position
                position = Position.objects.get(id=options["position"])
                result = self._create_profit_targets_for_position_sync(position, options)

                if result and result.get("status") == "success":
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully created profit targets for position {position.id}"
                        )
                    )
                else:
                    error_msg = (
                        result.get("message", "Unknown error")
                        if result
                        else "Failed to create profit targets"
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"Failed to create profit targets for position {position.id}: "
                            f"{error_msg}"
                        )
                    )

            else:
                # Handle all positions for user
                user = get_user_from_options(
                    options, require_user=True, allow_superuser_fallback=False
                )

                positions = Position.objects.filter(
                    user=user, status="open", is_app_managed=True, profit_targets_created=False
                )

                if not positions.exists():
                    self.stdout.write(
                        self.style.WARNING(f"No eligible positions found for user {user.email}")
                    )
                    return

                success_count = 0
                for position in positions:
                    result = self._create_profit_targets_for_position_sync(position, options)
                    if result and result.get("status") == "success":
                        success_count += 1
                        self.stdout.write(f"Position {position.id}: Created profit targets")
                    else:
                        error_msg = result.get("message", "Unknown error") if result else "Failed"
                        self.stdout.write(f"Position {position.id}: {error_msg}")

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created profit targets for {success_count}/{positions.count()} positions"
                    )
                )

        except Position.DoesNotExist:
            raise CommandError(f"Position {options['position']} not found")
        except Exception as e:
            raise CommandError(f"Command failed: {e!s}")

    def _create_profit_targets_for_position_sync(self, position: Position, options: dict) -> dict:
        """
        Create profit targets for a specific position using synchronous
        OrderExecutionService method.
        """
        try:
            self.stdout.write(f"\nStarting profit target creation for position {position.id}")

            # Check if profit targets already exist
            if position.profit_targets_created:
                self.stdout.write(f"Position {position.id} already has profit targets")
                return {"status": "error", "message": "Profit targets already exist"}

            # Get the opening trade (synchronously)
            opening_trade = Trade.objects.filter(position=position, trade_type="open").first()

            if not opening_trade:
                self.stdout.write(f"No opening trade found for position {position.id}")
                return {"status": "error", "message": "No opening trade found"}

            broker_order = opening_trade.broker_order_id
            self.stdout.write(
                f"Found opening trade {opening_trade.id} with broker_order_id: {broker_order}"
            )

            # Check if order is filled (if requested)
            if options.get("check_fill") and opening_trade.status != "filled":
                self.stdout.write(
                    f"Opening trade {opening_trade.id} not filled (status: {opening_trade.status})"
                )
                return {
                    "status": "error",
                    "message": f"Trade not filled (status: {opening_trade.status})",
                }

            # Use synchronous OrderExecutionService method
            # Test mode is automatically detected from the account
            service = OrderExecutionService(position.user)

            self.stdout.write("Calling synchronous create_profit_targets_sync...")

            # Call the synchronous method
            result = service.create_profit_targets_sync(position, opening_trade.broker_order_id)

            if result and result.get("status") == "success":
                order_ids = result.get("order_ids", [])

                # Update trade with profit target order IDs
                opening_trade.child_order_ids = order_ids
                opening_trade.save()

                # Display results
                if options.get("test"):
                    total_orders = result.get("total_orders", 0)
                    self.stdout.write(
                        f"\nTEST MODE: Created {total_orders} profit target orders"
                    )
                else:
                    self.stdout.write(
                        f"\nCreated {result.get('total_orders', 0)} profit target orders:"
                    )

                for target in result.get("targets", []):
                    spread_type = target["spread_type"]
                    profit_pct = target["profit_percentage"]
                    order_id = target["order_id"]
                    self.stdout.write(
                        f"  - {spread_type}: {profit_pct}% target → Order ID: {order_id}"
                    )

                return result
            error_msg = result.get("message", "Unknown error") if result else "No result returned"
            self.stdout.write(f"Failed to create profit targets: {error_msg}")
            return result or {"status": "error", "message": "Failed to create profit targets"}

        except Exception as e:
            self.stdout.write(f"Error creating profit targets for position {position.id}: {e}")
            return {"status": "error", "message": str(e)}
