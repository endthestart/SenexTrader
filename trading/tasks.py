"""
Trading Tasks - Celery background tasks for order monitoring and management
Phase 6: Trading Execution Implementation
"""

import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from asgiref.sync import sync_to_async
from celery import shared_task
from channels.layers import get_channel_layer

from accounts.models import TradingAccount
from services.core.cache import CacheManager
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from services.execution.order_service import OrderExecutionService
from services.monitoring.task_metrics import monitor_task
from services.notifications.email.suggestion_email_builder import SuggestionEmailBuilder
from services.positions.lifecycle.dte_manager import OPEN_STATES, DTEManager
from trading.models import Position, Trade, TradingSuggestion

User = get_user_model()
logger = get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=900,  # 15 minutes
    time_limit=1200,  # 20 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def batch_sync_data_task(self):
    """
    Unified reconciliation task that syncs and reconciles all position/order data.

    Uses ReconciliationOrchestrator to run the following phases:
    1. sync_order_history - Fetch recent orders from TastyTrade → TastyTradeOrderHistory
    2. sync_positions - Update Position model from TastyTrade
    3. reconcile_trades - Fix trade/position state mismatches
    4. fix_profit_targets - Validate/recreate profit target orders

    This is the same code used by the `reconcile` management command,
    ensuring consistent behavior between scheduled and manual reconciliation.

    Runs every 30 minutes via Celery Beat.
    """
    from services.reconciliation.orchestrator import (
        ReconciliationOptions,
        run_reconciliation_sync,
    )

    logger.info("=== Starting unified reconciliation task ===")

    try:
        # Run full reconciliation for all users
        options = ReconciliationOptions(
            sync_order_history=True,
            sync_positions=True,
            reconcile_trades=True,
            fix_profit_targets=True,
        )

        result = run_reconciliation_sync(options)

        phases_completed = len(result.get("phases_completed", []))
        phase_results = len(result.get("phase_results", {}))
        duration = result.get("total_duration_seconds", 0)

        logger.info(
            f"=== Reconciliation complete: {phases_completed}/{phase_results} "
            f"phases succeeded in {duration}s ==="
        )

        return result

    except Exception as e:
        logger.error(f"Fatal error in batch_sync_data_task: {e}", exc_info=True)

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            countdown = 120 * (2**self.request.retries)  # 2min, 4min, 8min
            logger.info(f"Retrying batch_sync_data_task in {countdown}s")
            raise self.retry(countdown=countdown)

        return {
            "success": False,
            "error": str(e),
            "phases_completed": [],
            "phases_failed": ["all"],
        }


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=60,  # 1 minute - quick order status checks
    time_limit=120,  # 2 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def monitor_open_orders(self):
    """
    Monitor open orders and update their status.

    This task polls TastyTrade for order status updates and sends
    WebSocket notifications for fills, rejections, and other status changes.

    P1.2: Quick task with 60s/120s timeout (overrides global 300s/600s)
    """
    try:
        # Using run_async to handle async-to-sync conversion safely
        return run_async(_async_monitor_orders())
    except Exception as e:
        logger.error(f"Error in monitor_open_orders task: {e}")

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            countdown = 60 * (2**self.request.retries)  # 60s, 120s, 240s
            logger.info(
                f"Retrying monitor_open_orders in {countdown}s "
                f"(attempt {self.request.retries + 1})"
            )
            raise self.retry(countdown=countdown)

        return {"status": "error", "message": str(e)}


async def _async_monitor_orders():
    channel_layer = get_channel_layer()
    updates_sent = 0

    try:
        open_trades = [
            trade
            async for trade in Trade.objects.filter(
                status__in=["pending", "submitted", "routed", "live", "working"]
            ).select_related("user")
        ]

        logger.info(f"Monitoring {len(open_trades)} open orders")

        for trade in open_trades:
            try:
                updated = await _check_trade_status(trade, channel_layer)
                if updated:
                    updates_sent += 1

            except Exception as e:
                logger.error(f"Error checking trade {trade.id}: {e}")
                continue

        logger.info(f"Order monitoring complete: {updates_sent} updates sent")
        return {
            "status": "success",
            "trades_checked": len(open_trades),
            "updates_sent": updates_sent,
        }

    except Exception as e:
        logger.error(f"Error in async order monitoring: {e}")
        raise


