"""
Order Cancellation Service - Simple, synchronous cancellation.

No intermediate states. Just check broker → cancel → update to final status.
"""

from django.utils import timezone

from asgiref.sync import sync_to_async

from services.core.exceptions import OAuthSessionError
from services.core.logging import get_logger
from trading.models import Trade

logger = get_logger(__name__)


class OrderCancellationService:
    """
    Simple order cancellation service.

    Flow:
    1. Check current broker status
    2. If terminal (filled/cancelled) → update our DB to match
    3. If still working → attempt cancel
    4. Update to final status
    """

    async def cancel_trade(
        self, trade_id: int, user, reason: str | None = None
    ) -> tuple[bool, dict]:
        """
        Cancel a trade by checking broker status and canceling if possible.

        Simple approach:
        - No pending_cancel status
        - Immediately check broker
        - Cancel if still working
        - Update to final status
        """

        try:
            trade = await Trade.objects.select_related("position").aget(id=trade_id, user=user)

            # Can't cancel if already in terminal state locally
            if trade.status in ["filled", "cancelled", "rejected"]:
                return False, {
                    "success": False,
                    "final_status": trade.status,
                    "message": f"Order already {trade.status}",
                }

            # Get session and account
            session = await self._get_oauth_session(user)
            account_number = await self._get_account_number(trade)

            from tastytrade import Account
            from tastytrade.utils import TastytradeError

            tt_account = await Account.a_get(session, account_number)

            # Check current broker status
            try:
                current_order = await tt_account.a_get_order(session, trade.broker_order_id)

                broker_status = (
                    current_order.status.value.lower()
                    if hasattr(current_order.status, "value")
                    else str(current_order.status).lower()
                )

                logger.info(f"Trade {trade_id} current broker status: {broker_status}")

                # If already filled/cancelled at broker, just sync our status
                if broker_status in ["filled", "cancelled", "expired", "rejected"]:
                    trade.status = broker_status
                    if broker_status == "filled":
                        trade.filled_at = timezone.now()

                    # Track in metadata
                    if not trade.metadata:
                        trade.metadata = {}
                    trade.metadata["cancel_attempt"] = {
                        "attempted_at": timezone.now().isoformat(),
                        "result": f"already_{broker_status}",
                        "reason": reason,
                    }

                    await trade.asave()

                    await self._maybe_archive_pending_position(trade, broker_status)

                    if broker_status == "filled":
                        return False, {
                            "success": False,
                            "final_status": "filled",
                            "message": "Order already filled at broker",
                            "race_condition": True,
                            "trade_id": trade_id,
                        }
                    return True, {
                        "success": True,
                        "final_status": broker_status,
                        "message": f"Order already {broker_status}",
                        "trade_id": trade_id,
                    }

            except TastytradeError as e:
                # Order not found (404) = already filled/removed
                if "record_not_found" in str(e).lower() or "404" in str(e):
                    logger.info(f"Trade {trade_id} not found at broker - assuming filled")

                    trade.status = "filled"
                    trade.filled_at = timezone.now()

                    if not trade.metadata:
                        trade.metadata = {}
                    trade.metadata["cancel_attempt"] = {
                        "attempted_at": timezone.now().isoformat(),
                        "result": "order_not_found_assumed_filled",
                        "broker_error": str(e),
                        "reason": reason,
                    }

                    await trade.asave()

                    return False, {
                        "success": False,
                        "final_status": "filled",
                        "message": "Order not found at broker - likely already filled",
                        "race_condition": True,
                        "trade_id": trade_id,
                    }
                raise  # Re-raise if different error

            # Order still working - attempt to cancel
            logger.info(f"Attempting to cancel order {trade.broker_order_id}")

            try:
                tried_complex = False
                if len(trade.order_legs) > 1:
                    tried_complex = True
                    try:
                        await tt_account.a_delete_complex_order(session, int(trade.broker_order_id))
                    except TastytradeError as cancel_error:
                        # Some multi-leg orders are still treated as standard orders at the broker.
                        if "record_not_found" in str(cancel_error).lower() or "404" in str(
                            cancel_error
                        ):
                            logger.info(
                                "Complex cancel endpoint returned 404; retrying simple order cancel"
                            )
                            await tt_account.a_delete_order(session, int(trade.broker_order_id))
                        else:
                            raise
                else:
                    await tt_account.a_delete_order(session, int(trade.broker_order_id))

                # Verify final status after cancel
                import asyncio

                await asyncio.sleep(0.1)

                final_order = await tt_account.a_get_order(session, trade.broker_order_id)

                final_status = (
                    final_order.status.value.lower()
                    if hasattr(final_order.status, "value")
                    else str(final_order.status).lower()
                )

                logger.info(f"Trade {trade_id} final status after cancel: {final_status}")

                # Update to final status
                trade.status = final_status
                if final_status == "filled":
                    trade.filled_at = timezone.now()

                if not trade.metadata:
                    trade.metadata = {}
                trade.metadata["cancel_attempt"] = {
                    "attempted_at": timezone.now().isoformat(),
                    "result": final_status,
                    "reason": reason,
                    "used_complex_endpoint": tried_complex,
                }

                await trade.asave()

                await self._maybe_archive_pending_position(trade, final_status)

                if final_status == "cancelled":
                    return True, {
                        "success": True,
                        "final_status": "cancelled",
                        "message": "Order cancelled successfully",
                        "trade_id": trade_id,
                    }
                if final_status == "filled":
                    return False, {
                        "success": False,
                        "final_status": "filled",
                        "message": "Order filled before cancellation",
                        "race_condition": True,
                        "trade_id": trade_id,
                    }
                return False, {
                    "success": False,
                    "final_status": final_status,
                    "message": f"Unexpected final status: {final_status}",
                    "trade_id": trade_id,
                }

            except TastytradeError as e:
                logger.error(f"Error cancelling order: {e}")

                # Don't change status on error - leave as-is
                return False, {
                    "success": False,
                    "error": str(e),
                    "message": f"Failed to cancel: {e!s}",
                    "trade_id": trade_id,
                }

        except Trade.DoesNotExist:
            return False, {"success": False, "message": "Trade not found"}
        except Exception as e:
            logger.error(f"Unexpected error cancelling trade {trade_id}: {e}", exc_info=True)
            return False, {
                "success": False,
                "error": str(e),
                "message": "Unexpected error during cancellation",
            }

    async def _maybe_archive_pending_position(self, trade: Trade, final_status: str) -> None:
        """If the position never filled, mark it closed/archived once cancellation completes."""

        if final_status not in {"cancelled", "rejected", "expired"}:
            return

        position = trade.position
        if position.lifecycle_state != "pending_entry":
            return

        metadata = position.metadata or {}
        metadata.update(
            {
                "closure_reason": f"order_{final_status}",
                "closure_timestamp": timezone.now().isoformat(),
                "auto_closed_by": "order_cancellation_service",
                "archived": True,
            }
        )

        position.lifecycle_state = "closed"
        position.metadata = metadata
        await position.asave(update_fields=["lifecycle_state", "metadata", "updated_at"])

    async def _get_oauth_session(self, user):
        """Get TastyTrade OAuth session for user."""
        from services.core.data_access import get_oauth_session

        session = await get_oauth_session(user)
        if not session:
            raise OAuthSessionError(user_id=user.id, reason="Unable to obtain TastyTrade session")

        return session

    async def _get_account_number(self, trade):
        """Get account number from trade's trading account."""
        return await sync_to_async(lambda: trade.trading_account.account_number)()
