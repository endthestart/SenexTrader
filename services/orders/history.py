"""
Service for syncing and querying order history from TastyTrade.
Creates local cache of order data for position reconstruction.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import TradingAccount
from services.core.logging import get_logger
from trading.models import CachedOrder, CachedOrderChain, Position

User = get_user_model()
logger = get_logger(__name__)


class OrderHistoryService:
    """
    Service for syncing and querying order history from TastyTrade.
    Creates local cache of order data for position reconstruction.
    """

    async def sync_order_history(
        self,
        account: TradingAccount,
        days_back: int = 30,
        symbol: str | None = None,
    ) -> dict:
        """
        Fetch and cache order history from TastyTrade.

        Args:
            account: Trading account to sync orders for
            days_back: Number of days back to fetch order history
            symbol: Optional symbol filter (fetch only orders for this symbol)

        Returns:
            {
                "orders_synced": 10,
                "new_orders": 5,
                "updated_orders": 5,
                "errors": []
            }
        """
        result = {
            "orders_synced": 0,
            "new_orders": 0,
            "updated_orders": 0,
            "errors": [],
        }

        try:
            from tastytrade import Account

            from services.core.data_access import get_oauth_session

            # Get OAuth session (ensure user is fetched)
            user = account.user
            session = await get_oauth_session(user)
            if not session:
                result["errors"].append("Unable to obtain TastyTrade session")
                return result

            # Fetch order history
            start_date = (timezone.now() - timedelta(days=days_back)).date()
            tt_account = await Account.a_get(session, account.account_number)
            order_history = await tt_account.a_get_order_history(session, start_date=start_date)

            logger.info(
                f"Fetched {len(order_history)} orders from TastyTrade for account "
                f"{account.account_number} (days_back={days_back}, symbol={symbol})"
            )

            # Process each order
            for order in order_history:
                # Filter by symbol if specified
                if symbol and order.underlying_symbol != symbol:
                    continue

                try:
                    created = await self._cache_order(account, order)
                    result["orders_synced"] += 1
                    if created:
                        result["new_orders"] += 1
                    else:
                        result["updated_orders"] += 1
                except Exception as e:
                    error_msg = f"Error caching order {order.id}: {e!s}"
                    result["errors"].append(error_msg)
                    logger.error(error_msg, exc_info=True)

            logger.info(
                f"Order history sync complete for account {account.account_number}: "
                f"{result['new_orders']} new, {result['updated_orders']} updated"
            )

        except Exception as e:
            error_msg = f"Order history sync failed: {e!s}"
            result["errors"].append(error_msg)
            logger.error(error_msg, exc_info=True)

        return result

    async def _cache_order(self, account: TradingAccount, order) -> bool:
        """
        Cache a single order in the database.

        Args:
            account: Trading account
            order: TastyTrade PlacedOrder object

        Returns:
            True if order was created (new), False if updated
        """
        # Extract order identifiers
        broker_order_id = order.id
        complex_order_id = getattr(order, "complex_order_id", None)
        parent_order_id = getattr(order, "parent_order_id", None)
        replaces_order_id = getattr(order, "replaces_order_id", None)
        replacing_order_id = getattr(order, "replacing_order_id", None)

        # Extract order data
        underlying_symbol = order.underlying_symbol
        order_type = (
            order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type)
        )
        status = order.status.value if hasattr(order.status, "value") else str(order.status)
        price_effect = (
            order.price_effect.value
            if hasattr(order, "price_effect") and hasattr(order.price_effect, "value")
            else "Credit"
        )

        # Extract timestamps
        received_at = getattr(order, "received_at", None)
        live_at = getattr(order, "live_at", None)
        filled_at = None
        cancelled_at = getattr(order, "cancelled_at", None)
        terminal_at = getattr(order, "terminal_at", None)

        # Extract filled_at from legs if available
        if hasattr(order, "legs") and order.legs:
            for leg in order.legs:
                if hasattr(leg, "fills") and leg.fills:
                    first_fill = leg.fills[0]
                    if hasattr(first_fill, "filled_at"):
                        filled_at = first_fill.filled_at
                        break

        # Serialize full order data
        order_data = self._serialize_order(order)

        # Calculate price based on order status
        # For filled orders, calculate actual fill price from leg fills
        # For other statuses (pending, working, cancelled), use limit price
        if status.lower() == "filled":
            # Calculate actual fill price from leg fills
            fill_price = self.calculate_fill_price(order_data)
            if fill_price is not None:
                price = fill_price
                logger.debug(
                    f"Order {order.id}: Calculated fill price ${fill_price} from leg fills"
                )
            else:
                # Fallback to order.price if fill data unavailable
                price = (
                    Decimal(str(order.price)) if hasattr(order, "price") and order.price else None
                )
                logger.warning(
                    f"Order {order.id}: Could not calculate fill price from legs, "
                    f"using limit price ${price}"
                )
        else:
            # For non-filled orders, use the limit price
            price = Decimal(str(order.price)) if hasattr(order, "price") and order.price else None

        # Check if order already exists
        existing_order = await CachedOrder.objects.filter(broker_order_id=broker_order_id).afirst()

        # Get user safely in async context
        user = account.user

        order_fields = {
            "user": user,
            "trading_account": account,
            "complex_order_id": complex_order_id,
            "parent_order_id": parent_order_id,
            "replaces_order_id": replaces_order_id,
            "replacing_order_id": replacing_order_id,
            "underlying_symbol": underlying_symbol,
            "order_type": order_type,
            "status": status,
            "price": price,
            "price_effect": price_effect,
            "received_at": received_at,
            "live_at": live_at,
            "filled_at": filled_at,
            "cancelled_at": cancelled_at,
            "terminal_at": terminal_at,
            "order_data": order_data,
        }

        if existing_order:
            # Update existing order
            for field, value in order_fields.items():
                setattr(existing_order, field, value)
            await existing_order.asave()
            logger.debug(f"Updated cached order {broker_order_id}")
            return False
        # Create new order
        order_fields["broker_order_id"] = broker_order_id
        await CachedOrder.objects.acreate(**order_fields)
        logger.debug(f"Created new cached order {broker_order_id}")
        return True

    def _serialize_order(self, order) -> dict:
        """Serialize TastyTrade PlacedOrder object to JSON-compatible dict."""

        # Helper to convert Decimal/numeric to string
        def to_str(val):
            if val is None:
                return None
            return str(val) if hasattr(val, "__str__") else val

        order_dict = {
            "id": order.id,
            "underlying_symbol": order.underlying_symbol,
            "order_type": (
                order.order_type.value
                if hasattr(order.order_type, "value")
                else str(order.order_type)
            ),
            "status": (order.status.value if hasattr(order.status, "value") else str(order.status)),
            "size": to_str(getattr(order, "size", None)),
            "price": to_str(getattr(order, "price", None)),
            "price_effect": (
                order.price_effect.value
                if hasattr(order, "price_effect") and hasattr(order.price_effect, "value")
                else None
            ),
            "time_in_force": (
                order.time_in_force.value
                if hasattr(order, "time_in_force") and hasattr(order.time_in_force, "value")
                else None
            ),
            "complex_order_id": getattr(order, "complex_order_id", None),
            "parent_order_id": getattr(order, "parent_order_id", None),
            "replaces_order_id": getattr(order, "replaces_order_id", None),
            "replacing_order_id": getattr(order, "replacing_order_id", None),
            "received_at": (
                order.received_at.isoformat()
                if hasattr(order, "received_at") and order.received_at
                else None
            ),
            "live_at": (
                order.live_at.isoformat() if hasattr(order, "live_at") and order.live_at else None
            ),
            "cancelled_at": (
                order.cancelled_at.isoformat()
                if hasattr(order, "cancelled_at") and order.cancelled_at
                else None
            ),
            "terminal_at": (
                order.terminal_at.isoformat()
                if hasattr(order, "terminal_at") and order.terminal_at
                else None
            ),
            "legs": [],
        }

        # Serialize legs
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
                    "quantity": to_str(getattr(leg, "quantity", None)),
                    "fills": [],
                }

                # Serialize fills
                if hasattr(leg, "fills") and leg.fills:
                    for fill in leg.fills:
                        fill_dict = {
                            "quantity": to_str(getattr(fill, "quantity", None)),
                            "fill_price": to_str(getattr(fill, "fill_price", None)),
                            "filled_at": (
                                fill.filled_at.isoformat()
                                if hasattr(fill, "filled_at") and fill.filled_at
                                else None
                            ),
                        }
                        leg_dict["fills"].append(fill_dict)

                order_dict["legs"].append(leg_dict)

        return order_dict

    async def sync_order_chains(
        self,
        account: TradingAccount,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> CachedOrderChain | None:
        """
        Fetch and cache order chain for a symbol.

        Args:
            account: Trading account
            symbol: Underlying symbol
            start_time: Start of date range
            end_time: End of date range

        Returns:
            CachedOrderChain or None if not found
        """
        try:
            from tastytrade import Account

            from services.core.data_access import get_oauth_session

            # Get OAuth session (ensure user is fetched)
            user = account.user
            session = await get_oauth_session(user)
            if not session:
                logger.error("Unable to obtain TastyTrade session for order chain sync")
                return None

            # Fetch order chains
            tt_account = await Account.a_get(session, account.account_number)
            order_chains = await tt_account.a_get_order_chains(
                session, symbol=symbol, start_time=start_time, end_time=end_time
            )

            if not order_chains:
                logger.info(
                    f"No order chains found for {symbol} between {start_time} and {end_time}"
                )
                return None

            # Cache the first chain (typically only one chain per symbol)
            chain = order_chains[0]
            cached_chain = await self._cache_order_chain(account, chain)

            logger.info(
                f"Synced order chain {chain.id} for {symbol} in account "
                f"{account.account_number}"
            )

            return cached_chain

        except Exception as e:
            logger.error(f"Error syncing order chain for {symbol}: {e}", exc_info=True)
            return None

    async def _cache_order_chain(self, account: TradingAccount, chain) -> CachedOrderChain:
        """Cache a single order chain in the database."""
        chain_id = chain.id
        underlying_symbol = chain.underlying_symbol
        description = getattr(chain, "description", "")

        # Extract P/L data
        total_commissions = Decimal(str(getattr(chain, "total_commissions", 0)))
        total_fees = Decimal(str(getattr(chain, "total_fees", 0)))
        realized_pnl = Decimal(str(getattr(chain, "realized_pnl", 0)))
        unrealized_pnl = Decimal(str(getattr(chain, "unrealized_pnl", 0)))

        # Serialize full chain data
        chain_data = self._serialize_order_chain(chain)

        # Extract timestamps
        created_at = getattr(chain, "created_at", timezone.now())
        updated_at = getattr(chain, "updated_at", timezone.now())

        # Check if chain already exists
        existing_chain = await CachedOrderChain.objects.filter(
            trading_account=account, chain_id=chain_id
        ).afirst()

        # Get user safely in async context
        user = account.user

        chain_fields = {
            "user": user,
            "trading_account": account,
            "underlying_symbol": underlying_symbol,
            "description": description,
            "total_commissions": total_commissions,
            "total_fees": total_fees,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "chain_data": chain_data,
            "created_at": created_at,
            "updated_at": updated_at,
        }

        if existing_chain:
            # Update existing chain
            for field, value in chain_fields.items():
                setattr(existing_chain, field, value)
            await existing_chain.asave()
            logger.debug(f"Updated cached order chain {chain_id}")
            return existing_chain
        # Create new chain
        chain_fields["chain_id"] = chain_id
        cached_chain = await CachedOrderChain.objects.acreate(**chain_fields)
        logger.debug(f"Created new cached order chain {chain_id}")
        return cached_chain

    def _serialize_order_chain(self, chain) -> dict:
        """Serialize TastyTrade OrderChain object to JSON-compatible dict."""
        return {
            "id": chain.id,
            "underlying_symbol": chain.underlying_symbol,
            "description": getattr(chain, "description", ""),
            "total_commissions": str(getattr(chain, "total_commissions", 0)),
            "total_fees": str(getattr(chain, "total_fees", 0)),
            "realized_pnl": str(getattr(chain, "realized_pnl", 0)),
            "unrealized_pnl": str(getattr(chain, "unrealized_pnl", 0)),
            "created_at": (
                chain.created_at.isoformat()
                if hasattr(chain, "created_at") and chain.created_at
                else None
            ),
            "updated_at": (
                chain.updated_at.isoformat()
                if hasattr(chain, "updated_at") and chain.updated_at
                else None
            ),
        }

    async def get_position_orders(self, position: Position) -> list[CachedOrder]:
        """
        Get all orders related to a position from cache.
        Includes opening order + all profit targets.

        Args:
            position: Position to get orders for

        Returns:
            List of CachedOrder objects
        """
        # Query by underlying symbol, date range, user, and account
        orders = [
            order
            async for order in CachedOrder.objects.filter(
                user=position.user,
                trading_account=position.trading_account,
                underlying_symbol=position.symbol,
                filled_at__gte=position.opened_at if position.opened_at else None,
                status="Filled",
            ).order_by("filled_at")
        ]

        logger.debug(f"Found {len(orders)} cached orders for position {position.id}")
        return orders

    async def get_opening_order_for_position(self, position: Position) -> CachedOrder | None:
        """
        Find the opening order that created this position.

        Args:
            position: Position to find opening order for

        Returns:
            CachedOrder or None
        """
        # Try to find by broker_order_id in position metadata
        broker_order_ids = position.broker_order_ids or []
        if broker_order_ids:
            for order_id in broker_order_ids:
                order = await CachedOrder.objects.filter(broker_order_id=order_id).afirst()
                if order:
                    logger.debug(
                        f"Found opening order {order.broker_order_id} for position "
                        f"{position.id}"
                    )
                    return order

        # Fallback: search by symbol, time range, and status
        if position.opened_at:
            order = await CachedOrder.objects.filter(
                user=position.user,
                trading_account=position.trading_account,
                underlying_symbol=position.symbol,
                filled_at__gte=position.opened_at - timedelta(hours=1),
                filled_at__lte=position.opened_at + timedelta(hours=1),
                status="Filled",
            ).afirst()

            if order:
                logger.debug(
                    f"Found opening order {order.broker_order_id} for position "
                    f"{position.id} by time range"
                )
                return order

        logger.warning(f"No opening order found for position {position.id}")
        return None

    async def link_profit_targets_to_opening_order(
        self, opening_order_id: str
    ) -> list[CachedOrder]:
        """
        Find all profit target orders linked to opening order.

        Args:
            opening_order_id: Broker order ID of opening order

        Returns:
            List of CachedOrder objects (profit targets)
        """
        # Query by parent_order_id or complex_order_id
        profit_targets = [
            order
            async for order in (
                CachedOrder.objects.filter(parent_order_id=opening_order_id)
                | CachedOrder.objects.filter(complex_order_id=opening_order_id)
            )
        ]

        logger.debug(
            f"Found {len(profit_targets)} profit target orders for opening order "
            f"{opening_order_id}"
        )
        return profit_targets

    def calculate_fill_price(self, order_data: dict) -> Decimal | None:
        """
        Calculate the actual fill price from leg fills.

        For multi-leg orders, calculates the net credit/debit from actual fill prices,
        not the order limit price.

        Args:
            order_data: Order data dictionary with legs and fills

        Returns:
            Decimal fill price (positive = credit, negative = debit), or None if no fills
        """
        legs = order_data.get("legs", [])
        if not legs:
            return None

        total_value = Decimal("0")
        has_fills = False

        for leg in legs:
            fills = leg.get("fills", [])
            if not fills:
                # No fill data, can't calculate
                logger.debug(f"Leg {leg.get('symbol')} has no fill data")
                continue

            has_fills = True
            action = leg.get("action", "")

            # Calculate fill value for this leg
            for fill in fills:
                fill_price = fill.get("fill_price")
                quantity = fill.get("quantity")

                if fill_price is None or quantity is None:
                    continue

                # Convert to Decimal
                price = Decimal(str(fill_price))
                qty = abs(Decimal(str(quantity)))

                # Determine if this is a debit or credit
                # Sell = credit (positive), Buy = debit (negative)
                if "sell" in action.lower():
                    total_value += price * qty
                else:
                    total_value -= price * qty

        if not has_fills:
            return None

        # Return net credit/debit (positive = credit, negative = debit)
        return total_value

    async def reconstruct_position_from_orders(self, position: Position) -> dict:
        """
        Use cached orders to determine correct position structure.
        Returns canonical position data.

        Args:
            position: Position to reconstruct

        Returns:
            Dict with corrected fields:
            {
                "number_of_spreads": 3,
                "quantity": 3,
                "metadata": {...}
            }
        """
        # Get opening order
        opening_order = await self.get_opening_order_for_position(position)
        if not opening_order:
            logger.warning(f"Cannot reconstruct position {position.id} - no opening order found")
            return {}

        # Parse order data to determine spread count
        order_data = opening_order.order_data
        legs = order_data.get("legs", [])

        if not legs:
            logger.warning(f"Cannot reconstruct position {position.id} - no legs in opening order")
            return {}

        # Calculate spread count based on order legs
        spread_count = self._calculate_spread_count_from_legs(legs, position.strategy_type)

        # Get profit target orders
        profit_targets = await self.link_profit_targets_to_opening_order(
            opening_order.broker_order_id
        )

        # Build corrected metadata
        corrected_metadata = {
            "opening_order_id": opening_order.broker_order_id,
            "profit_target_order_ids": [pt.broker_order_id for pt in profit_targets],
            "reconstructed_at": timezone.now().isoformat(),
            "reconstruction_source": "order_history_cache",
        }

        return {
            "number_of_spreads": spread_count,
            "quantity": spread_count,
            "metadata": corrected_metadata,
        }

    def _calculate_spread_count_from_legs(self, legs: list[dict], strategy_type: str) -> int:
        """
        Calculate spread count from order legs based on strategy type.

        Args:
            legs: List of leg dictionaries from order data
            strategy_type: Strategy type (e.g., "senex_trident")

        Returns:
            Number of spreads
        """

        # Helper to safely convert quantity to int
        def to_int(val):
            if val is None or val == "":
                return 0
            try:
                return int(float(str(val)))
            except (ValueError, TypeError):
                return 0

        if strategy_type == "senex_trident":
            # Senex Trident: 2 put spreads + 1 call spread = 3 total spreads
            # Look for put legs with quantity=2 and call legs with quantity=1
            put_quantity = 0
            call_quantity = 0

            for leg in legs:
                leg_symbol = leg.get("symbol", "")
                quantity = abs(to_int(leg.get("quantity", 0)))

                # Determine if put or call based on symbol (P/C indicator)
                if "P" in leg_symbol:
                    put_quantity = max(put_quantity, quantity)
                elif "C" in leg_symbol:
                    call_quantity = max(call_quantity, quantity)

            # Senex Trident should have 2 put contracts and 1 call contract
            total_spreads = put_quantity + call_quantity
            logger.debug(
                f"Senex Trident spread count: {put_quantity} puts + {call_quantity} "
                f"calls = {total_spreads} spreads"
            )
            return total_spreads
        # For other strategies, use min quantity across all legs
        spread_count = min(abs(to_int(leg.get("quantity", 0))) for leg in legs) if legs else 0
        logger.debug(f"Standard spread count: {spread_count}")
        return spread_count
