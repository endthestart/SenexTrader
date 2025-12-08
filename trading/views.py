"""
Trading views for Senex Trader.
All view functions for the trading app.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.models import OptionsAllocation
from services.account.state import AccountStateService
from services.core.cache import CacheManager
from services.core.logging import get_logger
from services.risk.manager import EnhancedRiskManager
from services.sdk.trading_utils import (
    is_market_open_now,
    now_in_new_york,
)
from streaming.services.stream_manager import GlobalStreamManager

if TYPE_CHECKING:
    from decimal import Decimal

logger = get_logger(__name__)

STRATEGY_DISPLAY_NAMES = {
    "short_put_vertical": "Short Put Vertical",
    "short_call_vertical": "Short Call Vertical",
    "long_put_vertical": "Long Put Vertical",
    "long_call_vertical": "Long Call Vertical",
    "long_call_calendar": "Long Call Calendar",
    "long_put_calendar": "Long Put Calendar",
    "short_iron_condor": "Short Iron Condor",
    "long_iron_condor": "Long Iron Condor",
    "iron_butterfly": "Iron Butterfly",
    "long_call_ratio_backspread": "Long Call Ratio Backspread",
    "long_straddle": "Long Straddle",
    "long_strangle": "Long Strangle",
    "cash_secured_put": "Cash-Secured Put",
    "covered_call": "Covered Call",
    "senex_trident": "Senex Trident",
}

# Logical ordering of strategies (grouped by type)
STRATEGY_ORDER = [
    # Vertical Spreads
    "short_put_vertical",
    "short_call_vertical",
    "long_put_vertical",
    "long_call_vertical",
    # Calendar Spreads
    "long_call_calendar",
    "long_put_calendar",
    # Multi-leg Strategies
    "short_iron_condor",
    "long_iron_condor",
    "iron_butterfly",
    # Volatility Strategies
    "long_straddle",
    "long_strangle",
    "long_call_ratio_backspread",
    # Stock + Option Strategies
    "cash_secured_put",
    "covered_call",
    # Custom Strategies
    "senex_trident",
]


def get_strategy_display_name(strategy_id: str) -> str:
    """Get TastyTrade-compliant display name for a strategy."""
    return STRATEGY_DISPLAY_NAMES.get(strategy_id, strategy_id.replace("_", " ").title())


def get_ordered_strategies(strategy_ids: list[str]) -> list[tuple[str, str]]:
    """
    Return strategies in logical order with proper display names.

    Args:
        strategy_ids: List of strategy identifiers from registry

    Returns:
        List of (strategy_id, display_name) tuples in logical order
    """
    # Filter to only include strategies we have, in our defined order
    ordered = [
        (sid, get_strategy_display_name(sid)) for sid in STRATEGY_ORDER if sid in strategy_ids
    ]

    # Add any strategies not in our order list (shouldn't happen, but be safe)
    remaining = [
        (sid, get_strategy_display_name(sid)) for sid in strategy_ids if sid not in STRATEGY_ORDER
    ]

    return ordered + remaining


@login_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Read-only dashboard showing critical trading information.
    All data is display-only with no interactive elements.
    """
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(request, "trading/broker_required.html", {"page_title": "Trading Dashboard"})

    context: dict[str, Any] = {
        "page_title": "Trading Dashboard",
    }

    # Get account state using service (falls back to DB snapshot if cache empty)
    account_data: dict[str, Any] = {}
    primary_account = request.user.trading_accounts.filter(is_primary=True).first()
    if primary_account:
        account_state_service = AccountStateService()
        account_state = account_state_service.get(request.user, primary_account.account_number)

        if account_state.get("available"):
            account_data = {
                "balance": account_state.get("balance"),
                "buying_power": account_state.get("buying_power"),
                "available": True,
                "source": account_state.get("source", "unknown"),
                "last_update": account_state.get("asof"),
            }
        else:
            account_data = {
                "available": False,
                "balance": None,
                "buying_power": None,
            }
    context["account_data"] = account_data

    # Get risk management data
    # Only calculate risk data if user has a configured primary trading account
    risk_data: dict[str, Any] = {}
    from services.core.data_access import has_configured_primary_account_sync

    if has_configured_primary_account_sync(request.user):
        try:
            risk_manager = EnhancedRiskManager(request.user)

            # Get tradeable capital and strategy power
            tradeable_capital, capital_available = risk_manager.get_tradeable_capital()
            strategy_power, power_available = risk_manager.calculate_strategy_power()

            if capital_available and power_available:
                current_risk: Decimal = risk_manager.get_app_managed_risk()
                utilization: float = (
                    (float(current_risk) / float(strategy_power) * 100)
                    if float(strategy_power) > 0
                    else 0
                )

                risk_data = {
                    "tradeable_capital": tradeable_capital,
                    "strategy_power": strategy_power,
                    "current_risk": current_risk,
                    "utilization_percent": round(utilization, 1),
                    "available": True,
                }
            else:
                risk_data = {"available": False}

            # Get allocation settings
            try:
                allocation = request.user.options_allocation
                risk_data["allocation_method"] = allocation.get_allocation_method_display()
                risk_data["risk_tolerance"] = allocation.risk_tolerance
            except OptionsAllocation.DoesNotExist:
                risk_data["allocation_method"] = "Not configured"

        except Exception as e:
            logger.error(f"Error getting risk data for dashboard: {e}")
            risk_data = {"available": False, "error": str(e)}
    else:
        # No configured account - risk data not available
        risk_data = {"available": False}

    context["risk_data"] = risk_data

    # Get market status
    # Convert NY time to naive datetime to prevent Django's UTC conversion
    ny_time = now_in_new_york()
    market_status = {
        "is_open": is_market_open_now(),
        "current_time": ny_time.replace(tzinfo=None),  # Make timezone-naive to display as-is
    }
    context["market_status"] = market_status

    # Get QQQ quote from cache (now consolidated by streaming service)
    # Fallback to API if cache is empty (e.g., before WebSocket connects)
    qqq_data: dict[str, Any] = {}
    quote_cache_key: str = CacheManager.quote("QQQ")
    cached_quote = cache.get(quote_cache_key)

    # If not in cache, try to fetch from API (fallback for when streaming hasn't started yet)
    if not cached_quote and primary_account:
        try:
            from services.market_data.service import MarketDataService

            market_service = MarketDataService(user=request.user)
            # Use sync wrapper to avoid ASGI deadlock
            cached_quote = market_service.get_quote_sync("QQQ")
            if cached_quote:
                logger.debug("Fetched QQQ quote from API for dashboard (cache was empty)")
        except Exception as e:
            logger.error(f"Failed to fetch QQQ quote from API for dashboard: {e}")

    if cached_quote:
        qqq_data = {
            "symbol": "QQQ",
            "last": cached_quote.get("last"),
            "bid": cached_quote.get("bid"),
            "ask": cached_quote.get("ask"),
            "volume": cached_quote.get("volume"),
            "available": True,
            "source": cached_quote.get("source", "cache"),
        }

        # Calculate daily change if we have previous close
        prev_close = cached_quote.get("previous_close")
        if prev_close and qqq_data["last"]:
            change = float(qqq_data["last"]) - float(prev_close)
            change_pct = (change / float(prev_close)) * 100
            qqq_data["change"] = change
            qqq_data["change_percent"] = round(change_pct, 2)
    else:
        qqq_data = {"available": False, "symbol": "QQQ"}

    context["qqq_data"] = qqq_data

    # Get IV data - fetch and cache if needed
    iv_cache_key = "market_metrics:QQQ"
    iv_data = cache.get(iv_cache_key)

    # If not in cache, try to fetch it using sync method (no asyncio.run deadlock)
    if not iv_data and primary_account:
        try:
            from services.market_data.service import MarketDataService

            market_service = MarketDataService(user=request.user)
            # Use sync wrapper instead of asyncio.run() to avoid ASGI deadlock
            iv_data = market_service.get_market_metrics_sync("QQQ")
        except Exception as e:
            logger.error(f"Failed to fetch IV data for dashboard: {e}")
            iv_data = None

    if iv_data:
        # FIX: SDK returns percentage format (22.15 for 22.15%), NOT decimal (0.2215)
        # No conversion needed - use value directly
        current_iv_raw = iv_data.get("iv_30_day")
        current_iv_pct = round(current_iv_raw, 1) if current_iv_raw is not None else None

        context["iv_data"] = {
            "iv_rank": iv_data.get("iv_rank"),
            "iv_percentile": iv_data.get("iv_percentile"),
            "current_iv": current_iv_pct,  # Already in percentage (22.1 for 22.1%)
            "available": True,
        }
    else:
        context["iv_data"] = {"available": False}

    # Check streaming status by looking for active stream manager and recent data
    streaming_status: dict[str, Any] = {}
    try:
        # Check if user has an active stream manager
        stream_manager_active = False
        streaming_data_available = False
        data_fresh = False
        age_seconds = None

        # Check if stream manager exists for this user
        if (
            hasattr(GlobalStreamManager, "_user_managers")
            and request.user.id in GlobalStreamManager._user_managers
        ):
            stream_manager = GlobalStreamManager._user_managers[request.user.id]
            stream_manager_active = stream_manager.is_streaming if stream_manager else False

        # Also check if we have any streaming data (QQQ is just one possible source)
        if cached_quote and cached_quote.get("source") == "consolidated_streaming":
            streaming_data_available = True
            # Check timestamp freshness if available
            if cached_quote.get("updated_at"):
                try:
                    from dateutil.parser import parse

                    updated_time = parse(cached_quote["updated_at"])
                    age_seconds = (timezone.now() - updated_time).total_seconds()
                    data_fresh = age_seconds < 300  # Data is fresh if < 5 minutes old

                    # Log if data is near expiry threshold
                    if age_seconds > 240:  # > 4 minutes
                        logger.debug(
                            f"Dashboard streaming check - Quote age nearing threshold: "
                            f"{age_seconds:.1f}s (threshold: 300s)"
                        )
                except Exception:
                    data_fresh = True  # Assume fresh if can't parse timestamp
        # Log why streaming data is not available
        elif not cached_quote:
            logger.debug("Dashboard streaming check - No cached quote available")
        elif cached_quote.get("source") != "consolidated_streaming":
            logger.debug(
                f"Dashboard streaming check - Quote source not streaming: "
                f"{cached_quote.get('source', 'unknown')}"
            )

        # Consider connected if either manager is active OR we have recent streaming data
        is_connected = stream_manager_active or streaming_data_available

        streaming_status = {
            "websocket_connected": is_connected,
            "data_streaming": is_connected and (data_fresh or stream_manager_active),
            "status": "Connected" if is_connected else "Disconnected",
        }

        # Log status determination for debugging
        age_str = f"{age_seconds:.1f}s" if age_seconds is not None else "N/A"
        logger.debug(
            f"Dashboard streaming status - Manager active: {stream_manager_active}, "
            f"Data available: {streaming_data_available}, Data fresh: {data_fresh}, "
            f"Age: {age_str}, "
            f"Final status: {streaming_status['status']}, "
            f"Data streaming: {streaming_status['data_streaming']}"
        )
    except Exception as e:
        logger.debug(f"Could not get streaming status: {e}")
        streaming_status = {
            "websocket_connected": False,
            "data_streaming": False,
            "status": "Unknown",
        }

    context["streaming_status"] = streaming_status

    # Get completed positions summary
    from decimal import Decimal

    from trading.models import Position

    completed_positions = Position.objects.filter(
        user=request.user, lifecycle_state="closed", is_app_managed=True
    )

    total_realized_pnl = sum(pos.total_realized_pnl or Decimal("0") for pos in completed_positions)

    context["completed_positions_data"] = {
        "count": completed_positions.count(),
        "total_realized_pnl": total_realized_pnl,
    }

    # Add timestamp
    context["dashboard_timestamp"] = timezone.now()

    return render(request, "trading/dashboard.html", context)