async def _check_trade_status(trade: Trade, channel_layer) -> bool:
    """
    Check status of a specific trade and send updates if changed.

    Returns True if status was updated, False otherwise.
    """
    try:
        if not trade.broker_order_id or trade.broker_order_id == "TEST_MODE":
            logger.debug(f"Skipping monitoring for test mode trade {trade.id}")
            return False

        # Defense-in-depth: Verify BOTH user ownership AND account ID match to prevent cross-user data access
        trading_account = await TradingAccount.objects.filter(
            user=trade.user, id=trade.trading_account_id
        ).afirst()

        if not trading_account:
            logger.error(
                "Security: Trade %s account mismatch - user %s, expected account %s",
                trade.id,
                trade.user.id,
                trade.trading_account_id,
                extra={
                    "trade_id": trade.id,
                    "user_id": trade.user.id,
                    "account_id": trade.trading_account_id,
                    "security_event": "account_mismatch",
                },
            )
            return False

        order_service = OrderExecutionService(trade.user)
        status_data = await order_service.check_order_status(trade.broker_order_id)

        if not status_data:
            logger.warning(f"Could not get status for order {trade.broker_order_id}")
            return False

        new_status = status_data.get("status", trade.status)
        filled_at = status_data.get("filled_at")
        fill_price = status_data.get("fill_price")
        commission = status_data.get("commission")

        status_changed = (
            new_status != trade.status
            or (filled_at and not trade.filled_at)
            or (fill_price and not trade.fill_price)
        )

        logger.info(
            f"Trade {trade.id} status check: current={trade.status}, new={new_status}, "
            f"changed={status_changed}, fill_price={fill_price}"
        )

        if status_changed:
            old_status = trade.status

            await _update_trade_record_async(trade, new_status, filled_at, fill_price, commission)

            await _send_order_update(
                channel_layer,
                trade.user.id,
                trade.id,
                new_status,
                filled_at,
                fill_price,
                commission,
            )

            if new_status.lower() == "filled" and old_status.lower() != "filled":
                await _handle_order_fill(trade, order_service, channel_layer)

            logger.info(f"Trade {trade.id} status updated: {old_status} -> {new_status}")
            return True

        return False

    except Exception as e:
        logger.error(f"Error checking trade {trade.id} status: {e}")
        return False


async def _update_trade_record_async(trade: Trade, status: str, filled_at, fill_price, commission):
    trade.status = status

    if filled_at:
        trade.filled_at = filled_at

    if fill_price:
        trade.fill_price = fill_price

    if commission:
        trade.commission = commission

    await trade.asave(update_fields=["status", "filled_at", "fill_price", "commission"])

    if status.lower() == "expired" and trade.trade_type == "open":
        position = await trade.position_async
        if position.lifecycle_state == "pending_entry":
            await position.adelete()
            logger.info(f"Deleted pending position {position.id} - opening order expired")


async def _send_order_update(
    channel_layer,
    user_id: int,
    trade_id: int,
    status: str,
    filled_at,
    fill_price,
    commission,
):
    """
    Send order status updates via WebSocket.

    Uses the same group (data_{user_id}) and message types (order_status, order_fill)
    as AlertStreamer for consistency. This task serves as a polling fallback when
    the user is disconnected from real-time streaming.
    """
    try:
        # Use data_{user_id} group to match AlertStreamer's broadcast path
        await channel_layer.group_send(
            f"data_{user_id}",
            {
                "type": "order_status",  # Matches AlertStreamer message type
                "trade_id": trade_id,
                "status": status,
                "filled_at": filled_at.isoformat() if filled_at else None,
                "fill_price": float(fill_price) if fill_price else None,
                "commission": float(commission) if commission else None,
            },
        )

        if status == "filled" and fill_price:
            await channel_layer.group_send(
                f"data_{user_id}",
                {
                    "type": "order_fill",  # Matches AlertStreamer message type
                    "trade_id": trade_id,
                    "fill_price": float(fill_price),
                    "quantity": 1,
                    "timestamp": timezone.now().isoformat(),
                },
            )

    except Exception as e:
        logger.error(f"Error sending order update for trade {trade_id}: {e}")


async def _handle_order_fill(trade: Trade, order_service: OrderExecutionService, channel_layer):
    """
    Handle order fill - create profit targets using existing service method
    """
    try:
        logger.info(
            f"_handle_order_fill called for trade {trade.id}: "
            f"trade_type={trade.trade_type}, parent_order_id={trade.parent_order_id}"
        )

        if not trade.parent_order_id:
            position = await trade.position_async

            if position and not position.profit_targets_created:
                result = await sync_to_async(order_service.create_profit_targets_sync)(
                    position, trade.broker_order_id
                )

                if result and result.get("order_ids"):
                    order_ids = result["order_ids"]

                    await Trade.objects.filter(id=trade.id).aupdate(child_order_ids=order_ids)

                    num_orders = len(order_ids)
                    logger.info(f"Created {num_orders} profit target orders for trade {trade.id}")

                    # Update position lifecycle_state when opening trade fills
                    if position.lifecycle_state == "pending_entry":
                        await Position.objects.filter(id=position.id).aupdate(
                            lifecycle_state="open_full"
                        )
                        logger.info(f"Updated position {position.id} to open_full")

                    # Send profit target notifications via data_{user_id} group
                    for target in result.get("targets", []):
                        await channel_layer.group_send(
                            f"data_{trade.user_id}",
                            {
                                "type": "profit_target_update",
                                "parent_trade_id": trade.id,
                                "profit_target_id": target.get("order_id"),
                                "spread_type": target.get("spread_type"),
                                "profit_percentage": target.get("profit_percentage"),
                                "status": "submitted",
                            },
                        )

    except Exception as e:
        logger.error(f"Error handling order fill for trade {trade.id}: {e}")


@shared_task
@monitor_task
def cleanup_old_records_task():
    """
    Clean up old records to prevent database bloat.

    Runs multiple cleanup operations:
    - Cancelled/rejected/expired trades older than 90 days (never executed)
    - Executed/rejected/expired suggestions older than 30 days (already acted upon)

    NEVER deletes filled trades - those are preserved as permanent trading history.
    """
    from services.account.utils.cleanup_utils import cleanup_old_records

    results = {}

    # Cleanup trades
    results["trades"] = cleanup_old_records(
        model=Trade,
        days=90,
        statuses=["cancelled", "rejected", "expired"],
        date_field="updated_at",
        record_type="trades",
    )

    # Cleanup suggestions
    results["suggestions"] = cleanup_old_records(
        model=TradingSuggestion,
        days=30,
        statuses=["executed", "rejected", "expired"],
        date_field="generated_at",
        record_type="suggestions",
    )

    return results


