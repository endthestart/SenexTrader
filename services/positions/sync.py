"""Position synchronization service for importing and managing TastyTrade positions."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone as dj_timezone

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.logging import get_logger
from services.orders.history import OrderHistoryService
from services.positions.lifecycle.leg_matcher import LegMatcher
from services.positions.lifecycle.pnl_calculator import PositionPnLCalculator
from trading.models import Position

User = get_user_model()
logger = get_logger(__name__)


class PositionSyncService:
    """Import and synchronize all positions from TastyTrade account."""

    def __init__(self, order_history_service=None):
        """
        Initialize PositionSyncService with optional dependency injection.

        Args:
            order_history_service: Optional OrderHistoryService instance for dependency injection.
                                  If None, a new instance will be created. Useful for testing and
                                  avoiding tight coupling.
        """
        self.order_history_service = order_history_service or OrderHistoryService()

    async def sync_all_positions(self, user: User) -> dict[str, object]:
        """
        Import all TastyTrade positions and categorize them.

        Returns:
            Dict with sync results including counts and any errors
        """
        import time

        start_time = time.time()

        logger.info(
            "🔄 Starting position sync for user %s (two-tier: app-managed + unmanaged)",
            user.id,
        )

        try:
            account = await self._get_primary_account(user)
            if not account:
                logger.warning("User %s: No primary trading account found", user.id)
                return {"error": "No primary trading account found"}

            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(user)
            if not session:
                return {"error": "Unable to obtain TastyTrade session"}

            # Sync order history first (provides data for position reconstruction)
            logger.info("User %s: Syncing order history (30 days back)...", user.id)
            order_start = time.time()
            order_sync_result = await self.order_history_service.sync_order_history(
                account, days_back=30
            )
            order_duration = time.time() - order_start
            logger.info(
                "User %s: Order history sync complete - %s orders synced [%.2fs]",
                user.id,
                order_sync_result["orders_synced"],
                order_duration,
            )

            # Get raw positions from TastyTrade (individual legs, not grouped)
            logger.info("User %s: Fetching positions from TastyTrade API...", user.id)
            fetch_start = time.time()
            from tastytrade import Account

            tt_account = await Account.a_get(session, account.account_number)
            raw_positions = await tt_account.a_get_positions(session, include_marks=True)
            fetch_duration = time.time() - fetch_start
            logger.info(
                "User %s: Fetched %s individual position legs from TastyTrade [%.2fs]",
                user.id,
                len(raw_positions) if raw_positions else 0,
                fetch_duration,
            )

            if not raw_positions:
                return {
                    "success": True,
                    "positions_found": 0,
                    "imported": 0,
                    "updated": 0,
                }

            # TWO-TIER SYNC APPROACH:
            # 1. App-managed positions: use cached orders as source of truth
            # 2. Unmanaged positions: use TastyTrade grouping (existing logic)

            imported_count = 0
            updated_count = 0
            errors = []

            # Tier 1: Sync app-managed positions using cached orders
            logger.info(
                "User %s: Tier 1 - syncing app-managed positions from cached orders...", user.id
            )
            tier1_start = time.time()
            app_managed_updated = await self._sync_app_managed_from_orders(
                user, account, raw_positions
            )
            tier1_duration = time.time() - tier1_start
            updated_count += app_managed_updated
            logger.info(
                "User %s: Tier 1 complete - updated %s app-managed positions [%.2fs]",
                user.id,
                app_managed_updated,
                tier1_duration,
            )

            # Tier 2: Sync unmanaged positions using TastyTrade grouping
            logger.info(
                "User %s: Tier 2 - syncing unmanaged positions via TastyTrade grouping...", user.id
            )
            tier2_start = time.time()
            # Group positions by underlying symbol (for multi-leg spreads)
            tt_positions = await self._group_positions_by_underlying(raw_positions)
            group_duration = time.time() - tier2_start

            for tt_position in tt_positions:
                try:
                    # Skip if this is an app-managed position (already synced above)
                    symbol = tt_position.get("symbol", "")
                    existing = await Position.objects.filter(
                        user=user,
                        trading_account=account,
                        symbol=symbol,
                        is_app_managed=True,
                    ).afirst()

                    if existing:
                        # Already synced by app-managed logic
                        logger.debug(f"Skipping {symbol} - already synced as app-managed position")
                        continue

                    created = await self._sync_single_position(user, account, tt_position)
                    if created:
                        imported_count += 1
                    else:
                        updated_count += 1
                except Exception as e:
                    pos_id = tt_position.get("id", "unknown")
                    errors.append(f"Error syncing position {pos_id}: {e!s}")
                    logger.error(f"Error syncing position: {e}", exc_info=True)

            tier2_duration = time.time() - tier2_start
            logger.info(
                "User %s: Tier 2 complete - imported %s, updated %s unmanaged positions [%.2fs (grouping: %.2fs)]",
                user.id,
                imported_count,
                updated_count - app_managed_updated,
                tier2_duration,
                group_duration,
            )

            # Check order status for pending positions (cancelled/rejected orders)
            logger.info("User %s: Checking pending order statuses...", user.id)
            pending_start = time.time()
            closed_pending = await self._sync_pending_order_statuses(user, account, session)
            pending_duration = time.time() - pending_start
            logger.info(
                "User %s: Closed %s pending positions [%.2fs]",
                user.id,
                closed_pending,
                pending_duration,
            )

            # Close positions that exist locally but not at broker (quantity=0)
            logger.info("User %s: Checking for positions closed at broker...", user.id)
            broker_close_start = time.time()
            closed_at_broker = await self._close_positions_not_at_broker(
                user, account, raw_positions
            )
            broker_close_duration = time.time() - broker_close_start
            logger.info(
                "User %s: Closed %s positions not found at broker [%.2fs]",
                user.id,
                closed_at_broker,
                broker_close_duration,
            )

            total_duration = time.time() - start_time
            result = {
                "success": True,
                "positions_found": len(tt_positions),
                "imported": imported_count,
                "updated": updated_count,
                "closed_pending": closed_pending,
                "closed_at_broker": closed_at_broker,
                "timestamp": dj_timezone.now().isoformat(),
            }

            if errors:
                result["errors"] = errors

            logger.info(
                "✅ Position sync complete for user %s: imported=%s, updated=%s, closed_pending=%s, closed_broker=%s "
                "(total: %.2fs, breakdown: order_history=%.2fs, fetch=%.2fs, tier1=%.2fs, tier2=%.2fs, pending=%.2fs, broker_close=%.2fs)",
                user.id,
                imported_count,
                updated_count,
                closed_pending,
                closed_at_broker,
                total_duration,
                order_duration,
                fetch_duration,
                tier1_duration,
                tier2_duration,
                pending_duration,
                broker_close_duration,
            )

            # After successful sync, broadcast to connected clients
            if result.get("success"):
                try:
                    from streaming.services.stream_manager import GlobalStreamManager

                    stream_manager = await GlobalStreamManager.get_user_manager(user.id)

                    await stream_manager._broadcast(
                        "position_sync_complete",
                        {
                            "positions_updated": result.get("updated", 0),
                            "positions_imported": result.get("imported", 0),
                            "timestamp": result.get("timestamp"),
                        },
                    )
                    logger.info(f"Broadcasted position sync completion to user {user.id}")
                except Exception as e:
                    # Don't fail sync if broadcast fails
                    logger.warning(f"Failed to broadcast position sync: {e}")

            return result

        except Exception as e:
            logger.error(f"Position sync failed for user {user.id}: {e}", exc_info=True)
            return {"error": str(e)}

    async def _group_positions_by_underlying(self, raw_positions: list) -> list[dict]:
        """
        Group individual position legs by underlying symbol.

        This is used for unmanaged positions where we don't have order history.
        For app-managed positions, use _sync_app_managed_from_orders() instead.

        Args:
            raw_positions: Individual legs from TastyTrade

        Returns:
            List of grouped position dicts
        """
        try:
            # Group positions by underlying symbol (for multi-leg spreads)
            grouped_positions = {}

            for pos in raw_positions:
                underlying = getattr(pos, "underlying_symbol", getattr(pos, "symbol", None))

                if underlying not in grouped_positions:
                    grouped_positions[underlying] = {
                        "underlying_symbol": underlying,
                        "legs": [],
                        "total_quantity": 0,
                        "total_unrealized_pnl": Decimal("0"),
                    }

                # Extract leg data
                leg_data = {
                    # Full OCC symbol for options
                    "symbol": getattr(pos, "symbol", None),
                    "instrument_type": str(getattr(pos, "instrument_type", "unknown")),
                    "quantity": int(getattr(pos, "quantity", 0)),
                    "quantity_direction": getattr(pos, "quantity_direction", ""),
                    "average_open_price": float(getattr(pos, "average_open_price", 0)),
                    "close_price": float(getattr(pos, "close_price", 0)),
                    "multiplier": getattr(pos, "multiplier", 100),
                    "cost_effect": getattr(pos, "cost_effect", ""),
                    "mark_price": (
                        float(getattr(pos, "mark_price", 0))
                        if getattr(pos, "mark_price", None)
                        else None
                    ),
                }

                # Add to legs
                grouped_positions[underlying]["legs"].append(leg_data)

                # Note: total_quantity will be calculated after all legs are added
                # For multi-leg positions (spreads), quantity = min(abs(leg quantities))
                # This is calculated below during position_data construction

                # Calculate P&L for this leg using centralized calculator
                avg_price = getattr(pos, "average_open_price", None)
                # Prefer mark_price (live) over close_price (can be stale)
                mark_price = getattr(pos, "mark_price", None)
                close_price = getattr(pos, "close_price", None)
                current_price = mark_price if mark_price is not None else close_price
                quantity = getattr(pos, "quantity", 0)
                quantity_direction = getattr(pos, "quantity_direction", "").lower()

                if avg_price and current_price and quantity:
                    multiplier = getattr(pos, "multiplier", 100)

                    # Use PositionPnLCalculator for direction-aware P&L calculation
                    leg_pnl = PositionPnLCalculator.calculate_leg_pnl(
                        avg_price=avg_price,
                        current_price=current_price,
                        quantity=quantity,
                        quantity_direction=quantity_direction,
                        multiplier=multiplier,
                    )

                    grouped_positions[underlying]["total_unrealized_pnl"] += leg_pnl

            # Convert grouped positions to list format
            position_data = []
            for underlying, group_data in grouped_positions.items():
                legs = group_data["legs"]

                # Calculate spread quantity: min absolute leg quantity
                # For Senex Trident: 2 put spreads + 1 call = 6 legs (quantities: -2, 2, -2, 2, -1, 1)
                # For single spread: [-1, 1] -> 1
                spread_quantity = min(abs(leg["quantity"]) for leg in legs) if legs else 0

                # Calculate average price from legs
                # For spreads: net credit/debit per spread
                # For single leg: just the leg's average price
                avg_price = None
                if len(legs) == 1:
                    # Single leg: use its average_open_price directly
                    avg_price = legs[0]["average_open_price"]
                else:
                    # Multi-leg: calculate net price per spread
                    # Sum (credit - debit) across all legs, divide by spread count
                    net_value = Decimal("0")

                    for leg in legs:
                        leg_price = Decimal(str(leg["average_open_price"]))
                        leg_qty = abs(leg["quantity"])
                        multiplier = leg["multiplier"]

                        # Credits are positive, debits are negative
                        if leg["quantity"] < 0:  # Short leg = credit
                            net_value += leg_price * leg_qty * multiplier
                        else:  # Long leg = debit
                            net_value -= leg_price * leg_qty * multiplier

                    # Average price per spread (per 100 shares for options)
                    if spread_quantity > 0:
                        avg_price = abs(net_value / (spread_quantity * 100))

                position_data.append(
                    {
                        "symbol": underlying,
                        "quantity": spread_quantity,
                        "average_price": float(avg_price) if avg_price else None,
                        "unrealized_pnl": float(group_data["total_unrealized_pnl"]),
                        "close_price": None,  # Not meaningful for multi-leg
                        "position_type": "spread" if len(legs) > 1 else "single",
                        "legs": legs,
                    }
                )

            logger.info(
                f"Fetched {len(position_data)} grouped positions "
                f"({len(raw_positions)} individual legs)"
            )
            return position_data

        except Exception as e:
            logger.error(f"Error fetching positions from TastyTrade: {e}", exc_info=True)
            return []

    async def _sync_single_position(
        self, user: User, account: TradingAccount, tt_position: dict
    ) -> bool:
        """
        Sync a single position from TastyTrade.

        IMPORTANT: This method preserves the is_app_managed status
        for existing positions. Only NEW positions will have their
        is_app_managed status set based on categorization.
        This prevents sync from overwriting app-managed positions.

        Returns:
            True if position was created (new), False if updated
        """
        # Use symbol as unique identifier since TastyTrade doesn't provide position IDs
        symbol = tt_position.get("symbol", "UNKNOWN")
        if not symbol or symbol == "UNKNOWN":
            logger.warning(f"Position missing symbol, skipping: {tt_position}")
            return False

        # Check if position already exists using symbol + account
        existing_position = await Position.objects.filter(
            user=user, trading_account=account, symbol=symbol
        ).afirst()

        if existing_position:
            logger.info(
                f"Found existing position {existing_position.id} for {symbol}, "
                f"is_app_managed={existing_position.is_app_managed}, "
                f"strategy_type={existing_position.strategy_type}"
            )
        else:
            logger.info(f"No existing position found for {symbol}, will create new")

        is_app_managed = await self._categorize_position(tt_position)

        # Epic 28 Task 009: Detect instrument type from position legs
        legs = tt_position.get("legs", [])
        instrument_type = "Equity Option"  # Default for options
        strategy_type = "external"  # Default for broker-discovered positions

        # Check if this is a stock position (single leg with instrument_type="Equity")
        if len(legs) == 1:
            leg_instrument_type = legs[0].get("instrument_type", "unknown")
            if leg_instrument_type == "Equity":
                instrument_type = "Equity"
                strategy_type = "stock_holding"  # Stock positions get stock_holding strategy
                logger.info(f"Detected stock position for {symbol}: {instrument_type}")
        elif len(legs) > 1:
            # Multi-leg: check if all legs are equity options
            if all(leg.get("instrument_type") == "Equity Option" for leg in legs):
                instrument_type = "Equity Option"

        position_data = {
            "user": user,
            "trading_account": account,
            "symbol": symbol,
            "quantity": int(tt_position.get("quantity", 0)),
            "avg_price": self._safe_decimal(tt_position.get("average_price")),
            "unrealized_pnl": self._safe_decimal(tt_position.get("unrealized_pnl")),
            "instrument_type": instrument_type,  # Epic 28 Task 009
            "strategy_type": strategy_type,
            "lifecycle_state": "open_full",  # All imported positions are open
        }

        # Only set is_app_managed for NEW positions, not existing ones
        if not existing_position:
            position_data["is_app_managed"] = is_app_managed

        # Add metadata with comprehensive broker data
        position_data["metadata"] = {
            "legs": tt_position.get("legs", []),  # NEW: Store all position legs
            "tastytrade_data": {
                "position_type": tt_position.get("position_type"),
                "expiration_date": (
                    str(tt_position.get("expiration_date"))
                    if tt_position.get("expiration_date")
                    else None
                ),
                "strike_price": (
                    str(tt_position.get("strike_price"))
                    if tt_position.get("strike_price")
                    else None
                ),
                "option_type": tt_position.get("option_type"),
                "close_price": (
                    str(tt_position.get("close_price")) if tt_position.get("close_price") else None
                ),
            },
            "sync_timestamp": dj_timezone.now().isoformat(),
            "sync_source": "tastytrade_api",
        }

        # Calculate DTE and check for attention flags
        needs_attention_reason = await self._check_needs_attention(tt_position)
        if needs_attention_reason:
            # Store in metadata since needs_attention_reason field was removed
            if "metadata" not in position_data:
                position_data["metadata"] = {}
            position_data["metadata"]["needs_attention_reason"] = needs_attention_reason

        # NEW: Reconstruct position from cached orders if available
        if existing_position and existing_position.is_app_managed:
            # For app-managed positions, use cached orders as source of truth
            logger.info(
                f"Reconstructing app-managed position {existing_position.id} from cached orders"
            )
            try:
                corrected_data = await self.order_history_service.reconstruct_position_from_orders(
                    existing_position
                )
                if corrected_data:
                    # Update number_of_spreads and quantity from cached orders
                    if "number_of_spreads" in corrected_data:
                        old_spreads = existing_position.number_of_spreads
                        new_spreads = corrected_data["number_of_spreads"]
                        if old_spreads != new_spreads:
                            logger.warning(
                                f"Position {existing_position.id} spread count correction: "
                                f"{old_spreads} -> {new_spreads} (from cached orders)"
                            )
                            existing_position.number_of_spreads = new_spreads

                    if "quantity" in corrected_data:
                        old_qty = existing_position.quantity
                        new_qty = corrected_data["quantity"]
                        if old_qty != new_qty:
                            logger.warning(
                                f"Position {existing_position.id} quantity correction: "
                                f"{old_qty} -> {new_qty} (from cached orders)"
                            )
                            existing_position.quantity = new_qty

                    # Merge corrected metadata
                    if "metadata" in corrected_data:
                        existing_metadata = existing_position.metadata or {}
                        existing_metadata.update(corrected_data["metadata"])
                        existing_position.metadata = existing_metadata

                    logger.info(
                        f"Position {existing_position.id} reconstructed: "
                        f"spreads={existing_position.number_of_spreads}, "
                        f"quantity={existing_position.quantity}"
                    )

                    # Clear any previous reconstruction failure flag
                    if existing_position.metadata and existing_position.metadata.get(
                        "reconstruction_failed"
                    ):
                        del existing_position.metadata["reconstruction_failed"]

            except Exception as e:
                # Log reconstruction failure with full context for monitoring
                logger.error(
                    f"Position reconstruction failed for position {existing_position.id} "
                    f"(symbol={existing_position.symbol}, user={existing_position.user_id}, "
                    f"broker_order_ids={existing_position.broker_order_ids}): {e}",
                    exc_info=True,
                    extra={
                        "position_id": existing_position.id,
                        "symbol": existing_position.symbol,
                        "user_id": existing_position.user_id,
                        "broker_order_ids": existing_position.broker_order_ids,
                        "error_type": "position_reconstruction_failure",
                    },
                )

                # Mark position as having reconstruction failure
                existing_position.metadata = existing_position.metadata or {}
                existing_position.metadata["reconstruction_failed"] = True
                existing_position.metadata["reconstruction_error"] = str(e)
                existing_position.metadata["reconstruction_failed_at"] = (
                    dj_timezone.now().isoformat()
                )

                # Continue with sync using TastyTrade data, but flag for manual review

        if existing_position:
            # Update existing position
            protected_fields = [
                "user",
                "trading_account",
                "is_app_managed",  # Never overwrite app-managed status
                "strategy_type",  # Preserve strategy type for app-managed positions
                "profit_targets_created",  # Protect profit target tracking
                "profit_target_details",  # Protect profit target order details
                "initial_risk",  # Preserve calculated risk amounts
                "spread_width",  # Keep original spread width
                "number_of_spreads",  # Keep original spread count (use cached orders)
                "quantity",  # Preserve quantity (use cached orders for app-managed positions)
                "opening_price_effect",  # Preserve credit/debit status
            ]

            for field, value in position_data.items():
                if field == "metadata":
                    # Merge metadata instead of replacing
                    existing_metadata = existing_position.metadata or {}
                    # Preserve critical existing metadata
                    merged_metadata = existing_metadata.copy()

                    # CRITICAL: Preserve app-managed metadata fields
                    # - suggestion_id: Required for profit target calculations
                    # - strikes: Used for conflict detection
                    # - streaming_pricing: Needed for pricing
                    # - strategy_type, is_complete_trident, expiration: Strategy data

                    if existing_position.is_app_managed:
                        # App-managed: ONLY update sync metadata
                        merged_metadata["sync_timestamp"] = value.get("sync_timestamp")
                        merged_metadata["sync_source"] = value.get("sync_source")

                        # Update legs from broker to ensure Greeks have latest data
                        # Critical: Trade.order_legs may not have all data
                        if value.get("legs"):
                            merged_metadata["legs"] = value.get("legs", [])

                        # Add tastytrade_data if missing
                        if "tastytrade_data" not in merged_metadata:
                            merged_metadata["tastytrade_data"] = value.get("tastytrade_data", {})
                    else:
                        # External positions: Update from broker (source of truth)
                        merged_metadata["legs"] = value.get("legs", [])
                        merged_metadata["tastytrade_data"] = value.get("tastytrade_data", {})
                        merged_metadata["sync_timestamp"] = value.get("sync_timestamp")
                        merged_metadata["sync_source"] = value.get("sync_source")

                    setattr(existing_position, field, merged_metadata)
                elif field not in protected_fields:
                    # Only update non-protected fields
                    old_value = getattr(existing_position, field, None)
                    if old_value != value:
                        # Allow updates when:
                        # 1. Old value is None (one-time population)
                        # 2. Old value is not None and differs (normal update)
                        logger.info(
                            f"Position {existing_position.id}: Updating {field} "
                            f"from {old_value} to {value}"
                        )
                    setattr(existing_position, field, value)

            await existing_position.asave()
            has_legs = bool(existing_position.metadata and existing_position.metadata.get("legs"))
            logger.info(
                f"Updated position {existing_position.id}: "
                f"strategy_type={existing_position.strategy_type}, "
                f"has_legs_in_metadata={has_legs}"
            )
            return False
        # Create new position
        new_position = await Position.objects.acreate(**position_data)
        logger.info(f"Created new position {new_position.id} for {symbol}")
        return True

    async def _sync_pending_order_statuses(self, user: User, account: TradingAccount, session):
        """
        Check TastyTrade order status for any local pending positions.
        Mark positions as closed if their orders were cancelled/rejected.

        This handles the case where orders are cancelled in TastyTrade but the local
        position records remain as "pending" because cancelled orders never appear
        in get_positions() (they were never filled).

        Returns:
            int: Number of pending positions closed
        """
        try:
            from trading.models import Trade

            # Get all pending positions locally
            pending_positions = [
                position
                async for position in Position.objects.filter(
                    user=user,
                    trading_account=account,
                    lifecycle_state="pending_entry",
                ).prefetch_related("trades")
            ]

            if not pending_positions:
                logger.info(f"No pending positions found for user {user.id}")
                return 0

            logger.info(
                f"Found {len(pending_positions)} pending positions to check " f"for user {user.id}"
            )

            # Get live orders from TastyTrade (past 24 hours)
            from tastytrade import Account

            tt_account = await Account.a_get(session, account.account_number)
            live_orders = await tt_account.a_get_live_orders(session)

            # Create lookup map: broker_order_id -> order_status
            # Normalize to strings to ensure matching
            order_status_map = {str(order.id): order.status.value for order in live_orders}

            # DEBUG: Log order IDs for troubleshooting
            if live_orders:
                order_ids_str = ", ".join(str(o.id) for o in live_orders[:10])
                logger.info(
                    f"Retrieved {len(live_orders)} live orders from TastyTrade. "
                    f"First 10 IDs: {order_ids_str}"
                )
            else:
                logger.info(f"Retrieved {len(live_orders)} live orders from TastyTrade")

            closed_count = 0
            for position in pending_positions:
                # Get broker_order_id from first trade (avoid lambda closure bug)
                first_trade = await Trade.objects.filter(position=position).afirst()
                if not first_trade or not first_trade.broker_order_id:
                    logger.warning(
                        f"Position {position.id} has no trade or " f"broker_order_id, skipping"
                    )
                    continue

                # Normalize broker_order_id to string for comparison
                broker_order_id = str(first_trade.broker_order_id)
                order_status = order_status_map.get(broker_order_id)

                logger.info(
                    f"Checking position {position.id}: "
                    f"broker_order_id={broker_order_id} "
                    f"(type={type(broker_order_id).__name__}), "
                    f"order_status={order_status}, "
                    f"trade_status={first_trade.status}"
                )

                # If order is explicitly in a terminal state, close position
                # Otherwise, if ambiguous (not in live orders), leave pending
                terminal_statuses = ["Cancelled", "Rejected", "Expired"]
                if order_status in terminal_statuses:
                    position.status = "closed"
                    position.metadata = position.metadata or {}
                    reason = f"order_{order_status.lower()}"
                    position.metadata["closure_reason"] = reason
                    position.metadata["closure_timestamp"] = dj_timezone.now().isoformat()
                    await position.asave()

                    # Also update trade status
                    if first_trade:
                        first_trade.status = order_status.lower()
                        await first_trade.asave()

                    closed_count += 1
                    logger.info(
                        f"Closed pending position {position.id} "
                        f"(symbol={position.symbol}): "
                        f"Order {broker_order_id} status is '{order_status}'."
                    )
                elif not order_status:
                    # Ambiguous: order not in live list. Could be filled/cancelled
                    # Fallback to checking order history directly
                    try:
                        order_history = await tt_account.a_get_order(session, broker_order_id)
                        history_status = (
                            order_history.status.value.lower()
                            if hasattr(order_history.status, "value")
                            else str(order_history.status).lower()
                        )

                        if history_status in ["filled", "completed"]:
                            logger.info(
                                f"Position {position.id} "
                                f"(order {broker_order_id}) found in history as "
                                f"'{history_status}'. Marking as open."
                            )
                            position.lifecycle_state = "open_full"
                            await position.asave()

                            if first_trade:
                                first_trade.status = "filled"
                                first_trade.filled_at = (
                                    order_history.filled_at
                                    if hasattr(order_history, "filled_at")
                                    else dj_timezone.now()
                                )
                                await first_trade.asave()

                        elif history_status in ["cancelled", "rejected", "expired"]:
                            logger.info(
                                f"Position {position.id} "
                                f"(order {broker_order_id}) found in history as "
                                f"'{history_status}'. Marking as closed."
                            )
                            position.lifecycle_state = "closed"
                            position.metadata = position.metadata or {}
                            reason = f"order_{history_status.lower()}"
                            position.metadata["closure_reason"] = reason
                            await position.asave()

                            if first_trade:
                                first_trade.status = history_status.lower()
                                await first_trade.asave()
                            closed_count += 1
                        else:
                            logger.warning(
                                f"Position {position.id} "
                                f"(order {broker_order_id}) has ambiguous "
                                f"history status: '{history_status}'. "
                                f"Leaving as pending."
                            )

                    except Exception as e:
                        logger.error(
                            f"Could not fetch order history for "
                            f"{broker_order_id}: {e}. Leaving as pending."
                        )
                else:
                    # Order is live but not terminal, keep it pending
                    logger.debug(
                        f"Position {position.id} order {broker_order_id} "
                        f"status is '{order_status}', keeping as pending."
                    )

            logger.info(
                f"Closed {closed_count} pending positions with "
                f"cancelled/expired orders for user {user.id}"
            )
            return closed_count

        except Exception as e:
            logger.error(
                f"Error syncing pending order statuses for user {user.id}: {e}",
                exc_info=True,
            )
            return 0

    async def _close_positions_not_at_broker(
        self, user: User, account: TradingAccount, raw_positions: list
    ) -> int:
        """
        Close local positions that don't exist at broker (quantity=0 at broker).

        This handles cases where:
        - Positions were closed manually at broker
        - Options expired and auto-closed
        - Partial closes resulted in quantity=0 but local DB still shows quantity>0

        Args:
            user: User to check positions for
            account: Trading account
            raw_positions: Raw positions from broker (from tt_account.a_get_positions())

        Returns:
            int: Number of positions closed
        """
        try:
            # Build set of underlying symbols that exist at broker
            broker_symbols = set()
            for pos in raw_positions:
                underlying = getattr(pos, "underlying_symbol", getattr(pos, "symbol", None))
                if underlying:
                    broker_symbols.add(underlying)

            logger.debug(
                f"User {user.id}: Broker has positions in {len(broker_symbols)} symbols: "
                f"{sorted(broker_symbols)}"
            )

            # Get all local positions that are not fully closed
            local_positions = [
                position
                async for position in Position.objects.filter(
                    user=user,
                    trading_account=account,
                    lifecycle_state__in=["open_full", "open_partial", "closing"],
                )
            ]

            if not local_positions:
                logger.debug(f"User {user.id}: No local open/closing positions to check")
                return 0

            logger.info(
                f"User {user.id}: Checking {len(local_positions)} local positions "
                f"against broker positions"
            )

            closed_count = 0
            for position in local_positions:
                # If position symbol exists at broker, skip (it's still open)
                if position.symbol in broker_symbols:
                    logger.debug(
                        f"Position {position.id} ({position.symbol}): "
                        f"Still exists at broker, keeping {position.lifecycle_state}"
                    )
                    continue

                # Position doesn't exist at broker - close it
                logger.info(
                    f"Position {position.id} ({position.symbol}, qty={position.quantity}): "
                    f"Not found at broker (quantity=0), marking as closed"
                )

                position.lifecycle_state = "closed"
                position.quantity = 0
                position.unrealized_pnl = Decimal("0")  # No more unrealized P&L when closed

                # Set closed_at timestamp if not already set
                if not position.closed_at:
                    position.closed_at = dj_timezone.now()

                # Add closure metadata
                position.metadata = position.metadata or {}
                position.metadata["closure_reason"] = "closed_at_broker"
                position.metadata["closure_detected_at"] = dj_timezone.now().isoformat()
                position.metadata["closure_method"] = "position_sync_detection"

                await position.asave()
                closed_count += 1

                logger.info(
                    f"✅ Closed position {position.id} ({position.symbol}): "
                    f"realized_pnl=${position.total_realized_pnl}, "
                    f"closed_at={position.closed_at.isoformat()}"
                )

            if closed_count > 0:
                logger.info(
                    f"User {user.id}: Closed {closed_count} positions that were "
                    f"no longer at broker"
                )

            return closed_count

        except Exception as e:
            logger.error(
                f"Error closing positions not at broker for user {user.id}: {e}",
                exc_info=True,
            )
            return 0

    async def _categorize_position(self, tt_position: dict) -> bool:
        """
        Determine if position is app-managed or external.

        App-managed positions are those created by our trading suggestions.
        External positions are opened outside the app.
        """
        # Check if this position matches any executed TradingSuggestion
        tt_position.get("symbol", "")

        # For options positions, we need more complex matching
        # For now, default to external for new positions
        # This ensures we don't accidentally mark external positions as app-managed
        # Existing app-managed positions will preserve their status (handled above)
        return False

    async def _check_needs_attention(self, tt_position: dict) -> str | None:
        """
        Check if position needs user attention and return reason.

        Positions need attention if:
        - 7 DTE or less for options
        - Unusual P&L swings
        - Partial fills (would need order data to determine this)
        """
        reasons = []

        # Check DTE for options
        expiration_date = tt_position.get("expiration_date")
        if expiration_date:
            try:
                if isinstance(expiration_date, str):
                    from datetime import datetime

                    exp_date = datetime.fromisoformat(expiration_date.replace("Z", "+00:00")).date()
                else:
                    exp_date = expiration_date

                dte = (exp_date - dj_timezone.now().date()).days
                if dte <= 7:
                    reasons.append(f"Low DTE: {dte} days to expiration")
            except Exception as e:
                logger.warning(f"Error calculating DTE: {e}")

        # Check for large unrealized losses (example threshold)
        unrealized_pnl = tt_position.get("unrealized_pnl")
        if unrealized_pnl and float(unrealized_pnl) < -1000:
            reasons.append(f"Large unrealized loss: ${unrealized_pnl}")

        return "; ".join(reasons) if reasons else None

    def calculate_dte(self, expiration_date) -> int | None:
        """Calculate days to expiration for a position."""
        if not expiration_date:
            return None

        try:
            if isinstance(expiration_date, str):
                from datetime import datetime

                exp_date = datetime.fromisoformat(expiration_date.replace("Z", "+00:00")).date()
            else:
                exp_date = expiration_date

            return (exp_date - dj_timezone.now().date()).days
        except Exception as e:
            logger.error(f"Error calculating DTE: {e}", exc_info=True)
            return None

    async def _sync_app_managed_from_orders(
        self, user: User, account: TradingAccount, raw_positions: list
    ) -> int:
        """
        Sync app-managed positions using cached orders as source of truth.

        This method solves the problem of TastyTrade grouping all positions
        by underlying symbol, which merges multiple positions with the same
        underlying (e.g., 5 QQQ positions) into one.

        For app-managed positions:
        1. Load from database using broker_order_ids
        2. Get opening order from cached_orders for structure
        3. Find matching legs in raw_positions for current prices
        4. Update only market data (prices, P&L), not structure

        Args:
            user: User object
            account: TradingAccount object
            raw_positions: Individual legs from TastyTrade (not grouped)

        Returns:
            Number of app-managed positions updated
        """
        # Get all app-managed positions for this user/account
        app_managed_positions = await self._load_app_managed_positions(user, account)
        if not app_managed_positions:
            return 0

        # Prepare batch data structures to avoid N+1 queries
        sync_context = await self._prepare_sync_context(app_managed_positions, raw_positions)

        # Sync each position
        updated_count = 0
        for position in app_managed_positions:
            try:
                if await self._sync_single_app_managed_position(position, account, sync_context):
                    updated_count += 1
            except Exception as e:
                logger.error(
                    f"Error syncing app-managed position {position.id}: {e}",
                    exc_info=True,
                )

        logger.info(f"Updated {updated_count} app-managed positions from cached orders")
        return updated_count

    async def _load_app_managed_positions(
        self, user: User, account: TradingAccount
    ) -> list[Position]:
        """Load all app-managed positions for this user/account."""
        positions = [
            position
            async for position in Position.objects.filter(
                user=user,
                trading_account=account,
                is_app_managed=True,
                lifecycle_state__in=["pending_entry", "open_full", "open_partial"],
            )
        ]

        if not positions:
            logger.info(f"No app-managed positions found for user {user.id}")
            return []

        logger.info(f"Syncing {len(positions)} app-managed positions using cached orders")
        return positions

    async def _prepare_sync_context(
        self, app_managed_positions: list[Position], raw_positions: list
    ) -> dict:
        """
        Prepare batch data structures for efficient sync.

        Returns dict with:
        - legs_by_symbol: OCC symbol -> leg data lookup map
        - cached_orders_map: broker_order_id -> CachedOrder lookup map
        - preloaded_orders: position_id -> filled orders lookup map
        - leg_matcher: LegMatcher utility instance
        - pnl_calculator: PositionPnLCalculator utility instance
        """
        # Build leg lookup map
        legs_by_symbol = self._build_legs_lookup_map(raw_positions)

        # Batch load cached opening orders
        cached_orders_map = await self._batch_load_cached_orders(app_managed_positions)

        # Batch load filled profit target orders
        preloaded_orders = await self._batch_load_filled_orders(app_managed_positions)

        return {
            "legs_by_symbol": legs_by_symbol,
            "cached_orders_map": cached_orders_map,
            "preloaded_orders": preloaded_orders,
            "leg_matcher": LegMatcher(legs_by_symbol),
            "pnl_calculator": PositionPnLCalculator(),
        }

    def _build_legs_lookup_map(self, raw_positions: list) -> dict[str, dict]:
        """Build lookup map from OCC symbol to leg data."""
        legs_by_symbol = {}
        for pos in raw_positions:
            symbol = getattr(pos, "symbol", None)
            if symbol:
                legs_by_symbol[symbol] = {
                    "symbol": symbol,
                    "quantity": int(getattr(pos, "quantity", 0)),
                    "quantity_direction": getattr(pos, "quantity_direction", ""),
                    "average_open_price": float(getattr(pos, "average_open_price", 0)),
                    "close_price": float(getattr(pos, "close_price", 0)),
                    "mark_price": (
                        float(getattr(pos, "mark_price", 0))
                        if getattr(pos, "mark_price", None)
                        else None
                    ),
                    "multiplier": getattr(pos, "multiplier", 100),
                    "instrument_type": str(getattr(pos, "instrument_type", "unknown")),
                }
        return legs_by_symbol

    async def _batch_load_cached_orders(
        self, app_managed_positions: list[Position]
    ) -> dict[str, object]:
        """Batch load all opening orders to avoid N+1 queries."""
        from trading.models import CachedOrder

        all_broker_order_ids = [
            pos.broker_order_ids[0]
            for pos in app_managed_positions
            if pos.broker_order_ids and len(pos.broker_order_ids) > 0
        ]

        if not all_broker_order_ids:
            return {}

        cached_orders_map = {
            order.broker_order_id: order
            async for order in CachedOrder.objects.filter(broker_order_id__in=all_broker_order_ids)
        }

        logger.debug(
            f"Batch loaded {len(cached_orders_map)} cached orders for "
            f"{len(all_broker_order_ids)} positions"
        )
        return cached_orders_map

    async def _sync_single_app_managed_position(
        self, position: Position, account: TradingAccount, sync_context: dict
    ) -> bool:
        """
        Sync a single app-managed position using cached orders.

        Returns:
            True if position was updated, False if skipped
        """
        # Extract opening order
        opening_order = self._get_opening_order(position, sync_context["cached_orders_map"])
        if not opening_order:
            logger.warning(f"Position {position.id} has no cached opening order, skipping")
            return False

        order_legs = opening_order.order_data.get("legs", [])
        if not order_legs:
            logger.warning(f"Position {position.id} opening order has no legs, skipping")
            return False

        # Calculate fill price
        fill_price = self._calculate_fill_price(position, opening_order)

        # Get closed leg quantities
        position_orders = sync_context["preloaded_orders"].get(position.id, {})
        closed_leg_quantities = await self._get_closed_leg_quantities(position, position_orders)

        # Match legs and calculate P&L
        matched_legs, total_unrealized_pnl = self._match_legs_and_calculate_pnl(
            position,
            order_legs,
            closed_leg_quantities,
            sync_context["leg_matcher"],
            sync_context["pnl_calculator"],
        )

        if not matched_legs:
            logger.warning(
                f"Position {position.id} has no matching legs in TastyTrade, may be expired/closed"
            )
            return False

        # Update profit targets and position data
        await self._update_position_data(
            position, account, fill_price, matched_legs, total_unrealized_pnl
        )

        logger.info(
            f"Updated app-managed position {position.id} ({position.symbol}): "
            f"matched {len(matched_legs)} legs, "
            f"avg_price={fill_price}, unrealized_pnl={total_unrealized_pnl}"
        )
        return True

    def _get_opening_order(self, position: Position, cached_orders_map: dict):
        """Get opening order from cached orders map."""
        if not position.broker_order_ids or len(position.broker_order_ids) == 0:
            return None
        return cached_orders_map.get(position.broker_order_ids[0])

    def _calculate_fill_price(self, position: Position, opening_order) -> Decimal:
        """Calculate actual fill price from opening order."""
        fill_price = self.order_history_service.calculate_fill_price(opening_order.order_data)

        if fill_price is None:
            fill_price = Decimal(str(opening_order.order_data.get("price", 0)))
            logger.warning(
                f"Position {position.id}: No fill data, using order limit price ${fill_price}"
            )
        else:
            order_price = opening_order.order_data.get("price")
            logger.debug(
                f"Position {position.id}: fill_price=${fill_price}, "
                f"order_limit_price=${order_price}"
            )

        return fill_price

    def _match_legs_and_calculate_pnl(
        self,
        position: Position,
        order_legs: list,
        closed_leg_quantities: dict,
        leg_matcher,
        pnl_calculator,
    ) -> tuple[list, Decimal]:
        """
        Match order legs to current TastyTrade positions and calculate P&L.

        Returns:
            (matched_legs, total_unrealized_pnl)
        """
        matched_legs = []
        total_unrealized_pnl = Decimal("0")

        for order_leg in order_legs:
            leg_symbol = order_leg.get("symbol")
            if not leg_symbol:
                continue

            # Parse and adjust quantity for partial closes
            order_quantity = self._parse_leg_quantity(order_leg)
            adjusted_quantity = self._adjust_quantity_for_closes(
                position, leg_symbol, order_quantity, closed_leg_quantities
            )

            if adjusted_quantity is None:
                continue  # Leg fully closed, skip

            # Match leg to TastyTrade data
            tt_leg = leg_matcher.match_leg(leg_symbol)
            if not tt_leg:
                continue

            # Build leg data and calculate P&L
            leg_data = self._build_leg_data(order_leg, tt_leg, adjusted_quantity)
            matched_legs.append(leg_data)

            leg_pnl = self._calculate_leg_pnl(position, leg_data, adjusted_quantity, pnl_calculator)
            if leg_pnl is not None:
                total_unrealized_pnl += leg_pnl

        return matched_legs, total_unrealized_pnl

    def _parse_leg_quantity(self, order_leg: dict) -> int:
        """Parse quantity from order leg."""
        order_qty_str = order_leg.get("quantity", "0")
        try:
            return int(float(str(order_qty_str)))
        except (ValueError, TypeError):
            return 0

    def _adjust_quantity_for_closes(
        self,
        position: Position,
        leg_symbol: str,
        order_quantity: int,
        closed_leg_quantities: dict,
    ) -> int | None:
        """
        Adjust quantity for partially filled profit targets.

        Returns:
            Adjusted quantity, or None if leg is fully closed
        """
        if leg_symbol not in closed_leg_quantities:
            return order_quantity

        closed_qty = closed_leg_quantities[leg_symbol]
        remaining_qty = order_quantity - closed_qty

        if remaining_qty <= 0:
            logger.debug(
                f"Position {position.id}: Skipping fully closed leg {leg_symbol} "
                f"(original={order_quantity}, all closed via profit targets)"
            )
            return None

        logger.debug(
            f"Position {position.id}: Leg {leg_symbol} partially closed "
            f"(original={order_quantity}, closed={closed_qty}, remaining={remaining_qty})"
        )
        return remaining_qty

    def _build_leg_data(self, order_leg: dict, tt_leg: dict, adjusted_quantity: int) -> dict:
        """Build complete leg data dict from order and TastyTrade data."""
        action = str(order_leg.get("action", "")).lower()
        quantity_direction = "short" if "sell" in action else "long"

        return {
            "symbol": tt_leg["symbol"],
            "quantity": adjusted_quantity,
            "quantity_direction": quantity_direction,
            "average_open_price": tt_leg["average_open_price"],
            "close_price": tt_leg["close_price"],
            "mark_price": tt_leg["mark_price"],
            "multiplier": tt_leg["multiplier"],
            "instrument_type": tt_leg["instrument_type"],
        }

    def _calculate_leg_pnl(
        self, position: Position, leg_data: dict, adjusted_quantity: int, pnl_calculator
    ) -> Decimal | None:
        """Calculate P&L for a single leg."""
        avg_price = leg_data["average_open_price"]
        current_price = leg_data["mark_price"] or leg_data["close_price"]

        # Log stale data warning
        if (
            leg_data["close_price"] is not None
            and avg_price is not None
            and abs(leg_data["close_price"] - avg_price) < 0.01
        ):
            logger.debug(
                f"Position {position.id} leg {leg_data['symbol']}: "
                f"close_price ({leg_data['close_price']}) equals avg_price ({avg_price}), "
                f"may be stale data"
            )

        if not (avg_price and current_price and adjusted_quantity):
            return None

        return pnl_calculator.calculate_leg_pnl(
            avg_price=avg_price,
            current_price=current_price,
            quantity=adjusted_quantity,
            quantity_direction=leg_data["quantity_direction"],
            multiplier=leg_data["multiplier"],
        )

    async def _update_position_data(
        self,
        position: Position,
        account: TradingAccount,
        fill_price: Decimal,
        matched_legs: list,
        total_unrealized_pnl: Decimal,
    ) -> None:
        """Update position with synced data."""
        # Populate profit target credits if missing
        await self._populate_profit_target_credits(position, fill_price)

        # Reconcile profit target fills
        await self._reconcile_profit_target_fills(position, account)

        # Update position fields
        position.metadata = position.metadata or {}
        position.metadata["legs"] = matched_legs
        position.metadata["sync_timestamp"] = dj_timezone.now().isoformat()
        position.metadata["sync_source"] = "cached_orders_with_tt_prices"

        if fill_price is not None:
            position.avg_price = fill_price
        position.unrealized_pnl = total_unrealized_pnl

        await position.asave()

    async def _populate_profit_target_credits(
        self, position: Position, fill_price: Decimal
    ) -> None:
        """
        Populate original_credit in profit_target_details if missing.

        For Senex Trident:
        - Each put spread gets the same fill_price per spread
        - Call spread gets its own fill_price

        Args:
            position: Position to update
            fill_price: Total fill price from opening order
        """
        if not position.profit_target_details:
            return

        # Calculate per-spread credit based on strategy
        # For Senex Trident: 2 put spreads + 1 call spread
        # fill_price is the total credit for the entire position
        if position.strategy_type == "senex_trident":
            # Example: If total credit is $2.50 and we have 2 put spreads + 1 call:
            # - Put spreads might be $1.00 each = $2.00
            # - Call spread might be $0.50
            # We need to derive individual spread credits

            # Get suggestion data from metadata to know individual spread credits
            suggestion_id = position.metadata.get("suggestion_id")
            if not suggestion_id:
                logger.warning(
                    f"Position {position.id}: No suggestion_id in metadata, "
                    f"cannot populate original_credit"
                )
                return

            # Query suggestion for individual spread credits
            from trading.models import TradingSuggestion

            suggestion = await TradingSuggestion.objects.filter(id=suggestion_id).afirst()

            if not suggestion:
                logger.warning(f"Position {position.id}: Suggestion {suggestion_id} not found")
                return

            # Update profit_target_details with original credits
            updated = False
            for spread_type, details in position.profit_target_details.items():
                if "original_credit" not in details or details["original_credit"] is None:
                    # Determine credit based on spread type
                    if "put_spread" in spread_type:
                        # Put spreads use put_spread_mid_credit
                        if suggestion.put_spread_mid_credit:
                            details["original_credit"] = float(suggestion.put_spread_mid_credit)
                            updated = True
                            logger.info(
                                f"Position {position.id}: Set {spread_type} "
                                f"original_credit=${details['original_credit']}"
                            )
                    elif "call_spread" in spread_type:
                        # Call spread uses call_spread_mid_credit
                        if suggestion.call_spread_mid_credit:
                            details["original_credit"] = float(suggestion.call_spread_mid_credit)
                            updated = True
                            logger.info(
                                f"Position {position.id}: Set {spread_type} "
                                f"original_credit=${details['original_credit']}"
                            )

            if updated:
                # Save will happen in caller
                pass

        else:
            # For other strategies (bull/bear put spreads), use total fill price
            for spread_type, details in position.profit_target_details.items():
                if "original_credit" not in details or details["original_credit"] is None:
                    details["original_credit"] = float(fill_price)
                    logger.info(
                        f"Position {position.id}: Set {spread_type} "
                        f"original_credit=${fill_price} from fill price"
                    )

    async def _reconcile_profit_target_fills(
        self, position: Position, account: TradingAccount
    ) -> None:
        """
        Check if any profit targets have filled and update position state accordingly.

        This handles the case where profit targets filled but position sync didn't catch them
        (e.g., WebSocket missed, manual sync after fills).

        Updates:
        - profit_target_details status for filled orders
        - position.quantity based on filled contracts
        - position.lifecycle_state (open_full → open_partial → closed)
        - position.total_realized_pnl from filled targets

        All position updates happen atomically within a database transaction to ensure
        data consistency and prevent partial state on errors.

        Args:
            position: Position to reconcile
            account: Trading account
        """
        # Early exits - no DB access needed
        if not position.profit_target_details or not position.profit_targets_created:
            return

        # Collect all profit target order IDs
        profit_target_order_ids = [
            details.get("order_id")
            for details in position.profit_target_details.values()
            if details.get("order_id") and not details.get("status")  # Only check unfilled
        ]

        if not profit_target_order_ids:
            logger.debug(f"Position {position.id}: No active profit targets to reconcile")
            return

        # ASYNC: Query cached orders BEFORE transaction
        # This must happen outside transaction to avoid SynchronousOnlyOperation
        from trading.models import CachedOrder

        cached_orders_map = {
            co.broker_order_id: co
            async for co in CachedOrder.objects.filter(broker_order_id__in=profit_target_order_ids)
        }

        # Check for missing or cancelled order IDs
        for order_id in profit_target_order_ids:
            cached = cached_orders_map.get(order_id)
            if not cached:
                logger.warning(
                    f"Position {position.id}: Profit target order {order_id} not found in "
                    f"cached_orders. Order may have been manually cancelled. Run order "
                    f"history sync or check position manually."
                )
            elif cached.status in ["Cancelled", "Rejected", "Expired"]:
                logger.warning(
                    f"Position {position.id}: Profit target order {order_id} has status "
                    f"{cached.status}. Position may need manual correction if order was "
                    f"replaced during testing/debugging."
                )

        logger.info(
            f"Position {position.id}: Reconciling {len(profit_target_order_ids)} "
            f"profit target orders"
        )

        # Query cached orders for profit target fills
        filled_orders = [
            order
            async for order in CachedOrder.objects.filter(
                broker_order_id__in=profit_target_order_ids, status="Filled"
            )
        ]

        if not filled_orders:
            logger.debug(f"Position {position.id}: No filled profit target orders found in cache")
            return

        # SYNC: Atomic position updates
        # All database writes must happen inside a synchronous transaction
        @sync_to_async
        def _update_position_atomic():
            """Inner sync function that performs atomic database updates."""
            with transaction.atomic():
                # Refresh from database to prevent stale data
                position.refresh_from_db()

                # Track original quantity for lifecycle state determination
                original_quantity = position.metadata.get("original_quantity", position.quantity)
                if "original_quantity" not in position.metadata:
                    position.metadata["original_quantity"] = position.quantity
                    original_quantity = position.quantity

                # Process each filled profit target
                contracts_closed = 0
                additional_realized_pnl = Decimal("0")

                for order in filled_orders:
                    # Find matching profit target in details
                    for spread_type, details in position.profit_target_details.items():
                        if details.get("order_id") == order.broker_order_id:
                            # Mark as filled
                            details["status"] = "filled"
                            details["filled_at"] = (
                                order.filled_at.isoformat()
                                if order.filled_at
                                else dj_timezone.now().isoformat()
                            )

                            # Calculate realized P&L from this fill
                            # Get fill price from order data
                            fill_price = self.order_history_service.calculate_fill_price(
                                order.order_data
                            )
                            if fill_price:
                                details["fill_price"] = float(abs(fill_price))

                            # Calculate P&L: (original_credit - fill_price) * quantity * 100
                            original_credit = Decimal(str(details.get("original_credit", 0)))
                            if fill_price and original_credit:
                                # For closing orders, fill_price is the debit we paid
                                # P&L = (credit received - debit paid) * contracts * multiplier
                                pnl = (original_credit - abs(fill_price)) * Decimal("100")
                                details["realized_pnl"] = float(pnl)
                                additional_realized_pnl += pnl
                                logger.info(
                                    f"Position {position.id} {spread_type}: Filled @ "
                                    f"${abs(fill_price)}, P&L=${pnl} "
                                    f"(original_credit=${original_credit})"
                                )

                            # Count contracts closed (1 per profit target for Senex)
                            contracts_closed += 1
                            break

                if contracts_closed == 0:
                    return False

                # Update position quantity
                new_quantity = position.quantity - contracts_closed
                if new_quantity < 0:
                    logger.warning(
                        f"Position {position.id}: Calculated negative quantity "
                        f"({position.quantity} - {contracts_closed} = {new_quantity}), "
                        f"clamping to 0"
                    )
                    new_quantity = 0

                position.quantity = new_quantity
                position.total_realized_pnl += additional_realized_pnl

                # Update lifecycle state based on remaining quantity
                if new_quantity == 0:
                    position.lifecycle_state = "closed"
                    logger.info(
                        f"Position {position.id}: All contracts closed via profit targets, "
                        f"state → closed, realized_pnl=${position.total_realized_pnl}"
                    )
                elif new_quantity < original_quantity:
                    position.lifecycle_state = "open_partial"
                    logger.info(
                        f"Position {position.id}: {contracts_closed} contracts closed via profit targets, "
                        f"{new_quantity}/{original_quantity} remaining, state → open_partial"
                    )

                # Save all changes atomically
                position.save()
                return True

        # Execute atomic update
        await _update_position_atomic()

    async def _batch_load_filled_orders(
        self, positions: list[Position]
    ) -> dict[int, dict[str, object]]:
        """
        Batch load all filled profit target orders to avoid N+1 queries.

        This method collects all order IDs from positions' profit_target_details,
        performs a single database query, and returns a lookup map for O(1) access.

        Args:
            positions: List of positions to load orders for

        Returns:
            Dict mapping position_id -> {order_id: CachedOrder}
            Example: {123: {"abc-order-1": CachedOrder(...), "abc-order-2": CachedOrder(...)}}
        """
        # Step 1: Collect all order IDs that need to be loaded
        order_ids_by_position = {}
        for position in positions:
            if not position.profit_target_details:
                continue

            filled_order_ids = []
            for details in position.profit_target_details.values():
                if details.get("status") == "filled" and details.get("order_id"):
                    filled_order_ids.append(details["order_id"])

            if filled_order_ids:
                order_ids_by_position[position.id] = filled_order_ids

        # Step 2: Batch query all orders at once
        all_order_ids = [oid for oids in order_ids_by_position.values() for oid in oids]

        if not all_order_ids:
            logger.debug("No filled profit target orders to batch load")
            return {}

        # Single database query for all orders with eager loading
        from trading.models import CachedOrder

        filled_orders = {
            order.broker_order_id: order
            async for order in CachedOrder.objects.filter(
                broker_order_id__in=all_order_ids, status="Filled"
            ).select_related("trading_account")
        }

        # Step 3: Organize by position ID for O(1) lookup
        result = {}
        for position_id, order_ids in order_ids_by_position.items():
            result[position_id] = {
                oid: filled_orders[oid] for oid in order_ids if oid in filled_orders
            }

        logger.info(
            f"Batch loaded {len(filled_orders)} filled orders for "
            f"{len(result)} positions (avoiding N+1 query)"
        )
        return result

    async def _get_closed_leg_quantities(
        self, position: Position, preloaded_orders: dict[str, object] | None = None
    ) -> dict[str, int]:
        """
        Get quantity of each leg closed via filled profit targets.

        For positions where multiple contracts of the same leg exist (e.g., Senex Trident
        with 2 put spreads), we need to track HOW MANY of each leg have been closed,
        not just whether the leg symbol was closed.

        Args:
            position: Position to calculate for
            preloaded_orders: Optional pre-loaded orders dict {order_id: CachedOrder} to avoid queries

        Returns:
            Dict mapping OCC symbol -> quantity closed
            Example: {"QQQ   251107P00594000": 1} means 1 contract of this leg was closed
        """
        if not position.profit_target_details:
            return {}

        # Get filled profit target order IDs
        filled_order_ids = [
            details.get("order_id")
            for details in position.profit_target_details.values()
            if details.get("status") == "filled" and details.get("order_id")
        ]

        if not filled_order_ids:
            return {}

        # Use preloaded orders if available, otherwise query database
        if preloaded_orders:
            filled_orders = [
                preloaded_orders[order_id]
                for order_id in filled_order_ids
                if order_id in preloaded_orders
            ]
            logger.debug(
                f"Position {position.id}: Using preloaded orders "
                f"({len(filled_orders)}/{len(filled_order_ids)} found)"
            )
        else:
            # Fallback to database query (only if preloaded_orders not provided)
            from trading.models import CachedOrder

            filled_orders = [
                order
                async for order in CachedOrder.objects.filter(
                    broker_order_id__in=filled_order_ids, status="Filled"
                )
            ]
            logger.debug(
                f"Position {position.id}: Queried database for {len(filled_orders)} filled orders "
                f"(preloaded_orders not provided)"
            )

        # Extract leg quantities from filled orders
        closed_quantities = {}
        for order in filled_orders:
            for leg in order.order_data.get("legs", []):
                symbol = leg.get("symbol")
                qty = abs(int(leg.get("quantity", 0)))
                if symbol and qty > 0:
                    # Accumulate quantities (in case multiple targets filled same leg)
                    closed_quantities[symbol] = closed_quantities.get(symbol, 0) + qty

        logger.debug(
            f"Position {position.id}: Found {len(closed_quantities)} unique leg symbols "
            f"with closed quantities from {len(filled_orders)} filled profit targets: "
            f"{closed_quantities}"
        )

        return closed_quantities

    async def _get_primary_account(self, user: User) -> TradingAccount | None:
        """Get user's primary TastyTrade account."""
        # Use centralized data_access utility
        from services.core.data_access import get_primary_tastytrade_account

        return await get_primary_tastytrade_account(user)

    @staticmethod
    def _safe_decimal(value) -> Decimal | None:
        """Safely convert value to Decimal."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None