@login_required
def positions_view(request: HttpRequest) -> HttpResponse:
    """
    Show managed and unmanaged positions.
    """
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(
            request, "trading/broker_required.html", {"page_title": "Positions Dashboard"}
        )

    from services.positions.lifecycle.dte_manager import DTEManager
    from trading.models import Position

    # Phase 4.2: Optimize queries with select_related and prefetch_related to avoid N+1
    # Include both 'pending_entry' (order submitted) and 'open' lifecycle states
    managed_positions = (
        Position.objects.filter(
            user=request.user,
            is_app_managed=True,
            lifecycle_state__in=["pending_entry", "open_full", "open_partial"],
        )
        .select_related("trading_account")
        .prefetch_related("trades")
        .order_by("-created_at")
    )

    unmanaged_positions = (
        Position.objects.filter(
            user=request.user,
            is_app_managed=False,
            lifecycle_state__in=["pending_entry", "open_full", "open_partial"],
        )
        .select_related("trading_account")
        .prefetch_related("trades")
        .order_by("-created_at")
    )

    # Initialize DTE manager once for all positions
    dte_manager = DTEManager(request.user)

    # Annotate positions with active trade status and DTE
    for position in managed_positions:
        # Get the most recent trade for this position
        active_trade = (
            position.trades.filter(status__in=["pending", "submitted", "routed", "live", "working"])
            .order_by("-submitted_at")
            .first()
        )
        position.active_trade = active_trade
        position.days_to_expiration = dte_manager.calculate_current_dte(position)

    for position in unmanaged_positions:
        active_trade = (
            position.trades.filter(status__in=["pending", "submitted", "routed", "live", "working"])
            .order_by("-submitted_at")
            .first()
        )
        position.active_trade = active_trade
        position.days_to_expiration = dte_manager.calculate_current_dte(position)

    # Calculate P&L totals for managed positions
    total_realized_pnl = sum(position.total_realized_pnl or 0 for position in managed_positions)
    total_unrealized_pnl = sum(position.unrealized_pnl or 0 for position in managed_positions)

    # Get recently closed positions (last 7 days)
    from datetime import timedelta

    seven_days_ago = timezone.now() - timedelta(days=7)
    recently_closed = (
        Position.objects.filter(
            user=request.user,
            is_app_managed=True,
            lifecycle_state="closed",
            closed_at__gte=seven_days_ago,
        )
        .select_related("trading_account")
        .order_by("-closed_at")
    )

    context = {
        "page_title": "Positions Dashboard",
        "managed_positions": managed_positions,
        "unmanaged_positions": unmanaged_positions,
        "managed_count": managed_positions.count(),
        "unmanaged_count": unmanaged_positions.count(),
        "total_realized_pnl": total_realized_pnl,
        "total_unrealized_pnl": total_unrealized_pnl,
        "recently_closed": recently_closed,
    }

    return render(request, "trading/positions.html", context)