@shared_task
def aggregate_historical_greeks():
    """
    Aggregate HistoricalGreeks data to reduce storage with progressive resolution.

    Single table approach (KISS principle):
    - All resolutions stored in same HistoricalGreeks table
    - Timestamp precision indicates resolution (1s, 1min, 5min)
    - Aggregation replaces high-res data with low-res summaries in-place
    - Never delete old data (indefinite retention with progressive compression)

    Strategy:
    - 0-30 days: Keep 1-second resolution (raw streaming data)
    - 30 days - 1 year: Aggregate to 1-minute resolution
    - 1+ years: Aggregate to 5-minute resolution

    This task runs both aggregation steps:
    1. Replace 30+ day old 1s data with 1min aggregates
    2. Replace 1+ year old 1min data with 5min aggregates

    Expected storage per symbol (steady state):
    - Recent (30 days @ 1s): 702,000 rows
    - Medium (335 days @ 1min): 130,650 rows
    - Old (indefinite @ 5min): ~28,470 rows/year

    Total: ~861K rows per symbol per year
    """
    from services.account.utils.greeks_aggregation import (
        aggregate_greeks_to_1min,
        aggregate_greeks_to_5min,
    )

    results = {}

    # Step 1: Aggregate 30+ day old data to 1-minute resolution
    logger.info("Starting Greeks aggregation: 1-second → 1-minute (in-place)")
    results["to_1min"] = aggregate_greeks_to_1min()

    # Step 2: Aggregate 1+ year old data to 5-minute resolution
    logger.info("Starting Greeks aggregation: 1-minute → 5-minute (in-place)")
    results["to_5min"] = aggregate_greeks_to_5min()

    logger.info(f"Greeks aggregation complete: {results}")
    return results


