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

            # Fetch order history for past 7 days
            start_date = (timezone.now() - timedelta(days=7)).date()
            tt_account = await Account.a_get(session, account.account_number)
            order_history = await tt_account.a_get_order_history(session, start_date=start_date)

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
                                    # Order exists - check if it's still live (not filled/cancelled)
                                    if order.status in ["Live", "Received", "Queued"]:
                                        valid_spread_types.add(spread_type)
                                        logger.info(
                                            f"Position {position.id}: Profit target {spread_type} "
                                            f"order {order_id} is VALID ({order.status})"
                                        )
                                    else:
                                        # Order was filled/cancelled - should recreate
                                        logger.warning(
                                            f"Position {position.id}: Profit target {spread_type} "
                                            f"order {order_id} is {order.status} - needs recreation"
                                        )
                                        invalid_order_ids.append(
                                            (spread_type, order_id, order.status)
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
                            report["missing_orders_recreated"] += len(
                                [x for x in invalid_order_ids if x[0] in missing_spread_types]
                            )

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
            "bull_put_spread",
            "bear_call_spread",
            "bull_call_spread",
            "bear_put_spread",
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

        # Most single spread strategies have one spread type
        if strategy_type in [
            "bull_put_spread",
            "bear_call_spread",
            "bull_call_spread",
            "bear_put_spread",
        ]:
            return ["spread"]  # Generic spread identifier

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

        # Get leg symbols currently in position
        current_leg_symbols = {leg.get("symbol") for leg in legs if leg.get("symbol")}

        if not current_leg_symbols:
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
                    spread_leg_symbols = spread_legs.get(spread_type, [])
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
                # Fallback: Analyze by option type if spread_legs not available
                # Count puts and calls
                puts = [s for s in current_leg_symbols if "P" in s[-9:]]  # Put indicator
                calls = [s for s in current_leg_symbols if "C" in s[-9:]]  # Call indicator

                logger.debug(
                    f"Position {position.id}: Detected {len(puts)} puts, {len(calls)} calls"
                )

                # Senex Trident: 2 put spreads (4 put legs) + 1 call spread (2 call legs)
                # If we have 2+ calls, call spread is open
                if len(calls) >= 2 and "call_spread" in expected_spread_types:
                    open_spread_types.append("call_spread")

                # If we have 4 puts, both put spreads are open
                # If we have 2 puts, only one put spread is open
                if len(puts) >= 4:
                    if "put_spread_1" in expected_spread_types:
                        open_spread_types.append("put_spread_1")
                    if "put_spread_2" in expected_spread_types:
                        open_spread_types.append("put_spread_2")
                elif len(puts) >= 2:
                    # Only one put spread open - prefer put_spread_1
                    if "put_spread_1" in expected_spread_types:
                        open_spread_types.append("put_spread_1")

                if open_spread_types:
                    logger.info(
                        f"Position {position.id}: Detected open spreads (fallback method): "
                        f"{open_spread_types}"
                    )

        else:
            # For other strategies, assume all expected spreads are open
            # if the position itself is marked as open
            logger.debug(f"Position {position.id}: Non-Trident strategy, assuming all spreads open")
            open_spread_types = expected_spread_types

        return open_spread_types
