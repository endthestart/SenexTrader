"""Days-to-expiration (DTE) lifecycle automation utilities."""

from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from services.core.logging import get_logger
from services.execution.order_service import OrderExecutionService
from services.orders.cancellation import OrderCancellationService
from services.orders.spec import OrderLeg, OrderSpec
from services.orders.utils.order_builder_utils import build_closing_spread_legs
from services.sdk.trading_utils import PriceEffect
from trading.models import Position, Trade

logger = get_logger(__name__)


OPEN_STATES = {"open_full", "open_partial", "closing"}


class DTEManager:
    """Encapsulates DTE threshold evaluation and automated closing workflows."""

    def __init__(self, user) -> None:
        self.user = user
        self.order_service = OrderExecutionService(user)
        self.cancellation_service = OrderCancellationService()

    def calculate_current_dte(self, position: Position) -> int | None:
        """Return integer DTE for the position or ``None`` if unavailable."""
        metadata = position.metadata or {}
        expiration = metadata.get("expiration")
        if not expiration:
            return None

        try:
            exp_date = datetime.fromisoformat(expiration).date()
        except ValueError:
            logger.warning(
                "Position %s has invalid expiration metadata: %s", position.id, expiration
            )
            return None

        today = timezone.now().date()
        return (exp_date - today).days

    def get_dte_threshold(self, position: Position) -> int:
        metadata = position.metadata or {}
        strategy_threshold = metadata.get("dte_close")
        if strategy_threshold is not None:
            try:
                return int(strategy_threshold)
            except (TypeError, ValueError):
                logger.warning(
                    "Position %s has invalid dte_close value: %s", position.id, strategy_threshold
                )
        # Default aligns with Senex Trident configuration
        return 7

    async def close_position_at_dte(self, position: Position, current_dte: int) -> bool:
        """Attempt to submit closing order with idempotency and retry handling"""
        metadata = position.metadata or {}
        dte_state = metadata.setdefault("dte_automation", {})

        last_processed_dte = dte_state.get("last_processed_dte")
        current_order_id = dte_state.get("current_order_id")
        retry_count = dte_state.get("retry_count", 0)

        # IDEMPOTENCY: Check if we already processed this DTE
        if last_processed_dte == current_dte and current_order_id:
            # Verify order still exists at broker
            order_status = await self._check_order_status_at_broker(current_order_id)

            if order_status in ["live", "working", "routed"]:
                logger.info(
                    f"Position {position.id}: DTE={current_dte} already processed, "
                    f"order {current_order_id} still working - skipping"
                )
                return False  # Don't create duplicate
            if order_status == "filled":
                logger.info(f"Position {position.id}: DTE close order {current_order_id} filled")
                return True
            if order_status in ["rejected", "cancelled"]:
                logger.warning(
                    f"Position {position.id}: DTE close order {current_order_id} was {order_status} "
                    f"- will retry (attempt {retry_count + 1}/3)"
                )
                # Fall through to retry logic

        # DTE ESCALATION: DTE decreased (7→6→5) - cancel old order and place new
        if last_processed_dte and last_processed_dte > current_dte:
            logger.info(
                f"Position {position.id}: DTE escalated from {last_processed_dte} to {current_dte} "
                f"- replacing order"
            )
            retry_count = 0  # Reset retries on escalation

        # RETRY LIMIT: Check if exceeded max retries
        if retry_count >= 3:
            error_msg = (
                f"Position {position.id}: Failed to close after 3 retries at DTE={current_dte}. "
                f"Last error: {dte_state.get('last_error', 'Unknown')}"
            )
            logger.error(error_msg)

            # Send email notification to user
            await self._send_dte_failure_notification(position, current_dte, error_msg)

            # Don't retry again this hour - wait for next hourly run
            return False

        # Validate metadata
        strikes = metadata.get("strikes", {})
        expiration = metadata.get("expiration")
        if not strikes or not expiration:
            error_msg = f"Position {position.id} missing strikes/expiration metadata"
            logger.error(error_msg)
            await self._send_dte_failure_notification(position, current_dte, error_msg)
            return False

        # Build closing legs
        closing_legs = self._build_closing_legs(position)
        if not closing_legs:
            error_msg = f"Position {position.id} has no closing legs configured"
            logger.error(error_msg)
            await self._send_dte_failure_notification(position, current_dte, error_msg)
            return False

        # Cancel ALL existing orders (opening trades + unfilled profit targets)
        cancelled_targets = await self._cancel_open_trades(position)

        # Determine pricing with cancelled targets for validation
        limit_price, order_type, price_effect = self._determine_close_parameters(
            position, current_dte, cancelled_targets
        )

        # Create Trade record FIRST (before submitting order) with a temporary order ID
        # This ensures our system knows this is a closing trade
        temp_order_id = f"pending_dte_close_{timezone.now().timestamp()}"
        quantity = sum(abs(leg.quantity) for leg in closing_legs)
        snapshot = {
            "submitted_at": timezone.now().isoformat(),
            "legs": [leg.__dict__ for leg in closing_legs],
            "trigger": "dte_close",
            "dte": current_dte,
            "cancelled_targets": cancelled_targets,  # Track what we cancelled
        }
        snapshot["limit_price"] = str(limit_price)
        snapshot["order_type"] = order_type

        # Create the Trade record with trade_type="close" BEFORE submitting
        trade = await Trade.objects.acreate(
            user=self.user,
            position=position,
            trading_account=position.trading_account,
            broker_order_id=temp_order_id,  # Temporary ID, will update after submission
            trade_type="close",  # CRITICAL: Mark as closing trade
            order_legs=[leg.__dict__ for leg in closing_legs],
            quantity=quantity,
            status="pending",
            lifecycle_event="dte_close",
            lifecycle_snapshot=snapshot,
            order_type=order_type,
        )

        # Build and submit order
        order_spec = OrderSpec(
            legs=closing_legs,
            limit_price=limit_price,
            order_type=order_type,
            time_in_force="DAY",
            description=f"DTE auto-close {position.id} ({position.symbol}) DTE={current_dte}",
            price_effect=price_effect,
        )

        try:
            order_id = await self.order_service.execute_order_spec(order_spec)
        except Exception as e:
            error_msg = f"Failed to submit DTE close order: {e}"
            logger.error(f"Position {position.id}: {error_msg}", exc_info=True)

            # Update Trade record with error
            trade.status = "rejected"
            trade.error_message = str(e)
            await trade.asave(update_fields=["status", "error_message"])

            # Update state with error
            dte_state.update(
                {
                    "last_processed_dte": current_dte,
                    "retry_count": retry_count + 1,
                    "last_error": str(e),
                    "last_attempt_at": timezone.now().isoformat(),
                }
            )
            position.metadata = metadata
            await position.asave(update_fields=["metadata"])
            return False

        if not order_id:
            error_msg = "Order submission returned None"
            logger.error(f"Position {position.id}: {error_msg}")

            # Update Trade record with error
            trade.status = "rejected"
            trade.metadata["error_message"] = error_msg
            await trade.asave(update_fields=["status", "metadata"])

            dte_state.update(
                {
                    "last_processed_dte": current_dte,
                    "retry_count": retry_count + 1,
                    "last_error": error_msg,
                    "last_attempt_at": timezone.now().isoformat(),
                }
            )
            position.metadata = metadata
            await position.asave(update_fields=["metadata"])
            return False

        # Update Trade record with actual order ID
        trade.broker_order_id = order_id
        trade.status = "submitted"
        await trade.asave(update_fields=["broker_order_id", "status"])

        # Update position state
        position.lifecycle_state = "closing"
        dte_state.update(
            {
                "last_processed_dte": current_dte,
                "dte": current_dte,
                "current_order_id": order_id,
                "order_id": order_id,
                "current_limit_price": str(limit_price),
                "order_placed_at": timezone.now().isoformat(),
                "retry_count": 0,  # Reset on success
                "last_error": None,
            }
        )

        # Track cancelled profit targets (if any)
        if cancelled_targets:
            dte_state["cancelled_profit_targets"] = cancelled_targets

        position.metadata = metadata
        await position.asave(update_fields=["lifecycle_state", "metadata"])

        logger.info(
            f"Position {position.id}: DTE close order placed - "
            f"order_id={order_id}, DTE={current_dte}, limit=${limit_price}"
        )
        return True

    async def _record_closing_trade(
        self, position: Position, closing_legs: list[OrderLeg], order_id: str
    ) -> None:
        quantity = sum(abs(leg.quantity) for leg in closing_legs)
        snapshot = {
            "submitted_at": timezone.now().isoformat(),
            "legs": [leg.__dict__ for leg in closing_legs],
            "trigger": "dte_close",
        }
        await Trade.objects.acreate(
            user=self.user,
            position=position,
            trading_account=position.trading_account,
            broker_order_id=order_id,
            trade_type="close",
            order_legs=[leg.__dict__ for leg in closing_legs],
            quantity=quantity,
            status="submitted",
            lifecycle_event="dte_close",
            lifecycle_snapshot=snapshot,
        )

    async def _cancel_open_trades(self, position: Position) -> dict:
        """
        Cancel ALL working orders: opening trades AND unfilled profit targets.

        Returns dict of cancelled profit targets for tracking in metadata.
        """
        # 1. Cancel opening trades (existing logic)
        open_trades = [
            trade
            async for trade in position.trades.filter(
                status__in=["pending", "submitted", "routed", "live", "working"]
            )
        ]
        for trade in open_trades:
            await self.cancellation_service.cancel_trade(
                trade.id, self.user, reason="dte_automation"
            )

        # 2. Cancel unfilled profit targets from position.profit_target_details
        # Use profit_target_details as source of truth (not child_order_ids which is stale)
        profit_targets = position.profit_target_details or {}
        cancelled_targets = {}

        for spread_type, target_details in profit_targets.items():
            # Skip if already filled or cancelled
            status = target_details.get("status")
            if status in ["filled", "cancelled", "cancelled_dte_automation"]:
                logger.info(
                    f"Position {position.id}: Skipping {spread_type} profit target "
                    f"(status={status})"
                )
                continue

            order_id = target_details.get("order_id")
            if not order_id:
                logger.warning(
                    f"Position {position.id}: {spread_type} has no order_id in profit_target_details"
                )
                continue

            # Cancel at broker
            try:
                success = await self._cancel_child_order_at_broker(order_id)
                if success:
                    # Update profit target status in position metadata
                    await self._update_profit_target_status(
                        position, order_id, status="cancelled_dte_automation"
                    )

                    # Track cancellation details
                    cancelled_targets[spread_type] = {
                        "order_id": order_id,
                        "original_percent": target_details.get("percent"),
                        "original_target_price": target_details.get("target_price"),
                        "cancelled_at": timezone.now().isoformat(),
                        "reason": f"dte_replacement_{position.metadata.get('dte_automation', {}).get('last_processed_dte', 'unknown')}",
                    }

                    logger.info(
                        f"Position {position.id}: Cancelled {spread_type} profit target "
                        f"order {order_id}"
                    )
            except Exception as e:
                logger.warning(
                    f"Position {position.id}: Failed to cancel {spread_type} profit target {order_id}: {e}"
                )

        return cancelled_targets

    def _build_closing_legs(self, position: Position) -> list[OrderLeg]:
        metadata = position.metadata or {}
        expiration = metadata.get("expiration")
        strikes = metadata.get("strikes", {})
        if not expiration:
            return []

        try:
            exp_date = datetime.fromisoformat(expiration).date()
        except ValueError:
            return []

        quantity = position.number_of_spreads or 1

        legs: list[OrderLeg] = []
        if strikes.get("short_put") and strikes.get("long_put"):
            legs.extend(
                build_closing_spread_legs(
                    position.symbol,
                    exp_date,
                    "put_spread_1",
                    {
                        "short_put": Decimal(str(strikes["short_put"])),
                        "long_put": Decimal(str(strikes["long_put"])),
                    },
                    quantity=quantity,
                )
            )
        if strikes.get("short_call") and strikes.get("long_call"):
            legs.extend(
                build_closing_spread_legs(
                    position.symbol,
                    exp_date,
                    "call_spread",
                    {
                        "short_call": Decimal(str(strikes["short_call"])),
                        "long_call": Decimal(str(strikes["long_call"])),
                    },
                    quantity=quantity,
                )
            )
        return legs

    def _determine_close_parameters(
        self, position: Position, current_dte: int, cancelled_targets: dict | None = None
    ) -> tuple[Decimal, str, str]:
        """
        Smart pricing based on position type, DTE urgency, and cancelled profit targets.

        Args:
            position: The position to close
            current_dte: Current days to expiration
            cancelled_targets: Dict of cancelled profit targets from _cancel_open_trades()
        """
        entry_price = Decimal(str(position.avg_price or 0))
        spread_width = Decimal(str(position.spread_width or 3))
        is_credit_position = position.opening_price_effect == "Credit"

        # Log the values we're using for calculation
        logger.info(
            f"Position {position.id}: Pricing calculation - "
            f"entry_price=${entry_price}, spread_width=${spread_width}, "
            f"is_credit={is_credit_position}"
        )

        # For credit spreads: entry_price = credit received, max_loss = width - credit
        # For debit spreads: entry_price = debit paid, max_value = width
        if is_credit_position:
            max_loss_per_spread = spread_width - entry_price
            logger.info(
                f"Position {position.id}: Credit spread max_loss = "
                f"${spread_width} - ${entry_price} = ${max_loss_per_spread}"
            )
        else:
            max_value_per_spread = spread_width

        # DTE 4-7: Progressive Escalation to Eliminate Risk
        # Rationale: Assignment risk increases exponentially as DTE → 0.
        # We prefer controlled losses over assignment complications.
        #
        # For CREDIT spreads, close price = entry_price + (% of max_loss)
        # Example: $3 wide spread, $1.50 credit, max_loss = $1.50
        #   DTE 7: Pay $1.50 (breakeven - entry price)
        #   DTE 6: Pay $1.50 + 70% × $1.50 = $2.55 (accept 70% of max loss)
        #   DTE 5: Pay $1.50 + 80% × $1.50 = $2.70 (accept 80% of max loss)
        #   DTE 4: Pay $1.50 + 90% × $1.50 = $2.85 (accept 90% of max loss)
        #   DTE 3: Pay $3.00 (full spread width - accept max loss to guarantee exit)
        #
        # For DEBIT spreads, close price = entry_price - (% of entry)
        # Example: $3 wide spread, $2.00 debit paid
        #   DTE 7: Accept $2.00 (breakeven - entry price)
        #   DTE 6: Accept $1.40 (70% of entry - accept 30% loss)
        #   DTE 5: Accept $1.00 (50% of entry - accept 50% loss)
        #   DTE 4: Accept $0.40 (20% of entry - accept 80% loss)
        #   DTE 3: Accept $0.05 (near worthless - accept total loss)

        if is_credit_position:
            # Credit spread: We sold for entry_price, now paying debit to close
            if current_dte <= 3:
                # URGENT: Pay full spread width to guarantee exit
                limit_price = spread_width
                logger.info(
                    f"Position {position.id}: DTE={current_dte} URGENT - "
                    f"paying full spread width ${spread_width} to guarantee exit"
                )
            elif current_dte == 4:
                # Accept 90% of max loss
                limit_price = entry_price + max_loss_per_spread * Decimal("0.90")
            elif current_dte == 5:
                # Accept 80% of max loss
                limit_price = entry_price + max_loss_per_spread * Decimal("0.80")
            elif current_dte == 6:
                # Accept 70% of max loss
                limit_price = entry_price + max_loss_per_spread * Decimal("0.70")
            else:  # DTE 7+
                # Breakeven - pay back what we received
                limit_price = entry_price

            limit_price = max(limit_price, Decimal("0.10"))  # Min $0.10

        else:
            # Debit spread: We paid entry_price, now selling to close (receiving credit)
            # Max loss = entry_price (lose entire debit paid)
            # Formula: sell_price = entry_price - (% × max_loss)
            # Example: $3 wide spread, $1.50 debit paid, max_loss = $1.50
            #   DTE 7: Sell for $1.50 (breakeven)
            #   DTE 6: Sell for $1.50 - (0.70 × $1.50) = $0.45 (accept 70% of max loss)
            #   DTE 5: Sell for $1.50 - (0.80 × $1.50) = $0.30 (accept 80% of max loss)
            #   DTE 4: Sell for $1.50 - (0.90 × $1.50) = $0.15 (accept 90% of max loss)
            #   DTE ≤3: Sell for $0.00 (accept 100% loss - let expire or close for nothing)
            max_loss_debit = entry_price  # Max loss is the debit paid

            if current_dte <= 3:
                # URGENT: Accept total loss to guarantee exit
                limit_price = Decimal("0.00")
                logger.info(
                    f"Position {position.id}: DTE={current_dte} URGENT - "
                    f"accepting $0 to guarantee exit (total loss)"
                )
            elif current_dte == 4:
                # Accept 90% of max loss
                limit_price = entry_price - max_loss_debit * Decimal("0.90")
            elif current_dte == 5:
                # Accept 80% of max loss
                limit_price = entry_price - max_loss_debit * Decimal("0.80")
            elif current_dte == 6:
                # Accept 70% of max loss
                limit_price = entry_price - max_loss_debit * Decimal("0.70")
            else:  # DTE 7+
                # Breakeven - get back what we paid
                limit_price = entry_price

            limit_price = max(limit_price, Decimal("0.00"))  # Can go to $0 for debit spreads

        # VALIDATION: Ensure closing price is higher than cancelled profit targets
        # This prevents us from closing at a price lower than what we were targeting
        if cancelled_targets and is_credit_position:
            max_target_price = Decimal("0")
            for _spread_type, target_info in cancelled_targets.items():
                target_price = Decimal(str(target_info.get("original_target_price", 0)))
                max_target_price = max(max_target_price, target_price)

            # For credit spreads, closing price must be at least 10% higher than highest profit target
            # This ensures we're actually closing due to risk, not just hitting profit target
            if max_target_price > 0:
                min_close_price = max_target_price * Decimal("1.10")
                if limit_price < min_close_price:
                    logger.warning(
                        f"Position {position.id}: Adjusting close price from ${limit_price} "
                        f"to ${min_close_price} (10% above profit target ${max_target_price})"
                    )
                    limit_price = min_close_price

        logger.info(
            f"Position {position.id}: DTE={current_dte}, "
            f"{'Credit' if is_credit_position else 'Debit'} spread, "
            f"limit_price=${limit_price}"
        )

        return (
            limit_price.quantize(Decimal("0.01")),
            "LIMIT",
            self._price_effect_for_close(position),
        )

    def _price_effect_for_close(self, position: Position) -> str:
        return (
            PriceEffect.DEBIT.value
            if position.opening_price_effect == PriceEffect.CREDIT.value
            else PriceEffect.CREDIT.value
        )

    async def _cancel_child_order_at_broker(self, order_id: str) -> bool:
        """Cancel single order at broker via TastyTrade API"""
        from tastytrade import Account
        from tastytrade.utils import TastytradeError

        from services.core.data_access import get_oauth_session, get_primary_tastytrade_account

        session = await get_oauth_session(self.user)
        account = await get_primary_tastytrade_account(self.user)

        if not session or not account:
            logger.error(f"Failed to get session/account for cancelling order {order_id}")
            return False

        try:
            tt_account = await Account.a_get(session, account.account_number)
            await tt_account.a_delete_order(session, order_id)
            logger.info(f"Cancelled profit target order {order_id}")
            return True
        except TastytradeError as e:
            if "not found" in str(e).lower() or "404" in str(e):
                # Already filled or cancelled
                logger.info(f"Order {order_id} not found at broker (already filled/cancelled)")
                return True
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def _update_profit_target_status(
        self, position: Position, order_id: str, status: str
    ) -> None:
        """Update profit_target_details with cancelled status"""
        details = position.profit_target_details or {}

        for _spread_type, target_info in details.items():
            if target_info.get("order_id") == order_id:
                target_info["status"] = status
                target_info["cancelled_at"] = timezone.now().isoformat()
                target_info["cancellation_reason"] = "dte_automation"
                break

        position.profit_target_details = details
        # Keep profit_targets_created = True (per user feedback)
        await position.asave(update_fields=["profit_target_details"])

    async def _check_order_status_at_broker(self, order_id: str) -> str | None:
        """Query broker for current order status"""
        from tastytrade import Account

        from services.core.data_access import get_oauth_session, get_primary_tastytrade_account

        try:
            session = await get_oauth_session(self.user)
            account = await get_primary_tastytrade_account(self.user)

            if not session or not account:
                logger.error("Failed to get session/account for checking order status")
                return None

            tt_account = await Account.a_get(session, account.account_number)
            order = await tt_account.a_get_order(session, order_id)
            return (
                order.status.value.lower()
                if hasattr(order.status, "value")
                else str(order.status).lower()
            )
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                return "not_found"
            logger.error(f"Failed to check order status for {order_id}: {e}")
            return None

    async def _send_dte_failure_notification(
        self, position: Position, current_dte: int, error_message: str
    ) -> None:
        """Send email to user when DTE close repeatedly fails"""
        from services.notifications.service import NotificationService

        notification = NotificationService(self.user)
        await notification.send_notification(
            message=f"DTE Auto-Close Failed: Position {position.symbol} (ID: {position.id})",
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                "strategy": position.strategy_type,
                "dte": current_dte,
                "error": error_message,
                "action_required": "Manual intervention required - check position and close manually if needed",
            },
            notification_type="error",
        )

    async def notify_manual_action(self, position: Position, current_dte: int) -> None:
        from services.notifications.service import NotificationService

        logger.warning(
            "Automation disabled for account %s. Position %s requires manual closure (DTE=%s).",
            position.trading_account.account_number,
            position.id,
            current_dte,
        )
        notification_service = NotificationService(self.user)
        await notification_service.send_notification(
            message=(
                f"Position {position.symbol} requires manual closure due to DTE of {current_dte}."
            ),
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                "dte": current_dte,
                "reason": "dte_threshold_reached",
            },
        )
