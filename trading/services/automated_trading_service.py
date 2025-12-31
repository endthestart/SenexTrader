"""Service layer for automated trading workflows."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from asgiref.sync import async_to_sync, sync_to_async

from accounts.models import TradingAccount
from services.core.logging import get_logger
from services.execution.order_service import OrderExecutionService
from services.notifications.email import EmailService
from services.orders.cancellation import OrderCancellationService
from services.risk.validation import RiskValidationService
from services.sdk.trading_utils import is_market_open_now
from services.strategies.senex_trident_strategy import SenexTridentStrategy

# Note: GlobalStreamManager imported at runtime to avoid circular dependency
from trading.models import Position, Trade, TradingSuggestion

logger = get_logger(__name__)


class AutomatedTradingService:
    """Automated trading orchestrator used by Celery tasks and management commands."""

    def process_user(self, user) -> dict:
        """Synchronously process automated trading for a user."""
        return async_to_sync(self.a_process_user)(user)

    def process_account(self, account: TradingAccount) -> dict:
        """Synchronously process automated trading for a specific account."""
        return async_to_sync(self.a_process_account)(account)

    async def a_process_user(self, user) -> dict:
        """Process automated trading for a user by locating their primary account."""
        account = await sync_to_async(
            lambda: TradingAccount.objects.filter(
                user=user,
                is_primary=True,
                is_active=True,
                trading_preferences__is_automated_trading_enabled=True,
            )
            .select_related("user", "trading_preferences")
            .first()
        )()

        if not account:
            logger.info("User %s has no eligible automated account. Skipping.", user.email)
            return {"status": "skipped", "reason": "no_active_account"}

        return await self._a_process(user=user, account=account)

    async def a_process_account(self, account: TradingAccount) -> dict:
        """Process automated trading using a specific account record."""
        # Access properties via sync_to_async to avoid async context DB access
        is_active = account.is_active
        is_enabled = await sync_to_async(lambda: account.is_automated_trading_enabled)()

        if not is_active or not is_enabled:
            logger.info(
                "Account %s not eligible for automation (active=%s, enabled=%s)",
                account.account_number,
                is_active,
                is_enabled,
            )
            return {"status": "skipped", "reason": "no_active_account"}

        user = await sync_to_async(lambda: account.user)()
        return await self._a_process(user=user, account=account)

    async def _cancel_pending_automated_orders(
        self, user, account: TradingAccount, stale_minutes: int = 5
    ) -> dict:
        """
        Cancel unfilled automated opening orders older than stale_minutes.

        Returns dict with cancelled_count and details.
        """
        stale_threshold = timezone.now() - timedelta(minutes=stale_minutes)

        @sync_to_async
        def get_stale_positions():
            return list(
                Position.objects.filter(
                    user=user,
                    trading_account=account,
                    lifecycle_state="pending_entry",
                    is_automated_entry=True,
                    created_at__lt=stale_threshold,
                ).select_related("trading_account")
            )

        stale_positions = await get_stale_positions()

        if not stale_positions:
            return {"cancelled_count": 0, "details": []}

        logger.info(
            "User %s: Found %d stale automated orders to cancel (older than %d min)",
            user.email,
            len(stale_positions),
            stale_minutes,
        )

        cancellation_service = OrderCancellationService()
        cancelled_count = 0
        details = []

        for position in stale_positions:
            # Get the trade associated with this position
            @sync_to_async
            def get_trade():
                return Trade.objects.filter(
                    position=position, trade_type="open"
                ).first()

            trade = await get_trade()

            if not trade:
                logger.warning(
                    "Position %d has no opening trade, marking as expired", position.id
                )
                @sync_to_async
                def mark_expired():
                    position.lifecycle_state = "expired"
                    position.metadata = position.metadata or {}
                    position.metadata["auto_expired_reason"] = "no_opening_trade"
                    position.save(update_fields=["lifecycle_state", "metadata", "updated_at"])

                await mark_expired()
                continue

            # Cancel the trade at the broker
            success, result = await cancellation_service.cancel_trade(
                trade.id, user, reason="stale_automated_order"
            )

            details.append({
                "position_id": position.id,
                "trade_id": trade.id,
                "broker_order_id": trade.broker_order_id,
                "success": success,
                "result": result,
            })

            if success or result.get("final_status") in ["cancelled", "expired", "rejected"]:
                cancelled_count += 1
                logger.info(
                    "User %s: Cancelled stale order %s (position %d)",
                    user.email,
                    trade.broker_order_id,
                    position.id,
                )
            elif result.get("final_status") == "filled":
                # Order filled while we were trying to cancel - this is actually good!
                logger.info(
                    "User %s: Order %s filled before cancellation (position %d)",
                    user.email,
                    trade.broker_order_id,
                    position.id,
                )
            else:
                logger.warning(
                    "User %s: Failed to cancel order %s: %s",
                    user.email,
                    trade.broker_order_id,
                    result.get("message", "unknown error"),
                )

        return {"cancelled_count": cancelled_count, "details": details}

    async def _a_process(self, *, user, account: TradingAccount) -> dict:
        import time

        start_time = time.time()

        logger.info(
            "Starting automated trading cycle for user %s (account: %s, offset: %sc)",
            user.email,
            account.account_number,
            account.automated_entry_offset_cents or 0,
        )

        try:
            if not is_market_open_now():
                logger.info("Market closed. Skipping automation for %s", user.email)
                return {"status": "skipped", "reason": "market_closed"}

            today = timezone.now().date()

            # Step 1: Cancel any stale pending automated orders (older than 5 minutes)
            # This ensures we don't have multiple orders competing and allows fresh pricing
            cancel_result = await self._cancel_pending_automated_orders(user, account)
            if cancel_result["cancelled_count"] > 0:
                logger.info(
                    "User %s: Cancelled %d stale automated orders before generating new suggestion",
                    user.email,
                    cancel_result["cancelled_count"],
                )

            # Step 2: Check if we already have an OPEN position today
            # (not just any trade - allows retries when orders don't fill)
            @sync_to_async
            def _has_open_position_today() -> bool:
                return Position.objects.filter(
                    user=user,
                    trading_account=account,
                    is_automated_entry=True,
                    created_at__date=today,
                    lifecycle_state__in=["open_full", "open_partial"],
                ).exists()

            has_open_position = await _has_open_position_today()
            if has_open_position:
                logger.info(
                    "User %s already has open automated position today. Skipping.",
                    user.email,
                )
                return {"status": "skipped", "reason": "open_position_exists_today"}

            # RETRY LOGIC: Attempt suggestion generation up to 3 times
            # Retries help with:
            # 1. Stale/corrupted streaming data at market open
            # 2. Transient DXFeed issues
            # 3. Negative credit detection (bad bid/ask data)
            MAX_ATTEMPTS = 3
            RETRY_DELAY = 5  # seconds between retries

            suggestion = None
            suggestion_start = time.time()

            for attempt in range(1, MAX_ATTEMPTS + 1):
                logger.info(
                    "User %s: Generating suggestion (attempt %d/%d)...",
                    user.email,
                    attempt,
                    MAX_ATTEMPTS,
                )

                attempt_start = time.time()
                suggestion = await self.a_generate_suggestion(user)
                attempt_duration = time.time() - attempt_start

                if suggestion:
                    logger.info(
                        "Suggestion generated successfully on attempt %d/%d [%.2fs]",
                        attempt,
                        MAX_ATTEMPTS,
                        attempt_duration,
                    )
                    break

                # If failed and not last attempt, wait and retry
                if attempt < MAX_ATTEMPTS:
                    logger.warning(
                        "Suggestion generation failed on attempt %d/%d (took %.2fs). "
                        "Retrying in %d seconds...",
                        attempt,
                        MAX_ATTEMPTS,
                        attempt_duration,
                        RETRY_DELAY,
                    )
                    import asyncio

                    await asyncio.sleep(RETRY_DELAY)
                else:
                    logger.warning(
                        "Suggestion generation failed after %d attempts (total %.2fs)",
                        MAX_ATTEMPTS,
                        time.time() - suggestion_start,
                    )

            suggestion_duration = time.time() - suggestion_start

            if not suggestion:
                logger.info(
                    "No suitable conditions for %s after %d attempts (%.2fs total)",
                    user.email,
                    MAX_ATTEMPTS,
                    suggestion_duration,
                )
                return {"status": "skipped", "reason": "unsuitable_market_conditions"}

            logger.info(
                "Suggestion created for %s: %s (expiry: %s, credit: $%.2f, risk: $%.2f) [%.2fs]",
                user.email,
                suggestion.underlying_symbol,
                suggestion.expiration_date,
                suggestion.total_mid_credit or 0,
                suggestion.max_risk or 0,
                suggestion_duration,
            )

            logger.info("User %s: Validating trade risk...", user.email)
            validation_start = time.time()
            validation = await RiskValidationService.validate_trade_risk(
                user=user, suggestion_id=suggestion.id
            )
            validation_duration = time.time() - validation_start

            if not validation.get("valid"):
                logger.warning(
                    "Risk validation blocked automation for %s: %s [%.2fs]",
                    user.email,
                    validation.get("message"),
                    validation_duration,
                )
                return {
                    "status": "skipped",
                    "reason": "risk_validation_failed",
                    "details": validation,
                }

            logger.info(
                "Risk validation passed for %s [%.2fs]",
                user.email,
                validation_duration,
            )

            custom_credit = self._calculate_automation_credit(account, suggestion)

            logger.info("User %s: Executing order via TastyTrade API...", user.email)
            execution_start = time.time()
            service = OrderExecutionService(user)
            result = await service.execute_suggestion_async(suggestion, custom_credit=custom_credit)
            execution_duration = time.time() - execution_start

            from services.execution.order_service import DryRunResult

            if isinstance(result, DryRunResult):
                logger.info(
                    "DRY-RUN: Skipped execution for %s - %s",
                    user.email,
                    result.message,
                )
                return {
                    "status": "skipped",
                    "reason": "dry_run_mode",
                    "suggestion_id": suggestion.id,
                    "symbol": suggestion.underlying_symbol,
                    "dry_run_result": {
                        "validated": result.simulated_status == "validated",
                        "message": result.message,
                    },
                }

            position = result
            if not position:
                logger.warning(
                    "Execution failed for %s [%.2fs]",
                    user.email,
                    execution_duration,
                )
                return {
                    "status": "failed",
                    "reason": "execution_failed",
                    "suggestion_id": suggestion.id,
                }

            total_duration = time.time() - start_time
            logger.info(
                "Automated trade executed for %s: Position %s (total: %.2fs, breakdown: suggestion=%.2fs, validation=%.2fs, execution=%.2fs)",
                user.email,
                position.id,
                total_duration,
                suggestion_duration,
                validation_duration,
                execution_duration,
            )
            await self.send_notification(user, suggestion, position, custom_credit)

            return {
                "status": "success",
                "suggestion_id": suggestion.id,
                "position_id": position.id,
                "symbol": suggestion.underlying_symbol,
            }

        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error(
                "Failed automation for %s (%s): %s",
                user.email,
                account.account_number,
                exc,
                exc_info=True,
            )
            return {"status": "failed", "reason": str(exc)}

    async def a_generate_suggestion(self, user) -> TradingSuggestion | None:
        """Generate a suggestion via direct streaming pipeline."""
        manager = None
        try:
            # Runtime import to avoid circular dependency
            from streaming.services.stream_manager import GlobalStreamManager

            logger.info("User %s: Starting streaming for SPX, QQQ, and SPY...", user.id)
            manager = await GlobalStreamManager.get_user_manager(user.id)
            streaming_ready = await manager.ensure_streaming_for_automation(["SPX", "QQQ", "SPY"])
            if not streaming_ready:
                logger.error("User %s: Failed to start streaming for automation", user.id)
                return None

            # DATA FRESHNESS: Wait for streaming data to stabilize
            # At market open (9:30-10:00 AM ET), DXFeed may have stale/wide spreads.
            # Give the streaming pipeline time to receive and cache fresh quotes.
            import asyncio

            DATA_STABILIZATION_DELAY = 3  # seconds
            logger.info(
                "User %s: Waiting %.1f seconds for streaming data to stabilize...",
                user.id,
                DATA_STABILIZATION_DELAY,
            )
            await asyncio.sleep(DATA_STABILIZATION_DELAY)
            logger.info("User %s: Data stabilization period complete, proceeding...", user.id)

            logger.info("User %s: Streaming ready, preparing suggestion context...", user.id)
            strategy = SenexTridentStrategy(user)
            context = await strategy.a_prepare_suggestion_context()
            if not context:
                logger.info(
                    "User %s: Market conditions not suitable (context preparation failed)", user.id
                )
                return None

            logger.info(
                "User %s: Context prepared - symbol=%s, expiry=%s, strategy=%s",
                user.id,
                context.get("underlying_symbol"),
                context.get("expiration_date"),
                context.get("strategy_name", "unknown"),
            )

            context["is_automated"] = True
            logger.info("User %s: Processing suggestion request via stream manager...", user.id)
            suggestion = await manager.a_process_suggestion_request(context)
            if suggestion:
                suggestion.status = "approved"
                await sync_to_async(suggestion.save)(update_fields=["status"])
                logger.info(
                    "User %s: Automated suggestion %s approved (symbol=%s)",
                    user.id,
                    suggestion.id,
                    suggestion.underlying_symbol,
                )
            else:
                logger.info("User %s: Suggestion generation returned None", user.id)

            return suggestion

        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("User %s: Error generating suggestion: %s", user.id, exc, exc_info=True)
            return None
        finally:
            # CRITICAL: Explicit cleanup to prevent RecursionError during event loop shutdown
            # When run_async() closes event loop, it cancels all pending tasks.
            # Deep task nesting (streaming_task → gather → 5 listeners) causes
            # recursive cancellation exceeding Python 3.13's stack limit.
            # Clean up streaming before task completes to prevent accumulated tasks.
            if manager:
                try:
                    await manager.stop_streaming()
                    logger.info("User %s: Streaming stopped cleanly after automation", user.id)
                except Exception as cleanup_exc:
                    logger.warning(
                        "User %s: Error stopping streaming (non-fatal): %s",
                        user.id,
                        cleanup_exc,
                    )

    async def send_notification(
        self, user, suggestion, position, custom_credit: float | None
    ) -> None:
        """Notify user about automated trade execution via email (async-safe)."""
        try:
            # Respect user email preference - only send immediate emails if enabled
            if user.email_preference != "immediate":
                logger.debug(
                    "Skipping immediate email for %s (preference: %s)",
                    user.email,
                    user.email_preference,
                )
                return

            price_line = ""
            if custom_credit is not None:
                price_line = f"Entry Price Sent: ${custom_credit:.2f}\n"

            email_service = EmailService()
            await sync_to_async(email_service.send_email)(
                subject=f"Automated Trade Executed - {suggestion.underlying_symbol}",
                body=(
                    "Your automated trade has been executed:\n\n"
                    f"Symbol: {suggestion.underlying_symbol}\n"
                    f"Expiration: {suggestion.expiration_date}\n"
                    "Strategy: Senex Trident (Iron Condor)\n"
                    f"Max Risk: ${suggestion.max_risk}\n"
                    f"Expected Credit: ${suggestion.total_mid_credit}\n"
                    f"{price_line}"
                    f"Position ID: {position.id}\n\n"
                    "Profit targets are automatically set.\n"
                    "View details in your dashboard."
                ),
                recipient=user.email,
                fail_silently=True,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Email failed for %s: %s", user.email, exc)

    def _calculate_automation_credit(
        self, account: TradingAccount, suggestion: TradingSuggestion
    ) -> Decimal | None:
        """
        Calculate adjusted entry credit based on automation offset setting.

        CRITICAL: Only uses mid-price credit (realistic bid/ask average).
        Does NOT fallback to natural credit (conservative bid-only price).
        If mid_credit unavailable, automation should fail rather than use wrong price.
        """
        offset_cents = account.automated_entry_offset_cents or 0
        if offset_cents <= 0:
            return None

        # CRITICAL: Use ONLY mid_credit - no fallback to total_credit!
        # total_credit is bid-based conservative pricing unsuitable for limit orders
        price = suggestion.total_mid_credit
        if not price:
            logger.error(
                f"No mid_credit available for suggestion {suggestion.id}. "
                f"Streaming data incomplete (missing bid/ask). "
                f"Cannot calculate safe automation entry price. "
                f"Automation should fail rather than use conservative bid-only pricing."
            )
            return None

        price = Decimal(price)
        offset_value = Decimal(offset_cents) / Decimal("100")

        # Case-insensitive comparison (price_effect stored as "Credit"/"Debit" since migration 0026)
        price_effect = (suggestion.price_effect or "").lower()

        if price_effect == "credit":
            # For credit spreads (selling): Subtract offset to get better fill
            # We want to sell for LESS than mid-price (easier to fill, competitive pricing)
            adjusted = price - offset_value

            # Floor at natural credit to prevent absurdly low limit prices
            # This ensures automation offset can't create prices below conservative bid
            #
            # CONTEXT: With max offset 10¢ and typical spread 40¢, this floor rarely triggers.
            # It's a safety net for edge cases (e.g., if offset range ever increases).
            #
            # EXAMPLE WHERE FLOOR MATTERS (large offset):
            #   mid_credit=$1.00, offset=50¢ → adjusted=$0.50
            #   natural_credit=$0.80 → floor kicks in → final=$0.80
            #
            # EXAMPLE IN NORMAL OPERATION (floor doesn't trigger):
            #   mid_credit=$4.00, offset=2¢ → adjusted=$3.98
            #   natural_credit=$3.60 → $3.98 > $3.60 → final=$3.98
            #
            # WHY ONLY FOR CREDITS:
            #   Credits (selling): Floor prevents selling below bid
            #   Debits (buying): No floor needed - we're paying MORE than mid anyway
            natural_credit = Decimal(suggestion.total_credit or "0")
            pre_floor_adjusted = adjusted
            adjusted = max(adjusted, natural_credit)

            # Log warning if floor was triggered (indicates offset may be too large)
            if adjusted > pre_floor_adjusted:
                logger.warning(
                    f"Automation offset floored at natural credit!\n"
                    f"  Suggestion: {suggestion.id}\n"
                    f"  Mid-credit: ${price}\n"
                    f"  Offset: {offset_cents}c\n"
                    f"  Calculated: ${pre_floor_adjusted}\n"
                    f"  Natural credit: ${natural_credit}\n"
                    f"  -> Final: ${adjusted} (floored)\n"
                    f"This indicates offset may be too large for current spread."
                )

        elif price_effect == "debit":
            # For debit spreads (buying): Add offset to ensure fill
            # We want to pay MORE than mid-price (easier to fill, willing to pay up)
            # No floor needed - we're already paying above mid
            adjusted = price + offset_value
        else:
            logger.error(
                f"Cannot calculate automation credit: invalid price_effect '{suggestion.price_effect}'\n"
                f"  Suggestion: {suggestion.id}\n"
                f"  Expected: 'Credit' or 'Debit' (case-insensitive)\n"
                f"  Received: '{suggestion.price_effect}'"
            )
            return None

        # Final safety: Ensure non-negative price
        adjusted = max(adjusted, Decimal("0"))

        logger.info(
            "Applying automation offset %s¢: mid=%s → limit=%s",
            offset_cents,
            price,
            adjusted,
        )
        return adjusted