@shared_task
def clear_expired_option_chains():
    """
    Clear option chain caches from previous days.

    Cache Bug 5 Fix: Option chain cache keys now include current date suffix.
    This task cleans up old caches to prevent unbounded Redis growth.

    Runs daily at 12:05 AM to clear previous day's caches.

    Returns:
        dict: Cleanup statistics including keys deleted
    """
    from datetime import date, timedelta

    from django.core.cache import cache

    try:
        # Clear yesterday's and older caches
        yesterday = date.today() - timedelta(days=1)
        patterns = [
            f"option_chain:*:*:{yesterday.isoformat()}",  # Specific expiration format
            f"option_chain:full:*:{yesterday.isoformat()}",  # Full chain format
        ]

        total_deleted = 0
        for pattern in patterns:
            try:
                # Note: Redis keys() method - may need adjustment for non-Redis cache backends
                keys = cache.keys(pattern) if hasattr(cache, "keys") else []
                if keys:
                    cache.delete_many(keys)
                    deleted = len(keys)
                    total_deleted += deleted
                    logger.info(
                        f"Cleared {deleted} expired option chain caches matching pattern: {pattern}"
                    )
            except Exception as e:
                logger.error(f"Error clearing cache pattern {pattern}: {e}")

        result = {
            "status": "success",
            "keys_deleted": total_deleted,
            "cleanup_date": yesterday.isoformat(),
        }

        if total_deleted > 0:
            logger.info(f"Cache cleanup complete: {total_deleted} keys deleted from {yesterday}")
        else:
            logger.debug(f"Cache cleanup complete: no keys found for {yesterday}")

        return result

    except Exception as e:
        logger.error(f"Error in clear_expired_option_chains task: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@shared_task
@monitor_task
def generate_trading_summary():
    """
    Generate and email daily trading summary to users with 'summary' email preference.

    Sends personalized daily reports including:
    - New positions opened today
    - Profit targets filled today
    - Cancelled/rejected trades

    Runs once per day 30 minutes after market close.
    """
    from services.notifications.email import EmailService

    email_service = EmailService()

    try:
        today = timezone.now().date()

        # Get users who want daily summaries
        users_wanting_summaries = User.objects.filter(preferences__email_preference="summary")

        emails_sent = 0
        users_with_activity = 0

        for user in users_wanting_summaries:
            # Get today's trades for this user
            todays_trades = Trade.objects.filter(
                user=user, submitted_at__date=today
            ).select_related("position")

            # Categorize trades
            new_positions = todays_trades.filter(trade_type="open", status="filled")
            profit_targets = todays_trades.filter(trade_type="close", status="filled")
            cancelled = todays_trades.filter(status__in=["cancelled", "rejected", "expired"])

            # Skip users with no activity
            if not (new_positions.exists() or profit_targets.exists() or cancelled.exists()):
                continue

            users_with_activity += 1

            # Build email content
            email_body = f"Daily Trading Summary - {today.strftime('%B %d, %Y')}\n\n"

            # New positions section
            if new_positions.exists():
                email_body += f"NEW POSITIONS OPENED ({new_positions.count()})\n\n"
                for trade in new_positions:
                    pos = trade.position
                    credit = trade.fill_price or "N/A"

                    # Format strategy name
                    strategy_display = pos.strategy_type.replace("_", " ").title()

                    # Format expiration from metadata
                    from datetime import datetime

                    exp_str = pos.metadata.get("expiration", "Unknown")
                    try:
                        if exp_str != "Unknown":
                            exp_dt = (
                                datetime.fromisoformat(exp_str)
                                if isinstance(exp_str, str)
                                else exp_str
                            )
                            exp_date = exp_dt.strftime("%b %d, %Y")
                        else:
                            exp_date = "Unknown"
                    except (ValueError, AttributeError):
                        exp_date = "Unknown"

                    # Position header
                    email_body += f"{pos.symbol} {strategy_display} - Exp: {exp_date}\n"
                    email_body += f"  Entry: ${credit} credit\n"

                    # Show strike prices based on strategy
                    strikes = []
                    if pos.short_put_strike and pos.long_put_strike:
                        put_str = f"{int(pos.short_put_strike)}/{int(pos.long_put_strike)}"
                        # Check for double put spreads (Senex Trident)
                        if pos.strategy_type == "senex_trident" and pos.put_spread_quantity == 2:
                            put_str += " (2x)"
                        strikes.append(f"Put Spread: {put_str}")

                    if pos.short_call_strike and pos.long_call_strike:
                        call_str = f"{int(pos.short_call_strike)}/{int(pos.long_call_strike)}"
                        strikes.append(f"Call Spread: {call_str}")

                    if strikes:
                        email_body += f"  Strikes: {', '.join(strikes)}\n"

                    # Show profit targets if created
                    if pos.profit_targets_created and pos.profit_target_details:
                        email_body += "  Profit Targets:\n"
                        for spread_type, details in pos.profit_target_details.items():
                            spread_label = spread_type.replace("_", " ").title()
                            percent = details.get("percent", "N/A")
                            price = details.get("target_price", "N/A")
                            if isinstance(price, (int, float)):
                                price = f"${price:.2f}"
                            email_body += f"    • {spread_label}: {percent}% @ {price}\n"

                    email_body += "\n"

            # Profit targets section
            if profit_targets.exists():
                email_body += f"PROFIT TARGETS FILLED ({profit_targets.count()})\n\n"
                for trade in profit_targets:
                    pos = trade.position
                    profit = trade.fill_price or "N/A"
                    strategy_display = pos.strategy_type.replace("_", " ").title()

                    email_body += f"{pos.symbol} {strategy_display}\n"
                    email_body += f"  Closed @ ${profit}\n"

                    # Show which spread if we have the info
                    if trade.trade_type == "exit" and hasattr(trade, "notes") and trade.notes:
                        email_body += f"  {trade.notes}\n"

                    email_body += "\n"

            # Cancelled/rejected section
            if cancelled.exists():
                email_body += f"CANCELLED/REJECTED ({cancelled.count()})\n\n"
                for trade in cancelled:
                    pos = trade.position
                    strategy_display = pos.strategy_type.replace("_", " ").title()
                    email_body += f"{pos.symbol} {strategy_display} - {trade.status}\n"
                email_body += "\n"

            email_body += f"\nView full details in your dashboard at {settings.APP_BASE_URL}"

            # Send email
            success = email_service.send_email(
                subject=f"Daily Trading Summary - {today.strftime('%b %d')}",
                body=email_body,
                recipient=user.email,
                fail_silently=True,
            )
            if success:
                emails_sent += 1

        logger.info(
            f"Daily trading summary: {emails_sent} emails sent to "
            f"{users_with_activity} users with activity"
        )

        return {
            "status": "success",
            "date": today.isoformat(),
            "emails_sent": emails_sent,
            "users_with_activity": users_with_activity,
        }

    except Exception as e:
        logger.error(f"Error generating trading summary: {e}")
        return {"status": "error", "message": str(e)}


@shared_task
@monitor_task
def generate_and_email_daily_suggestions():
    """
    Generate and email daily trade suggestions at 10:00 AM ET.

    Uses StrategySelector auto-mode to pick best strategy for current conditions.
    Email-only - does not execute trades.

    This task runs separately from automated_daily_trade_cycle:
    - automated_daily_trade_cycle: Executes trades for users with automation enabled
    - generate_and_email_daily_suggestions: Sends email suggestions only (no execution)
    """
    try:
        return run_async(_async_generate_and_email_daily_suggestions())
    except Exception as e:
        logger.error(f"Error in generate_and_email_daily_suggestions: {e}", exc_info=True)
        return {"emails_sent": 0, "failed": 0, "skipped": 0}


async def _async_generate_and_email_daily_suggestions():
    """Async implementation of daily trade suggestion email task."""
    from django.conf import settings

    from services.notifications.email import EmailService
    from services.strategies.selector import StrategySelector

    email_service = EmailService()

    logger.info("Starting daily trade suggestion email generation...")

    # Query users who want daily suggestions (and have email enabled)
    # Note: email_daily_trade_suggestion is on UserPreferences, not User directly
    eligible_users = await sync_to_async(list)(
        User.objects.filter(
            is_active=True, preferences__email_daily_trade_suggestion=True
        ).exclude(preferences__email_preference="none")
    )

    logger.info(f"Found {len(eligible_users)} users opted-in for daily trade suggestions")

    results = {"emails_sent": 0, "failed": 0, "skipped": 0}

    # Initialize email builder
    email_builder = SuggestionEmailBuilder(base_url=settings.APP_BASE_URL)

    for user in eligible_users:
        logger.info(f"Generating suggestion for: {user.email}")

        try:
            # Get user's watchlist symbols (default to SPY if empty)
            from trading.models import Watchlist

            watchlist_items = [
                item async for item in Watchlist.objects.filter(user=user).order_by("order")
            ]

            selector = StrategySelector(user)

            # Initialize streaming for suggestion generation (matching automated cycle pattern)
            from streaming.services.stream_manager import GlobalStreamManager

            manager = await GlobalStreamManager.get_user_manager(user.id)

            # Get symbols for streaming initialization
            stream_symbols = (
                [item.symbol for item in watchlist_items] if watchlist_items else ["SPY"]
            )

            logger.info(f"User {user.id}: Starting streaming for {len(stream_symbols)} symbols...")
            streaming_ready = await manager.ensure_streaming_for_automation(
                stream_symbols
            )  # Subscribe to ALL symbols

            if not streaming_ready:
                logger.error(
                    f"User {user.id}: Failed to start streaming - skipping email generation"
                )
                results["failed"] += 1
                continue

            # Wait for data stabilization (matching automated cycle pattern)
            import asyncio

            DATA_STABILIZATION_DELAY = 3
            logger.info(
                f"User {user.id}: Waiting {DATA_STABILIZATION_DELAY}s for streaming data..."
            )
            await asyncio.sleep(DATA_STABILIZATION_DELAY)

            # Determine flow based on watchlist size
            if not watchlist_items:
                # Case 1: Empty watchlist → Default to SPY (backward compatibility)
                symbol = "SPY"
                logger.info(f"User {user.email} has empty watchlist, defaulting to SPY")

                # Single-symbol flow (all strategies, Senex excluded)
                suggestions_list, global_context = await selector.a_select_top_suggestions(
                    symbol=symbol, count=2, suggestion_mode=True  # Top 2 strategies
                )

                subject, body = email_builder.build_single_symbol_email(
                    user=user, suggestions_list=suggestions_list, global_context=global_context
                )

            elif len(watchlist_items) == 1:
                # Case 2: Single symbol → Use original single-symbol flow
                symbol = watchlist_items[0].symbol
                logger.info(f"User {user.email} watchlist: single symbol {symbol}")

                suggestions_list, global_context = await selector.a_select_top_suggestions(
                    symbol=symbol, count=2, suggestion_mode=True  # Top 2 strategies
                )

                subject, body = email_builder.build_single_symbol_email(
                    user=user, suggestions_list=suggestions_list, global_context=global_context
                )

            else:
                # Case 3: Multiple symbols → Use multi-symbol parallel flow
                symbols = [item.symbol for item in watchlist_items]
                logger.info(
                    f"User {user.email} watchlist: {len(symbols)} symbols "
                    f"({', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''})"
                )

                # Process all symbols in parallel, get top candidates
                result = await _process_symbols_parallel(selector, symbols)
                candidates = result["candidates"]
                failed_symbols = result["failed_symbols"]

                # Build consolidated multi-symbol email
                subject, body = email_builder.build_multi_symbol_email(
                    user=user,
                    candidates=candidates,
                    failed_symbols=failed_symbols,
                    watchlist=symbols,
                )

            # Send email
            success = await email_service.asend_email(
                subject=subject,
                body=body,
                recipient=user.email,
                fail_silently=True,
            )

            if success:
                results["emails_sent"] += 1
                logger.info(f"Sent daily suggestion email to {user.email}")

            # Clean up streaming (matching automated cycle pattern)
            await manager.stop_streaming()
            logger.info(f"User {user.id}: Streaming stopped after email generation")

        except Exception as exc:
            logger.error(f"Failed to send suggestion to {user.email}: {exc}", exc_info=True)
            results["failed"] += 1
            # Ensure streaming is stopped even on error
            try:
                if "manager" in locals():
                    await manager.stop_streaming()
            except Exception:
                pass
            continue

    logger.info(
        f"Daily suggestions complete. Sent: {results['emails_sent']}, "
        f"Failed: {results['failed']}, Skipped: {results['skipped']}"
    )

    return results


async def _process_symbols_parallel(selector, symbols: list[str]) -> list[dict]:
    """
    Process multiple symbols in parallel for multi-equity trade suggestions.

    For each symbol, evaluates all strategies and returns the BEST strategy
    with its score. Results are sorted globally by score descending.

    Args:
        selector: StrategySelector instance
        symbols: List of symbols to process

    Returns:
        List of dicts sorted by score (highest first):
        [
            {
                "symbol": "NVDA",
                "strategy_name": "senex_trident",
                "suggestion": TradingSuggestion obj,
                "explanation": dict,
                "score": 85,
                "market_report": dict
            },
            ...
        ]
    """
    import asyncio

    # Task-local semaphore for rate limiting (max 5 concurrent API calls)
    # Created here to avoid module-level issues with distributed workers
    semaphore = asyncio.Semaphore(5)

    async def process_with_limit(symbol: str):
        """Process single symbol with rate limiting."""
        async with semaphore:
            return await selector.a_select_top_suggestions(symbol, count=1, suggestion_mode=True)

    logger.info(f"Processing {len(symbols)} symbols (max 5 concurrent)...")

    # Process all symbols with rate limiting (semaphore limits actual concurrency)
    tasks = [process_with_limit(symbol) for symbol in symbols]

    # Gather with exception handling
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate successful results AND diagnostic info
    all_candidates = []
    failed_symbols = []  # Track symbols with no trades for diagnostics

    for symbol, result in zip(symbols, results, strict=False):
        if isinstance(result, Exception):
            logger.error(f"Failed to process {symbol}: {result}")
            failed_symbols.append({"symbol": symbol, "reason": "exception", "details": str(result)})
            continue

        suggestions_list, global_context = result

        if not suggestions_list:
            # No suitable strategy for this symbol - capture diagnostic info
            all_scores = global_context.get("all_scores", {})
            context_type = global_context.get("type", "unknown")

            # Get best score for this symbol
            best_score = 0
            best_strategy = None
            if all_scores:
                for strategy, score_data in all_scores.items():
                    score = score_data.get("score", 0)
                    if score > best_score:
                        best_score = score
                        best_strategy = strategy

            failed_symbols.append(
                {
                    "symbol": symbol,
                    "reason": context_type,  # "low_scores" or "generation_failures"
                    "best_score": best_score,
                    "best_strategy": best_strategy,
                    "all_scores": all_scores,
                }
            )

            logger.info(f"{symbol}: No suitable trades")
            continue

        # Extract the top strategy for this symbol
        strategy_name, suggestion, explanation = suggestions_list[0]
        all_scores = global_context.get("all_scores", {})
        score = all_scores.get(strategy_name, {}).get("score", 0)

        all_candidates.append(
            {
                "symbol": symbol,
                "strategy_name": strategy_name,
                "suggestion": suggestion,
                "explanation": explanation,
                "score": score,
                "market_report": global_context.get("market_report"),
            }
        )

        logger.info(f"{symbol}: {strategy_name} (score: {score:.1f})")

    # Sort by score descending (highest scores first)
    all_candidates.sort(key=lambda x: x["score"], reverse=True)

    logger.info(
        f"Parallel processing complete: {len(all_candidates)}/{len(symbols)} symbols "
        f"have suitable trades"
    )

    # Return both candidates AND diagnostic info
    return {"candidates": all_candidates, "failed_symbols": failed_symbols}


@shared_task
@monitor_task
def automated_daily_trade_cycle():
    """Execute automated trades for opted-in users."""
    try:
        return run_async(_async_automated_daily_trade_cycle())
    except Exception as e:
        logger.error(f"Error in automated_daily_trade_cycle: {e}", exc_info=True)
        return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}


