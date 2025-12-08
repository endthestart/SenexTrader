"""
Position Closure Service - Handle position closures with P&L calculation.

This service detects positions that have been closed at the broker and:
1. Calculates P&L from actual transactions
2. Determines closure reason (profit target, manual, assignment, expiration)
3. Creates equity positions when options are assigned
4. Updates position state to "closed"

Usage:
    from services.positions.closure_service import PositionClosureService

    service = PositionClosureService()
    result = await service.process_closed_positions(user, account)
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from asgiref.sync import sync_to_async
from tastytrade import Account

from accounts.models import TradingAccount
from services.core.data_access import get_oauth_session
from services.core.logging import get_logger
from trading.models import Position, TastyTradeTransaction

User = get_user_model()
logger = get_logger(__name__)


# Closure reason constants
CLOSURE_PROFIT_TARGET = "profit_target"
CLOSURE_MANUAL = "manual_close"
CLOSURE_ASSIGNMENT = "assignment"
CLOSURE_EXPIRED_WORTHLESS = "expired_worthless"
CLOSURE_EXERCISE = "exercise"
CLOSURE_UNKNOWN = "unknown"


class PositionClosureService:
    """
    Handle position closures with P&L calculation.

    Detects positions no longer at broker and:
    1. Gets opening transactions (related_position + action="Sell/Buy to Open")
    2. Gets closing transactions (related_position + action="Sell/Buy to Close")
    3. Gets assignment transactions (transaction_sub_type contains "assignment")
    4. Calculates P&L: opening_value + closing_value
    5. Handles all scenarios: profit target, manual, assignment, expiration

    P&L Formula:
        opening_value = sum(
            +tx.net_value if tx.action == "Sell to Open" else -tx.net_value
            for tx in opening_txns
        )
        closing_value = sum(
            -tx.net_value if tx.action == "Buy to Close" else +tx.net_value
            for tx in closing_txns
        )
        pnl = opening_value + closing_value
    """

    async def process_closed_positions(
        self,
        user: User,
        account: TradingAccount,
    ) -> dict:
        """
        Detect and process closed positions.

        Args:
            user: User to process positions for
            account: Trading account to check

        Returns:
            {
                "positions_closed": N,
                "total_pnl": Decimal,
                "assignments_processed": M,
                "expirations_detected": X,
                "errors": [...],
            }
        """
        result = {
            "positions_closed": 0,
            "total_pnl": Decimal("0"),
            "assignments_processed": 0,
            "expirations_detected": 0,
            "errors": [],
        }

        try:
            # Get broker position leg symbols (full OCC symbols, not just underlying)
            broker_leg_symbols = await self._get_broker_leg_symbols(user, account)
            if broker_leg_symbols is None:
                result["errors"].append("Failed to get broker positions")
                return result

            logger.info(
                f"User {user.id}: Broker has {len(broker_leg_symbols)} "
                f"open position legs"
            )

            # Get all open positions that might be closed
            open_positions = await sync_to_async(list)(
                Position.objects.filter(
                    user=user,
                    trading_account=account,
                    lifecycle_state__in=[
                        "open_full",
                        "open_partial",
                        "closing",
                    ],
                )
            )

            if not open_positions:
                logger.debug(f"User {user.id}: No open positions to check")
                return result

            logger.info(
                f"User {user.id}: Checking {len(open_positions)} "
                f"open positions for closures"
            )

            for position in open_positions:
                # Check if ANY of the position's legs are still at broker
                # A position is only closed when ALL its legs are gone
                if self._position_has_open_legs(position, broker_leg_symbols):
                    continue  # Still open at broker

                # Position closed at broker - process closure
                try:
                    closure_result = await self._process_single_closure(
                        position, user, account
                    )

                    if closure_result.get("closed"):
                        result["positions_closed"] += 1
                        result["total_pnl"] += closure_result.get(
                            "pnl", Decimal("0")
                        )

                        if closure_result.get("reason") == CLOSURE_ASSIGNMENT:
                            result["assignments_processed"] += 1
                        elif closure_result.get("reason") in [
                            CLOSURE_EXPIRED_WORTHLESS,
                        ]:
                            result["expirations_detected"] += 1

                except Exception as e:
                    logger.error(
                        f"Position {position.id}: Error processing closure: {e}",
                        exc_info=True,
                    )
                    result["errors"].append(
                        {
                            "position_id": position.id,
                            "error": str(e),
                        }
                    )

            if result["positions_closed"]:
                logger.info(
                    f"User {user.id}: Closed {result['positions_closed']} "
                    f"positions with total P&L: ${result['total_pnl']}"
                )

        except Exception as e:
            logger.error(
                f"User {user.id}: Position closure processing failed: {e}",
                exc_info=True,
            )
            result["errors"].append({"error": str(e)})

        return result

    def _position_has_open_legs(
        self,
        position: Position,
        broker_leg_symbols: set[str],
    ) -> bool:
        """
        Check if position has any legs still open at broker.

        A position is considered open if ANY of its legs are still
        present in the broker's position list.

        Args:
            position: Position to check
            broker_leg_symbols: Set of OCC symbols currently at broker

        Returns:
            True if any leg is still at broker, False if all closed
        """
        # Get position's leg symbols from metadata
        legs = position.metadata.get("legs", []) if position.metadata else []

        if not legs:
            # No leg data - fall back to underlying symbol check
            # This handles simple stock positions
            return position.symbol in broker_leg_symbols

        # Check if ANY leg is still at broker
        for leg in legs:
            leg_symbol = leg.get("symbol")
            if leg_symbol and leg_symbol in broker_leg_symbols:
                return True

        return False

    async def _get_broker_leg_symbols(
        self,
        user: User,
        account: TradingAccount,
    ) -> set[str] | None:
        """
        Get set of OCC leg symbols with open positions at broker.

        Returns actual OCC symbols (e.g., "QQQ   251219P00616000") not just
        underlying symbols, so we can distinguish between multiple positions
        on the same underlying.

        Args:
            user: User
            account: Trading account

        Returns:
            Set of OCC leg symbols, or None on error
        """
        try:
            session = await get_oauth_session(user)
            if not session:
                logger.error(f"User {user.id}: Failed to get OAuth session")
                return None

            tt_account = await Account.a_get(session, account.account_number)
            positions = await tt_account.a_get_positions(session)

            broker_leg_symbols = set()
            for pos in positions:
                # Get full OCC symbol (or stock symbol for equities)
                symbol = getattr(pos, "symbol", None)
                if symbol:
                    broker_leg_symbols.add(symbol)

            return broker_leg_symbols

        except Exception as e:
            logger.error(
                f"User {user.id}: Error fetching broker positions: {e}",
                exc_info=True,
            )
            return None

    async def _process_single_closure(
        self,
        position: Position,
        user: User,
        account: TradingAccount,
    ) -> dict:
        """
        Process closure for a single position.

        Args:
            position: Position to process
            user: User
            account: Trading account

        Returns:
            {
                "closed": bool,
                "reason": str,
                "pnl": Decimal,
            }
        """
        result = {
            "closed": False,
            "reason": None,
            "pnl": Decimal("0"),
        }

        # Get transactions for this position
        opening_txns = await self._get_opening_transactions(position)
        closing_txns = await self._get_closing_transactions(position)
        assignment_txns = await self._get_assignment_transactions(position)

        # Determine closure reason
        closure_reason = self._determine_closure_reason(
            position=position,
            opening_txns=opening_txns,
            closing_txns=closing_txns,
            assignment_txns=assignment_txns,
        )

        # Calculate P&L
        all_closing = list(closing_txns)
        if assignment_txns:
            all_closing.extend(assignment_txns)

        pnl = self._calculate_pnl(opening_txns, all_closing)

        # Handle assignment - create equity position if needed
        if closure_reason == CLOSURE_ASSIGNMENT and assignment_txns:
            await self._handle_assignment(
                position=position,
                assignment_txns=assignment_txns,
                user=user,
                account=account,
            )

        # Update position
        position.lifecycle_state = "closed"
        position.closed_at = timezone.now()
        position.closure_reason = closure_reason
        position.total_realized_pnl = pnl
        position.quantity = 0
        position.unrealized_pnl = Decimal("0")

        await position.asave()

        logger.info(
            f"Position {position.id} ({position.symbol}): "
            f"Closed with reason={closure_reason}, P&L=${pnl}"
        )

        result["closed"] = True
        result["reason"] = closure_reason
        result["pnl"] = pnl

        return result

    async def _get_opening_transactions(
        self,
        position: Position,
    ) -> list[TastyTradeTransaction]:
        """
        Get opening transactions for position.

        Args:
            position: Position to get transactions for

        Returns:
            List of opening transactions
        """
        return await sync_to_async(list)(
            TastyTradeTransaction.objects.filter(
                related_position=position,
                action__in=["Sell to Open", "Buy to Open"],
            ).order_by("executed_at")
        )

    async def _get_closing_transactions(
        self,
        position: Position,
    ) -> list[TastyTradeTransaction]:
        """
        Get closing transactions for position.

        Args:
            position: Position to get transactions for

        Returns:
            List of closing transactions
        """
        return await sync_to_async(list)(
            TastyTradeTransaction.objects.filter(
                related_position=position,
                action__in=["Buy to Close", "Sell to Close"],
            ).order_by("executed_at")
        )

    async def _get_assignment_transactions(
        self,
        position: Position,
    ) -> list[TastyTradeTransaction]:
        """
        Get assignment/exercise transactions for position.

        Args:
            position: Position to get transactions for

        Returns:
            List of assignment/exercise transactions
        """
        # Get assignment transactions
        assignments = await sync_to_async(list)(
            TastyTradeTransaction.objects.filter(
                related_position=position,
                transaction_sub_type__icontains="assignment",
            )
        )

        # Get exercise transactions
        exercises = await sync_to_async(list)(
            TastyTradeTransaction.objects.filter(
                related_position=position,
                transaction_sub_type__icontains="exercise",
            )
        )

        # Combine and sort by executed_at
        all_txns = assignments + exercises
        return sorted(all_txns, key=lambda tx: tx.executed_at)

    def _determine_closure_reason(
        self,
        position: Position,
        opening_txns: list[TastyTradeTransaction],
        closing_txns: list[TastyTradeTransaction],
        assignment_txns: list[TastyTradeTransaction],
    ) -> str:
        """
        Determine why position was closed.

        Args:
            position: Position
            opening_txns: Opening transactions
            closing_txns: Closing transactions
            assignment_txns: Assignment transactions

        Returns:
            Closure reason string
        """
        # Check for assignment first
        if assignment_txns:
            return CLOSURE_ASSIGNMENT

        # Check for closing transactions
        if closing_txns:
            # Check if profit target order exists
            profit_target_order_ids = set()
            if position.profit_target_details:
                for details in position.profit_target_details.values():
                    order_id = details.get("order_id")
                    if order_id:
                        profit_target_order_ids.add(str(order_id))

            # Check if closing transactions match profit target orders
            for tx in closing_txns:
                if tx.order_id and str(tx.order_id) in profit_target_order_ids:
                    return CLOSURE_PROFIT_TARGET

            # Otherwise it's a manual close
            return CLOSURE_MANUAL

        # Check for expiration
        expiration_date = self._get_expiration_date(position)
        if expiration_date and expiration_date <= date.today():
            return CLOSURE_EXPIRED_WORTHLESS

        # Unknown reason - no closing transactions found
        return CLOSURE_UNKNOWN

    def _get_expiration_date(self, position: Position) -> date | None:
        """
        Get expiration date from position metadata.

        Args:
            position: Position

        Returns:
            Expiration date or None
        """
        if not position.metadata:
            return None

        exp_str = position.metadata.get("expiration_date")
        if not exp_str:
            return None

        try:
            from datetime import datetime
            return datetime.fromisoformat(exp_str).date()
        except (ValueError, TypeError):
            return None

    def _calculate_pnl(
        self,
        opening_txns: list[TastyTradeTransaction],
        closing_txns: list[TastyTradeTransaction],
    ) -> Decimal:
        """
        Calculate P&L from transactions.

        Formula:
            opening_value = sum(
                +tx.net_value if tx.action == "Sell to Open" else -tx.net_value
                for tx in opening_txns
            )
            closing_value = sum(
                -tx.net_value if tx.action == "Buy to Close" else +tx.net_value
                for tx in closing_txns
            )
            pnl = opening_value + closing_value

        Args:
            opening_txns: Opening transactions
            closing_txns: Closing transactions (including assignments)

        Returns:
            Realized P&L
        """
        # Calculate opening value (credits positive, debits negative)
        opening_value = Decimal("0")
        for tx in opening_txns:
            if tx.net_value is None:
                continue
            if tx.action == "Sell to Open":
                opening_value += tx.net_value  # Credit received
            elif tx.action == "Buy to Open":
                opening_value -= abs(tx.net_value)  # Debit paid

        # Calculate closing value (opposite signs)
        closing_value = Decimal("0")
        for tx in closing_txns:
            if tx.net_value is None:
                continue
            if tx.action == "Buy to Close":
                closing_value -= abs(tx.net_value)  # Debit paid to close
            elif tx.action == "Sell to Close":
                closing_value += tx.net_value  # Credit received to close
            else:
                # Assignment/exercise - use net_value as-is
                # Assignments typically show as negative (you paid)
                closing_value += tx.net_value

        return opening_value + closing_value

    async def _handle_assignment(
        self,
        position: Position,
        assignment_txns: list[TastyTradeTransaction],
        user: User,
        account: TradingAccount,
    ) -> Position | None:
        """
        Handle option assignment - create equity position if shares acquired.

        Args:
            position: Option position that was assigned
            assignment_txns: Assignment transactions
            user: User
            account: Trading account

        Returns:
            Created equity Position or None
        """
        # Calculate total shares from assignment transactions
        total_shares = 0
        total_cost = Decimal("0")

        for tx in assignment_txns:
            # Options are 100 shares per contract
            quantity = tx.quantity or 0
            shares = int(abs(quantity) * 100)

            # Determine if we bought or sold shares
            # Put assignment = buy shares, Call assignment = sell shares
            if tx.symbol and "P" in tx.symbol:
                # Put - we bought shares
                total_shares += shares
            elif tx.symbol and "C" in tx.symbol:
                # Call - we sold shares
                total_shares -= shares

            # Add cost/credit
            if tx.net_value:
                total_cost += tx.net_value

        if total_shares == 0:
            logger.info(
                f"Position {position.id}: Assignment resulted in net 0 shares"
            )
            return None

        # Create equity position for the shares
        try:
            avg_price = abs(total_cost / total_shares) if total_shares else 0

            equity_position = await Position.objects.acreate(
                user=user,
                trading_account=account,
                symbol=position.symbol,
                instrument_type="Equity",
                strategy_type="stock_holding",
                lifecycle_state="open_full",
                quantity=total_shares,
                avg_price=avg_price,
                is_app_managed=False,  # Created by assignment
                opened_at=assignment_txns[0].executed_at,
                metadata={
                    "created_from": "assignment",
                    "original_position_id": position.id,
                    "assignment_transactions": [
                        tx.transaction_id for tx in assignment_txns
                    ],
                },
            )

            logger.info(
                f"Position {position.id}: Created equity position "
                f"{equity_position.id} for {total_shares} shares of "
                f"{position.symbol} @ ${avg_price}"
            )

            # Update original position with assignment info
            position.assigned_at = timezone.now()
            position.metadata["assigned_equity_position_id"] = equity_position.id
            await position.asave(update_fields=["assigned_at", "metadata"])

            return equity_position

        except Exception as e:
            logger.error(
                f"Position {position.id}: Failed to create equity position: {e}",
                exc_info=True,
            )
            return None

    async def recalculate_pnl(self, position: Position) -> Decimal:
        """
        Recalculate P&L for an existing position.

        Useful for fixing incorrect P&L values.

        Args:
            position: Position to recalculate P&L for

        Returns:
            Calculated P&L
        """
        opening_txns = await self._get_opening_transactions(position)
        closing_txns = await self._get_closing_transactions(position)
        assignment_txns = await self._get_assignment_transactions(position)

        all_closing = list(closing_txns)
        if assignment_txns:
            all_closing.extend(assignment_txns)

        return self._calculate_pnl(opening_txns, all_closing)