@login_required
def orders_view(request: HttpRequest) -> HttpResponse:
    """
    Display all active application-managed orders.
    Shows orders that are pending, submitted, or working.
    Includes both opening/closing orders from Trade table and profit target orders from TastyTradeOrderHistory.
    Enriches each order with parsed leg details and DTE calculations.
    """
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(request, "trading/broker_required.html", {"page_title": "Orders"})

    from datetime import date

    from services.sdk.instruments import parse_occ_symbol
    from trading.models import Position, TastyTradeOrderHistory, Trade

    # Get opening/closing orders from Trade table
    trade_orders = (
        Trade.objects.filter(
            user=request.user,
            position__is_app_managed=True,
            status__in=["pending", "submitted", "routed", "live", "working"],
        )
        .select_related("position", "trading_account")
        .order_by("-submitted_at")
    )

    # Get all open positions to extract profit target order IDs
    open_positions = Position.objects.filter(
        user=request.user,
        is_app_managed=True,
        lifecycle_state__in=["open_full", "open_partial"],
    ).select_related("trading_account")

    # Collect profit target order IDs from all open positions
    profit_target_order_ids = []
    position_by_profit_target = {}  # Maps order_id -> position

    for position in open_positions:
        if position.profit_target_details:
            for _spread_type, details in position.profit_target_details.items():
                order_id = details.get("order_id")
                status = details.get("status")

                # Only count active orders (not filled/cancelled)
                # Filled/cancelled spreads should not appear in order list
                if order_id and status not in ["filled", "cancelled", "cancelled_dte_automation"]:
                    profit_target_order_ids.append(order_id)
                    position_by_profit_target[order_id] = position

    # Get profit target orders from TastyTradeOrderHistory table
    profit_target_orders = []
    if profit_target_order_ids:
        profit_target_orders = list(
            TastyTradeOrderHistory.objects.filter(
                broker_order_id__in=profit_target_order_ids,
                status__in=["Received", "Routed", "In Flight", "Live"],
            ).select_related("trading_account")
        )

    # Create adapter objects for TastyTradeOrderHistory to match Trade interface
    class TastyTradeOrderHistoryAdapter:
        """Adapter to make TastyTradeOrderHistory compatible with Trade-expecting template"""

        def __init__(self, cached_order, position):
            self._cached_order = cached_order
            self.position = position
            self.trading_account = cached_order.trading_account
            self.id = cached_order.broker_order_id
            self.broker_order_id = cached_order.broker_order_id
            self.quantity = 1  # Profit targets are typically 1 contract
            self.submitted_at = cached_order.received_at or cached_order.created_at

            # Mark this as a profit target (used by template to disable cancel button)
            self.is_profit_target = True

            # Extract legs from order_data JSON
            self.order_legs = cached_order.order_data.get("legs", [])

            # Extract limit price (executed_price for Trade compatibility)
            self.executed_price = cached_order.price

            # Map TastyTrade status to Trade status
            tt_status = cached_order.status.lower()
            if tt_status in ["received", "routed", "in flight"]:
                self._status = "submitted"
            elif tt_status == "live":
                self._status = "live"
            else:
                self._status = tt_status

            # Map order type
            self.order_type = cached_order.order_type.upper()

            # Profit targets are always "close" type
            self._trade_type = "close"

        @property
        def status(self):
            return self._status

        @property
        def trade_type(self):
            return self._trade_type

        def get_status_display(self):
            status_map = {
                "submitted": "Submitted",
                "routed": "Routed",
                "live": "Live/Working",
                "working": "Working",
            }
            return status_map.get(self._status, self._status.title())

        def get_trade_type_display(self):
            return "Profit Target"

    # Combine Trade orders and adapted TastyTradeOrderHistory profit targets
    all_orders = list(trade_orders)

    # Mark regular trades as non-profit-targets
    for trade in all_orders:
        trade.is_profit_target = False

    # Add profit target adapters
    for cached_order in profit_target_orders:
        position = position_by_profit_target.get(cached_order.broker_order_id)
        if position:
            adapter = TastyTradeOrderHistoryAdapter(cached_order, position)
            all_orders.append(adapter)

    # Enrich each order with parsed leg information
    enriched_orders = []
    for order in all_orders:
        order_data = {
            "order": order,
            "parsed_legs": [],
            "expiration_date": None,
            "dte": None,
        }

        # Parse each leg to extract strike, expiration, option type
        if order.order_legs:
            for leg in order.order_legs:
                symbol = leg.get("symbol")
                if symbol and len(symbol) == 21:  # OCC format
                    try:
                        parsed = parse_occ_symbol(symbol)
                        leg_info = {
                            "symbol": symbol,
                            "action": leg.get("action", ""),
                            "quantity": leg.get("quantity", 0),
                            "underlying": parsed["underlying"],
                            "strike": parsed["strike"],
                            "expiration": parsed["expiration"],
                            "option_type": "Call" if parsed["option_type"] == "C" else "Put",
                            "option_type_short": parsed["option_type"],
                        }
                        order_data["parsed_legs"].append(leg_info)

                        # Set expiration date from first leg (all legs typically same expiration)
                        if order_data["expiration_date"] is None:
                            order_data["expiration_date"] = parsed["expiration"]
                    except (ValueError, KeyError):
                        # Skip legs that can't be parsed
                        continue

        # Calculate DTE if we have an expiration date
        if order_data["expiration_date"]:
            today = date.today()
            delta = order_data["expiration_date"] - today
            order_data["dte"] = delta.days

        enriched_orders.append(order_data)

    # Sort by DTE (shortest to longest), then by submission time for orders without DTE
    enriched_orders.sort(
        key=lambda o: (
            o["dte"] if o["dte"] is not None else 9999,  # Orders without DTE go last
            -(
                o["order"].submitted_at or date.min
            ).timestamp(),  # Secondary sort by time (newest first within same DTE)
        )
    )

    context = {
        "page_title": "Active Orders",
        "enriched_orders": enriched_orders,
        "order_count": len(enriched_orders),
    }

    return render(request, "trading/orders.html", context)


