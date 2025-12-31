"""
Service for reconciling local trade data with TastyTrade's order history.
"""

from services.core.logging import get_logger

logger = get_logger(__name__)


class TradeReconciliationService:
    """
    Periodically fetches order history from TastyTrade and reconciles it with the local database.
    """

    def __init__(self, user) -> None:
        self.user = user

    async def reconcile_trades(self) -> dict:
        """
        Fetch recent trades from TastyTrade and update local records.

        Returns:
            dict with reconciliation report
        """
        from datetime import timedelta

        from django.utils import timezone

        from asgiref.sync import sync_to_async
        from tastytrade import Account

        from services.core.data_access import get_oauth_session
        from trading.models import Trade

        logger.info(f"User {self.user.id}: Starting trade reconciliation.")

        report = {
            "success": False,
            "trades_checked": 0,
            "trades_updated": 0,
            "orphaned_orders": [],
            "positions_updated": 0,
            "errors": [],
        }

        try:
            # Get OAuth session
            session = await get_oauth_session(self.user)
            if not session:
                report["errors"].append("Unable to obtain TastyTrade session")
                return report

            # Get primary trading account
            account = await sync_to_async(
                lambda: self.user.trading_accounts.filter(is_primary=True).first()
            )()
            if not account:
                report["errors"].append("No primary trading account found")
                return report

            # Fetch order history for past 7 days with pagination
            start_date = (timezone.now() - timedelta(days=7)).date()
            tt_account = await Account.a_get(session, account.account_number)

            # Paginate through all orders
            all_orders = []
            page_offset = 0
            per_page = 100

            while True:
                order_page = await tt_account.a_get_order_history(
                    session,
                    start_date=start_date,
                    per_page=per_page,
                    page_offset=page_offset,
                )

                if not order_page:
                    break

                all_orders.extend(order_page)

                if len(order_page) < per_page:
                    break

                page_offset += 1

            order_history = all_orders

            logger.info(f"User {self.user.id}: Fetched {len(order_history)} orders from TastyTrade")

            # Process each order
            for order in order_history:
                report["trades_checked"] += 1

                # Only process filled orders
                order_status = (
                    order.status.value.lower()
                    if hasattr(order.status, "value")
                    else str(order.status).lower()
                )

                if order_status != "filled":
                    continue

                # Find local trade by broker_order_id
                try:
                    trade = await Trade.objects.select_related("position").aget(
                        broker_order_id=order.id
                    )

                    # If trade exists but status != filled, update it
                    if trade.status != "filled":
                        logger.info(
                            f"User {self.user.id}: Found unfilled trade {trade.id} "
                            f"for order {order.id}, updating"
                        )

                        # Extract fill data from order
                        fill_data = self._extract_fill_data(order)

                        # Update trade
                        trade.status = "filled"
                        if fill_data["filled_at"]:
                            trade.filled_at = fill_data["filled_at"]
                        if fill_data["fill_price"]:
                            trade.fill_price = fill_data["fill_price"]
                        if fill_data["order_legs"]:
                            trade.order_legs = fill_data["order_legs"]

                        # Look up commission from transactions
                        commission = await self._get_commission_for_order(str(order.id))
                        if commission:
                            trade.commission = commission
                            logger.info(
                                f"User {self.user.id}: Trade {trade.id} commission=${commission}"
                            )

                        await trade.asave()
                        report["trades_updated"] += 1

                        # Update position if this was an entry order
                        if trade.trade_type == "open":
                            position = trade.position
                            if position.lifecycle_state == "pending_entry":
                                position.lifecycle_state = "open_full"
                                await position.asave(update_fields=["lifecycle_state"])
                                report["positions_updated"] += 1
                                logger.info(
                                    f"User {self.user.id}: Updated position {position.id} "
                                    "to open_full"
                                )

                except Trade.DoesNotExist:
                    # Order exists at broker but no Trade record in our DB
                    # This is expected for:
                    # - External positions (created via broker UI, not our app)
                    # - Profit target fills (child orders tracked in position.profit_target_details)
                    # - Manual closing orders
                    # Log at debug level since this is informational, not an error
                    logger.debug(
                        f"User {self.user.id}: Filled order {order.id} has no Trade record "
                        f"(symbol={order.underlying_symbol}) - likely external or profit target"
                    )
                    report["orphaned_orders"].append(
                        {
                            "order_id": order.id,
                            "symbol": order.underlying_symbol,
                            "status": order_status,
                        }
                    )

            report["success"] = True
            logger.info(
                f"User {self.user.id}: Reconciliation complete - "
                f"{report['trades_updated']} trades updated, "
                f"{report['orphaned_orders'].__len__()} orphaned orders found"
            )

        except Exception as e:
            logger.error(f"User {self.user.id}: Error during reconciliation: {e}", exc_info=True)
            report["errors"].append(str(e))

        return report

    def _extract_fill_data(self, order) -> dict:
        """Extract fill data from a TastyTrade order (same logic as StreamManager)."""
        from decimal import Decimal

        fill_data = {
            "order_legs": [],
            "filled_quantity": 0,
            "fill_price": None,
            "filled_at": None,
        }

        try:
            if hasattr(order, "size") and order.size:
                fill_data["filled_quantity"] = int(order.size)

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

                    if hasattr(leg, "fills") and leg.fills:
                        first_fill = leg.fills[0]
                        if hasattr(first_fill, "quantity"):
                            leg_dict["quantity"] = int(first_fill.quantity)
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
                        leg_dict["quantity"] = int(leg.quantity)

                    fill_data["order_legs"].append(leg_dict)

        except Exception as e:
            logger.warning(f"User {self.user.id}: Error extracting fill data: {e}")

        return fill_data

    async def fix_stuck_positions(self) -> dict:
        """
        Detect and fix positions stuck in pending_entry despite filled orders.

        State Machine Self-Correction:
        - Uses TastyTradeOrderHistory as source of truth (TastyTrade data already synced locally)
        - Detects positions in pending_entry with filled opening trades
        - Updates Trade.filled_at from TastyTradeOrderHistory
        - Transitions Position to open_full
        - Creates profit targets if missing

        Returns:
            dict with fix report: {
                "positions_fixed": 0,
                "profit_targets_created": 0,
                "errors": []
            }
        """
        from asgiref.sync import sync_to_async

        from services.execution.order_service import OrderExecutionService
        from trading.models import Position, TastyTradeOrderHistory, Trade

        report = {
            "positions_fixed": 0,
            "profit_targets_created": 0,
            "errors": [],
        }

        try:
            # Get primary account
            account = await sync_to_async(
                lambda: self.user.trading_accounts.filter(is_primary=True).first()
            )()
            if not account:
                report["errors"].append("No primary trading account found")
                return report

            # Find positions stuck in pending_entry with opening trades
            stuck_positions = await sync_to_async(list)(
                Position.objects.filter(
                    user=self.user,
                    trading_account=account,
                    lifecycle_state="pending_entry",
                    is_app_managed=True,
                    trades__trade_type="open",
                )
                .distinct()
                .prefetch_related("trades")
            )

            if not stuck_positions:
                logger.debug(f"User {self.user.id}: No stuck positions found")
                return report

            logger.info(
                f"User {self.user.id}: Found {len(stuck_positions)} positions in pending_entry. "
                f"Checking for filled orders..."
            )

            for position in stuck_positions:
                try:
                    # Get the opening trade
                    opening_trade = await sync_to_async(
                        lambda: Trade.objects.filter(position=position, trade_type="open").first()
                    )()

                    if not opening_trade or not opening_trade.broker_order_id:
                        logger.warning(
                            f"Position {position.id}: No opening trade or broker_order_id found"
                        )
                        continue

                    # Check TastyTradeOrderHistory for fill status (source of truth)
                    try:
                        cached_order = await TastyTradeOrderHistory.objects.aget(
                            broker_order_id=opening_trade.broker_order_id
                        )
                    except TastyTradeOrderHistory.DoesNotExist:
                        logger.debug(
                            f"Position {position.id}: No cached order found for {opening_trade.broker_order_id}"
                        )
                        continue

                    # If order is filled on TastyTrade, fix the stuck state
                    if cached_order.status.lower() == "filled":
                        logger.info(
                            f"STUCK POSITION DETECTED: Position {position.id} "
                            f"in pending_entry but order {cached_order.broker_order_id} "
                            f"is filled on TastyTrade (filled_at={cached_order.filled_at})"
                        )

                        # Update Trade with fill data from TastyTradeOrderHistory
                        if opening_trade.status != "filled" or not opening_trade.filled_at:
                            opening_trade.status = "filled"
                            opening_trade.filled_at = cached_order.filled_at
                            if cached_order.price:
                                opening_trade.fill_price = cached_order.price
                            await opening_trade.asave(
                                update_fields=["status", "filled_at", "fill_price"]
                            )
                            logger.info(
                                f"Position {position.id}: Updated Trade {opening_trade.id} "
                                f"with fill data from TastyTradeOrderHistory"
                            )

                        # Transition position to open_full
                        if position.lifecycle_state == "pending_entry":
                            position.lifecycle_state = "open_full"
                            await position.asave(update_fields=["lifecycle_state"])
                            logger.info(f"Position {position.id}: Transitioned to open_full")
                            report["positions_fixed"] += 1

                        # Create profit targets if missing
                        if not position.profit_targets_created:
                            logger.info(
                                f"Position {position.id}: Creating missing profit targets..."
                            )
                            try:
                                order_service = OrderExecutionService(self.user)
                                result = await sync_to_async(
                                    order_service.create_profit_targets_sync
                                )(position, opening_trade.broker_order_id)

                                if result and result.get("status") == "success":
                                    order_ids = result.get("order_ids", [])
                                    if order_ids:
                                        # Update trade with profit target order IDs
                                        opening_trade.child_order_ids = order_ids
                                        await opening_trade.asave(update_fields=["child_order_ids"])

                                        logger.info(
                                            f"Position {position.id}: Created {len(order_ids)} "
                                            f"profit target orders: {order_ids}"
                                        )
                                        report["profit_targets_created"] += 1
                                else:
                                    error_msg = (
                                        result.get("message", "Unknown error")
                                        if result
                                        else "No result returned"
                                    )
                                    logger.warning(
                                        f"Position {position.id}: Failed to create profit targets: "
                                        f"{error_msg}"
                                    )
                                    report["errors"].append(
                                        {
                                            "position_id": position.id,
                                            "error": f"Profit target creation failed: {error_msg}",
                                        }
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Position {position.id}: Error creating profit targets: {e}",
                                    exc_info=True,
                                )
                                report["errors"].append(
                                    {
                                        "position_id": position.id,
                                        "error": f"Profit target error: {e!s}",
                                    }
                                )

                except Exception as e:
                    logger.error(
                        f"Position {position.id}: Error fixing stuck position: {e}", exc_info=True
                    )
                    report["errors"].append(
                        {"position_id": position.id, "error": f"Fix error: {e!s}"}
                    )

            if report["positions_fixed"] > 0:
                logger.info(
                    f"User {self.user.id}: Fixed {report['positions_fixed']} stuck positions, "
                    f"created {report['profit_targets_created']} profit target sets"
                )

        except Exception as e:
            logger.error(f"User {self.user.id}: Error in fix_stuck_positions: {e}", exc_info=True)
            report["errors"].append(str(e))

        return report

    async def fix_incomplete_profit_targets(self) -> dict:
        """
        Detect and fix positions with incomplete or missing profit targets.

        NOW VALIDATES AGAINST TASTYTRADE:
        - Checks if profit target orders actually exist at broker
        - Recreates orders that were deleted/cancelled
        - Verifies position still has open legs at broker

        For each open position:
        1. Check if profit_target_details has order IDs
        2. Verify those orders still exist at TastyTrade
        3. Verify the position still has open legs
        4. Recreate missing profit targets

        For Senex Trident: expects 3 profit targets (40%, 50%, 60%)
        For other strategies: verifies against strategy specification

        Returns:
            dict with fix report: {
                "positions_checked": 0,
                "incomplete_targets_fixed": 0,
                "missing_orders_recreated": 0,
                "errors": []
            }
        """
        from asgiref.sync import sync_to_async
        from tastytrade import Account

        from services.core.data_access import get_oauth_session
        from services.execution.order_service import OrderExecutionService
        from trading.models import Position, Trade

        report = {
            "positions_checked": 0,
            "incomplete_targets_fixed": 0,
            "missing_orders_recreated": 0,
            "errors": [],
        }

        try:
            # Get OAuth session for TastyTrade API
            session = await get_oauth_session(self.user)
            if not session:
                report["errors"].append("Unable to obtain TastyTrade session")
                return report

            # Get primary account
            account = await sync_to_async(
                lambda: self.user.trading_accounts.filter(is_primary=True).first()
            )()
            if not account:
                report["errors"].append("No primary trading account found")
                return report

            # Get TastyTrade account for API calls
            tt_account = await Account.a_get(session, account.account_number)

            # Find ALL open positions (full or partial) that are app-managed
            # Don't filter by profit_targets_created - we want to check all
            open_positions = await sync_to_async(list)(
                Position.objects.filter(
                    user=self.user,
                    trading_account=account,
                    lifecycle_state__in=["open_full", "open_partial"],
                    is_app_managed=True,
                )
                .exclude(strategy_type=None)  # Skip stock holdings
                .prefetch_related("trades")
            )

            if not open_positions:
                logger.debug(f"User {self.user.id}: No open positions to check")
                return report

            logger.info(
                f"User {self.user.id}: Checking {len(open_positions)} open positions "
                f"for profit target validity at TastyTrade..."
            )

            for position in open_positions:
                report["positions_checked"] += 1

                # Guard 4: Reload position to catch race conditions
                # Position may have been closed during earlier phases of sync
                fresh_position = await Position.objects.filter(
                    id=position.id
                ).afirst()
                if fresh_position is None:
                    logger.info(
                        f"Position {position.id} deleted during sync, skipping"
                    )
                    continue
                if fresh_position.lifecycle_state not in [
                    "open_full", "open_partial"
                ]:
                    logger.info(
                        f"Position {position.id} closed during sync "
                        f"(state={fresh_position.lifecycle_state}), "
                        f"skipping profit target check"
                    )
                    continue

                logger.info(
                    f"Position {position.id}: Starting check (strategy={position.strategy_type})"
                )

                try:
                    # Determine expected number of profit targets based on strategy
                    expected_target_count = self._get_expected_target_count(position.strategy_type)

                    if expected_target_count is None:
                        logger.info(
                            f"Position {position.id}: Unknown strategy {position.strategy_type}, "
                            f"skipping profit target verification"
                        )
                        continue

                    # Get expected spread types based on strategy
                    expected_spread_types = self._get_expected_spread_types(position.strategy_type)
                    if not expected_spread_types:
                        logger.info(
                            f"Position {position.id}: Unknown spread types for {position.strategy_type}, "
                            f"skipping profit target verification"
                        )
                        continue

                    # CRITICAL: Filter to only spreads that are actually still open
                    # Check position metadata to see which legs still exist
                    open_spread_types = await sync_to_async(
                        self._get_open_spread_types_from_position
                    )(position, expected_spread_types)

                    if not open_spread_types:
                        logger.info(
                            f"Position {position.id}: No open spreads detected (position may be fully closed), "
                            f"skipping profit target creation"
                        )
                        continue

                    # Update expected spread types to only include open ones
                    if len(open_spread_types) < len(expected_spread_types):
                        logger.info(
                            f"Position {position.id}: Only {len(open_spread_types)}/{len(expected_spread_types)} "
                            f"spreads are still open: {open_spread_types} "
                            f"(closed: {set(expected_spread_types) - set(open_spread_types)})"
                        )
                    expected_spread_types = open_spread_types

                    logger.info(
                        f"Position {position.id}: Checking profit targets "
                        f"(expected {len(expected_spread_types)} spreads: {expected_spread_types})"
                    )

                    # STEP 1: Check which profit targets exist in metadata
                    (
                        set(position.profit_target_details.keys())
                        if position.profit_target_details
                        else set()
                    )

                    # STEP 2: Verify each existing profit target order actually exists at TastyTrade
                    valid_spread_types = set()
                    invalid_order_ids = []

                    if position.profit_target_details:
                        for spread_type, details in position.profit_target_details.items():
                            # Check for manual skip flag (set via manual intervention)
                            if details.get("skip_recreation"):
                                skip_reason = details.get("skip_reason", "manual_skip")
                                logger.info(
                                    f"Position {position.id}: Profit target {spread_type} "
                                    f"marked skip_recreation=True ({skip_reason}) - skipping"
                                )
                                valid_spread_types.add(spread_type)
                                continue

                            order_id = details.get("order_id")
                            if not order_id:
                                # If profit_targets_created is True but order_id is null,
                                # the orders likely exist at the broker but we lost the reference
                                # (e.g., due to a race condition). Do NOT try to recreate - that
                                # will cause duplicate orders. Flag for manual review instead.
                                logger.error(
                                    f"Position {position.id}: Profit target {spread_type} has no order_id "
                                    f"but profit_targets_created=True. Orders may exist at broker. "
                                    f"MANUAL INVESTIGATION REQUIRED - not recreating to avoid duplicates."
                                )
                                # Mark as valid to prevent recreation
                                valid_spread_types.add(spread_type)
                                invalid_order_ids.append((spread_type, None, "missing_order_id"))
                                continue

                            # Check if order exists at TastyTrade
                            try:
                                order = tt_account.get_order(session, order_id)
                                if order:
                                    # Get status value (handle both enum and string)
                                    order_status = (
                                        order.status.value
                                        if hasattr(order.status, "value")
                                        else str(order.status)
                                    )

                                    # Order exists - check if it's still live (not filled/cancelled)
                                    if order_status in ["Live", "Received", "Queued"]:
                                        valid_spread_types.add(spread_type)
                                        logger.info(
                                            f"Position {position.id}: Profit target {spread_type} "
                                            f"order {order_id} is VALID ({order_status})"
                                        )
                                    elif order_status == "Filled":
                                        # CRITICAL: Profit target was FILLED - the spread closed!
                                        # This is SUCCESS, not an error. We need to:
                                        # 1. Update profit_target_details with fill info
                                        # 2. Update position lifecycle state
                                        # 3. Mark as valid (don't recreate!)
                                        valid_spread_types.add(spread_type)
                                        logger.info(
                                            f"Position {position.id}: Profit target {spread_type} "
                                            f"order {order_id} is FILLED - processing closure"
                                        )

                                        # Process the filled profit target
                                        await self._process_filled_profit_target(
                                            position, spread_type, order_id, order
                                        )
                                    else:
                                        # Order was cancelled/rejected/expired - may need recreation
                                        logger.warning(
                                            f"Position {position.id}: Profit target {spread_type} "
                                            f"order {order_id} is {order_status} - needs recreation"
                                        )
                                        invalid_order_ids.append(
                                            (spread_type, order_id, order_status)
                                        )
                                else:
                                    logger.warning(
                                        f"Position {position.id}: Profit target {spread_type} "
                                        f"order {order_id} not found at broker"
                                    )
                                    invalid_order_ids.append((spread_type, order_id, "not_found"))
                            except Exception as e:
                                logger.error(
                                    f"Position {position.id}: Error checking order {order_id}: {e}"
                                )
                                invalid_order_ids.append((spread_type, order_id, f"error: {e}"))

                    # STEP 3: Determine which spread types need to be (re)created
                    missing_spread_types = [
                        st for st in expected_spread_types if st not in valid_spread_types
                    ]

                    if missing_spread_types:
                        if invalid_order_ids:
                            logger.warning(
                                f"INVALID PROFIT TARGET ORDERS: Position {position.id} ({position.strategy_type}) "
                                f"has {len(invalid_order_ids)} invalid orders: {invalid_order_ids}"
                            )

                        # STEP 3.5: Before recreating, check if there's already a LIVE order at broker
                        # This handles race conditions where multiple orders were submitted
                        # and one succeeded while another was rejected (e.g., Position 50 scenario)
                        spreads_with_existing_live_orders = []
                        for spread_type in list(missing_spread_types):
                            existing_live_order_id = await self._find_existing_live_order_for_spread(
                                position, spread_type, tt_account, session
                            )
                            if existing_live_order_id:
                                logger.info(
                                    f"Position {position.id}: Found existing LIVE order {existing_live_order_id} "
                                    f"for {spread_type} - updating position instead of recreating"
                                )
                                # Update the position's order_id to point to the live order
                                await self._update_profit_target_order_id(
                                    position, spread_type, existing_live_order_id
                                )
                                spreads_with_existing_live_orders.append(spread_type)
                                valid_spread_types.add(spread_type)

                        # Remove spreads that we found live orders for
                        for spread_type in spreads_with_existing_live_orders:
                            missing_spread_types.remove(spread_type)

                        if not missing_spread_types:
                            logger.info(
                                f"Position {position.id}: All missing profit targets resolved by "
                                f"finding existing LIVE orders"
                            )
                            continue

                        report["missing_orders_recreated"] += len(missing_spread_types)

                        # CRITICAL: Check if position is in DTE automation mode
                        # If DTE <= threshold, the DTE manager handles closing, not profit targets
                        dte_automation = (position.metadata or {}).get("dte_automation", {})
                        last_processed_dte = dte_automation.get("last_processed_dte")
                        if last_processed_dte is not None:
                            logger.info(
                                f"Position {position.id}: In DTE automation mode "
                                f"(last_processed_dte={last_processed_dte}), "
                                f"skipping profit target recreation - DTE manager handles closing"
                            )
                            report.setdefault("skipped_dte_automation", 0)
                            report["skipped_dte_automation"] += 1
                            continue

                        logger.warning(
                            f"MISSING PROFIT TARGETS: Position {position.id} ({position.strategy_type}) "
                            f"missing {len(missing_spread_types)}/{len(expected_spread_types)} profit targets: "
                            f"{missing_spread_types}"
                        )

                        # Get the opening trade
                        opening_trade = await sync_to_async(
                            lambda: Trade.objects.filter(
                                position=position, trade_type="open"
                            ).first()
                        )()

                        if not opening_trade or not opening_trade.broker_order_id:
                            logger.error(
                                f"Position {position.id}: No opening trade or broker_order_id found"
                            )
                            report["errors"].append(
                                {"position_id": position.id, "error": "No opening trade found"}
                            )
                            continue

                        # Create the missing profit targets
                        logger.info(
                            f"Position {position.id}: Creating {len(missing_spread_types)} profit targets: "
                            f"{missing_spread_types}"
                        )

                        try:
                            order_service = OrderExecutionService(self.user)
                            result = await sync_to_async(order_service.create_profit_targets_sync)(
                                position,
                                opening_trade.broker_order_id,
                                preserve_existing=False,  # Replace all since we validated
                                filter_spread_types=missing_spread_types,
                            )

                            if result and result.get("status") == "success":
                                order_ids = result.get("order_ids", [])
                                if len(order_ids) == len(missing_spread_types):
                                    logger.info(
                                        f"Position {position.id}: Successfully created {len(missing_spread_types)} "
                                        f"missing profit targets: {order_ids}"
                                    )
                                    report["incomplete_targets_fixed"] += 1
                                else:
                                    logger.warning(
                                        f"Position {position.id}: Created {len(order_ids)}/{len(missing_spread_types)} "
                                        f"profit targets (still incomplete)"
                                    )
                                    report["errors"].append(
                                        {
                                            "position_id": position.id,
                                            "error": f"Created {len(order_ids)}/{len(missing_spread_types)} targets",
                                        }
                                    )
                            else:
                                error_msg = (
                                    result.get("message", "Unknown error")
                                    if result
                                    else "No result returned"
                                )
                                logger.error(
                                    f"Position {position.id}: Failed to create profit targets: {error_msg}"
                                )
                                report["errors"].append(
                                    {
                                        "position_id": position.id,
                                        "error": f"Creation failed: {error_msg}",
                                    }
                                )

                        except Exception as e:
                            logger.error(
                                f"Position {position.id}: Error creating profit targets: {e}",
                                exc_info=True,
                            )
                            report["errors"].append(
                                {"position_id": position.id, "error": f"Creation error: {e!s}"}
                            )

                except Exception as e:
                    logger.error(
                        f"Position {position.id}: Error checking profit targets: {e}", exc_info=True
                    )
                    report["errors"].append(
                        {"position_id": position.id, "error": f"Check error: {e!s}"}
                    )

            if report["incomplete_targets_fixed"] > 0:
                logger.info(
                    f"User {self.user.id}: Fixed {report['incomplete_targets_fixed']} positions "
                    f"with incomplete profit targets (checked {report['positions_checked']} total)"
                )

        except Exception as e:
            logger.error(
                f"User {self.user.id}: Error in fix_incomplete_profit_targets: {e}", exc_info=True
            )
            report["errors"].append(str(e))

        return report

    def _get_expected_target_count(self, strategy_type: str) -> int | None:
        """
        Get expected number of profit targets for a strategy.

        Args:
            strategy_type: Strategy identifier (e.g., "senex_trident", "iron_condor")

        Returns:
            Expected count or None if unknown strategy
        """
        # Senex Trident has 3 profit targets (40%, 50%, 60%)
        if strategy_type == "senex_trident":
            return 3

        # Iron Condor typically has 2 profit targets (call and put sides)
        if strategy_type in ["iron_condor", "short_iron_condor", "long_iron_condor"]:
            return 2

        # Most single spread strategies have 1 profit target
        if strategy_type in [
            "short_put_vertical",
            "short_call_vertical",
            "long_call_vertical",
            "long_put_vertical",
            "cash_secured_put",
            "covered_call",
        ]:
            return 1

        # Unknown strategy
        return None

    def _get_expected_spread_types(self, strategy_type: str) -> list[str] | None:
        """
        Get expected spread types for a strategy.

        Args:
            strategy_type: Strategy identifier (e.g., "senex_trident", "iron_condor")

        Returns:
            List of expected spread_type identifiers or None if unknown strategy
        """
        # Senex Trident has 3 profit targets with specific spread types
        if strategy_type == "senex_trident":
            return ["put_spread_1", "put_spread_2", "call_spread"]

        # Iron Condor has call and put sides
        if strategy_type in ["iron_condor", "short_iron_condor", "long_iron_condor"]:
            return ["put_spread", "call_spread"]

        # Vertical spread strategies have one spread type
        if strategy_type in [
            "short_put_vertical",
            "short_call_vertical",
            "long_call_vertical",
            "long_put_vertical",
        ]:
            return ["spread"]

        # Single leg strategies
        if strategy_type in ["cash_secured_put", "covered_call"]:
            return ["single_leg"]

        # Unknown strategy
        return None

    def _get_open_spread_types_from_position(
        self, position, expected_spread_types: list[str]
    ) -> list[str]:
        """
        Determine which spreads from a position are actually still open.

        Validates against position.metadata['legs'] to ensure we only create
        profit targets for spreads that actually have open legs.

        Args:
            position: Position object with metadata
            expected_spread_types: List of spread types defined by the strategy

        Returns:
            List of spread_type identifiers that are still open
        """
        metadata = position.metadata or {}
        legs = metadata.get("legs", [])

        if not legs:
            logger.warning(
                f"Position {position.id}: No legs found in metadata, cannot validate spreads"
            )
            return []

        leg_entries: list[dict] = []
        current_leg_symbols = set()

        for leg in legs:
            symbol = leg.get("symbol")
            if not symbol:
                continue

            normalized_symbol = symbol.strip()
            quantity = self._normalize_leg_quantity(leg)
            direction = self._infer_leg_direction(leg)

            if quantity <= 0:
                continue

            leg_entries.append(
                {"symbol": normalized_symbol, "quantity": quantity, "direction": direction}
            )
            current_leg_symbols.add(normalized_symbol)

        if not leg_entries:
            logger.warning(f"Position {position.id}: No valid leg symbols found in metadata")
            return []

        logger.debug(f"Position {position.id}: Current legs: {sorted(current_leg_symbols)}")

        open_spread_types = []

        # For Senex Trident, check which spreads are still open
        if position.strategy_type == "senex_trident":
            # Get the spread composition from metadata if available
            spread_legs = metadata.get("spread_legs", {})

            if spread_legs:
                # Use spread_legs mapping if available
                for spread_type in expected_spread_types:
                    spread_leg_symbols = [
                        (symbol or "").strip() for symbol in spread_legs.get(spread_type, [])
                    ]
                    spread_leg_symbols = [symbol for symbol in spread_leg_symbols if symbol]

                    if not spread_leg_symbols:
                        continue

                    if all(symbol in current_leg_symbols for symbol in spread_leg_symbols):
                        open_spread_types.append(spread_type)
                        logger.debug(
                            f"Position {position.id}: Spread {spread_type} is OPEN "
                            f"(legs: {spread_leg_symbols})"
                        )
                    else:
                        missing = [s for s in spread_leg_symbols if s not in current_leg_symbols]
                        logger.info(
                            f"Position {position.id}: Spread {spread_type} is CLOSED "
                            f"(missing legs: {missing})"
                        )
            else:
                put_counts = {"short": 0, "long": 0}
                call_counts = {"short": 0, "long": 0}

                for entry in leg_entries:
                    symbol = entry["symbol"]
                    direction = entry["direction"]
                    quantity = entry["quantity"]
                    tail = symbol[-9:] if len(symbol) >= 9 else symbol

                    if "P" in tail:
                        put_counts[direction] += quantity
                    elif "C" in tail:
                        call_counts[direction] += quantity

                call_spreads_open = min(call_counts["short"], call_counts["long"])
                if (
                    call_spreads_open >= 1
                    and "call_spread" in expected_spread_types
                ):
                    open_spread_types.append("call_spread")

                put_spreads_open = min(put_counts["short"], put_counts["long"])
                if put_spreads_open >= 2:
                    if "put_spread_1" in expected_spread_types:
                        open_spread_types.append("put_spread_1")
                    if "put_spread_2" in expected_spread_types:
                        open_spread_types.append("put_spread_2")
                elif put_spreads_open == 1 and "put_spread_1" in expected_spread_types:
                    open_spread_types.append("put_spread_1")

                if open_spread_types:
                    logger.info(
                        f"Position {position.id}: Detected open spreads (fallback method): "
                        f"{open_spread_types} "
                        f"(call spreads remaining: {call_spreads_open}, "
                        f"put spreads remaining: {put_spreads_open})"
                    )

        else:
            # For other strategies, assume all expected spreads are open
            # if the position itself is marked as open
            logger.debug(f"Position {position.id}: Non-Trident strategy, assuming all spreads open")
            open_spread_types = expected_spread_types

        return open_spread_types

    def _normalize_leg_quantity(self, leg: dict) -> int:
        """Normalize leg quantity to a positive integer for counting."""
        quantity = leg.get("quantity")

        if quantity in (None, ""):
            return 1

        try:
            qty = int(float(quantity))
        except (TypeError, ValueError):
            return 1

        return abs(qty)

    def _infer_leg_direction(self, leg: dict) -> str:
        """Infer whether a leg is short or long."""
        direction = str(leg.get("quantity_direction", "")).lower()
        if direction in ("short", "long"):
            return direction

        action = str(leg.get("action", "")).lower()
        if "sell" in action:
            return "short"
        if "buy" in action:
            return "long"

        quantity = leg.get("quantity")
        try:
            qty = float(quantity)
            if qty < 0:
                return "short"
            if qty > 0:
                return "long"
        except (TypeError, ValueError):
            pass

        return "long"

    async def _process_filled_profit_target(
        self,
        position,
        spread_type: str,
        order_id: str,
        order,
    ) -> None:
        """
        Process a filled profit target order discovered during reconciliation.

        This handles the case where:
        1. A profit target order filled at the broker
        2. The order history cache didn't get updated (pagination issue, timing, etc.)
        3. The PositionSyncService._reconcile_profit_target_fills() couldn't detect it
        4. This reconciliation service discovers the fill via direct API call

        Updates:
        - profit_target_details[spread_type].status = "filled"
        - profit_target_details[spread_type].filled_at
        - profit_target_details[spread_type].fill_price
        - profit_target_details[spread_type].realized_pnl
        - position.quantity (decrement by 1)
        - position.total_realized_pnl
        - position.lifecycle_state (open_full -> open_partial or closed)

        Args:
            position: Position object to update
            spread_type: Spread type identifier (e.g., "call_spread")
            order_id: TastyTrade order ID
            order: TastyTrade order object with fill data
        """
        from decimal import Decimal

        from django.db import transaction
        from django.utils import timezone as dj_timezone

        from asgiref.sync import sync_to_async

        from trading.models import Position, TastyTradeOrderHistory

        # Extract fill data from order
        fill_price = self._extract_fill_price_from_order(order)
        filled_at = self._extract_filled_at_from_order(order)

        # Look up submission timestamp from order history
        submitted_at = None
        try:
            order_history = await TastyTradeOrderHistory.objects.filter(
                broker_order_id=order_id
            ).afirst()
            if order_history and order_history.received_at:
                submitted_at = order_history.received_at
        except Exception as e:
            logger.warning(f"Position {position.id}: Error looking up submitted_at: {e}")

        @sync_to_async
        def _update_position_atomic():
            """Inner sync function that performs atomic database updates."""
            with transaction.atomic():
                # Refresh position from database to prevent stale data
                fresh_position = Position.objects.select_for_update().get(id=position.id)

                # Initialize profit_target_details if needed
                if not fresh_position.profit_target_details:
                    fresh_position.profit_target_details = {}

                # Get or create details for this spread type
                details = fresh_position.profit_target_details.setdefault(spread_type, {})

                # Skip if already processed
                if details.get("status") == "filled":
                    logger.info(
                        f"Position {position.id}: Spread {spread_type} already marked as filled, skipping"
                    )
                    return False

                # Mark as filled with timing data
                details["status"] = "filled"
                details["order_id"] = order_id
                if submitted_at:
                    details["submitted_at"] = submitted_at.isoformat()
                details["filled_at"] = (
                    filled_at.isoformat() if filled_at else dj_timezone.now().isoformat()
                )

                if fill_price is not None:
                    details["fill_price"] = float(abs(fill_price))

                # Calculate realized P&L
                original_credit = Decimal(str(details.get("original_credit", 0)))
                pnl = Decimal("0")
                if fill_price is not None and original_credit:
                    # P&L = (credit received - debit paid) * contracts * multiplier
                    pnl = (original_credit - abs(fill_price)) * Decimal("100")
                    details["realized_pnl"] = float(pnl)

                # Update position fields
                # Track original quantity for lifecycle state determination
                original_quantity = fresh_position.metadata.get(
                    "original_quantity", fresh_position.quantity
                )
                if "original_quantity" not in (fresh_position.metadata or {}):
                    if fresh_position.metadata is None:
                        fresh_position.metadata = {}
                    fresh_position.metadata["original_quantity"] = fresh_position.quantity
                    original_quantity = fresh_position.quantity

                # Decrement quantity (1 contract per spread for Senex Trident)
                new_quantity = max(0, fresh_position.quantity - 1)
                fresh_position.quantity = new_quantity
                fresh_position.total_realized_pnl = (
                    fresh_position.total_realized_pnl or Decimal("0")
                ) + pnl

                # Update lifecycle state
                if new_quantity == 0:
                    fresh_position.lifecycle_state = "closed"
                    fresh_position.closed_at = dj_timezone.now()
                    logger.info(
                        f"Position {position.id}: All contracts closed via reconciled profit target, "
                        f"state → closed, realized_pnl=${fresh_position.total_realized_pnl}"
                    )
                elif new_quantity < original_quantity:
                    fresh_position.lifecycle_state = "open_partial"
                    logger.info(
                        f"Position {position.id}: {spread_type} closed via reconciliation, "
                        f"{new_quantity}/{original_quantity} remaining, state → open_partial, "
                        f"P&L=${pnl}"
                    )

                # Save changes
                fresh_position.save(
                    update_fields=[
                        "quantity",
                        "total_realized_pnl",
                        "lifecycle_state",
                        "closed_at",
                        "profit_target_details",
                        "metadata",
                    ]
                )

                return True

        try:
            updated = await _update_position_atomic()
            if updated:
                logger.info(
                    f"Position {position.id}: Successfully processed filled profit target "
                    f"{spread_type} (order {order_id})"
                )
        except Exception as e:
            logger.error(
                f"Position {position.id}: Error processing filled profit target {spread_type}: {e}",
                exc_info=True,
            )

    def _extract_fill_price_from_order(self, order) -> "Decimal | None":
        """Extract the fill price from a TastyTrade order object."""
        from decimal import Decimal

        try:
            # Check if order has price attribute (the net credit/debit)
            if hasattr(order, "price") and order.price:
                return Decimal(str(order.price))

            # Try to calculate from leg fills
            if hasattr(order, "legs") and order.legs:
                total_value = Decimal("0")
                has_fills = False

                for leg in order.legs:
                    if hasattr(leg, "fills") and leg.fills:
                        has_fills = True
                        action = (
                            leg.action.value
                            if hasattr(leg.action, "value")
                            else str(leg.action)
                        )

                        for fill in leg.fills:
                            if hasattr(fill, "fill_price") and fill.fill_price:
                                price = Decimal(str(fill.fill_price))
                                qty = abs(
                                    Decimal(str(fill.quantity))
                                    if hasattr(fill, "quantity")
                                    else Decimal("1")
                                )

                                if "sell" in action.lower():
                                    total_value += price * qty
                                else:
                                    total_value -= price * qty

                if has_fills:
                    return total_value

        except Exception as e:
            logger.warning(f"Error extracting fill price from order: {e}")

        return None

    def _extract_filled_at_from_order(self, order):
        """Extract the filled_at timestamp from a TastyTrade order object."""
        try:
            # Check if order has terminal_at (when order reached terminal state)
            if hasattr(order, "terminal_at") and order.terminal_at:
                return order.terminal_at

            # Check leg fills for filled_at
            if hasattr(order, "legs") and order.legs:
                for leg in order.legs:
                    if hasattr(leg, "fills") and leg.fills:
                        for fill in leg.fills:
                            if hasattr(fill, "filled_at") and fill.filled_at:
                                return fill.filled_at

        except Exception as e:
            logger.warning(f"Error extracting filled_at from order: {e}")

        return None

    async def _find_existing_live_order_for_spread(
        self,
        position,
        spread_type: str,
        tt_account,
        session,
    ) -> str | None:
        """
        Search for an existing LIVE order at the broker for the given spread.

        This handles the race condition scenario where multiple orders were submitted
        for the same spread, one was recorded in the position (and got rejected),
        but another one actually went through and is live at the broker.

        IMPORTANT: When multiple positions have identical legs (e.g., two Senex Trident
        positions on the same underlying with same strikes), we must be careful to
        only return orders that belong to THIS position. We do this by:
        1. Filtering to orders created around the same time as this position
        2. Excluding orders already claimed by other positions

        Args:
            position: Position object
            spread_type: Spread type identifier (e.g., "put_spread_1")
            tt_account: TastyTrade account object
            session: OAuth session

        Returns:
            Order ID of the live order if found, None otherwise
        """
        from trading.models import Position as PositionModel
        from trading.models import TastyTradeOrderHistory

        try:
            # Get the leg symbols for this spread type from the position
            spread_legs = self._get_spread_leg_symbols(position, spread_type)
            if not spread_legs:
                logger.debug(
                    f"Position {position.id}: Could not determine leg symbols for {spread_type}"
                )
                return None

            # Get the position's opened_at time for filtering
            position_opened_at = position.opened_at
            if not position_opened_at:
                logger.debug(
                    f"Position {position.id}: No opened_at timestamp, cannot correlate orders"
                )
                return None

            # Search for LIVE orders that:
            # 1. Match the leg symbols
            # 2. Were created within a reasonable time window of position opening
            #    (allow 5 minutes before/after to handle timing differences)
            from datetime import timedelta

            time_window_start = position_opened_at - timedelta(minutes=5)
            time_window_end = position_opened_at + timedelta(minutes=5)

            # Get all order IDs already claimed by OTHER positions
            # This ensures we don't steal another position's order
            @sync_to_async
            def get_claimed_order_ids():
                claimed = set()
                other_positions = PositionModel.objects.filter(
                    symbol=position.symbol,
                    lifecycle_state__in=["open_full", "open_partial"],
                ).exclude(pk=position.id)

                for other_pos in other_positions:
                    if other_pos.profit_target_details:
                        for _st, details in other_pos.profit_target_details.items():
                            order_id = details.get("order_id")
                            if order_id:
                                claimed.add(str(order_id))
                return claimed

            claimed_order_ids = await get_claimed_order_ids()
            logger.debug(
                f"Position {position.id}: Order IDs already claimed by other positions: {claimed_order_ids}"
            )

            live_orders = await sync_to_async(
                lambda: list(
                    TastyTradeOrderHistory.objects.filter(
                        underlying_symbol=position.symbol,
                        status="Live",
                        received_at__gte=time_window_start,
                        received_at__lte=time_window_end,
                    ).order_by("received_at")  # Oldest first
                )
            )()

            for order in live_orders:
                # Skip orders already claimed by other positions
                if str(order.broker_order_id) in claimed_order_ids:
                    logger.debug(
                        f"Position {position.id}: Skipping order {order.broker_order_id} "
                        f"- already claimed by another position"
                    )
                    continue

                order_legs = order.order_data.get("legs", []) if order.order_data else []
                order_leg_symbols = {leg.get("symbol", "").strip() for leg in order_legs}

                # Check if order legs match our spread legs
                spread_leg_set = {s.strip() for s in spread_legs}
                if order_leg_symbols == spread_leg_set:
                    logger.info(
                        f"Position {position.id}: Found matching LIVE order {order.broker_order_id} "
                        f"for {spread_type} (created at {order.received_at}, position opened at {position_opened_at})"
                    )
                    return order.broker_order_id

            logger.debug(
                f"Position {position.id}: No matching unclaimed LIVE order found for {spread_type} "
                f"in time window {time_window_start} to {time_window_end}"
            )
            return None

        except Exception as e:
            logger.error(
                f"Position {position.id}: Error searching for existing live order: {e}",
                exc_info=True,
            )
            return None

    def _get_spread_leg_symbols(self, position, spread_type: str) -> list[str] | None:
        """
        Get the leg symbols for a specific spread type from the position metadata.

        For Senex Trident:
        - call_spread: 2 call legs
        - put_spread_1: 2 put legs (higher strikes for 40% target)
        - put_spread_2: same 2 put legs (for 60% target)

        Returns list of OCC symbols for the spread legs, or None if not determinable.
        """
        legs = (position.metadata or {}).get("legs", [])
        if not legs:
            return None

        # Separate calls and puts
        calls = [leg.get("symbol") for leg in legs if "C0" in leg.get("symbol", "")]
        puts = [leg.get("symbol") for leg in legs if "P0" in leg.get("symbol", "")]

        if spread_type == "call_spread":
            return calls if len(calls) == 2 else None
        if spread_type in ["put_spread_1", "put_spread_2"]:
            # For Senex Trident, there are 4 put legs (2 spreads with same strikes)
            # Return the unique put symbols (should be 2)
            unique_puts = list(set(puts))
            return unique_puts if len(unique_puts) == 2 else None

        return None

    async def _update_profit_target_order_id(
        self,
        position,
        spread_type: str,
        new_order_id: str,
    ) -> None:
        """
        Update the position's profit_target_details with a new order_id for a spread.

        This is used when we discover that the position points to a rejected order
        but there's actually a live order at the broker for the same spread.

        Args:
            position: Position object to update
            spread_type: Spread type identifier (e.g., "put_spread_1")
            new_order_id: The correct order ID to use
        """
        from django.db import transaction

        @sync_to_async
        def _update_atomic():
            with transaction.atomic():
                from trading.models import Position as PositionModel

                fresh_position = PositionModel.objects.select_for_update().get(
                    pk=position.id
                )

                if not fresh_position.profit_target_details:
                    fresh_position.profit_target_details = {}

                if spread_type not in fresh_position.profit_target_details:
                    fresh_position.profit_target_details[spread_type] = {}

                old_order_id = fresh_position.profit_target_details[spread_type].get(
                    "order_id"
                )
                fresh_position.profit_target_details[spread_type]["order_id"] = new_order_id

                fresh_position.save(update_fields=["profit_target_details"])

                logger.info(
                    f"Position {position.id}: Updated {spread_type} order_id from "
                    f"{old_order_id} to {new_order_id}"
                )

        try:
            await _update_atomic()
        except Exception as e:
            logger.error(
                f"Position {position.id}: Failed to update {spread_type} order_id: {e}",
                exc_info=True,
            )

    async def _get_commission_for_order(self, broker_order_id: str) -> "Decimal | None":
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

        from asgiref.sync import sync_to_async

        from trading.models import TastyTradeTransaction

        try:
            order_id_int = int(broker_order_id)
        except (ValueError, TypeError):
            return None

        @sync_to_async
        def _get_commission():
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

        return await _get_commission()
