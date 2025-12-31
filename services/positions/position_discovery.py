"""
Position Discovery Service - Discover unmanaged positions from transactions.

This service discovers positions that were opened directly at TastyTrade (not
through our app) by analyzing transaction data. It uses the order_id from
transactions to create Position records with unique opening_order_id values.

This enables tracking BOTH app-managed and user-managed positions separately,
even when they have identical strikes and expirations.

Usage:
    from services.positions.position_discovery import PositionDiscoveryService

    service = PositionDiscoveryService()
    result = await service.discover_unmanaged_positions(user, account)
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.logging import get_logger
from trading.models import (
    Position,
    TastyTradeOrderHistory,
    TastyTradeTransaction,
)

User = get_user_model()
logger = get_logger(__name__)


class PositionDiscoveryService:
    """
    Discover unmanaged positions from transactions.

    Process:
    1. Find opening transactions (Sell to Open, Buy to Open) without related_position
    2. Group transactions by order_id
    3. For each order_id without a matching Position.opening_order_id:
       - Create a new Position with is_app_managed=False
       - Link transactions via related_position FK
    4. Fetch order details from TastyTradeOrderHistory for leg structure

    This allows differentiation of identical positions by their unique opening_order_id.

    Example:
        - App opens QQQ P616/P613 spread (order_id=424091156) → is_app_managed=True
        - User opens identical spread at broker (order_id=999888777)
        - Discovery finds order_id=999888777 transactions without position
        - Creates Position with opening_order_id=999888777, is_app_managed=False
        - Both positions tracked separately
    """

    # Opening transaction actions
    OPENING_ACTIONS = ["Sell to Open", "Buy to Open"]

    # Days back to look for transactions
    DEFAULT_LOOKBACK_DAYS = 30

    async def discover_unmanaged_positions(
        self,
        user: User,
        account: TradingAccount,
        lookback_days: int | None = None,
    ) -> dict:
        """
        Discover new unmanaged positions from transactions.

        Args:
            user: User to discover positions for
            account: Trading account to analyze
            lookback_days: Days back to look for transactions (default: 30)

        Returns:
            {
                "positions_created": N,
                "transactions_linked": M,
                "order_ids_processed": X,
                "errors": [...],
            }
        """
        result = {
            "positions_created": 0,
            "transactions_linked": 0,
            "order_ids_processed": 0,
            "errors": [],
        }

        if lookback_days is None:
            lookback_days = self.DEFAULT_LOOKBACK_DAYS

        try:
            # Step 1: Find opening transactions without a linked position
            start_date = date.today() - timedelta(days=lookback_days)

            opening_transactions = await sync_to_async(list)(
                TastyTradeTransaction.objects.filter(
                    user=user,
                    trading_account=account,
                    action__in=self.OPENING_ACTIONS,
                    related_position__isnull=True,
                    executed_at__gte=start_date,
                    order_id__isnull=False,  # Must have order_id
                ).order_by("executed_at")
            )

            if not opening_transactions:
                logger.debug(
                    f"User {user.id}: No unlinked opening transactions found "
                    f"in last {lookback_days} days"
                )
                return result

            logger.info(
                f"User {user.id}: Found {len(opening_transactions)} unlinked "
                f"opening transactions to process"
            )

            # Step 2: Group transactions by order_id
            by_order_id = {}
            for tx in opening_transactions:
                if tx.order_id not in by_order_id:
                    by_order_id[tx.order_id] = []
                by_order_id[tx.order_id].append(tx)

            logger.info(
                f"User {user.id}: Grouped into {len(by_order_id)} unique order_ids"
            )

            # Step 3: Process each order_id
            for order_id, transactions in by_order_id.items():
                result["order_ids_processed"] += 1

                try:
                    created, linked = await self._process_order_transactions(
                        user=user,
                        account=account,
                        order_id=order_id,
                        transactions=transactions,
                    )
                    result["positions_created"] += created
                    result["transactions_linked"] += linked

                except Exception as e:
                    logger.error(
                        f"User {user.id}: Error processing order_id {order_id}: {e}",
                        exc_info=True,
                    )
                    result["errors"].append(
                        {
                            "order_id": order_id,
                            "error": str(e),
                        }
                    )

            logger.info(
                f"User {user.id}: Position discovery complete - "
                f"{result['positions_created']} positions created, "
                f"{result['transactions_linked']} transactions linked"
            )

        except Exception as e:
            logger.error(
                f"User {user.id}: Position discovery failed: {e}",
                exc_info=True,
            )
            result["errors"].append({"error": str(e)})

        return result

    async def _process_order_transactions(
        self,
        user: User,
        account: TradingAccount,
        order_id: int,
        transactions: list[TastyTradeTransaction],
    ) -> tuple[int, int]:
        """
        Process transactions for a single order_id.

        Args:
            user: User
            account: Trading account
            order_id: TastyTrade order ID
            transactions: List of transactions with this order_id

        Returns:
            Tuple of (positions_created, transactions_linked)
        """
        # Check if position already exists with this opening_order_id
        existing_position = await Position.objects.filter(
            opening_order_id=str(order_id)
        ).afirst()

        if existing_position:
            # Position exists - just link transactions
            logger.debug(
                f"Order {order_id}: Position {existing_position.id} already exists, "
                f"linking {len(transactions)} transactions"
            )
            linked = await self._link_transactions(existing_position, transactions)
            return (0, linked)

        # Create new position from transactions
        logger.info(
            f"Order {order_id}: Creating new unmanaged position "
            f"from {len(transactions)} transactions"
        )

        position = await self._create_position_from_transactions(
            user=user,
            account=account,
            order_id=order_id,
            transactions=transactions,
        )

        if position:
            linked = await self._link_transactions(position, transactions)
            return (1, linked)

        return (0, 0)

    async def _create_position_from_transactions(
        self,
        user: User,
        account: TradingAccount,
        order_id: int,
        transactions: list[TastyTradeTransaction],
    ) -> Position | None:
        """
        Create a Position record from opening transactions.

        Args:
            user: User
            account: Trading account
            order_id: Opening order ID from TastyTrade
            transactions: Opening transactions for this order

        Returns:
            Created Position object, or None if creation failed
        """
        if not transactions:
            logger.warning(f"Order {order_id}: No transactions to create position from")
            return None

        # Get the order from TastyTradeOrderHistory for leg structure
        order = await TastyTradeOrderHistory.objects.filter(
            broker_order_id=str(order_id)
        ).afirst()

        # Extract position details from order if available
        underlying_symbol = None
        legs = []
        strategy_type = None
        price_effect = "Credit"  # Default

        if order:
            underlying_symbol = order.underlying_symbol
            order_data = order.order_data or {}
            legs = order_data.get("legs", [])
            price_effect = order.price_effect or "Credit"
            strategy_type = self._detect_strategy_type(legs)
        else:
            # Fall back to transaction data
            underlying_symbol = self._extract_underlying_from_transactions(transactions)
            strategy_type = self._detect_strategy_from_transactions(transactions)
            price_effect = self._detect_price_effect_from_transactions(transactions)
            # Build legs from transactions so closure detection works
            legs = self._build_legs_from_transactions(transactions)

        if not underlying_symbol:
            logger.error(
                f"Order {order_id}: Could not determine underlying symbol"
            )
            return None

        # Calculate opening value from transactions
        opening_value = self._calculate_opening_value(transactions)

        # Calculate quantity (number of spreads/contracts)
        quantity = self._calculate_quantity(transactions)

        # Calculate average price per spread
        avg_price = abs(opening_value / quantity) if quantity else Decimal("0")

        # Determine expiration date from transactions
        expiration_date = self._extract_expiration_date(transactions)

        # Build metadata
        metadata = {
            "legs": legs,
            "discovery_method": "transaction_analysis",
            "opening_value": str(opening_value),
            "discovered_at": timezone.now().isoformat(),
            "opening_transactions": [
                {
                    "transaction_id": tx.transaction_id,
                    "action": tx.action,
                    "symbol": tx.symbol,
                    "quantity": str(tx.quantity) if tx.quantity else None,
                    "net_value": str(tx.net_value) if tx.net_value else None,
                }
                for tx in transactions
            ],
        }

        # Create the position
        try:
            position = await Position.objects.acreate(
                user=user,
                trading_account=account,
                symbol=underlying_symbol,
                opening_order_id=str(order_id),
                is_app_managed=False,  # User created at broker
                lifecycle_state="open_full",
                quantity=quantity,
                avg_price=avg_price,
                opening_price_effect=price_effect,
                strategy_type=strategy_type,
                opened_at=transactions[0].executed_at,
                metadata=metadata,
            )

            # Set expiration date in metadata if found
            if expiration_date:
                position.metadata["expiration_date"] = expiration_date.isoformat()
                await position.asave(update_fields=["metadata"])

            logger.info(
                f"Order {order_id}: Created position {position.id} "
                f"({underlying_symbol}, strategy={strategy_type}, qty={quantity})"
            )

            return position

        except Exception as e:
            logger.error(
                f"Order {order_id}: Failed to create position: {e}",
                exc_info=True,
            )
            return None

    async def _link_transactions(
        self,
        position: Position,
        transactions: list[TastyTradeTransaction],
    ) -> int:
        """
        Link transactions to position via related_position FK.

        Args:
            position: Position to link to
            transactions: Transactions to link

        Returns:
            Number of transactions linked
        """
        linked = 0
        for tx in transactions:
            if tx.related_position_id != position.id:
                tx.related_position = position
                await tx.asave(update_fields=["related_position"])
                linked += 1

        if linked:
            logger.debug(
                f"Position {position.id}: Linked {linked} transactions"
            )

        return linked

    def _calculate_opening_value(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> Decimal:
        """
        Calculate opening value from transactions.

        Credits (Sell to Open) are positive.
        Debits (Buy to Open) are negative.

        Args:
            transactions: Opening transactions

        Returns:
            Net opening value (positive for credit, negative for debit)
        """
        opening_value = Decimal("0")

        for tx in transactions:
            if tx.net_value is None:
                continue

            if tx.action == "Sell to Open":
                # Credit received
                opening_value += tx.net_value
            elif tx.action == "Buy to Open":
                # Debit paid (already negative in net_value usually)
                opening_value -= abs(tx.net_value)

        return opening_value

    def _calculate_quantity(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> int:
        """
        Calculate number of spreads from transactions.

        For spreads, count the quantity of one leg.
        For single-leg, use the transaction quantity.

        Args:
            transactions: Opening transactions

        Returns:
            Number of spreads/contracts
        """
        if not transactions:
            return 1

        # For spreads, each leg has the same quantity
        # Take the quantity from the first transaction
        first_tx = transactions[0]
        if first_tx.quantity:
            return int(abs(first_tx.quantity))

        return 1

    def _detect_strategy_type(self, legs: list[dict]) -> str | None:
        """
        Detect strategy type from order legs.

        Args:
            legs: List of leg dictionaries from order_data

        Returns:
            Strategy type string or None
        """
        if not legs:
            return None

        leg_count = len(legs)

        if leg_count == 6:
            return "senex_trident"
        if leg_count == 2:
            # Check leg types to distinguish put spread vs call spread
            leg_types = [leg.get("instrument_type", "") for leg in legs]
            if all("Put" in lt or "P" in lt for lt in leg_types):
                return "short_put_vertical"
            if all("Call" in lt or "C" in lt for lt in leg_types):
                return "short_call_vertical"
            return "short_put_vertical"  # Default to put spread

        return None

    def _detect_strategy_from_transactions(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> str | None:
        """
        Detect strategy type from transactions (fallback if order not available).

        Args:
            transactions: Opening transactions

        Returns:
            Strategy type string or None
        """
        if not transactions:
            return None

        # Count unique OCC symbols to determine number of legs
        symbols = {tx.symbol for tx in transactions if tx.symbol}
        leg_count = len(symbols)

        if leg_count == 6:
            return "senex_trident"
        if leg_count == 2:
            # Check if put or call from OCC symbol
            # OCC format: SYMBOL YYMMDD P/C STRIKE
            for tx in transactions:
                if tx.symbol:
                    if "P" in tx.symbol[6:]:
                        return "short_put_vertical"
                    if "C" in tx.symbol[6:]:
                        return "short_call_vertical"
            return "short_put_vertical"  # Default

        return None

    def _detect_price_effect_from_transactions(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> str:
        """
        Determine if position was opened for credit or debit.

        Args:
            transactions: Opening transactions

        Returns:
            "Credit" or "Debit"
        """
        total = sum(
            tx.net_value or Decimal("0")
            for tx in transactions
        )
        return "Credit" if total > 0 else "Debit"

    def _build_legs_from_transactions(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> list[dict]:
        """
        Build legs list from opening transactions.

        When order history is unavailable, we construct the legs
        from transaction data to enable proper closure detection.

        Args:
            transactions: Opening transactions

        Returns:
            List of leg dictionaries with symbol, action, quantity
        """
        legs = []
        seen_symbols = set()

        for tx in transactions:
            if not tx.symbol or tx.symbol in seen_symbols:
                continue

            seen_symbols.add(tx.symbol)

            # Determine action from transaction action
            action = "SELL" if "Sell" in (tx.action or "") else "BUY"

            leg = {
                "symbol": tx.symbol,
                "action": action,
                "quantity": int(abs(tx.quantity)) if tx.quantity else 1,
                "instrument_type": tx.instrument_type or "Equity Option",
            }
            legs.append(leg)

        return legs

    def _extract_underlying_from_transactions(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> str | None:
        """
        Extract underlying symbol from transactions.

        Args:
            transactions: List of transactions

        Returns:
            Underlying symbol or None
        """
        for tx in transactions:
            if tx.underlying_symbol:
                return tx.underlying_symbol

        # Try to parse from OCC symbol
        for tx in transactions:
            if tx.symbol and len(tx.symbol) >= 6:
                # OCC symbol format: SYMBOL YYMMDD ...
                # Underlying is at the start
                underlying = tx.symbol[:6].strip()
                # Remove trailing spaces and numbers
                underlying = "".join(
                    c for c in underlying if c.isalpha()
                )
                if underlying:
                    return underlying

        return None

    def _extract_expiration_date(
        self,
        transactions: list[TastyTradeTransaction],
    ) -> date | None:
        """
        Extract expiration date from OCC symbols in transactions.

        OCC format: SYMBOL YYMMDD P/C STRIKE

        Args:
            transactions: List of transactions

        Returns:
            Expiration date or None
        """
        for tx in transactions:
            if not tx.symbol or len(tx.symbol) < 15:
                continue

            try:
                # Find the date portion (YYMMDD) in OCC symbol
                # Skip the underlying symbol part
                symbol = tx.symbol.ljust(21)  # Ensure minimum length
                date_str = symbol[6:12]
                if date_str.isdigit():
                    return datetime.strptime(date_str, "%y%m%d").date()
            except (ValueError, IndexError):
                continue

        return None

    async def link_closing_transactions_to_position(
        self,
        position: Position,
    ) -> dict:
        """
        Link closing transactions to a position.

        Finds transactions with action "Buy to Close" or "Sell to Close"
        that haven't been linked yet but match the position's underlying.

        This is called after position closure detection to ensure all
        closing transactions are properly linked for P&L calculation.

        Args:
            position: Position to link closing transactions to

        Returns:
            {"linked": N}
        """
        result = {"linked": 0}

        # Get the OCC symbols from position's legs for precise matching
        position_leg_symbols = set()
        if position.metadata and position.metadata.get("legs"):
            for leg in position.metadata["legs"]:
                if leg.get("symbol"):
                    position_leg_symbols.add(leg["symbol"])

        # Get already linked transaction IDs
        linked_ids = set()
        async for tx in TastyTradeTransaction.objects.filter(
            related_position=position
        ).values_list("transaction_id", flat=True):
            linked_ids.add(tx)

        if not position_leg_symbols:
            # No leg data - this is likely a stock/equity position or
            # discovery failed to populate legs. For stocks, we can safely
            # match by underlying symbol since there's only one "leg".
            # For options without leg data, match by underlying + order_id.
            if position.instrument_type == "Equity":
                # Stock position - match by symbol (underlying)
                closing_transactions = await sync_to_async(list)(
                    TastyTradeTransaction.objects.filter(
                        user=position.user,
                        trading_account=position.trading_account,
                        symbol=position.symbol,  # Stock symbol directly
                        action__in=["Buy to Close", "Sell to Close", "Sell"],
                        related_position__isnull=True,
                        executed_at__gte=position.opened_at,
                    ).order_by("executed_at")
                )
            elif position.opening_order_id:
                # Option position without legs - match by order_id to be safe
                closing_transactions = await sync_to_async(list)(
                    TastyTradeTransaction.objects.filter(
                        user=position.user,
                        trading_account=position.trading_account,
                        underlying_symbol=position.symbol,
                        order_id=int(position.opening_order_id),
                        action__in=["Buy to Close", "Sell to Close"],
                        related_position__isnull=True,
                    ).order_by("executed_at")
                )
            else:
                # Cannot safely link without leg symbols or order_id
                logger.warning(
                    f"Position {position.id}: No leg symbols or opening_order_id, "
                    f"skipping closing transaction linking to avoid conflicts"
                )
                return result
        else:
            # Has leg symbols - match by exact OCC symbol (most precise)
            closing_transactions = await sync_to_async(list)(
                TastyTradeTransaction.objects.filter(
                    user=position.user,
                    trading_account=position.trading_account,
                    symbol__in=position_leg_symbols,
                    action__in=["Buy to Close", "Sell to Close"],
                    related_position__isnull=True,
                    executed_at__gte=position.opened_at,
                ).order_by("executed_at")
            )

        for tx in closing_transactions:
            # Skip if already linked
            if tx.transaction_id in linked_ids:
                continue

            # Link to position
            tx.related_position = position
            await tx.asave(update_fields=["related_position"])
            result["linked"] += 1

        if result["linked"]:
            logger.info(
                f"Position {position.id}: Linked {result['linked']} "
                f"closing transactions by leg symbol"
            )

        return result