@login_required
def watchlist_view(request: HttpRequest) -> HttpResponse:
    """
    Watchlist management page.
    Users can search for and track equities.
    """
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(request, "trading/broker_required.html", {"page_title": "My Watchlist"})

    context: dict[str, Any] = {
        "page_title": "My Watchlist",
    }

    return render(request, "trading/watchlist.html", context)


@login_required
def trading_view(request):
    """Main trading page - All Options Strategies."""
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(request, "trading/broker_required.html", {"page_title": "Options Trading"})

    from services.strategies.registry import list_registered_strategies
    from trading.models import StrategyConfiguration, Trade, Watchlist

    all_strategy_types = [
        name
        for name in list_registered_strategies()
        if name not in ["senex_trident", "calendar_spread"]
    ]

    pending_trades = (
        Trade.objects.filter(
            user=request.user,
            position__strategy_type__in=all_strategy_types,
            status__in=["pending", "submitted", "routed", "live", "working"],
        )
        .select_related("position")
        .order_by("-submitted_at")
    )

    strategy_configs = StrategyConfiguration.objects.filter(
        user=request.user, strategy_id__in=all_strategy_types, is_active=True
    )

    available_strategies = get_ordered_strategies(all_strategy_types)

    watchlist_symbols = list(
        Watchlist.objects.filter(user=request.user)
        .order_by("order", "symbol")
        .values_list("symbol", flat=True)
    )
    available_symbols = watchlist_symbols if watchlist_symbols else ["QQQ", "SPY", "IWM"]

    context = {
        "page_title": "Options Trading",
        "pending_trades": pending_trades,
        "strategy_configs": strategy_configs,
        "available_strategies": available_strategies,
        "available_symbols": available_symbols,
    }

    return render(request, "trading/trading.html", context)


