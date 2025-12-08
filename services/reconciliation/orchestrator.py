"""
Reconciliation Orchestrator - Unified reconciliation workflow.

This orchestrator consolidates all position and order reconciliation logic
into a single workflow that can be used by:
- Celery scheduled tasks (batch_sync_data_task)
- Management commands (reconcile command)
- API endpoints (manual sync button)

The reconciliation workflow follows this order:
1. Sync order history from TastyTrade -> TastyTradeOrderHistory model
1.5. Sync transactions from TastyTrade -> TastyTradeTransaction model
2. Discover unmanaged positions from transactions
3. Sync positions from TastyTrade -> Position model
4. Process closures and calculate P&L
5. Reconcile trade states (pending_entry -> open_full)
6. Validate and fix profit targets

Each phase can be run independently or as part of the full workflow.
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from django.contrib.auth import get_user_model

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.logging import get_logger

User = get_user_model()
logger = get_logger(__name__)


@dataclass
class ReconciliationOptions:
    """Options for controlling reconciliation behavior."""

    # Which phases to run
    sync_order_history: bool = True
    sync_transactions: bool = True  # Phase 1.5: Transaction history sync
    discover_positions: bool = True  # Phase 2: Discover unmanaged positions
    sync_positions: bool = True
    process_closures: bool = True  # Phase 4: Process closed positions & P&L
    reconcile_trades: bool = True
    fix_profit_targets: bool = True

    # Filtering options
    user_id: int | None = None  # If set, only reconcile this user
    position_id: int | None = None  # If set, only reconcile this position
    symbol: str | None = None  # If set, only reconcile positions with this symbol

    # Behavior options
    dry_run: bool = False  # If True, don't make changes
    cancel_orphaned_orders: bool = False  # Cancel orders at broker not in DB
    replace_cancelled_targets: bool = False  # Replace cancelled profit targets
    days_back: int = 30  # Days of order history to sync

    # Output options
    verbose: bool = False  # Extra logging


@dataclass
class PhaseResult:
    """Result from a single reconciliation phase."""

    phase: str
    success: bool
    duration_seconds: float = 0.0
    items_processed: int = 0
    items_updated: int = 0
    items_created: int = 0
    errors: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class ReconciliationResult:
    """Complete result from a reconciliation run."""

    success: bool
    total_duration_seconds: float = 0.0
    phases_completed: list = field(default_factory=list)
    phases_failed: list = field(default_factory=list)
    phase_results: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "total_duration_seconds": self.total_duration_seconds,
            "phases_completed": self.phases_completed,
            "phases_failed": self.phases_failed,
            "phase_results": {
                phase: {
                    "success": result.success,
                    "duration_seconds": result.duration_seconds,
                    "items_processed": result.items_processed,
                    "items_updated": result.items_updated,
                    "items_created": result.items_created,
                    "errors": result.errors,
                    "details": result.details,
                }
                for phase, result in self.phase_results.items()
            },
            "summary": self.summary,
        }


class ReconciliationOrchestrator:
    """
    Orchestrates the complete reconciliation workflow.

    Usage:
        # Full reconciliation for all users (scheduled task)
        orchestrator = ReconciliationOrchestrator()
        result = await orchestrator.run()

        # Reconciliation for specific user (management command)
        orchestrator = ReconciliationOrchestrator(
            options=ReconciliationOptions(user_id=123)
        )
        result = await orchestrator.run()

        # Dry run for specific position
        orchestrator = ReconciliationOrchestrator(
            options=ReconciliationOptions(
                position_id=456,
                dry_run=True,
                verbose=True
            )
        )
        result = await orchestrator.run()
    """

    def __init__(self, options: ReconciliationOptions | None = None):
        """Initialize orchestrator with options."""
        self.options = options or ReconciliationOptions()

    async def run(self) -> ReconciliationResult:
        """
        Execute the full reconciliation workflow.

        Runs phases in order:
        1. sync_order_history - Get order states from broker
        2. sync_positions - Update positions from broker
        3. reconcile_trades - Fix trade/position state mismatches
        4. fix_profit_targets - Validate/recreate profit targets

        Returns:
            ReconciliationResult with details of each phase
        """
        start_time = time.time()

        result = ReconciliationResult(
            success=True,
            phases_completed=[],
            phases_failed=[],
            phase_results={},
            summary={},
        )

        # Get users to process
        users = await self._get_users_to_process()
        if not users:
            result.summary["message"] = "No users to process"
            result.total_duration_seconds = round(time.time() - start_time, 2)
            return result

        logger.info(
            f"Starting reconciliation for {len(users)} user(s) "
            f"(options: dry_run={self.options.dry_run})"
        )

        # Define phases with their enable flags and handlers
        # Order is critical - each phase depends on previous phases completing
        phases = [
            # Phase 1: Get order history from broker
            (
                "sync_order_history",
                self.options.sync_order_history,
                self._phase_sync_order_history,
            ),
            # Phase 1.5: Get transactions & link to positions
            (
                "sync_transactions",
                self.options.sync_transactions,
                self._phase_sync_transactions,
            ),
            # Phase 2: Discover NEW unmanaged positions from transactions
            (
                "discover_positions",
                self.options.discover_positions,
                self._phase_discover_positions,
            ),
            # Phase 3: Sync ALL positions (managed + unmanaged)
            (
                "sync_positions",
                self.options.sync_positions,
                self._phase_sync_positions,
            ),
            # Phase 4: Process closures & calculate P&L
            (
                "process_closures",
                self.options.process_closures,
                self._phase_process_closures,
            ),
            # Phase 5: Reconcile trade states
            (
                "reconcile_trades",
                self.options.reconcile_trades,
                self._phase_reconcile_trades,
            ),
            # Phase 6: Fix profit targets (LAST - after all closures processed)
            (
                "fix_profit_targets",
                self.options.fix_profit_targets,
                self._phase_fix_profit_targets,
            ),
        ]

        for phase_name, enabled, handler in phases:
            if not enabled:
                continue

            phase_result = await handler(users)
            result.phase_results[phase_name] = phase_result

            if phase_result.success:
                result.phases_completed.append(phase_name)
            else:
                result.phases_failed.append(phase_name)
                result.success = False

        result.total_duration_seconds = round(time.time() - start_time, 2)

        # Build summary
        result.summary = {
            "users_processed": len(users),
            "phases_completed": len(result.phases_completed),
            "phases_failed": len(result.phases_failed),
            "total_duration_seconds": result.total_duration_seconds,
        }

        completed = len(result.phases_completed)
        total = len(result.phase_results)
        duration = result.total_duration_seconds
        log_level = "info" if result.success else "warning"
        getattr(logger, log_level)(
            f"Reconciliation complete: {completed}/{total} phases succeeded in {duration}s"
        )

        return result

    async def _get_users_to_process(self) -> list:
        """Get list of users to process based on options."""
        if self.options.user_id:
            # Specific user
            try:
                user = await User.objects.aget(id=self.options.user_id)
                return [user]
            except User.DoesNotExist:
                logger.error(f"User {self.options.user_id} not found")
                return []

        if self.options.position_id:
            # Get user from position
            from trading.models import Position

            try:
                position = await Position.objects.select_related("user").aget(
                    id=self.options.position_id
                )
                return [position.user]
            except Position.DoesNotExist:
                logger.error(f"Position {self.options.position_id} not found")
                return []

        # All active users with valid tokens
        return await sync_to_async(list)(
            User.objects.filter(
                is_active=True,
                trading_accounts__is_primary=True,
                trading_accounts__is_token_valid=True,
            ).distinct()
        )

    async def _phase_sync_order_history(self, users: list) -> PhaseResult:
        """
        Phase 1: Sync order history from TastyTrade.

        Fetches recent orders from TastyTrade and caches them in TastyTradeOrderHistory model.
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="sync_order_history",
            success=True,
        )

        from services.orders.history import OrderHistoryService

        service = OrderHistoryService()

        for user in users:
            try:
                # Get accounts for this user
                accounts = await sync_to_async(list)(
                    TradingAccount.objects.filter(
                        user=user,
                        is_active=True,
                        is_token_valid=True,
                    )
                )

                for account in accounts:
                    if self.options.dry_run:
                        acct = account.account_number
                        logger.info(f"[DRY RUN] Would sync orders: {acct}")
                        result.items_processed += 1
                        continue

                    try:
                        sync_result = await service.sync_order_history(
                            account, days_back=self.options.days_back
                        )
                        result.items_processed += 1
                        result.items_created += sync_result.get("new_orders", 0)
                        result.items_updated += sync_result.get("updated_orders", 0)

                        if self.options.verbose:
                            synced = sync_result.get("orders_synced", 0)
                            logger.info(
                                f"Account {account.account_number}: " f"synced {synced} orders"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error syncing orders for {account.account_number}: {e}",
                            exc_info=True,
                        )
                        result.errors.append(
                            {
                                "account": account.account_number,
                                "error": str(e),
                            }
                        )

            except Exception as e:
                logger.error(f"Error processing user {user.id}: {e}", exc_info=True)
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 1 (sync_order_history): {result.items_processed} accounts, "
            f"{result.items_created} new orders, {result.items_updated} updated "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_sync_transactions(self, users: list) -> PhaseResult:
        """
        Phase 1.5: Sync transactions from TastyTrade.

        Fetches transaction history (fills, assignments, exercises, expirations)
        and links them to Position objects using opening_order_id.
        """
        import time
        from datetime import date, timedelta

        start_time = time.time()

        result = PhaseResult(
            phase="sync_transactions",
            success=True,
        )

        from services.orders.transactions import TransactionImporter

        importer = TransactionImporter()

        for user in users:
            try:
                # Get accounts for this user
                accounts = await sync_to_async(list)(
                    TradingAccount.objects.filter(
                        user=user,
                        is_active=True,
                        is_token_valid=True,
                    )
                )

                for account in accounts:
                    if self.options.dry_run:
                        acct = account.account_number
                        logger.info(f"[DRY RUN] Would sync txns: {acct}")
                        result.items_processed += 1
                        continue

                    try:
                        import_result = await importer.import_transactions(
                            user=user,
                            account=account,
                            start_date=date.today() - timedelta(days=self.options.days_back),
                        )
                        link_result = await importer.link_transactions_to_positions(
                            user=user,
                            account=account,
                        )

                        result.items_processed += 1
                        result.items_created += import_result.get("imported", 0)
                        result.items_updated += link_result.get("linked", 0)

                        if self.options.verbose:
                            imported = import_result.get("imported", 0)
                            linked = link_result.get("linked", 0)
                            logger.info(
                                f"Account {account.account_number}: "
                                f"{imported} txns imported, {linked} linked"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error syncing txns for {account.account_number}: {e}",
                            exc_info=True,
                        )
                        result.errors.append(
                            {
                                "account": account.account_number,
                                "error": str(e),
                            }
                        )

            except Exception as e:
                logger.error(f"Error processing user {user.id}: {e}", exc_info=True)
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 1.5 (sync_transactions): {result.items_processed} accounts, "
            f"{result.items_created} imported, {result.items_updated} linked "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_discover_positions(self, users: list) -> PhaseResult:
        """
        Phase 2: Discover unmanaged positions from transactions.

        Creates Position records for user-opened positions at TastyTrade.
        Uses opening_order_id to differentiate identical positions.
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="discover_positions",
            success=True,
        )

        from services.positions.position_discovery import PositionDiscoveryService

        service = PositionDiscoveryService()

        for user in users:
            try:
                # Get accounts for this user
                accounts = await sync_to_async(list)(
                    TradingAccount.objects.filter(
                        user=user,
                        is_active=True,
                        is_token_valid=True,
                    )
                )

                for account in accounts:
                    if self.options.dry_run:
                        logger.info(
                            f"[DRY RUN] Would discover positions for "
                            f"{account.account_number}"
                        )
                        result.items_processed += 1
                        continue

                    try:
                        discovery_result = await service.discover_unmanaged_positions(
                            user=user,
                            account=account,
                            lookback_days=self.options.days_back,
                        )

                        result.items_processed += 1
                        created = discovery_result.get("positions_created", 0)
                        linked = discovery_result.get("transactions_linked", 0)
                        result.items_created += created
                        result.items_updated += linked

                        if self.options.verbose and created:
                            logger.info(
                                f"Account {account.account_number}: "
                                f"discovered {created} positions"
                            )

                        if discovery_result.get("errors"):
                            for error in discovery_result["errors"]:
                                result.errors.append({
                                    "account": account.account_number,
                                    "error": str(error),
                                })

                    except Exception as e:
                        logger.error(
                            f"Error discovering positions for "
                            f"{account.account_number}: {e}",
                            exc_info=True,
                        )
                        result.errors.append({
                            "account": account.account_number,
                            "error": str(e),
                        })

            except Exception as e:
                logger.error(
                    f"Error processing user {user.id}: {e}",
                    exc_info=True,
                )
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 2 (discover_positions): {result.items_processed} accounts, "
            f"{result.items_created} positions discovered, "
            f"{result.items_updated} txns linked "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_sync_positions(self, users: list) -> PhaseResult:
        """
        Phase 3: Sync positions from TastyTrade.

        Updates Position model with current state from TastyTrade.
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="sync_positions",
            success=True,
        )

        from services.positions.sync import PositionSyncService

        service = PositionSyncService()

        for user in users:
            try:
                if self.options.dry_run:
                    logger.info(f"[DRY RUN] Would sync positions for user {user.id}")
                    result.items_processed += 1
                    continue

                sync_result = await service.sync_all_positions(user)

                if sync_result.get("error"):
                    result.errors.append(
                        {
                            "user_id": user.id,
                            "error": sync_result["error"],
                        }
                    )
                else:
                    result.items_processed += 1
                    imported: int = sync_result.get("imported") or 0  # type: ignore
                    updated: int = sync_result.get("updated") or 0  # type: ignore
                    result.items_created += imported
                    result.items_updated += updated

                    if self.options.verbose:
                        found = sync_result.get("positions_found", 0)
                        logger.info(
                            f"User {user.id}: synced {found} positions "
                            f"({imported} new, {updated} updated)"
                        )

            except Exception as e:
                logger.error(
                    f"Error syncing positions for user {user.id}: {e}",
                    exc_info=True,
                )
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 3 (sync_positions): {result.items_processed} users, "
            f"{result.items_created} new, {result.items_updated} updated "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_process_closures(self, users: list) -> PhaseResult:
        """
        Phase 4: Process closed positions and calculate P&L.

        Detects positions no longer at broker, calculates P&L from transactions,
        handles assignments by creating equity positions.
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="process_closures",
            success=True,
        )

        from services.positions.closure_service import PositionClosureService

        service = PositionClosureService()

        for user in users:
            try:
                # Get accounts for this user
                accounts = await sync_to_async(list)(
                    TradingAccount.objects.filter(
                        user=user,
                        is_active=True,
                        is_token_valid=True,
                    )
                )

                for account in accounts:
                    if self.options.dry_run:
                        logger.info(
                            f"[DRY RUN] Would process closures for "
                            f"{account.account_number}"
                        )
                        result.items_processed += 1
                        continue

                    try:
                        closure_result = await service.process_closed_positions(
                            user=user,
                            account=account,
                        )

                        result.items_processed += 1
                        closed = closure_result.get("positions_closed", 0)
                        result.items_updated += closed

                        # Track P&L in details
                        result.details.setdefault("total_pnl", Decimal("0"))
                        result.details["total_pnl"] += closure_result.get(
                            "total_pnl", Decimal("0")
                        )

                        if self.options.verbose and closed:
                            pnl = closure_result.get("total_pnl", 0)
                            logger.info(
                                f"Account {account.account_number}: "
                                f"closed {closed} positions, P&L=${pnl}"
                            )

                        if closure_result.get("errors"):
                            for error in closure_result["errors"]:
                                result.errors.append({
                                    "account": account.account_number,
                                    "error": str(error),
                                })

                    except Exception as e:
                        logger.error(
                            f"Error processing closures for "
                            f"{account.account_number}: {e}",
                            exc_info=True,
                        )
                        result.errors.append({
                            "account": account.account_number,
                            "error": str(e),
                        })

            except Exception as e:
                logger.error(
                    f"Error processing user {user.id}: {e}",
                    exc_info=True,
                )
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        total_pnl = result.details.get("total_pnl", 0)
        logger.info(
            f"Phase 4 (process_closures): {result.items_processed} accounts, "
            f"{result.items_updated} positions closed, P&L=${total_pnl} "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_reconcile_trades(self, users: list) -> PhaseResult:
        """
        Phase 5: Reconcile trade states.

        Fixes discrepancies between Trade status and TastyTrade order status.
        Also fixes stuck positions (pending_entry -> open_full).
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="reconcile_trades",
            success=True,
        )

        from services.positions.lifecycle.trade_reconciliation_service import (
            TradeReconciliationService,
        )

        for user in users:
            try:
                if self.options.dry_run:
                    logger.info(f"[DRY RUN] Would reconcile trades for user {user.id}")
                    result.items_processed += 1
                    continue

                service = TradeReconciliationService(user)

                # Reconcile trades
                reconcile_result = await service.reconcile_trades()
                result.items_processed += 1
                result.items_updated += reconcile_result.get("trades_updated", 0)

                if reconcile_result.get("errors"):
                    for error in reconcile_result["errors"]:
                        result.errors.append({"user_id": user.id, "error": error})

                # Fix stuck positions
                fix_result = await service.fix_stuck_positions()
                result.details.setdefault("stuck_positions_fixed", 0)
                fixed = fix_result.get("positions_fixed", 0)
                result.details["stuck_positions_fixed"] += fixed

                if fix_result.get("errors"):
                    for error in fix_result["errors"]:
                        result.errors.append({"user_id": user.id, "error": str(error)})

                if self.options.verbose:
                    trades_upd = reconcile_result.get("trades_updated", 0)
                    pos_fixed = fix_result.get("positions_fixed", 0)
                    logger.info(
                        f"User {user.id}: {trades_upd} trades updated, "
                        f"{pos_fixed} stuck positions fixed"
                    )

            except Exception as e:
                logger.error(
                    f"Error reconciling trades for user {user.id}: {e}",
                    exc_info=True,
                )
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 3 (reconcile_trades): {result.items_processed} users, "
            f"{result.items_updated} trades updated, "
            f"{result.details.get('stuck_positions_fixed', 0)} fixed "
            f"[{result.duration_seconds}s]"
        )

        return result

    async def _phase_fix_profit_targets(self, users: list) -> PhaseResult:
        """
        Phase 6: Validate and fix profit targets.

        LAST phase - runs after all closures processed to avoid recreating
        profit targets for positions that closed during sync.

        Checks each open position to ensure profit target orders:
        - Exist at TastyTrade
        - Are in the correct state (live, not cancelled)
        - Recreates missing/cancelled profit targets
        """
        import time

        start_time = time.time()

        result = PhaseResult(
            phase="fix_profit_targets",
            success=True,
        )

        from services.positions.lifecycle.trade_reconciliation_service import (
            TradeReconciliationService,
        )

        for user in users:
            try:
                if self.options.dry_run:
                    logger.info(f"[DRY RUN] Would check profit targets for {user.id}")
                    result.items_processed += 1
                    continue

                service = TradeReconciliationService(user)

                fix_result = await service.fix_incomplete_profit_targets()

                result.items_processed += fix_result.get("positions_checked", 0)
                result.items_updated += fix_result.get("incomplete_targets_fixed", 0)
                result.details.setdefault("orders_recreated", 0)
                recreated = fix_result.get("missing_orders_recreated", 0)
                result.details["orders_recreated"] += recreated

                if fix_result.get("errors"):
                    for error in fix_result["errors"]:
                        result.errors.append({"user_id": user.id, "error": str(error)})

                if self.options.verbose:
                    checked = fix_result.get("positions_checked", 0)
                    fixed = fix_result.get("incomplete_targets_fixed", 0)
                    logger.info(f"User {user.id}: checked {checked} positions, " f"fixed {fixed}")

            except Exception as e:
                logger.error(
                    f"Error fixing profit targets for user {user.id}: {e}",
                    exc_info=True,
                )
                result.errors.append({"user_id": user.id, "error": str(e)})

        result.duration_seconds = round(time.time() - start_time, 2)
        result.success = len(result.errors) == 0

        logger.info(
            f"Phase 4 (fix_profit_targets): "
            f"{result.items_processed} positions checked, "
            f"{result.items_updated} fixed, "
            f"{result.details.get('orders_recreated', 0)} orders recreated "
            f"[{result.duration_seconds}s]"
        )

        return result


# Convenience function for running reconciliation synchronously
def run_reconciliation_sync(options: ReconciliationOptions | None = None) -> dict:
    """
    Run reconciliation synchronously (for use in Celery tasks).

    Args:
        options: ReconciliationOptions to control behavior

    Returns:
        Dict with reconciliation results
    """
    from services.core.utils.async_utils import run_async

    orchestrator = ReconciliationOrchestrator(options=options)
    result = run_async(orchestrator.run())
    return result.to_dict()
