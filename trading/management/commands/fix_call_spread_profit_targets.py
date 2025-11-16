"""
Management command to fix call spread profit targets with incorrect percentages.

This command:
1. Finds all positions with call_spread profit targets that have incorrect percentages
2. Cancels the incorrect profit target orders at TastyTrade
3. Creates new profit target orders with correct 40% profit target (buying back at 60% of credit)
4. Updates Position.profit_target_details and Trade.child_order_ids

Background:
- Bug: Call spreads were set to 50% profit (buying back at 50% of credit)
- Fix: Should be 40% profit (buying back at 60% of credit) per SENEX_TRIDENT_DEFAULTS
"""

import asyncio
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from asgiref.sync import sync_to_async
from tastytrade import Account
from tastytrade.order import (
    InstrumentType,
    Leg,
    NewOrder,
    OrderAction,
    OrderTimeInForce,
    OrderType,
)

from services.core.data_access import get_oauth_session, get_primary_tastytrade_account
from services.execution.order_service import OrderExecutionService
from services.strategies.utils.pricing_utils import round_option_price
from trading.models import Position, Trade

User = get_user_model()


class Command(BaseCommand):
    help = "Fix call spread profit targets with incorrect 50% percentage (should be 40%)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be fixed without making changes",
        )
        parser.add_argument(
            "--position",
            type=int,
            help="Fix specific position ID (default: all affected positions)",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt (for non-interactive execution)",
        )

    def handle(self, *args, **options):
        """Fix call spread profit targets across all affected positions."""
        dry_run = options["dry_run"]
        position_id = options.get("position")
        skip_confirm = options.get("yes", False)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("🔧 CALL SPREAD PROFIT TARGET FIX")
        self.stdout.write("=" * 80)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n⚠️  DRY RUN MODE - No changes will be made\n"))

        # Find affected positions
        positions = self._find_affected_positions(position_id)

        if not positions:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n✅ No positions found with incorrect call spread profit targets"
                )
            )
            return

        self.stdout.write(
            f"\n📋 Found {len(positions)} position(s) with incorrect call spread profit targets:\n"
        )

        for pos in positions:
            details = pos.profit_target_details or {}
            call_spread_info = details.get("call_spread", {})
            self.stdout.write(
                f"   Position {pos.id} ({pos.symbol}): "
                f"Current {call_spread_info.get('percent', 'N/A')}% → Should be 40%"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("\n⚠️  DRY RUN - Exiting without making changes"))
            return

        # Confirm before proceeding (unless --yes flag provided)
        if not skip_confirm:
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  This will cancel and recreate profit target orders at TastyTrade"
                )
            )
            confirm = input("Continue? (yes/no): ")

            if confirm.lower() != "yes":
                self.stdout.write(self.style.WARNING("❌ Aborted by user"))
                return

        # Process each position
        success_count = 0
        error_count = 0

        for position in positions:
            self.stdout.write("\n" + "-" * 80)
            try:
                if self._fix_position(position):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error fixing position {position.id}: {e}"))
                error_count += 1
                import traceback

                traceback.print_exc()

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("📊 SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"✅ Successfully fixed: {success_count}")
        self.stdout.write(f"❌ Errors: {error_count}")
        self.stdout.write(f"📦 Total processed: {len(positions)}")

    def _find_affected_positions(self, position_id=None):
        """Find positions with incorrect call spread profit targets."""

        if position_id:
            # Fix specific position
            try:
                positions = [Position.objects.get(id=position_id)]
            except Position.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Position {position_id} not found"))
                return []
        else:
            # Find all Senex Trident positions with profit targets
            positions = Position.objects.filter(
                strategy_type="senex_trident",
                profit_targets_created=True,
                lifecycle_state__in=["open_full", "open_partial"],
            ).select_related("user")

        # Filter to those with incorrect call_spread percentage
        affected = []
        for pos in positions:
            details = pos.profit_target_details or {}
            if "call_spread" in details:
                call_spread_info = details["call_spread"]
                current_percent = call_spread_info.get("percent")
                status = call_spread_info.get("status")

                # Skip if already filled
                if status == "filled":
                    continue

                # Check if percentage is incorrect (not 40)
                if current_percent and current_percent != 40:
                    affected.append(pos)

        return affected

    def _fix_position(self, position: Position) -> bool:
        """Fix a single position's call spread profit target."""
        self.stdout.write(f"\n🔄 Processing Position {position.id} ({position.symbol})")

        # Get opening trade
        opening_trade = Trade.objects.filter(position=position, trade_type="open").first()

        if not opening_trade:
            self.stdout.write(self.style.ERROR("   ❌ No opening trade found"))
            return False

        # Get current call spread details
        details = position.profit_target_details or {}
        call_spread_info = details.get("call_spread")

        if not call_spread_info:
            self.stdout.write(self.style.ERROR("   ❌ No call_spread in profit_target_details"))
            return False

        old_order_id = call_spread_info.get("order_id")
        old_percent = call_spread_info.get("percent")
        old_price = call_spread_info.get("target_price")

        self.stdout.write(
            f"   📍 Current: {old_percent}% profit @ ${old_price} (Order: {old_order_id})"
        )

        # Step 1: Cancel old order
        self.stdout.write("\n   🗑️  Step 1: Cancelling old order...")
        cancelled = self._cancel_order_sync(position.user, old_order_id)

        if cancelled:
            self.stdout.write(self.style.SUCCESS(f"      ✅ Cancelled order {old_order_id}"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"      ⚠️  Could not cancel order {old_order_id} (may already be filled/cancelled)"
                )
            )

        # Step 2: Create new profit target with correct percentage
        self.stdout.write("\n   🎯 Step 2: Creating new profit target...")

        # Try using service first (requires TradingSuggestion)
        service = OrderExecutionService(position.user)
        result = service.create_profit_targets_sync(
            position,
            opening_trade.broker_order_id,
            filter_spread_types=["call_spread"],
            preserve_existing=True,
        )

        # If service fails (likely due to missing TradingSuggestion), build order manually
        if not result or result.get("status") != "success":
            self.stdout.write(
                self.style.WARNING(
                    "      ⚠️  Service method failed, building order manually from position metadata"
                )
            )
            result = self._create_call_spread_manually(position)

        if result and result.get("status") == "success":
            targets = result.get("targets", [])
            call_target = next((t for t in targets if t["spread_type"] == "call_spread"), None)

            if call_target:
                new_order_id = call_target["order_id"]
                new_percent = call_target["profit_percentage"]
                new_price = call_target.get("target_price")

                self.stdout.write(
                    self.style.SUCCESS(
                        f"      ✅ Created new order: {new_percent}% profit @ ${new_price} (Order: {new_order_id})"
                    )
                )

                # Step 3: Update child_order_ids (remove old, add new)
                child_ids = opening_trade.child_order_ids or []
                if old_order_id in child_ids:
                    child_ids.remove(old_order_id)
                if new_order_id not in child_ids:
                    child_ids.append(new_order_id)
                opening_trade.child_order_ids = child_ids
                opening_trade.save()

                self.stdout.write(
                    self.style.SUCCESS(f"\n   ✅ Position {position.id} fixed successfully")
                )
                return True
            self.stdout.write(self.style.ERROR("      ❌ No call_spread in result"))
            return False
        error_msg = result.get("message", "Unknown error") if result else "No result"
        self.stdout.write(
            self.style.ERROR(f"      ❌ Failed to create profit target: {error_msg}")
        )
        return False

    def _create_call_spread_manually(self, position: Position) -> dict:
        """
        Create call spread profit target manually from position metadata.
        Fallback when TradingSuggestion is deleted.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(self._create_call_spread_async(position))
            return result
        finally:
            loop.close()

    async def _create_call_spread_async(self, position: Position) -> dict:
        """Build and submit call spread profit target order (pure async)."""
        try:
            # Get session
            session = await get_oauth_session(position.user)
            account = await get_primary_tastytrade_account(position.user)

            if not session or not account:
                return {"status": "error", "message": "Failed to get session/account"}

            # Get TastyTrade Account object
            tt_account = await Account.a_get(session, account.account_number)

            # Extract position data
            metadata = position.metadata or {}
            strikes = metadata.get("strikes", {})
            expiration = metadata.get("expiration")

            if not strikes.get("short_call") or not strikes.get("long_call"):
                return {"status": "error", "message": "Missing call strike data in metadata"}

            short_call_strike = Decimal(str(strikes.get("short_call")))
            long_call_strike = Decimal(str(strikes.get("long_call")))

            # Get original credit from profit_target_details
            details = position.profit_target_details or {}
            call_spread_info = details.get("call_spread", {})
            original_credit = Decimal(str(call_spread_info.get("original_credit", "0")))

            if original_credit == 0:
                return {
                    "status": "error",
                    "message": "Missing original_credit in profit_target_details",
                }

            # Calculate 40% profit target (buy back at 60% of credit)
            closing_multiplier = Decimal("0.60")  # 100% - 40% = 60%
            raw_price = original_credit * closing_multiplier
            target_price = round_option_price(raw_price, position.symbol)

            # Build OCC symbols
            exp_parts = expiration.split("-")
            exp_formatted = f"{exp_parts[0][2:]}{exp_parts[1]}{exp_parts[2]}"

            short_symbol = (
                f"{position.symbol:<6}{exp_formatted}C{int(short_call_strike * 1000):08d}"
            )
            long_symbol = f"{position.symbol:<6}{exp_formatted}C{int(long_call_strike * 1000):08d}"

            # Build order legs (closing a credit spread = BUY short, SELL long)
            legs = [
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=short_symbol,
                    quantity=1,
                    action=OrderAction.BUY_TO_CLOSE,
                ),
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=long_symbol,
                    quantity=1,
                    action=OrderAction.SELL_TO_CLOSE,
                ),
            ]

            # Create order
            # CRITICAL: TastyTrade uses price sign to indicate debit/credit
            # Negative price = debit (we pay to close)
            # Positive price = credit (we receive to open)
            new_order = NewOrder(
                time_in_force=OrderTimeInForce.GTC,
                order_type=OrderType.LIMIT,
                legs=legs,
                price=-abs(float(target_price)),  # NEGATIVE for debit (closing)
            )

            # Submit to TastyTrade
            response = await tt_account.a_place_order(session, new_order, dry_run=False)

            if not response or not hasattr(response, "order"):
                return {"status": "error", "message": "Failed to create order - no response"}

            order_id = str(response.order.id)

            # Update position.profit_target_details (use sync_to_async)
            details["call_spread"] = {
                "order_id": order_id,
                "target_price": float(target_price),
                "percent": 40,
                "original_credit": float(original_credit),
            }
            position.profit_target_details = details
            await sync_to_async(position.save)()

            return {
                "status": "success",
                "targets": [
                    {
                        "spread_type": "call_spread",
                        "order_id": order_id,
                        "profit_percentage": 40,
                        "target_price": float(target_price),
                    }
                ],
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _cancel_order_sync(self, user, order_id: str) -> bool:
        """Cancel an order synchronously using TastyTrade API."""
        from tastytrade import Account
        from tastytrade.utils import TastytradeError

        from services.core.data_access import get_oauth_session, get_primary_tastytrade_account

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            session = loop.run_until_complete(get_oauth_session(user))
            account = loop.run_until_complete(get_primary_tastytrade_account(user))

            if not session or not account:
                self.stdout.write("      ❌ Failed to get session/account")
                return False

            tt_account = loop.run_until_complete(Account.a_get(session, account.account_number))
            loop.run_until_complete(tt_account.a_delete_order(session, int(order_id)))

            return True

        except TastytradeError as e:
            if "not found" in str(e).lower() or "404" in str(e):
                # Already filled or cancelled
                return True
            self.stdout.write(f"      ❌ TastyTrade error: {e}")
            return False
        except Exception as e:
            self.stdout.write(f"      ❌ Error: {e}")
            return False
        finally:
            loop.close()
