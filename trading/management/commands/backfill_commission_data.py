"""
Backfill commission data on trading_trade from tastytrade_transactions.

Phase 3 of commission tracking implementation:
- Links existing trades to their transaction data
- Sums commission + clearing_fees + regulatory_fees per order
- Updates trading_trade.commission field

Also backfills submitted_at on profit target details from order history.

Usage:
    python manage.py backfill_commission_data
    python manage.py backfill_commission_data --dry-run
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from trading.models import Position, TastyTradeOrderHistory, TastyTradeTransaction, Trade


class Command(BaseCommand):
    help = "Backfill commission data from transactions to trades"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        self.stdout.write("\n=== Phase 3a: Backfilling trade commission data ===")
        trades_updated = self._backfill_trade_commissions(dry_run)

        self.stdout.write("\n=== Phase 3b: Backfilling profit target submitted_at ===")
        positions_updated = self._backfill_profit_target_timestamps(dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nComplete: {trades_updated} trades updated, "
                f"{positions_updated} positions updated"
            )
        )

    def _backfill_trade_commissions(self, dry_run: bool) -> int:
        """Backfill commission data on trades from transactions."""
        trades = Trade.objects.filter(
            status="filled",
            commission__isnull=True,
        ).select_related("position")

        updated_count = 0

        for trade in trades:
            try:
                order_id = int(trade.broker_order_id)
            except (ValueError, TypeError):
                continue

            result = TastyTradeTransaction.objects.filter(order_id=order_id).aggregate(
                total_commission=Sum("commission"),
                total_clearing=Sum("clearing_fees"),
                total_regulatory=Sum("regulatory_fees"),
            )

            commission = result.get("total_commission") or Decimal("0")
            clearing = result.get("total_clearing") or Decimal("0")
            regulatory = result.get("total_regulatory") or Decimal("0")
            total = commission + clearing + regulatory

            if total != Decimal("0"):
                self.stdout.write(
                    f"  Trade {trade.id} (order {trade.broker_order_id}): "
                    f"commission={commission}, clearing={clearing}, regulatory={regulatory}, "
                    f"total={total}"
                )
                if not dry_run:
                    trade.commission = total
                    trade.save(update_fields=["commission"])
                updated_count += 1

        self.stdout.write(f"  Found {updated_count} trades to update")
        return updated_count

    def _backfill_profit_target_timestamps(self, dry_run: bool) -> int:
        """Backfill submitted_at on profit target details from order history."""
        positions = Position.objects.filter(
            is_app_managed=True,
            profit_targets_created=True,
        ).exclude(profit_target_details={})

        updated_count = 0

        for position in positions:
            if not position.profit_target_details:
                continue

            updated = False
            details = position.profit_target_details.copy()

            for spread_type, pt_details in details.items():
                order_id = pt_details.get("order_id")
                if not order_id:
                    continue

                # Skip if already has submitted_at
                if pt_details.get("submitted_at"):
                    continue

                # Look up from order history
                try:
                    order_history = TastyTradeOrderHistory.objects.filter(
                        broker_order_id=str(order_id)
                    ).first()

                    if order_history and order_history.received_at:
                        pt_details["submitted_at"] = order_history.received_at.isoformat()
                        updated = True
                        self.stdout.write(
                            f"  Position {position.id} {spread_type}: "
                            f"submitted_at={order_history.received_at.isoformat()}"
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Position {position.id} {spread_type}: Error - {e}"
                        )
                    )

            if updated:
                if not dry_run:
                    position.profit_target_details = details
                    position.save(update_fields=["profit_target_details"])
                updated_count += 1

        self.stdout.write(f"  Found {updated_count} positions to update")
        return updated_count
