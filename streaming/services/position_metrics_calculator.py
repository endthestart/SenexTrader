"""
Position Metrics Calculator - Calculates balance, Greeks, and P&L from cache.

This helper extracts pure calculation logic for position metrics, following the
stateless helper pattern from Phase 5.1a (OrderEventProcessor).

Responsibility:
- Fetch account balance from TastyTrade
- Calculate Greeks from cache via GreeksService
- Calculate P&L from cached quotes
- Return unified metrics data structure

Design Principles (from phase-5-boundary-validation.md):
- Pure calculation logic, no side effects
- No state dependencies
- Receives all inputs as parameters
- Returns structured data for broadcast
"""

import time
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.utils import timezone as dj_timezone

from asgiref.sync import sync_to_async

from accounts.models import AccountSnapshot, TradingAccount
from services.core.cache import CacheManager
from services.core.logging import get_logger
from services.market_data.greeks import GreeksService
from services.positions.lifecycle.pnl_calculator import PositionPnLCalculator
from streaming.constants import ACCOUNT_STATE_CACHE_TTL
from streaming.services.enhanced_cache import enhanced_cache
from trading.models import Position

logger = get_logger(__name__)


class PositionMetricsCalculator:
    """Calculates unified metrics (balance, Greeks, P&L) from cached data."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.greeks_service = GreeksService()

    async def calculate_unified_metrics(self) -> dict[str, Any] | None:
        """
        Calculate unified position metrics from cached data.

        Returns:
            dict: {
                "type": "position_metrics_update",
                "timestamp": <ms since epoch>,
                "balance": {"balance": float, "buying_power": float},
                "portfolio_greeks": {"delta": float, "gamma": float, ...},
                "positions": [{"position_id": int, "greeks": dict, "pnl": float}]
            }
        """
        logger.info(f"User {self.user_id}: Starting calculate_unified_metrics")
        update_data = {
            "type": "position_metrics_update",
            "timestamp": time.time() * 1000,
        }

        # Get balance data
        balance_data = await self._fetch_account_balance()
        logger.info(f"User {self.user_id}: Balance data fetched: {bool(balance_data)}")
        if balance_data:
            update_data["balance"] = balance_data

        # Get position metrics
        position_metrics = await self._calculate_position_metrics()
        logger.info(
            f"User {self.user_id}: Position metrics calculated: {len(position_metrics) if position_metrics else 0} positions"
        )
        if position_metrics:
            update_data["positions"] = position_metrics

        # Get portfolio-level Greeks
        portfolio_greeks = await self._calculate_portfolio_greeks()
        logger.info(f"User {self.user_id}: Portfolio Greeks calculated: {bool(portfolio_greeks)}")
        if portfolio_greeks:
            update_data["portfolio_greeks"] = portfolio_greeks

        has_data = balance_data or position_metrics
        logger.info(f"User {self.user_id}: Returning metrics: has_data={has_data}")
        return update_data if has_data else None

    async def _fetch_account_balance(self) -> dict[str, float] | None:
        """
        Fetch account balance from TastyTrade and cache for AccountStateService.

        Returns:
            dict: {"balance": float, "buying_power": float} or None
        """
        try:
            # Get TastyTrade account
            account_obj = await TradingAccount.objects.filter(
                user_id=self.user_id, connection_type="TASTYTRADE", is_active=True
            ).afirst()

            if not account_obj or not account_obj.account_number:
                logger.warning(
                    f"User {self.user_id}: No active TastyTrade account for balance fetch"
                )
                return None

            # Get user and OAuth session
            from django.contrib.auth import get_user_model

            from tastytrade import Account

            from services.core.data_access import get_oauth_session

            User = get_user_model()
            user = await User.objects.aget(id=self.user_id)
            session = await get_oauth_session(user)

            if not session:
                logger.warning(f"User {self.user_id}: No OAuth session for balance fetch")
                return None

            # Fetch balance from TastyTrade
            account = await Account.a_get(session, account_obj.account_number)
            balances = await account.a_get_balances(session)

            if not balances:
                logger.warning(f"User {self.user_id}: No balance data from TastyTrade")
                return None

            balance_data = {
                "balance": (
                    float(balances.net_liquidating_value) if balances.net_liquidating_value else 0
                ),
                "buying_power": (
                    float(balances.derivative_buying_power)
                    if balances.derivative_buying_power
                    else 0
                ),
            }

            # Cache for AccountStateService compatibility
            account_state_data = {
                "buying_power": balance_data["buying_power"],
                "balance": balance_data["balance"],
                "pnl": 0.0,
                "asof": dj_timezone.now().isoformat(),
                "source": "stream",
                "stale": False,
                "available": True,
            }
            account_state_key = CacheManager.account_state(self.user_id, account_obj.account_number)
            await enhanced_cache.set(
                account_state_key, account_state_data, ttl=ACCOUNT_STATE_CACHE_TTL
            )

            # Save to database
            try:
                await AccountSnapshot.objects.acreate(
                    user_id=self.user_id,
                    account_number=account_obj.account_number,
                    buying_power=Decimal(str(balance_data["buying_power"])),
                    balance=Decimal(str(balance_data["balance"])),
                    source="stream",
                )
            except Exception as e:
                logger.error(f"User {self.user_id}: Failed to save AccountSnapshot: {e}")

            return balance_data

        except Exception as e:
            logger.error(f"User {self.user_id}: Error fetching balance: {e}", exc_info=True)
            return None

    async def _calculate_position_metrics(self) -> list[dict[str, Any]]:
        """
        Calculate Greeks and P&L for all open positions from cached data.

        Returns:
            list[dict]: [{"position_id": int, "greeks": dict, "pnl": float}]
        """
        position_metrics = []

        try:
            # Get all open positions
            positions = [
                p
                async for p in Position.objects.filter(
                    user_id=self.user_id,
                    is_app_managed=True,
                    lifecycle_state__in=["open_full", "open_partial"],
                ).select_related("trading_account")
            ]

            logger.debug(
                f"User {self.user_id}: Found {len(positions)} open positions for metrics calculation"
            )

            for position in positions:
                try:
                    # Get Greeks from cache (GreeksService reads from dxfeed:greeks cache)
                    greeks = await sync_to_async(self.greeks_service.get_position_greeks_cached)(
                        position
                    )
                    logger.debug(
                        f"User {self.user_id}: Position {position.id} Greeks: {bool(greeks)}"
                    )

                    # Calculate P&L from cached quotes
                    pnl = await self._calculate_position_pnl(position)
                    logger.info(f"User {self.user_id}: Position {position.id} P&L: {pnl}")

                    # Add to metrics if we have data
                    if greeks or pnl is not None:
                        position_metrics.append(
                            {"position_id": position.id, "greeks": greeks, "pnl": pnl}
                        )
                        logger.debug(
                            f"User {self.user_id}: Position {position.id} added to metrics"
                        )
                    else:
                        logger.debug(
                            f"User {self.user_id}: Position {position.id} has no Greeks or P&L data"
                        )

                except Exception as e:
                    logger.warning(
                        f"User {self.user_id}: Error calculating metrics "
                        f"for position {position.id}: {e}"
                    )
                    continue

        except Exception as e:
            logger.error(
                f"User {self.user_id}: Error calculating position metrics: {e}",
                exc_info=True,
            )

        logger.info(f"User {self.user_id}: Returning {len(position_metrics)} position metrics")
        return position_metrics

    async def _calculate_portfolio_greeks(self) -> dict[str, Any] | None:
        """
        Calculate portfolio-level Greeks from all open positions.

        Returns:
            dict: {"delta": float, "gamma": float, "theta": float, "vega": float, "rho": float}
        """
        try:
            # Get user object
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = await User.objects.aget(id=self.user_id)

            # Use cached portfolio Greeks calculation
            portfolio_greeks = await sync_to_async(self.greeks_service.get_portfolio_greeks_cached)(
                user
            )

            # Return None if no position count (empty portfolio)
            if portfolio_greeks.get("position_count", 0) == 0:
                return None

            # Filter out error field for WebSocket broadcast
            return {
                "delta": portfolio_greeks.get("delta", 0.0),
                "gamma": portfolio_greeks.get("gamma", 0.0),
                "theta": portfolio_greeks.get("theta", 0.0),
                "vega": portfolio_greeks.get("vega", 0.0),
                "rho": portfolio_greeks.get("rho", 0.0),
                "position_count": portfolio_greeks.get("position_count", 0),
            }

        except Exception as e:
            logger.error(
                f"User {self.user_id}: Error calculating portfolio Greeks: {e}",
                exc_info=True,
            )
            return None

    async def _calculate_position_pnl(self, position: Position) -> float | None:
        """
        Calculate P&L for a position from cached quote data.

        Args:
            position: Position model instance

        Returns:
            float: P&L value or None if cannot be calculated
        """
        is_multi_leg = position.metadata and "legs" in position.metadata

        if is_multi_leg:
            # Multi-leg position
            total_pnl = Decimal("0")
            all_legs_have_marks = True

            for leg in position.metadata["legs"]:
                quote_key = CacheManager.quote(leg["symbol"])
                cached_quote = cache.get(quote_key)

                if cached_quote and cached_quote.get("mark"):
                    leg_pnl = PositionPnLCalculator.calculate_leg_pnl(
                        avg_price=leg.get("average_open_price", 0),
                        current_price=float(cached_quote["mark"]),
                        quantity=leg.get("quantity", 0),
                        quantity_direction=leg.get("quantity_direction", "long"),
                    )
                    total_pnl += leg_pnl
                else:
                    all_legs_have_marks = False
                    break

            return float(total_pnl) if all_legs_have_marks else None

        # Single-leg position
        quote_key = CacheManager.quote(position.symbol)
        cached_quote = cache.get(quote_key)

        if cached_quote and cached_quote.get("mark") and position.avg_price:
            unrealized_pnl = PositionPnLCalculator.calculate_unrealized_pnl(
                opening_credit=position.avg_price,
                current_mark=Decimal(str(cached_quote["mark"])),
                quantity=position.quantity,
            )
            return float(unrealized_pnl)

        return None