@login_required
def senex_trident_view(request):
    """Dedicated Senex Trident algorithm trading page."""
    # Check if user has a configured primary trading account
    from services.core.data_access import has_configured_primary_account_sync

    if not has_configured_primary_account_sync(request.user):
        return render(
            request, "trading/broker_required.html", {"page_title": "Senex Trident Algorithm"}
        )

    from trading.models import StrategyConfiguration, Trade, TradingSuggestion

    # StrategyConfiguration is created automatically via signals when broker is connected
    config = StrategyConfiguration.objects.filter(
        user=request.user, strategy_id="senex_trident", is_active=True
    ).first()

    suggestion = (
        TradingSuggestion.objects.filter(
            user=request.user,
            strategy_configuration__strategy_id="senex_trident",
            status="pending",
            expires_at__gt=timezone.now(),
        )
        .order_by("-generated_at")
        .first()
    )

    suggestion_json = None
    if suggestion:
        suggestion_json = json.dumps(suggestion.to_dict())

    pending_trades = (
        Trade.objects.filter(
            user=request.user,
            position__strategy_type="senex_trident",
            status__in=["pending", "submitted", "routed", "live", "working"],
        )
        .select_related("position")
        .order_by("-submitted_at")
    )

    automation_enabled = False
    if config:
        from accounts.models import TradingAccount

        account = TradingAccount.objects.filter(user=request.user, is_primary=True).first()
        if account:
            automation_enabled = account.is_automated_trading_enabled

    context = {
        "page_title": "Senex Trident Algorithm",
        "config": config,
        "suggestion_json": suggestion_json,
        "pending_trades": pending_trades,
        "automation_enabled": automation_enabled,
        "available_symbols": ["QQQ"],
    }

    return render(request, "trading/senex_trident.html", context)
