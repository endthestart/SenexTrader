"""Order Event Processor - Handles order fills and profit target creation."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone as dj_timezone

from asgiref.sync import sync_to_async
from tastytrade.order import PlacedOrder

from services.core.logging import get_logger
from trading.models import Position, Trade

logger = get_logger(__name__)


class OrderEventProcessor:
    """
    Processes order events and profit target fills for a user's trading activity.

    This class handles:
    1. Order status updates from AlertStreamer
    2. Profit target fill detection and processing
    3. Profit target creation when opening orders fill
    4. Position state updates (open_full, open_partial, closed)

    Design:
    - Stateless (no internal state between calls)
    - Dependency injection via callbacks
    - No direct access to channel layers or streamers
    """

    def __init__(self, user_id: int, broadcast_fn: Callable[[str, dict], Awaitable[None]]):
        """
        Initialize order event processor.

        Args:
            user_id: User ID for logging and context
            broadcast_fn: Callback to broadcast WebSocket messages
                         Signature: async def broadcast(message_type: str, data: dict)
        """
        self.user_id = user_id
        self._broadcast = broadcast_fn

    async def handle_order_event(self, order: PlacedOrder) -> None:
        """
        Process real-time order updates from AlertStreamer.

        Handles:
        - Order status changes (filled, cancelled, rejected, expired)
        - Position lifecycle state updates
        - Profit target creation for opening fills
        - Profit target fills (delegated to _handle_profit_target_fill)

        Args:
            order: PlacedOrder object from TastyTrade AlertStreamer
        """
        try:
            # Find the trade associated with this order
            trade = await Trade.objects.select_related("position").aget(broker_order_id=order.id)

            position = await trade.position_async

            # Check if this is a profit target fill
            is_profit_target_fill = False
            if position.profit_target_details:
                for _pt_key, pt_details in position.profit_target_details.items():
                    if pt_details.get("order_id") == order.id:
                        is_profit_target_fill = True
                        break

            if is_profit_target_fill:
                await self._handle_profit_target_fill(trade, order)
                return

            # The rest of the original _handle_order_event logic for non-profit-target fills
            old_status = trade.status
            new_status = (
                order.status.value.lower()
                if hasattr(order.status, "value")
                else str(order.status).lower()
            )

            # Update trade if status changed
            if new_status != old_status:
                trade.status = new_status
                if new_status == "filled":
                    trade.filled_at = (
                        order.filled_at if hasattr(order, "filled_at") else dj_timezone.now()
                    )

                    # Extract fill price from order (AlertStreamer DOES provide this)
                    if hasattr(order, "price") and order.price:
                        trade.fill_price = Decimal(str(order.price))
                        logger.info(
                            f"User {self.user_id}: Trade {trade.id} fill_price=${trade.fill_price} "
                            f"from order.price"
                        )
                    else:
                        # Fallback: calculate from leg fills if available
                        fill_price = self._calculate_fill_price_from_legs(order)
                        if fill_price:
                            trade.fill_price = fill_price
                            logger.info(
                                f"User {self.user_id}: Trade {trade.id} calculated fill_price="
                                f"${fill_price} from leg fills"
                            )
                        else:
                            logger.warning(
                                f"User {self.user_id}: Trade {trade.id} - No fill price available "
                                f"from order.price or leg fills"
                            )

                    # Look up commission from transactions (may be null if not yet synced)
                    commission = await self._get_commission_for_order(str(order.id))
                    if commission:
                        trade.commission = commission
                        logger.info(
                            f"User {self.user_id}: Trade {trade.id} commission=${commission}"
                        )

                    if trade.trade_type == "open":
                        position.lifecycle_state = "open_full"
                        await position.asave(update_fields=["lifecycle_state"])
                        logger.info(
                            f"User {self.user_id}: Position {position.id} "
                            f"marked as open (order filled)"
                        )
                        try:
                            from django.contrib.auth import get_user_model

                            from services.positions.sync import PositionSyncService

                            User = get_user_model()
                            user = await User.objects.aget(id=self.user_id)
                            sync_service = PositionSyncService()
                            sync_result = await sync_service.sync_all_positions(user)
                            if sync_result.get("success"):
                                logger.info(
                                    f"User {self.user_id}: Position sync complete - "
                                    f"avg_price and legs populated for position {position.id}"
                                )
                            else:
                                logger.warning(
                                    f"User {self.user_id}: Position sync failed: "
                                    f"{sync_result.get('error')}"
                                )
                        except Exception as e:
                            logger.error(
                                f"User {self.user_id}: Error during position sync: {e}",
                                exc_info=True,
                            )

                elif new_status in ["cancelled", "rejected", "expired"]:
                    if position.lifecycle_state == "pending_entry":
                        position.lifecycle_state = "closed"
                        position.metadata = position.metadata or {}
                        position.metadata["closure_reason"] = f"order_{new_status}"
                        position.metadata["closure_timestamp"] = dj_timezone.now().isoformat()
                        position.metadata["auto_closed_by"] = "alert_streamer"
                        await position.asave(update_fields=["lifecycle_state", "metadata"])
                        logger.info(
                            f"User {self.user_id}: Position {position.id} auto-closed "
                            f"(order {order.id} {new_status})"
                        )
                        await self._broadcast(
                            "position_closed",
                            {
                                "position_id": position.id,
                                "symbol": position.symbol,
                                "reason": f"order_{new_status}",
                                "trade_id": trade.id,
                            },
                        )

                await trade.asave()
                logger.info(
                    f"User {self.user_id}: Order {order.id} status: {old_status} -> {new_status}"
                )

                position_symbol = (await trade.position_async).symbol

                await self._broadcast(
                    "order_status",
                    {
                        "trade_id": trade.id,
                        "order_id": order.id,
                        "status": new_status,
                        "old_status": old_status,
                        "symbol": position_symbol,
                        "trade_type": trade.trade_type,
                    },
                )

                if (
                    new_status == "filled"
                    and trade.trade_type == "open"
                    and not trade.child_order_ids
                ):
                    await self._create_profit_targets_for_trade(trade)

        except Trade.DoesNotExist:
            logger.debug(f"User {self.user_id}: Order {order.id} not found in our trades, ignoring")
        except Exception as e:
            logger.error(f"User {self.user_id}: Error handling order event for {order.id}: {e}")

    async def _handle_profit_target_fill(self, trade: Trade, order: PlacedOrder) -> None:
        """
        Handle profit target fill by updating position state and recording P&L.

        IMPORTANT: Does NOT cancel other profit targets. All profit targets stay
        active until either:
        - They individually fill (handled by this method), OR
        - DTE threshold triggers full position closure (handled by DTEManager)

        This allows multiple profit targets to fill independently at different times,
        maximizing realized P&L opportunities. For a Senex Trident with 3 targets:
        - Target 1 fills → record P&L, leave targets 2 & 3 active
        - Target 2 fills → record P&L, leave target 3 active
        - Target 3 fills → position fully closed

        At 7 DTE, if any targets remain unfilled, DTEManager cancels them and
        closes the entire position via market/limit order.

        Args:
            trade: Trade object associated with the profit target order
            order: PlacedOrder from AlertStreamer containing fill details
        """
        logger.info(
            f"User {self.user_id}: Profit target fill detected for order {order.id} - "
            f"other targets remain active (DTE closure at 7 DTE handles cancellation)"
        )

        try:
            position = await trade.position_async
            account = await trade.trading_account_async

            fill_data = await self._extract_and_validate_fill_data(trade, order)

            update_data = await self._prepare_profit_target_update(position, order, fill_data)

            position = await self._record_profit_target_fill(
                trade, position, fill_data, update_data
            )

            await self._notify_profit_target_fill(position, trade, order, account)

        except Exception as e:
            logger.error(
                f"User {self.user_id}: Error handling profit target fill for order {order.id}: {e}"
            )

    async def _extract_and_validate_fill_data(
        self, trade: Trade, order: PlacedOrder
    ) -> dict[str, Any]:
        """
        Extract and validate fill data from order.

        Args:
            trade: Trade object for context
            order: PlacedOrder from AlertStreamer

        Returns:
            dict: Validated fill data containing order_id, filled_quantity, fill_price, order_legs, filled_at
        """
        fill_data = self._extract_fill_data(order)
        filled_quantity = fill_data["filled_quantity"]
        fill_price = fill_data["fill_price"]
        order_legs = fill_data["order_legs"]
        filled_at = fill_data["filled_at"]

        logger.info(
            f"User {self.user_id}: Extracted fill data - order_id={order.id}, quantity={filled_quantity}, "
            f"price={fill_price}, legs={len(order_legs)}"
        )

        return {
            "order_id": order.id,  # Actual profit target order ID from AlertStreamer
            "filled_quantity": filled_quantity,
            "fill_price": fill_price,
            "order_legs": order_legs,
            "filled_at": filled_at,
        }

    async def _prepare_profit_target_update(
        self, position: Position, order: PlacedOrder, fill_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Prepare position update data including P&L calculation and lifecycle state.

        Args:
            position: Position being updated
            order: PlacedOrder from AlertStreamer
            fill_data: Validated fill data

        Returns:
            dict: Update data containing realized_pnl, profit_target_details, new_lifecycle_state, metadata
        """
        from decimal import Decimal

        from services.positions.lifecycle.profit_calculator import ProfitCalculator

        filled_quantity = fill_data["filled_quantity"]
        fill_price = fill_data["fill_price"]
        filled_at = fill_data["filled_at"]

        # Track original quantity in metadata if not already tracked
        if not position.metadata:
            position.metadata = {}
        if "original_quantity" not in position.metadata:
            position.metadata["original_quantity"] = position.quantity

        original_quantity = position.metadata["original_quantity"]

        # Prepare updated metadata
        updated_metadata = position.metadata.copy()

        # Find the matching profit target and extract spread-specific original_credit
        # This is critical for multi-spread positions like Senex Trident
        updated_profit_target_details = position.profit_target_details.copy()
        original_credit = None
        matched_pt_key = None

        for pt_key, pt_details in updated_profit_target_details.items():
            if pt_details.get("order_id") == order.id:
                matched_pt_key = pt_key
                # Extract spread-specific original_credit for accurate P&L calculation
                if "original_credit" in pt_details and pt_details["original_credit"] is not None:
                    original_credit = Decimal(str(pt_details["original_credit"]))
                    logger.debug(
                        f"User {self.user_id}: Using spread-specific original_credit "
                        f"${original_credit} for {pt_key}"
                    )
                break

        # Calculate P&L using spread-specific original_credit if available
        # This ensures multi-spread positions (Senex Trident) have accurate per-spread P&L
        calculator = ProfitCalculator()
        realized_pnl = calculator.calculate_profit_target_pnl(
            position, fill_price, filled_quantity, opening_price=original_credit
        )

        # Update the matched profit target details
        if matched_pt_key:
            pt_details = updated_profit_target_details[matched_pt_key]
            pt_details["status"] = "filled"
            pt_details["filled_at"] = filled_at.isoformat()
            pt_details["fill_price"] = float(fill_price) if fill_price else None
            pt_details["realized_pnl"] = float(realized_pnl)

            # Look up submission timestamp from order history for time-to-fill analytics
            try:
                from trading.models import TastyTradeOrderHistory

                order_history = await TastyTradeOrderHistory.objects.filter(
                    broker_order_id=str(order.id)
                ).afirst()
                if order_history and order_history.received_at:
                    pt_details["submitted_at"] = order_history.received_at.isoformat()
            except Exception as e:
                logger.debug(f"User {self.user_id}: Could not look up submitted_at: {e}")

            logger.info(
                f"User {self.user_id}: Marking profit target {matched_pt_key} as filled "
                f"(P&L: ${realized_pnl}, original_credit: ${original_credit or position.avg_price})"
            )

        # Calculate new lifecycle state based on remaining quantity
        new_quantity = position.quantity - filled_quantity
        if new_quantity <= 0:
            new_lifecycle_state = "closed"
            logger.info(
                f"User {self.user_id}: Position {position.id} will be fully closed (quantity=0)"
            )
        elif new_quantity < original_quantity:
            new_lifecycle_state = "open_partial"
            logger.info(
                f"User {self.user_id}: Position {position.id} will be partially closed "
                f"(quantity={new_quantity}/{original_quantity})"
            )
        else:
            new_lifecycle_state = position.lifecycle_state

        return {
            "realized_pnl": realized_pnl,
            "profit_target_details": updated_profit_target_details,
            "new_lifecycle_state": new_lifecycle_state,
            "metadata": updated_metadata,
        }

    async def _record_profit_target_fill(
        self,
        trade: Trade,
        position: Position,
        fill_data: dict[str, Any],
        update_data: dict[str, Any],
    ) -> Position:
        """
        Atomically record profit target fill in database.

        Creates Trade record and updates Position in single transaction.

        Args:
            trade: Original opening trade
            position: Position being updated
            fill_data: Validated fill data
            update_data: Prepared update data

        Returns:
            Position: Updated position object
        """
        filled_quantity = fill_data["filled_quantity"]
        fill_price = fill_data["fill_price"]
        order_legs = fill_data["order_legs"]
        filled_at = fill_data["filled_at"]

        realized_pnl = update_data["realized_pnl"]
        profit_target_details = update_data["profit_target_details"]
        new_lifecycle_state = update_data["new_lifecycle_state"]
        metadata = update_data["metadata"]

        # ATOMIC UPDATE: Single database transaction with row locking
        position = await self._update_position_profit_target_atomic(
            position_id=position.id,
            filled_quantity=filled_quantity,
            realized_pnl=realized_pnl,
            profit_target_details=profit_target_details,
            new_lifecycle_state=new_lifecycle_state,
            metadata=metadata,
        )

        # Create a new Trade record for the profit target fill with actual fill data
        # NOTE: realized_pnl is tracked on Position.total_realized_pnl, not on Trade
        new_trade = await Trade.objects.acreate(
            user=trade.user,
            position=position,
            trading_account=await trade.trading_account_async,
            broker_order_id=fill_data.get("order_id", str(trade.broker_order_id)),
            trade_type="close",
            order_legs=order_legs if order_legs else trade.order_legs,
            quantity=filled_quantity,
            status="filled",
            executed_at=filled_at,
            filled_at=filled_at,
            fill_price=fill_price,
            lifecycle_event="profit_target_fill",
            lifecycle_snapshot={
                "fill_price": float(fill_price) if fill_price else None,
                "filled_quantity": filled_quantity,
                "remaining_quantity": position.quantity,
                "realized_pnl": float(realized_pnl) if realized_pnl else None,
            },
        )
        logger.info(
            f"User {self.user_id}: Created Trade {new_trade.id} for profit target fill "
            f"(P&L: ${realized_pnl})"
        )

        return position

    async def _notify_profit_target_fill(
        self, position: Position, trade: Trade, order: PlacedOrder, account: Any
    ) -> None:
        """
        Send notifications and broadcast updates for profit target fill.

        Args:
            position: Updated position
            trade: Original opening trade
            order: PlacedOrder from AlertStreamer
            account: Trading account
        """
        # Log profit target fill for monitoring
        remaining_targets_count = len(
            [
                d
                for d in position.profit_target_details.values()
                if d.get("order_id") and d["order_id"] != order.id
            ]
        )

        logger.info(
            f"User {self.user_id}: Profit target filled - "
            f"{remaining_targets_count} targets remain active, "
            f"{position.quantity} contracts still open"
        )

        # Send notification (regardless of automation flag)
        from services.notifications.service import NotificationService

        notification_service = NotificationService(trade.user)
        await notification_service.send_notification(
            message=(
                f"Profit target hit for {position.symbol}. "
                f"{remaining_targets_count} targets remain active."
            ),
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                "reason": "profit_target_hit",
                "remaining_quantity": position.quantity,
                "remaining_targets": remaining_targets_count,
                "filled_order_id": order.id,
            },
            notification_type="success",
        )

        # Broadcast position update
        await self._broadcast(
            "position_update",
            {
                "position_id": position.id,
                "lifecycle_state": position.lifecycle_state,
                "total_realized_pnl": float(position.total_realized_pnl),
            },
        )

    async def _create_profit_targets_for_trade(self, trade: Trade) -> None:
        """
        Create profit targets when opening order fills using strategy-specific logic.

        This method:
        1. Acquires a database lock on the trade to prevent race conditions
        2. Re-checks if profit targets already exist or are in progress
        3. Marks position as "creating" (in metadata) while submitting orders
        4. Submits profit target orders to the broker
        5. Updates position with actual order IDs on success
        6. Cleans up "creating" flag on completion (success or failure)

        RACE CONDITION PREVENTION:
        Multiple processes (web container, celery worker) may receive the same
        order fill event via WebSocket and call this method simultaneously.
        We use select_for_update() and a metadata flag to ensure only one
        process can create profit targets for a given trade.

        FAILURE RECOVERY:
        If order submission fails partway through, profit_targets_created stays False
        and the "creating" metadata flag is cleared after a timeout. This allows
        the reconciliation process to retry on the next run.

        Args:
            trade: Trade object for the filled opening order
        """
        try:
            from datetime import timedelta

            from django.db import transaction
            from django.utils import timezone

            from services.execution.order_service import OrderExecutionService
            from services.strategies.factory import get_strategy, is_strategy_registered
            from trading.models import StrategyConfiguration

            user = await trade.user_async

            # CRITICAL: Acquire lock, check state, and mark as in-progress atomically
            # This prevents race conditions where multiple processes try to create
            # profit targets for the same trade simultaneously
            @sync_to_async
            def acquire_lock_and_mark_in_progress():
                """
                Acquire DB lock on trade/position, check if profit targets exist or
                are being created, and mark as in-progress if OK to proceed.

                Uses metadata["profit_targets_creating"] with a timestamp to track
                in-progress state. This flag is cleared on success OR after a timeout
                (to handle crashes).

                Returns (trade, position, skip_reason) - skip_reason is None if OK to proceed.
                """
                with transaction.atomic():
                    # Lock the trade row - other processes will wait here
                    locked_trade = Trade.objects.select_for_update(nowait=False).get(
                        pk=trade.pk
                    )
                    # Re-check after acquiring lock
                    if locked_trade.child_order_ids:
                        return None, None, "already_has_child_orders"

                    # Also lock position
                    locked_position = Position.objects.select_for_update(nowait=False).get(
                        pk=locked_trade.position_id
                    )
                    if locked_position.profit_targets_created:
                        return None, None, "profit_targets_already_created"

                    # Check if another process is already creating profit targets
                    metadata = locked_position.metadata or {}
                    creating_info = metadata.get("profit_targets_creating")
                    if creating_info:
                        # Check if the creating process has timed out (> 5 minutes)
                        creating_at = creating_info.get("started_at")
                        if creating_at:
                            try:
                                from datetime import datetime

                                started = datetime.fromisoformat(creating_at)
                                if timezone.is_naive(started):
                                    started = timezone.make_aware(started)
                                elapsed = timezone.now() - started
                                if elapsed < timedelta(minutes=5):
                                    return None, None, f"creation_in_progress_by_{creating_info.get('process_id', 'unknown')}"
                                logger.warning(
                                    f"Position {locked_position.id}: Previous profit target creation "
                                    f"timed out (started {elapsed} ago), taking over"
                                )
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Error parsing creating_at timestamp: {e}")

                    # Mark as in-progress with our process ID and timestamp
                    import os
                    import uuid

                    process_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
                    if not locked_position.metadata:
                        locked_position.metadata = {}
                    locked_position.metadata["profit_targets_creating"] = {
                        "started_at": timezone.now().isoformat(),
                        "process_id": process_id,
                        "trade_id": locked_trade.id,
                    }
                    locked_position.save(update_fields=["metadata"])

                    return locked_trade, locked_position, None

            locked_trade, locked_position, skip_reason = await acquire_lock_and_mark_in_progress()

            if skip_reason:
                logger.info(
                    f"User {self.user_id}: Skipping profit target creation for trade {trade.id} "
                    f"- {skip_reason} (likely handled by another process)"
                )
                return

            # Use locked objects for the rest of the method
            trade = locked_trade
            position = locked_position
            strategy_type = position.strategy_type

            if strategy_type == "external":
                logger.info(
                    f"User {self.user_id}: Skipping profit targets for "
                    f"external position {position.id}"
                )
                # Clear the creating flag
                await self._clear_creating_flag(position)
                return

            # Get trading account and check preferences
            account = await trade.trading_account_async

            if not account:
                logger.error(
                    f"User {self.user_id}: CRITICAL - No trading account found for "
                    f"trade {trade.id}. Aborting profit target creation."
                )
                return

            # Senex Trident ALWAYS creates profit targets (algorithm-driven)
            # For other strategies, check the auto_profit_targets_enabled preference
            is_senex_trident = strategy_type == "senex_trident"

            if not is_senex_trident:
                prefs = await self._get_trading_preferences(account)
                if prefs and not prefs.auto_profit_targets_enabled:
                    logger.info(
                        f"User {self.user_id}: Auto profit targets disabled for account "
                        f"{account.id} - skipping for {strategy_type}"
                    )
                    return

            # Use the unified strategy factory
            if not is_strategy_registered(strategy_type):
                logger.warning(
                    f"User {self.user_id}: Unknown strategy type {strategy_type} "
                    f"for position {position.id}"
                )
                return

            strategy = get_strategy(strategy_type, user)

            # Get user-configured profit target percentage for spread strategies
            target_pct = None
            if not is_senex_trident:
                config = await StrategyConfiguration.objects.filter(
                    user=user, strategy_id=strategy_type
                ).afirst()
                if config and config.parameters:
                    target_pct = config.parameters.get("profit_target_pct")

            # Handle different method signatures: Senex takes (position, trade),
            # others take (position) with optional target_pct
            if is_senex_trident:
                profit_target_specs = await strategy.a_get_profit_target_specifications(
                    position, trade
                )
            elif target_pct is not None:
                profit_target_specs = await strategy.a_get_profit_target_specifications(
                    position, target_pct=target_pct
                )
            else:
                profit_target_specs = await strategy.a_get_profit_target_specifications(
                    position
                )

            if not profit_target_specs:
                logger.warning(
                    f"User {self.user_id}: No profit target specs generated for trade {trade.id}"
                )
                return

            logger.info(
                f"User {self.user_id}: Creating {len(profit_target_specs)} "
                f"profit targets for filled trade {trade.id}"
            )

            # Defensive check: verify is_test field exists
            if not hasattr(account, "is_test"):
                logger.error(
                    f"User {self.user_id}: CRITICAL - Trading account {account.id} "
                    f"missing is_test field. Aborting profit target creation."
                )
                return

            logger.info(
                f"User {self.user_id}: Creating profit targets with test_mode={account.is_test} "
                f"for trade {trade.id}"
            )

            # Execute each profit target order using generic OrderExecutionService
            # Test mode is automatically detected from the account via _get_test_mode()
            service = OrderExecutionService(user)
            order_ids = []
            all_succeeded = True

            for spec in profit_target_specs:
                try:
                    order_id = await service.execute_order_spec(spec.order_spec)
                    if order_id:
                        order_ids.append(order_id)
                        logger.info(
                            f"User {self.user_id}: Created {spec.spread_type} "
                            f"profit target ({spec.profit_percentage}%): {order_id}"
                        )
                    else:
                        logger.error(
                            f"User {self.user_id}: Failed to create {spec.spread_type} profit target"
                        )
                        all_succeeded = False
                except Exception as order_error:
                    logger.error(
                        f"User {self.user_id}: Exception creating {spec.spread_type} profit target: {order_error}"
                    )
                    all_succeeded = False

            # Update trade with profit target order IDs (even partial)
            trade.child_order_ids = order_ids
            await trade.asave(update_fields=["child_order_ids"])

            # Update position with profit target details
            # Build details for ALL specs, using actual order_ids where we have them
            position.profit_target_details = {
                spec.spread_type: {
                    "order_id": order_ids[i] if i < len(order_ids) else None,
                    "percent": spec.profit_percentage,
                    "original_credit": float(spec.original_credit),
                    "target_price": float(spec.order_spec.limit_price),
                }
                for i, spec in enumerate(profit_target_specs)
            }

            # CRITICAL: Only set profit_targets_created=True if ALL orders succeeded
            # If any failed, leave it False so reconciliation can retry
            if all_succeeded and len(order_ids) == len(profit_target_specs):
                position.profit_targets_created = True
                await position.asave(update_fields=["profit_targets_created", "profit_target_details"])
                logger.info(
                    f"User {self.user_id}: Successfully created all {len(order_ids)} profit targets: {order_ids}"
                )
            else:
                await position.asave(update_fields=["profit_target_details"])
                logger.warning(
                    f"User {self.user_id}: Partial profit target creation - {len(order_ids)}/{len(profit_target_specs)} "
                    f"succeeded. profit_targets_created=False, reconciliation will retry missing ones."
                )

            # Clear the creating flag now that we're done
            await self._clear_creating_flag(position)

            # Broadcast is non-critical - don't let failures affect the save
            try:
                await self._broadcast(
                    "profit_targets_created",
                    {
                        "trade_id": trade.id,
                        "profit_target_ids": order_ids,
                        "position_id": position.id,
                        "target_details": position.profit_target_details,
                    },
                )
            except Exception as broadcast_error:
                logger.warning(
                    f"User {self.user_id}: Broadcast failed (non-critical): {broadcast_error}"
                )

        except Exception as e:
            logger.error(
                f"User {self.user_id}: Failed to create profit targets for trade {trade.id}: {e}",
                exc_info=True,
            )
            # Try to clear the creating flag so reconciliation can retry
            try:
                if "position" in locals() and position:
                    await self._clear_creating_flag(position)
            except Exception as cleanup_error:
                logger.warning(
                    f"User {self.user_id}: Failed to clear creating flag after error: {cleanup_error}"
                )

    async def _clear_creating_flag(self, position) -> None:
        """Clear the profit_targets_creating metadata flag."""
        from django.db import transaction

        @sync_to_async
        def _clear():
            with transaction.atomic():
                from trading.models import Position as PositionModel

                fresh = PositionModel.objects.select_for_update().get(pk=position.id)
                if fresh.metadata and "profit_targets_creating" in fresh.metadata:
                    del fresh.metadata["profit_targets_creating"]
                    fresh.save(update_fields=["metadata"])

        try:
            await _clear()
        except Exception as e:
            logger.warning(f"Position {position.id}: Failed to clear creating flag: {e}")

    def _calculate_fill_price_from_legs(self, order: PlacedOrder) -> Decimal | None:
        """
        Calculate fill price from leg fills in a multi-leg order.

        For multi-leg spread orders, calculates the net credit/debit from actual fill prices,
        not the order limit price. This matches the logic in order_history_service.py.

        Args:
            order: PlacedOrder from TastyTrade AlertStreamer

        Returns:
            Decimal: Net credit (positive) or debit (negative) from leg fills, or None if no fills
        """
        if not hasattr(order, "legs") or not order.legs:
            return None

        total_value = Decimal("0")
        has_fills = False

        for leg in order.legs:
            if not hasattr(leg, "fills") or not leg.fills:
                continue

            has_fills = True
            action = str(leg.action).lower() if hasattr(leg, "action") else ""

            # Calculate fill value for this leg
            for fill in leg.fills:
                if not hasattr(fill, "fill_price") or not hasattr(fill, "quantity"):
                    continue

                price = Decimal(str(fill.fill_price))
                qty = abs(Decimal(str(fill.quantity)))

                # Sell = credit (+), Buy = debit (-)
                if "sell" in action:
                    total_value += price * qty
                else:
                    total_value -= price * qty

        return total_value if has_fills else None

    def _extract_fill_data(self, order: PlacedOrder) -> dict[str, Any]:
        """
        Extract fill data from a PlacedOrder object.

        Returns dict with:
        - order_legs: List of leg dicts with fill prices
        - filled_quantity: Total quantity filled
        - fill_price: Overall fill price
        - filled_at: Fill timestamp

        Args:
            order: PlacedOrder from TastyTrade AlertStreamer

        Returns:
            dict: Fill data extracted from order
        """
        fill_data = {
            "order_legs": [],
            "filled_quantity": 0,
            "fill_price": None,
            "filled_at": dj_timezone.now(),
        }

        try:
            # Extract order-level data
            # IMPORTANT: Use abs() because TastyTrade returns negative quantities for buy-to-close
            if hasattr(order, "size") and order.size:
                fill_data["filled_quantity"] = abs(int(order.size))

            if hasattr(order, "price") and order.price:
                fill_data["fill_price"] = Decimal(str(order.price))

            # Extract leg-level fill data
            if hasattr(order, "legs") and order.legs:
                for leg in order.legs:
                    leg_dict = {
                        "symbol": leg.symbol,
                        "instrument_type": (
                            leg.instrument_type.value
                            if hasattr(leg.instrument_type, "value")
                            else str(leg.instrument_type)
                        ),
                        "action": (
                            leg.action.value if hasattr(leg.action, "value") else str(leg.action)
                        ),
                        "quantity": None,
                        "fill_price": None,
                        "filled_at": None,
                    }

                    # Extract fill information if available
                    if hasattr(leg, "fills") and leg.fills:
                        # Use first fill (most complete data)
                        first_fill = leg.fills[0]
                        if hasattr(first_fill, "quantity"):
                            leg_dict["quantity"] = abs(int(first_fill.quantity))
                        if hasattr(first_fill, "fill_price"):
                            leg_dict["fill_price"] = float(first_fill.fill_price)
                        if hasattr(first_fill, "filled_at"):
                            leg_dict["filled_at"] = (
                                first_fill.filled_at.isoformat()
                                if hasattr(first_fill.filled_at, "isoformat")
                                else str(first_fill.filled_at)
                            )
                            fill_data["filled_at"] = first_fill.filled_at
                    elif hasattr(leg, "quantity"):
                        # Fallback to leg quantity if no fill details
                        leg_dict["quantity"] = abs(int(leg.quantity))

                    fill_data["order_legs"].append(leg_dict)

        except Exception as e:
            logger.warning(
                f"User {self.user_id}: Error extracting fill data from order {order.id}: {e}"
            )
            # Return partial data - better than nothing

        return fill_data

    @sync_to_async
    def _update_position_profit_target_atomic(
        self,
        position_id: int,
        filled_quantity: int,
        realized_pnl: Decimal,
        profit_target_details: dict[str, Any],
        new_lifecycle_state: str,
        metadata: dict[str, Any],
    ) -> Position:
        """
        Atomically update position after profit target fill to prevent race conditions.

        CRITICAL: Uses select_for_update() to lock the position row during the update.
        This prevents concurrent profit target fills from causing lost updates or
        incorrect position quantities.

        Args:
            position_id: ID of position to update
            filled_quantity: Quantity filled by this profit target
            realized_pnl: P&L realized from this fill
            profit_target_details: Updated profit target details dict
            new_lifecycle_state: New lifecycle state (open_partial, closed, etc.)
            metadata: Updated metadata dict

        Returns:
            Updated Position instance
        """
        from trading.models import Position

        with transaction.atomic():
            # Lock the row for update - prevents concurrent modifications
            position = Position.objects.select_for_update().get(id=position_id)

            # Update all fields in single transaction
            position.quantity -= filled_quantity
            position.total_realized_pnl = (
                position.total_realized_pnl or Decimal("0")
            ) + realized_pnl
            position.profit_target_details = profit_target_details
            position.lifecycle_state = new_lifecycle_state
            position.metadata = metadata

            # Track fields to save
            fields_to_save = [
                "quantity",
                "total_realized_pnl",
                "profit_target_details",
                "lifecycle_state",
                "metadata",
            ]

            # Update closed_at when position is fully closed
            if position.quantity <= 0:
                position.closed_at = datetime.now(UTC)
                fields_to_save.append("closed_at")

            position.save(update_fields=fields_to_save)
            logger.info(
                f"User {self.user_id}: Atomically updated position {position_id} - "
                f"quantity={position.quantity}, state={new_lifecycle_state}, "
                f"realized_pnl=${realized_pnl}"
            )

            return position

    @sync_to_async
    def _get_trading_preferences(self, account):
        """
        Get trading preferences for account.

        Returns TradingAccountPreferences or None if not configured.
        """
        from accounts.models import TradingAccountPreferences

        try:
            return account.trading_preferences
        except TradingAccountPreferences.DoesNotExist:
            return None

    @sync_to_async
    def _get_commission_for_order(self, broker_order_id: str) -> "Decimal | None":
        """
        Get total commission (including fees) for an order from transactions.

        Looks up TastyTradeTransaction records linked to this order_id and sums:
        - commission
        - clearing_fees
        - regulatory_fees

        Args:
            broker_order_id: The TastyTrade order ID

        Returns:
            Total commission as Decimal, or None if no transactions found
        """
        from decimal import Decimal

        from django.db.models import Sum

        from trading.models import TastyTradeTransaction

        try:
            order_id_int = int(broker_order_id)
        except (ValueError, TypeError):
            return None

        result = TastyTradeTransaction.objects.filter(order_id=order_id_int).aggregate(
            total_commission=Sum("commission"),
            total_clearing=Sum("clearing_fees"),
            total_regulatory=Sum("regulatory_fees"),
        )

        commission = result.get("total_commission") or Decimal("0")
        clearing = result.get("total_clearing") or Decimal("0")
        regulatory = result.get("total_regulatory") or Decimal("0")

        total = commission + clearing + regulatory
        return total if total != Decimal("0") else None
