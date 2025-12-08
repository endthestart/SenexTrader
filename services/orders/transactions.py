"""
Service for importing and managing transaction history from TastyTrade.

Transactions are the ground truth for what actually executed - every fill,
assignment, dividend, and fee is recorded as a transaction. This complements
TastyTradeOrderHistory (what was requested) with what actually happened.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.logging import get_logger
from trading.models import Position, TastyTradeTransaction

User = get_user_model()
logger = get_logger(__name__)


class TransactionImporter:
    """
    Import transaction history from TastyTrade.

    Transactions provide:
    - Exact fill prices and quantities
    - Assignment/exercise detection
    - Fee breakdown
    - Ground truth for P&L

    Usage:
        importer = TransactionImporter()
        result = await importer.import_transactions(user, account)
        linked = await importer.link_transactions_to_positions(user)
    """

    async def import_transactions(
        self,
        user: User,
        account: TradingAccount,
        start_date: date | None = None,
        underlying_symbol: str | None = None,
        transaction_types: list[str] | None = None,
    ) -> dict:
        """
        Import transactions from TastyTrade.

        Args:
            user: User to import transactions for
            account: Trading account to fetch from
            start_date: How far back to fetch (default: 90 days)
            underlying_symbol: Optional filter by underlying
            transaction_types: Optional filter by type (default: ["Trade"])

        Returns:
            {
                "imported": N,
                "updated": M,
                "errors": [...],
                "total_processed": X
            }
        """
        from tastytrade import Account

        from services.core.data_access import get_oauth_session

        result = {
            "imported": 0,
            "updated": 0,
            "errors": [],
            "total_processed": 0,
        }

        try:
            session = await get_oauth_session(user)
            if not session:
                result["errors"].append("Failed to get OAuth session")
                return result

            tt_account = await Account.a_get(session, account.account_number)

            # Calculate date range
            if start_date is None:
                start_date = date.today() - timedelta(days=90)

            # Default to Trade transactions (the most important for position tracking)
            if transaction_types is None:
                transaction_types = ["Trade"]

            logger.info(
                f"Importing transactions for user {user.id}, "
                f"account {account.account_number}, "
                f"start_date={start_date}, types={transaction_types}"
            )

            # Fetch transactions from TastyTrade
            # Note: get_history is synchronous in the SDK
            transactions = await sync_to_async(tt_account.get_history)(
                session,
                start_date=start_date,
            )

            if not transactions:
                logger.info("No transactions found")
                return result

            # Filter by type if specified
            if transaction_types:
                transactions = [
                    tx for tx in transactions if tx.transaction_type in transaction_types
                ]

            # Filter by underlying if specified
            if underlying_symbol:
                transactions = [
                    tx
                    for tx in transactions
                    if getattr(tx, "underlying_symbol", None) == underlying_symbol
                ]

            logger.info(f"Processing {len(transactions)} transactions")

            for tx in transactions:
                result["total_processed"] += 1
                try:
                    created = await self._import_single_transaction(user, account, tx)
                    if created:
                        result["imported"] += 1
                    else:
                        result["updated"] += 1
                except Exception as e:
                    tx_id = getattr(tx, "id", "unknown")
                    logger.error(f"Error importing transaction {tx_id}: {e}")
                    result["errors"].append(
                        {
                            "transaction_id": tx_id,
                            "error": str(e),
                        }
                    )

            logger.info(
                f"Transaction import complete: "
                f"{result['imported']} imported, "
                f"{result['updated']} updated, "
                f"{len(result['errors'])} errors"
            )

        except Exception as e:
            logger.error(f"Transaction import failed: {e}", exc_info=True)
            result["errors"].append({"error": str(e)})

        return result

    async def _import_single_transaction(
        self,
        user: User,
        account: TradingAccount,
        tx,
    ) -> bool:
        """
        Import a single transaction into the database.

        Args:
            user: User to associate transaction with
            account: Trading account
            tx: TastyTrade Transaction object

        Returns:
            True if created (new), False if updated (existing)
        """
        # Extract transaction ID
        tx_id = tx.id

        # Check if transaction exists
        existing = await TastyTradeTransaction.objects.filter(transaction_id=tx_id).afirst()

        # Build field values
        tx_fields = {
            "user": user,
            "trading_account": account,
            "order_id": getattr(tx, "order_id", None),
            "transaction_type": tx.transaction_type,
            "transaction_sub_type": getattr(tx, "transaction_sub_type", None),
            "description": getattr(tx, "description", None),
            "action": self._extract_action(tx),
            "value": Decimal(str(tx.value)) if tx.value else Decimal("0"),
            "net_value": Decimal(str(tx.net_value)) if tx.net_value else Decimal("0"),
            "commission": self._to_decimal(getattr(tx, "commission", None)),
            "clearing_fees": self._to_decimal(getattr(tx, "clearing_fees", None)),
            "regulatory_fees": self._to_decimal(getattr(tx, "regulatory_fees", None)),
            "symbol": getattr(tx, "symbol", None),
            "underlying_symbol": getattr(tx, "underlying_symbol", None),
            "instrument_type": self._extract_instrument_type(tx),
            "quantity": self._to_decimal(getattr(tx, "quantity", None)),
            "price": self._to_decimal(getattr(tx, "price", None)),
            "executed_at": tx.executed_at,
            "raw_data": self._serialize_transaction(tx),
        }

        if existing:
            # Update existing transaction
            for field, value in tx_fields.items():
                setattr(existing, field, value)
            await existing.asave()
            logger.debug(f"Updated transaction {tx_id}")
            return False
        # Create new transaction
        tx_fields["transaction_id"] = tx_id
        await TastyTradeTransaction.objects.acreate(**tx_fields)
        logger.debug(f"Created transaction {tx_id}")
        return True

    def _extract_action(self, tx) -> str | None:
        """Extract action string from transaction."""
        action = getattr(tx, "action", None)
        if action is None:
            return None
        if hasattr(action, "value"):
            return action.value
        return str(action)

    def _extract_instrument_type(self, tx) -> str:
        """Extract instrument type string from transaction."""
        inst_type = getattr(tx, "instrument_type", None)
        if inst_type is None:
            return "Unknown"
        if hasattr(inst_type, "value"):
            return inst_type.value
        return str(inst_type)

    def _to_decimal(self, value) -> Decimal | None:
        """Convert value to Decimal, handling None."""
        if value is None:
            return None
        return Decimal(str(value))

    def _serialize_transaction(self, tx) -> dict:
        """Serialize transaction to JSON-compatible dict."""
        # Try pydantic model_dump first (tastytrade SDK uses pydantic)
        if hasattr(tx, "model_dump"):
            try:
                return tx.model_dump(mode="json")
            except Exception:
                pass

        # Fallback to manual serialization
        result = {}
        for attr in [
            "id",
            "account_number",
            "transaction_type",
            "transaction_sub_type",
            "description",
            "executed_at",
            "action",
            "value",
            "value_effect",
            "net_value",
            "net_value_effect",
            "commission",
            "commission_effect",
            "clearing_fees",
            "clearing_fees_effect",
            "regulatory_fees",
            "regulatory_fees_effect",
            "symbol",
            "instrument_type",
            "underlying_symbol",
            "quantity",
            "quantity_direction",
            "price",
            "order_id",
            "lot_id",
        ]:
            val = getattr(tx, attr, None)
            if val is not None:
                if hasattr(val, "value"):  # Enum
                    result[attr] = val.value
                elif hasattr(val, "isoformat"):  # datetime
                    result[attr] = val.isoformat()
                else:
                    result[attr] = str(val)
        return result

    async def link_transactions_to_positions(
        self,
        user: User,
        account: TradingAccount | None = None,
    ) -> dict:
        """
        Link transactions to their Positions using order_id matching.

        Process:
        1. Get all transactions with order_id that aren't linked
        2. For each, find Position with matching opening_order_id
        3. Set related_position

        Args:
            user: User to process transactions for
            account: Optional filter by account

        Returns:
            {"linked": N, "not_found": M, "already_linked": X}
        """
        result = {
            "linked": 0,
            "not_found": 0,
            "already_linked": 0,
        }

        # Build query for unlinked transactions
        query = TastyTradeTransaction.objects.filter(
            user=user,
            order_id__isnull=False,
            related_position__isnull=True,
        )
        if account:
            query = query.filter(trading_account=account)

        # Process in batches
        transactions = [tx async for tx in query]

        logger.info(f"Processing {len(transactions)} unlinked transactions")

        for tx in transactions:
            # Find position by opening_order_id matching transaction's order_id
            position = await Position.objects.filter(
                user=user,
                opening_order_id=str(tx.order_id),
            ).afirst()

            if position:
                tx.related_position = position
                await tx.asave(update_fields=["related_position"])
                result["linked"] += 1
                logger.debug(
                    f"Linked transaction {tx.transaction_id} " f"to position {position.id}"
                )
            else:
                result["not_found"] += 1

        # Also count already-linked for reporting
        already_linked = await TastyTradeTransaction.objects.filter(
            user=user,
            related_position__isnull=False,
        ).acount()
        result["already_linked"] = already_linked

        logger.info(
            f"Transaction linking complete: "
            f"{result['linked']} newly linked, "
            f"{result['not_found']} position not found, "
            f"{result['already_linked']} already linked"
        )

        return result

    async def get_transactions_for_position(
        self,
        position: Position,
    ) -> list[TastyTradeTransaction]:
        """
        Get all transactions related to a position.

        This includes:
        - Transactions linked via related_position FK
        - Transactions matched by opening_order_id

        Args:
            position: Position to get transactions for

        Returns:
            List of TastyTradeTransaction objects
        """
        transactions = []
        seen_ids = set()

        # Get transactions linked via related_position FK
        linked = [
            tx
            async for tx in TastyTradeTransaction.objects.filter(
                related_position=position
            ).order_by("executed_at")
        ]
        for tx in linked:
            if tx.transaction_id not in seen_ids:
                transactions.append(tx)
                seen_ids.add(tx.transaction_id)

        # Also get transactions by opening_order_id if set
        if position.opening_order_id:
            by_order = [
                tx
                async for tx in TastyTradeTransaction.objects.filter(
                    order_id=position.opening_order_id
                ).order_by("executed_at")
            ]
            for tx in by_order:
                if tx.transaction_id not in seen_ids:
                    transactions.append(tx)
                    seen_ids.add(tx.transaction_id)

        return sorted(transactions, key=lambda x: x.executed_at)

    async def calculate_position_pnl_from_transactions(
        self,
        position: Position,
    ) -> dict:
        """
        Calculate P&L for a position from its transactions.

        This provides ground-truth P&L from actual fills.

        Args:
            position: Position to calculate P&L for

        Returns:
            {
                "total_value": Decimal,
                "total_fees": Decimal,
                "net_value": Decimal,
                "opening_value": Decimal,
                "closing_value": Decimal,
            }
        """
        transactions = await self.get_transactions_for_position(position)

        result = {
            "total_value": Decimal("0"),
            "total_fees": Decimal("0"),
            "net_value": Decimal("0"),
            "opening_value": Decimal("0"),
            "closing_value": Decimal("0"),
            "transaction_count": len(transactions),
        }

        for tx in transactions:
            result["total_value"] += tx.value or Decimal("0")
            result["net_value"] += tx.net_value or Decimal("0")

            # Sum fees
            if tx.commission:
                result["total_fees"] += tx.commission
            if tx.clearing_fees:
                result["total_fees"] += tx.clearing_fees
            if tx.regulatory_fees:
                result["total_fees"] += tx.regulatory_fees

            # Categorize by action type
            action = (tx.action or "").lower()
            if "open" in action:
                result["opening_value"] += tx.value or Decimal("0")
            elif "close" in action:
                result["closing_value"] += tx.value or Decimal("0")

        return result


# Convenience function for sync context
def get_transaction_importer() -> TransactionImporter:
    """Get a TransactionImporter instance."""
    return TransactionImporter()