async def _async_automated_daily_trade_cycle():
    """Async implementation of automated daily trade cycle."""
    from trading.services.automated_trading_service import AutomatedTradingService

    logger.info("Starting automated daily trade cycle...")

    # Query database synchronously to get list
    eligible_accounts = await sync_to_async(list)(
        TradingAccount.objects.filter(
            is_active=True,
            trading_preferences__is_automated_trading_enabled=True,
            is_token_valid=True,
        ).select_related("user", "trading_preferences")
    )

    logger.info(f"Found {len(eligible_accounts)} eligible accounts with valid tokens")

    results = {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    service = AutomatedTradingService()

    for account in eligible_accounts:
        user = account.user
        logger.info(f"Processing automated trade for: {user.email}")

        try:
            # Use async version to stay in same event loop
            result = await service.a_process_account(account)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Failed for {user.email}: {exc}", exc_info=True)
            results["failed"] += 1
            continue

        status = result.get("status")
        if status == "success":
            results["succeeded"] += 1
            results["processed"] += 1
        elif status == "skipped":
            results["skipped"] += 1
        else:
            results["failed"] += 1

    logger.info(
        f"Automated cycle complete. "
        f"Processed: {results['processed']}, "
        f"Succeeded: {results['succeeded']}, "
        f"Failed: {results['failed']}, "
        f"Skipped: {results['skipped']}"
    )

    return results


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=180,  # 3 minutes
    time_limit=300,  # 5 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def monitor_positions_for_dte_closure(self):
    """
    Evaluate open positions and submit closing orders near expiration.

    P1.2: Medium-duration task with 3min/5min timeout
    """
    try:
        return run_async(_async_monitor_positions_for_dte())
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(f"Error in monitor_positions_for_dte_closure: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries))
        return {"status": "error", "message": str(exc)}


async def _async_monitor_positions_for_dte():
    positions = [
        position
        async for position in Position.objects.select_related(
            "user", "trading_account", "trading_account__trading_preferences"
        )
        .filter(lifecycle_state__in=OPEN_STATES)
        .order_by("trading_account__id")
    ]

    if not positions:
        return {"status": "success", "evaluated": 0, "closed": 0, "notified": 0}

    managers: dict[int, DTEManager] = {}
    evaluated = 0
    closed = 0
    notified = 0

    for position in positions:
        evaluated += 1
        account = position.trading_account
        if account is None:
            logger.warning(
                "Position %s has no linked trading account; skipping DTE automation",
                position.id,
            )
            continue

        manager = managers.setdefault(position.user_id, DTEManager(position.user))
        current_dte = manager.calculate_current_dte(position)
        if current_dte is None:
            continue

        threshold = manager.get_dte_threshold(position)
        if current_dte > threshold and current_dte >= 0:
            continue

        # DTE management applies to app-managed positions with profit targets,
        # regardless of whether automated trading is enabled for new entries
        if not position.is_app_managed or not position.profit_targets_created:
            await manager.notify_manual_action(position, current_dte)
            notified += 1
            continue

        if position.lifecycle_state not in OPEN_STATES:
            continue

        try:
            success = await manager.close_position_at_dte(position, current_dte)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Error closing position %s for DTE automation: %s",
                position.id,
                exc,
                exc_info=True,
            )
            continue

        if success:
            closed += 1

    return {
        "status": "success",
        "evaluated": evaluated,
        "closed": closed,
        "notified": notified,
    }


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=600,  # 10 minutes
    time_limit=900,  # 15 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def sync_transactions_task(self):
    """
    Periodic task to sync transactions from TastyTrade.

    Imports transaction history (fills, assignments, exercises, expirations)
    and links them to Position objects using opening_order_id.

    This is part of the order-aware position tracking system.
    """
    try:
        return run_async(_async_sync_transactions())
    except Exception as e:
        logger.error(f"Transaction sync task failed: {e}", exc_info=True)
        if self.request.retries < self.max_retries:
            countdown = 60 * (2**self.request.retries)
            logger.info(f"Retrying sync_transactions_task in {countdown}s")
            raise self.retry(countdown=countdown)
        return {
            "status": "failed",
            "accounts_processed": 0,
            "accounts_failed": 0,
            "transactions_imported": 0,
            "transactions_linked": 0,
            "errors": [],
            "fatal_error": str(e),
        }


async def _async_sync_transactions():
    """Async implementation of transaction sync task."""
    from datetime import date, timedelta

    from services.orders.transactions import TransactionImporter

    logger.info("Starting transaction sync task")

    summary = {
        "status": "success",
        "accounts_processed": 0,
        "accounts_failed": 0,
        "transactions_imported": 0,
        "transactions_linked": 0,
        "errors": [],
    }

    # Get all active accounts with automated trading enabled and valid tokens
    accounts = await sync_to_async(list)(
        TradingAccount.objects.filter(
            is_active=True,
            trading_preferences__is_automated_trading_enabled=True,
            is_token_valid=True,
        ).select_related("user", "trading_preferences")
    )

    num_accounts = len(accounts)
    logger.info(f"Syncing transactions for {num_accounts} active accounts")

    importer = TransactionImporter()

    for account in accounts:
        try:
            user = account.user
            acct_num = account.account_number
            logger.info(f"Syncing transactions for account {acct_num}")

            import_result = await importer.import_transactions(
                user=user,
                account=account,
                start_date=date.today() - timedelta(days=7),
            )

            if import_result.get("errors"):
                logger.warning(
                    f"Transaction import for {acct_num} "
                    f"had {len(import_result['errors'])} errors"
                )

            # Link transactions to positions
            link_result = await importer.link_transactions_to_positions(
                user=user,
                account=account,
            )

            summary["accounts_processed"] += 1
            summary["transactions_imported"] += import_result.get("imported", 0)
            summary["transactions_linked"] += link_result.get("linked", 0)

            logger.info(
                f"Synced transactions for account {acct_num}: "
                f"{import_result.get('imported', 0)} imported, "
                f"{link_result.get('linked', 0)} linked to positions"
            )

        except Exception as e:
            logger.error(
                f"Error syncing transactions for account {account.account_number}: {e}",
                exc_info=True,
            )
            summary["accounts_failed"] += 1
            summary["errors"].append(
                {
                    "account_number": account.account_number,
                    "error": str(e),
                }
            )
            # Continue with next account instead of failing entire task

    accts_proc = summary["accounts_processed"]
    accts_fail = summary["accounts_failed"]
    txns_imp = summary["transactions_imported"]
    txns_link = summary["transactions_linked"]
    logger.info(
        f"Transaction sync complete: {accts_proc} accounts processed, "
        f"{accts_fail} failed, {txns_imp} imported, {txns_link} linked"
    )

    return summary


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=300,  # 5 minutes
    time_limit=600,  # 10 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def ensure_historical_data(self):
    """
    Ensure all user watchlist symbols have minimum historical data (90 days default).

    Scheduled daily at 5:30 PM ET (after market close) via Celery Beat.
    Checks database for data availability and fetches from Stooq if insufficient.

    This task:
    - Iterates over all active users and their watchlists
    - Validates watchlist symbols have adequate historical data
    - Fills gaps automatically using HistoricalDataProvider
    - Logs warnings if fetch fails (non-blocking)
    - Deduplicates symbols across users for efficiency

    P1.2: Medium-duration task with 5min/10min timeout
    """
    try:
        from services.market_data.historical import HistoricalDataProvider
        from trading.models import Watchlist

        provider = HistoricalDataProvider()
        min_days = getattr(settings, "MINIMUM_HISTORICAL_DAYS", 90)

        # Collect all unique symbols from all user watchlists
        all_symbols = set(Watchlist.objects.values_list("symbol", flat=True).distinct())

        # Also include DEFAULT_WATCHLIST_SYMBOLS to ensure defaults are covered
        # Extract symbols from (symbol, description) tuples
        default_list = getattr(settings, "DEFAULT_WATCHLIST_SYMBOLS", [])
        default_symbols = [s[0] for s in default_list]
        all_symbols.update(default_symbols)

        logger.info(
            f"Ensuring {min_days} days of historical data for {len(all_symbols)} symbols "
            f"(from {Watchlist.objects.values('user').distinct().count()} user watchlists)"
        )

        results = {
            "status": "success",
            "symbols_checked": len(all_symbols),
            "symbols_updated": 0,
            "symbols_failed": 0,
            "errors": [],
        }

        for symbol in sorted(all_symbols):
            try:
                success = provider.ensure_minimum_data(symbol, min_days=min_days)
                if success:
                    results["symbols_updated"] += 1
                    logger.info(f"[OK] {symbol}: Historical data validated/updated")
                else:
                    results["symbols_failed"] += 1
                    results["errors"].append(
                        {"symbol": symbol, "error": "Failed to fetch/validate historical data"}
                    )
                    logger.warning(f"[FAIL] {symbol}: Failed to ensure historical data")

                # Rate limit: be nice to Stooq API (1 second between requests)
                time.sleep(1)

            except Exception as e:
                results["symbols_failed"] += 1
                results["errors"].append({"symbol": symbol, "error": str(e)})
                logger.error(f"Error ensuring data for {symbol}: {e}")

        logger.info(
            f"Historical data check complete: {results['symbols_updated']} updated, "
            f"{results['symbols_failed']} failed"
        )

        return results

    except Exception as e:
        logger.error(f"Fatal error in ensure_historical_data task: {e}", exc_info=True)
        if self.request.retries < self.max_retries:
            countdown = 60 * (2**self.request.retries)
            logger.info(f"Retrying ensure_historical_data in {countdown}s")
            raise self.retry(countdown=countdown)
        return {
            "status": "failed",
            "symbols_checked": 0,
            "symbols_updated": 0,
            "symbols_failed": 0,
            "errors": [],
            "fatal_error": str(e),
        }


@shared_task(
    bind=True,
    max_retries=2,
    soft_time_limit=180,  # 3 minutes
    time_limit=300,  # 5 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
@monitor_task
def persist_greeks_from_cache(self):
    """
    Persist Greeks data from cache to HistoricalGreeks model.

    Following REALTIME_DATA_FLOW_PATTERN.md:
    - StreamManager calculates and caches Greeks
    - This task persists to database (separate concern)
    - Scheduled every 10 minutes via Celery Beat


    Returns:
        dict: Summary with counts of persisted records and any errors
    """
    try:
        return run_async(_async_persist_greeks_from_cache())
    except Exception as e:
        logger.error(f"Error in persist_greeks_from_cache task: {e}", exc_info=True)

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            countdown = 120 * (2**self.request.retries)  # 2min, 4min
            logger.info(
                f"Retrying persist_greeks_from_cache in {countdown}s "
                f"(attempt {self.request.retries + 1})"
            )
            raise self.retry(countdown=countdown)

        return {"status": "error", "message": str(e)}


async def _async_persist_greeks_from_cache():
    """Async implementation of Greeks persistence from cache."""
    from decimal import Decimal

    from django.core.cache import cache

    from trading.models import HistoricalGreeks

    summary = {
        "status": "success",
        "symbols_checked": 0,
        "records_persisted": 0,
        "errors": [],
    }

    try:
        # Get all active positions to know which Greeks to persist
        active_positions = [
            pos
            async for pos in Position.objects.filter(
                lifecycle_state__in=["open_full", "open_partial", "closing"]
            ).select_related("user")
        ]

        logger.info(f"Checking Greeks for {len(active_positions)} active positions")

        # Collect unique option symbols from all positions
        option_symbols = set()
        for position in active_positions:
            if position.metadata and "legs" in position.metadata:
                for leg in position.metadata["legs"]:
                    option_symbol = leg.get("symbol")
                    if option_symbol:
                        option_symbols.add(option_symbol)

        summary["symbols_checked"] = len(option_symbols)

        # Persist Greeks for each option symbol
        for option_symbol in option_symbols:
            try:
                # Try to get Greeks from cache (set by StreamManager)
                greeks_data = cache.get(CacheManager.dxfeed_greeks(option_symbol))

                if not greeks_data:
                    # Try streamer format as fallback
                    from tastytrade.instruments import Option

                    try:
                        streamer_symbol = Option.occ_to_streamer_symbol(option_symbol)
                        greeks_data = cache.get(CacheManager.dxfeed_greeks(streamer_symbol))
                    except Exception:
                        pass

                if greeks_data:
                    # Parse option symbol to extract components
                    from services.sdk.instruments import parse_occ_symbol

                    parsed = parse_occ_symbol(option_symbol)

                    # Create or update historical record
                    await HistoricalGreeks.objects.aupdate_or_create(
                        option_symbol=option_symbol,
                        timestamp=timezone.now(),
                        defaults={
                            "underlying_symbol": parsed["underlying"],
                            "delta": Decimal(str(greeks_data.get("delta", 0))),
                            "gamma": Decimal(str(greeks_data.get("gamma", 0))),
                            "theta": Decimal(str(greeks_data.get("theta", 0))),
                            "vega": Decimal(str(greeks_data.get("vega", 0))),
                            "rho": Decimal(str(greeks_data.get("rho", 0))),
                            "implied_volatility": Decimal(
                                str(greeks_data.get("implied_volatility", 0))
                            ),
                            "strike": parsed["strike"],
                            "expiration_date": parsed["expiration"],
                            "option_type": parsed["option_type"],
                        },
                    )

                    summary["records_persisted"] += 1

            except Exception as e:
                logger.warning(f"Failed to persist Greeks for {option_symbol}: {e}")
                summary["errors"].append({"symbol": option_symbol, "error": str(e)})

        logger.info(
            f"Greeks persistence complete: {summary['records_persisted']} records "
            f"persisted from {summary['symbols_checked']} symbols"
        )

        return summary

    except Exception as e:
        logger.error(f"Fatal error in Greeks persistence: {e}", exc_info=True)
        summary["status"] = "error"
        summary["message"] = str(e)
        return summary
