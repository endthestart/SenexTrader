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
                                await position.asave()
                                report["positions_updated"] += 1
                                logger.info(
                                    f"User {self.user.id}: Updated position {position.id} "
                                    "to open_full"
                                )

                except Trade.DoesNotExist:
                    # Orphaned order - exists at broker but not in our DB
                    logger.warning(
                        f"User {self.user.id}: Found orphaned order {order.id} "
                        f"(status={order_status}, symbol={order.underlying_symbol})"
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
        - Uses CachedOrder as source of truth (TastyTrade data already synced locally)
        - Detects positions in pending_entry with filled opening trades
        - Updates Trade.filled_at from CachedOrder
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
        from trading.models import CachedOrder, Position, Trade

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

                    # Check CachedOrder for fill status (source of truth)
                    try:
                        cached_order = await CachedOrder.objects.aget(
                            broker_order_id=opening_trade.broker_order_id
                        )
                    except CachedOrder.DoesNotExist:
                        logger.debug(
                            f"Position {position.id}: No cached order found for {opening_trade.broker_order_id}"
                        )
                        continue

                    # If order is filled on TastyTrade, fix the stuck state
                    if cached_order.status.lower() == "filled":
                        logger.info(
                            f"🔧 STUCK POSITION DETECTED: Position {position.id} "
                            f"in pending_entry but order {cached_order.broker_order_id} "
                            f"is filled on TastyTrade (filled_at={cached_order.filled_at})"
                        )

                        # Update Trade with fill data from CachedOrder
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
                                f"with fill data from CachedOrder"
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
        Detect and fix positions with incomplete profit targets.

        Checks positions in open_full state where profit_targets_created=True
        but the actual number of profit targets is less than expected for the strategy.

        For Senex Trident: expects 3 profit targets (40%, 50%, 60%)
        For other strategies: verifies against strategy specification

        Returns:
            dict with fix report: {
                "positions_checked": 0,
                "incomplete_targets_fixed": 0,
                "errors": []
            }
        """
        from asgiref.sync import sync_to_async

        from services.execution.order_service import OrderExecutionService
        from trading.models import Position, Trade

        report = {
            "positions_checked": 0,
            "incomplete_targets_fixed": 0,
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

            # Find positions in open_full with profit_targets_created=True
            open_positions = await sync_to_async(list)(
                Position.objects.filter(
                    user=self.user,
                    trading_account=account,
                    lifecycle_state="open_full",
                    is_app_managed=True,
                    profit_targets_created=True,
                )
                .exclude(strategy_type=None)  # Skip stock holdings
                .prefetch_related("trades")
            )

            if not open_positions:
                logger.debug(f"User {self.user.id}: No open positions with profit targets to check")
                return report

            logger.info(
                f"User {self.user.id}: Checking {len(open_positions)} open positions "
                f"for incomplete profit targets..."
            )

            for position in open_positions:
                report["positions_checked"] += 1

                try:
                    # Determine expected number of profit targets based on strategy
                    expected_target_count = self._get_expected_target_count(position.strategy_type)

                    if expected_target_count is None:
                        logger.debug(
                            f"Position {position.id}: Unknown strategy {position.strategy_type}, "
                            f"skipping profit target verification"
                        )
                        continue

                    # Get expected spread types based on strategy
                    expected_spread_types = self._get_expected_spread_types(position.strategy_type)
                    if not expected_spread_types:
                        logger.debug(
                            f"Position {position.id}: Unknown spread types for {position.strategy_type}, "
                            f"skipping profit target verification"
                        )
                        continue

                    # Determine which spread types are missing
                    existing_spread_types = (
                        set(position.profit_target_details.keys())
                        if position.profit_target_details
                        else set()
                    )
                    missing_spread_types = [
                        st for st in expected_spread_types if st not in existing_spread_types
                    ]

                    if missing_spread_types:
                        logger.warning(
                            f"🔍 INCOMPLETE PROFIT TARGETS: Position {position.id} ({position.strategy_type}) "
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

                        # Create only the missing profit targets
                        logger.info(
                            f"Position {position.id}: Creating {len(missing_spread_types)} missing profit targets: "
                            f"{missing_spread_types}"
                        )

                        try:
                            order_service = OrderExecutionService(self.user)
                            result = await sync_to_async(order_service.create_profit_targets_sync)(
                                position,
                                opening_trade.broker_order_id,
                                preserve_existing=True,
                                filter_spread_types=missing_spread_types,
                            )

                            if result and result.get("status") == "success":
                                order_ids = result.get("order_ids", [])
                                if len(order_ids) == len(missing_spread_types):
                                    logger.info(
                                        f"Position {position.id}: ✅ Successfully created {len(missing_spread_types)} "
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
