"""
Management command to reconcile QQQ profit target orders between TastyTrade and database.

This command:
1. Fetches all active QQQ orders from TastyTrade
2. Compares with database Position.profit_target_details
3. Identifies orphaned orders (in TastyTrade but not in database)
4. Identifies invalid orders (in database but not in TastyTrade)
5. Offers to:
   - Cancel orphaned orders in TastyTrade
   - Clear invalid order IDs from database
   - Trigger recreation of missing profit targets

Pattern: Management Command (Pattern 1 - Pure Sync + Event Loop)
- Main handle() is sync
- Django ORM calls stay in sync context
- Async TastyTrade SDK calls use event loop pattern
- Database saves in async helpers use sync_to_async
"""

import asyncio
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tastytrade import Account

from services.core.data_access import get_oauth_session, get_primary_tastytrade_account
from trading.models import Position

User = get_user_model()


class Command(BaseCommand):
    help = "Reconcile QQQ profit target orders between TastyTrade and database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompts",
        )
        parser.add_argument(
            "--cancel-orphaned",
            action="store_true",
            help="Cancel orphaned orders in TastyTrade",
        )
        parser.add_argument(
            "--clear-invalid",
            action="store_true",
            help="Clear invalid order IDs from database",
        )
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Create missing profit target orders after cleanup",
        )
        parser.add_argument(
            "--replace-cancelled",
            action="store_true",
            help="Replace cancelled orders with new ones at current prices",
        )
        parser.add_argument(
            "--output",
            type=str,
            help="Save analysis results to file",
        )
        parser.add_argument(
            "--user",
            type=str,
            required=True,
            help="Email address of the user to reconcile orders for",
        )

    def handle(self, *args, **options):
        """Main reconciliation logic - sync function."""
        dry_run = options["dry_run"]
        skip_confirm = options.get("yes", False)
        cancel_orphaned = options.get("cancel_orphaned", False)
        clear_invalid = options.get("clear_invalid", False)
        user_email = options["user"]

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("🔄 QQQ ORDER RECONCILIATION")
        self.stdout.write("=" * 80)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n⚠️  DRY RUN MODE - No changes will be made\n"))

        # Get user (sync Django ORM)
        try:
            user = User.objects.get(email=user_email)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ User not found: {user_email}"))
            return

        # Step 1: Get open positions from database (sync Django ORM)
        self.stdout.write("\n💾 Step 1: Checking database positions...")
        positions = (
            Position.objects.filter(
                symbol="QQQ", lifecycle_state__in=["open_full", "open_partial"], user=user
            )
            .select_related("user")
            .order_by("id")
        )

        self.stdout.write(f"   Found {positions.count()} open QQQ positions")

        # Determine lookback window based on oldest position
        oldest_position = positions.order_by("opened_at").first()
        days_lookback = 60  # Default
        if oldest_position and oldest_position.opened_at:
            from django.utils import timezone

            days_old = (timezone.now() - oldest_position.opened_at).days
            days_lookback = max(
                60, days_old + 7
            )  # At least 60 days, or oldest position + 7 days buffer

        # Step 2: Fetch active orders from TastyTrade (via async bridge)
        self.stdout.write(
            f"\n📡 Step 2: Fetching active orders from TastyTrade (last {days_lookback} days)..."
        )
        tt_orders = self._fetch_tastytrade_orders_sync(user, days_lookback)

        qqq_orders = [o for o in tt_orders if o["symbol"] == "QQQ"]
        self.stdout.write(f"   Found {len(qqq_orders)} active QQQ orders")

        # Step 3: Analyze discrepancies
        self.stdout.write("\n🔍 Step 3: Analyzing discrepancies...")

        analysis = self._analyze_orders(qqq_orders, positions)

        self._print_analysis(analysis)

        # Step 4: Execute fixes if requested
        if not dry_run:
            # Step 4a: Clean up orphaned/invalid orders first
            if cancel_orphaned and analysis["orphaned_orders"]:
                if not skip_confirm:
                    confirm = input(
                        f"\n❓ Cancel {len(analysis['orphaned_orders'])} orphaned orders? (yes/no): "
                    )
                    if confirm.lower() != "yes":
                        self.stdout.write(
                            self.style.WARNING("⏭️  Skipping orphaned order cancellation")
                        )
                        cancel_orphaned = False

                if cancel_orphaned:
                    self._cancel_orphaned_orders_sync(user, analysis["orphaned_orders"])

            if clear_invalid and analysis["invalid_positions"]:
                if not skip_confirm:
                    confirm = input(
                        f"\n❓ Clear invalid order IDs from {len(analysis['invalid_positions'])} positions? (yes/no): "
                    )
                    if confirm.lower() != "yes":
                        self.stdout.write(
                            self.style.WARNING("⏭️  Skipping invalid order ID clearing")
                        )
                        clear_invalid = False

                if clear_invalid:
                    self._clear_invalid_orders_sync(analysis["invalid_positions"])

            # Step 4b: Replace cancelled orders (Level 3)
            replace_cancelled = options.get("replace_cancelled", False)
            if replace_cancelled and analysis.get("cancelled_orders"):
                if not skip_confirm:
                    confirm = input(
                        f"\n❓ Replace {len(analysis['cancelled_orders'])} cancelled orders? (yes/no): "
                    )
                    if confirm.lower() != "yes":
                        self.stdout.write(
                            self.style.WARNING("⏭️  Skipping cancelled order replacement")
                        )
                        replace_cancelled = False

                if replace_cancelled:
                    self._replace_cancelled_orders_sync(analysis["cancelled_orders"])

            # Step 4c: Create missing orders (Levels 1 & 2)
            create_missing = options.get("create_missing", False)
            if create_missing and (analysis["missing_orders"] or analysis.get("partial_orders")):
                total_to_create = len(analysis["missing_orders"]) + len(
                    analysis.get("partial_orders", [])
                )
                if not skip_confirm:
                    confirm = input(
                        f"\n❓ Create missing orders for {total_to_create} positions? (yes/no): "
                    )
                    if confirm.lower() != "yes":
                        self.stdout.write(self.style.WARNING("⏭️  Skipping missing order creation"))
                        create_missing = False

                if create_missing:
                    self._create_missing_orders_sync(
                        analysis["missing_orders"], analysis.get("partial_orders", [])
                    )

        # Step 5: Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("📊 SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"✅ Matched positions: {len(analysis['matched_positions'])}")
        self.stdout.write(f"❌ Level 1 - No orders: {len(analysis['missing_orders'])}")
        self.stdout.write(f"⚠️  Level 2 - Partial orders: {len(analysis.get('partial_orders', []))}")
        self.stdout.write(
            f"🔄 Level 3 - Cancelled orders: {len(analysis.get('cancelled_orders', []))}"
        )
        self.stdout.write(f"⚠️  Level 4 - Invalid orders: {len(analysis['invalid_positions'])}")
        self.stdout.write(f"🔗 Orphaned orders: {len(analysis['orphaned_orders'])}")

        # Next steps guidance
        needs_attention = (
            len(analysis["missing_orders"])
            + len(analysis.get("partial_orders", []))
            + len(analysis.get("cancelled_orders", []))
            + len(analysis["invalid_positions"])
        )

        if needs_attention > 0:
            self.stdout.write("\n💡 NEXT STEPS:")
            self.stdout.write(f"   {needs_attention} positions need attention")

            if not dry_run:
                if analysis["invalid_positions"] or analysis["orphaned_orders"]:
                    self.stdout.write("   ✓ Run cleanup: --clear-invalid --cancel-orphaned")
                if (
                    analysis["missing_orders"]
                    or analysis.get("partial_orders")
                    or analysis.get("cancelled_orders")
                ):
                    self.stdout.write("   ✓ Run creation: --create-missing --replace-cancelled")
            else:
                self.stdout.write("   Run without --dry-run to fix issues")

    def _analyze_orders(self, tt_orders: list[dict], positions) -> dict:
        """
        Analyze discrepancies between TastyTrade orders and database.
        Multi-level analysis for different reconciliation scenarios.
        Pure sync function - no async calls.
        """
        # Create set of TastyTrade order IDs
        tt_order_ids = {int(o["order_id"]) for o in tt_orders}

        matched_positions = []
        invalid_positions = []
        missing_orders = []
        partial_orders = []  # Level 2: Has some orders but missing others
        cancelled_orders = []  # Level 3: Has cancelled orders needing replacement

        # Check each position
        for pos in positions:
            # Level 1: Position has NO profit_target_details at all
            if not pos.profit_target_details:
                missing_orders.append(pos)
                continue

            stored_orders = []
            matched_orders = []
            invalid_orders = []
            cancelled_spreads = []
            missing_spreads = []

            # Extract order IDs from profit_target_details
            for key in ["call_spread", "put_spread_1", "put_spread_2"]:
                if key in pos.profit_target_details:
                    detail = pos.profit_target_details[key]
                    order_id_str = detail.get("order_id", "")
                    status = detail.get("status", "unknown")

                    try:
                        order_id = int(order_id_str)
                        stored_orders.append((key, order_id, status))

                        # Level 3: Cancelled order that needs replacement
                        if status in ["cancelled", "cancelled_dte_automation"]:
                            cancelled_spreads.append((key, order_id, status))
                        elif order_id in tt_order_ids:
                            matched_orders.append((key, order_id))
                        elif status not in ["filled"]:
                            # Invalid: order ID in DB but not in TastyTrade (and not cancelled/filled)
                            invalid_orders.append((key, order_id, status))
                    except (ValueError, TypeError):
                        pass
                else:
                    # Level 2: Spread completely missing from profit_target_details
                    # This is different from Level 1 (no details at all)
                    missing_spreads.append(key)

            # Categorize position
            if cancelled_spreads:
                # Level 3: Has cancelled orders
                cancelled_orders.append(
                    {
                        "position": pos,
                        "cancelled_spreads": cancelled_spreads,
                        "matched_orders": matched_orders,
                    }
                )
            elif invalid_orders:
                # Level 4: Has invalid orders (desync)
                invalid_positions.append(
                    {
                        "position": pos,
                        "invalid_orders": invalid_orders,
                        "matched_orders": matched_orders,
                    }
                )
            elif missing_spreads:
                # Level 2: Partial orders (some spreads missing entirely)
                partial_orders.append(
                    {
                        "position": pos,
                        "missing_spreads": missing_spreads,
                        "matched_orders": matched_orders,
                    }
                )
            elif matched_orders:
                matched_positions.append(pos)
            elif not stored_orders:
                # Shouldn't happen (would be caught by no profit_target_details check)
                # but include for completeness
                missing_orders.append(pos)

        # Find orphaned orders (in TastyTrade but not in database)
        all_matched_order_ids = set()

        # Add matched orders from all categories
        for pos_info in invalid_positions:
            for _, order_id in pos_info["matched_orders"]:
                all_matched_order_ids.add(order_id)

        for pos_info in cancelled_orders:
            for _, order_id in pos_info["matched_orders"]:
                all_matched_order_ids.add(order_id)

        for pos_info in partial_orders:
            for _, order_id in pos_info["matched_orders"]:
                all_matched_order_ids.add(order_id)

        for pos in matched_positions:
            for key in ["call_spread", "put_spread_1", "put_spread_2"]:
                if key in pos.profit_target_details:
                    try:
                        order_id = int(pos.profit_target_details[key].get("order_id", ""))
                        all_matched_order_ids.add(order_id)
                    except:
                        pass

        orphaned_orders = [o for o in tt_orders if int(o["order_id"]) not in all_matched_order_ids]

        return {
            "matched_positions": matched_positions,
            "invalid_positions": invalid_positions,
            "missing_orders": missing_orders,
            "partial_orders": partial_orders,
            "cancelled_orders": cancelled_orders,
            "orphaned_orders": orphaned_orders,
        }

    def _print_analysis(self, analysis: dict):
        """Print multi-level analysis results."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("📋 MULTI-LEVEL ANALYSIS RESULTS")
        self.stdout.write("=" * 80)

        # Matched positions
        if analysis["matched_positions"]:
            self.stdout.write(
                f"\n✅ {len(analysis['matched_positions'])} positions with ALL orders correct:"
            )
            for pos in analysis["matched_positions"][:5]:
                self.stdout.write(f"   Position #{pos.id}")
            if len(analysis["matched_positions"]) > 5:
                self.stdout.write(f"   ... and {len(analysis['matched_positions']) - 5} more")

        # Level 1: Missing ALL orders
        if analysis["missing_orders"]:
            self.stdout.write(
                f"\n❌ LEVEL 1: {len(analysis['missing_orders'])} positions with NO orders (profit_targets_created=False):"
            )
            for pos in analysis["missing_orders"][:5]:
                self.stdout.write(f"   Position #{pos.id} - needs ALL profit targets created")
            if len(analysis["missing_orders"]) > 5:
                self.stdout.write(f"   ... and {len(analysis['missing_orders']) - 5} more")

        # Level 2: Partial orders (some spreads missing)
        if analysis.get("partial_orders"):
            self.stdout.write(
                f"\n⚠️  LEVEL 2: {len(analysis['partial_orders'])} positions with PARTIAL orders:"
            )
            for pos_info in analysis["partial_orders"]:
                pos = pos_info["position"]
                missing = ", ".join(pos_info["missing_spreads"])
                self.stdout.write(f"\n   Position #{pos.id}:")
                self.stdout.write(f"      Missing: {missing}")
                if pos_info["matched_orders"]:
                    self.stdout.write(
                        f"      Has: {', '.join([key for key, _ in pos_info['matched_orders']])}"
                    )

        # Level 3: Cancelled orders needing replacement
        if analysis.get("cancelled_orders"):
            self.stdout.write(
                f"\n🔄 LEVEL 3: {len(analysis['cancelled_orders'])} positions with CANCELLED orders:"
            )
            for pos_info in analysis["cancelled_orders"]:
                pos = pos_info["position"]
                self.stdout.write(f"\n   Position #{pos.id}:")
                for key, order_id, status in pos_info["cancelled_spreads"]:
                    self.stdout.write(f"      🔄 {key}: {order_id} ({status}) - needs replacement")
                if pos_info["matched_orders"]:
                    self.stdout.write(
                        f"      Active: {', '.join([key for key, _ in pos_info['matched_orders']])}"
                    )

        # Level 4: Invalid orders (system desync)
        if analysis["invalid_positions"]:
            self.stdout.write(
                f"\n⚠️  LEVEL 4: {len(analysis['invalid_positions'])} positions with INVALID orders (desync):"
            )
            for pos_info in analysis["invalid_positions"]:
                pos = pos_info["position"]
                self.stdout.write(f"\n   Position #{pos.id}:")

                if pos_info["matched_orders"]:
                    self.stdout.write("      Valid orders:")
                    for key, order_id in pos_info["matched_orders"]:
                        self.stdout.write(f"        ✓ {key}: {order_id}")

                if pos_info["invalid_orders"]:
                    self.stdout.write("      Invalid orders (not in TastyTrade):")
                    for key, order_id, status in pos_info["invalid_orders"]:
                        self.stdout.write(f"        ✗ {key}: {order_id} (status: {status})")

        # Orphaned orders
        if analysis["orphaned_orders"]:
            self.stdout.write(
                f"\n🔗 ORPHANED: {len(analysis['orphaned_orders'])} orders in TastyTrade not linked to any position:"
            )
            for order in analysis["orphaned_orders"]:
                self.stdout.write(
                    f"   Order {order['order_id']}: {order['strikes']} {order['type']} exp {order['expiration']}"
                )

    def _fetch_tastytrade_orders_sync(self, user, days_lookback: int = 60) -> list[dict]:
        """
        Fetch active orders from TastyTrade.
        Sync wrapper around async function.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(self._fetch_orders_async(user, days_lookback))
            return result
        finally:
            loop.close()

    async def _fetch_orders_async(self, user, days_lookback: int) -> list[dict]:
        """
        Async function to fetch orders from TastyTrade.
        NO Django ORM calls here - all data passed in.
        """
        from tastytrade.order import OrderStatus

        session = await get_oauth_session(user)
        account = await get_primary_tastytrade_account(user)
        tt_account = await Account.a_get(session, account.account_number)

        # Get order history with appropriate lookback
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_lookback)

        all_orders = await tt_account.a_get_order_history(session, start_date=start_date)

        # Filter for LIVE orders (active, not filled/cancelled)
        orders_data = []
        for order in all_orders:
            # Check if order is still live/active
            if order.status not in [OrderStatus.LIVE, OrderStatus.RECEIVED]:
                continue

            # Extract strikes and expiration
            strikes = []
            exp_date = None
            symbol = None
            order_type = None

            for leg in order.legs:
                leg_symbol = leg.symbol
                if not symbol:
                    symbol = leg_symbol.split()[0] if leg_symbol else None

                if len(leg_symbol) >= 15:
                    exp_part = leg_symbol[6:12]
                    strike_part = leg_symbol[13:]
                    option_type = leg_symbol[12] if len(leg_symbol) > 12 else None

                    try:
                        exp_date = f"20{exp_part[:2]}-{exp_part[2:4]}-{exp_part[4:6]}"
                        strike = int(strike_part) / 1000.0
                        strikes.append(strike)

                        if option_type and not order_type:
                            order_type = "Call" if option_type == "C" else "Put"
                    except:
                        pass

            if strikes and exp_date and symbol:
                orders_data.append(
                    {
                        "order_id": order.id,
                        "symbol": symbol,
                        "strikes": sorted(strikes),
                        "expiration": exp_date,
                        "type": order_type,
                        "price": float(order.price) if order.price else None,
                    }
                )

        return orders_data

    def _cancel_orphaned_orders_sync(self, user, orphaned_orders: list[dict]):
        """
        Cancel orphaned orders in TastyTrade.
        Sync wrapper around async function.
        """
        self.stdout.write(f"\n🗑️  Cancelling {len(orphaned_orders)} orphaned orders...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                self._cancel_orders_async(user, [o["order_id"] for o in orphaned_orders])
            )

            self.stdout.write(self.style.SUCCESS(f"   ✅ Cancelled {result['cancelled']} orders"))
            if result["failed"]:
                self.stdout.write(
                    self.style.WARNING(f"   ⚠️  Failed to cancel {result['failed']} orders")
                )
        finally:
            loop.close()

    async def _cancel_orders_async(self, user, order_ids: list[int]) -> dict:
        """
        Async function to cancel orders.
        NO Django ORM calls here.
        """
        session = await get_oauth_session(user)
        account = await get_primary_tastytrade_account(user)
        tt_account = await Account.a_get(session, account.account_number)

        cancelled = 0
        failed = 0

        for order_id in order_ids:
            try:
                await tt_account.a_delete_order(session, int(order_id))
                cancelled += 1
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"      ⚠️  Failed to cancel order {order_id}: {e}")
                )
                failed += 1

        return {"cancelled": cancelled, "failed": failed}

    def _clear_invalid_orders_sync(self, invalid_positions: list[dict]):
        """
        Clear invalid order IDs from database positions.
        Sync function - direct Django ORM access.
        """
        self.stdout.write(
            f"\n🧹 Clearing invalid order IDs from {len(invalid_positions)} positions..."
        )

        for pos_info in invalid_positions:
            pos = pos_info["position"]
            invalid_orders = pos_info["invalid_orders"]

            # Clear invalid order IDs
            for key, order_id, status in invalid_orders:
                if key in pos.profit_target_details:
                    # Remove the entire entry or just mark as needs_recreation
                    del pos.profit_target_details[key]
                    self.stdout.write(f"   Cleared {key} order {order_id} from Position #{pos.id}")

            pos.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"   ✅ Cleared invalid orders from {len(invalid_positions)} positions"
            )
        )

    def _create_missing_orders_sync(self, missing_positions: list, partial_positions: list):
        """
        Create missing profit target orders.
        Level 1: Positions with NO orders
        Level 2: Positions with PARTIAL orders
        """
        from services.execution.order_service import OrderExecutionService
        from trading.models import Trade

        total_positions = len(missing_positions) + len(partial_positions)
        self.stdout.write(f"\n🎯 Creating profit targets for {total_positions} positions...")

        success_count = 0
        error_count = 0

        # Level 1: Create ALL orders for positions with none
        for pos in missing_positions:
            try:
                # Get opening trade
                opening_trade = Trade.objects.filter(position=pos, trade_type="open").first()
                if not opening_trade:
                    self.stdout.write(
                        self.style.WARNING(f"   ⚠️  Position #{pos.id}: No opening trade found")
                    )
                    error_count += 1
                    continue

                # Create all profit targets
                service = OrderExecutionService(pos.user)
                result = service.create_profit_targets_sync(pos, opening_trade.broker_order_id)

                if result and result.get("status") == "success":
                    targets = result.get("targets", [])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   ✅ Position #{pos.id}: Created {len(targets)} profit targets"
                        )
                    )
                    success_count += 1
                else:
                    error_msg = result.get("message", "Unknown error") if result else "No result"
                    self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {error_msg}"))
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {e!s}"))
                error_count += 1

        # Level 2: Create MISSING orders for positions with partial orders
        for pos_info in partial_positions:
            pos = pos_info["position"]
            missing_spreads = pos_info["missing_spreads"]

            try:
                opening_trade = Trade.objects.filter(position=pos, trade_type="open").first()
                if not opening_trade:
                    self.stdout.write(
                        self.style.WARNING(f"   ⚠️  Position #{pos.id}: No opening trade found")
                    )
                    error_count += 1
                    continue

                # Create only the missing spread types
                service = OrderExecutionService(pos.user)
                result = service.create_profit_targets_sync(
                    pos,
                    opening_trade.broker_order_id,
                    filter_spread_types=missing_spreads,
                    preserve_existing=True,
                )

                if result and result.get("status") == "success":
                    targets = result.get("targets", [])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   ✅ Position #{pos.id}: Created {len(targets)} missing profit targets"
                        )
                    )
                    success_count += 1
                else:
                    error_msg = result.get("message", "Unknown error") if result else "No result"
                    self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {error_msg}"))
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {e!s}"))
                error_count += 1

        self.stdout.write(f"\n   ✅ Success: {success_count}, ❌ Errors: {error_count}")

    def _replace_cancelled_orders_sync(self, cancelled_positions: list):
        """
        Replace cancelled orders with new ones at current market prices.
        Level 3: Positions with CANCELLED orders
        """
        from services.execution.order_service import OrderExecutionService
        from trading.models import Trade

        self.stdout.write(
            f"\n🔄 Replacing cancelled orders for {len(cancelled_positions)} positions..."
        )

        success_count = 0
        error_count = 0

        for pos_info in cancelled_positions:
            pos = pos_info["position"]
            cancelled_spreads = pos_info["cancelled_spreads"]

            try:
                opening_trade = Trade.objects.filter(position=pos, trade_type="open").first()
                if not opening_trade:
                    self.stdout.write(
                        self.style.WARNING(f"   ⚠️  Position #{pos.id}: No opening trade found")
                    )
                    error_count += 1
                    continue

                # Get list of spread types to replace
                spread_types = [key for key, _, _ in cancelled_spreads]

                # Clear the cancelled order entries first
                for key, order_id, status in cancelled_spreads:
                    if key in pos.profit_target_details:
                        del pos.profit_target_details[key]
                pos.save()

                # Create replacement orders at current prices
                service = OrderExecutionService(pos.user)
                result = service.create_profit_targets_sync(
                    pos,
                    opening_trade.broker_order_id,
                    filter_spread_types=spread_types,
                    preserve_existing=True,
                )

                if result and result.get("status") == "success":
                    targets = result.get("targets", [])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   ✅ Position #{pos.id}: Replaced {len(targets)} cancelled orders"
                        )
                    )
                    success_count += 1
                else:
                    error_msg = result.get("message", "Unknown error") if result else "No result"
                    self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {error_msg}"))
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Position #{pos.id}: {e!s}"))
                error_count += 1

        self.stdout.write(f"\n   ✅ Success: {success_count}, ❌ Errors: {error_count}")
