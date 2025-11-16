from django.urls import path

from . import api_views, views

app_name = "trading"

urlpatterns = [
    # Main trading routes
    path("", views.trading_view, name="trading"),
    path("senex-trident/", views.senex_trident_view, name="senex_trident"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("positions/", views.positions_view, name="positions"),
    path("orders/", views.orders_view, name="orders"),
    path("watchlist/", views.watchlist_view, name="watchlist"),
    # API endpoints - all consolidated in api_views.py
    path("api/risk-budget/", api_views.get_risk_budget, name="api_risk_budget"),
    path("api/validate-trade-risk/", api_views.validate_trade_risk, name="api_validate_trade_risk"),
    path("api/streamer/status/", api_views.check_streamer_readiness, name="streamer_status"),
    path("api/risk-settings/", api_views.save_risk_settings, name="api_risk_settings"),
    # Strategy Selector API endpoints (Phase 4)
    path("api/suggestions/auto/", api_views.generate_suggestion_auto, name="api_suggestions_auto"),
    path(
        "api/suggestions/forced/",
        api_views.generate_suggestion_forced,
        name="api_suggestions_forced",
    ),
    # Dynamic strategy API endpoints (Phase 2)
    path(
        "api/<str:strategy>/generate/",
        api_views.generate_suggestion,
        name="api_generate_suggestion",
    ),
    path(
        "api/suggestions/<int:suggestion_id>/execute/",
        api_views.execute_suggestion,
        name="api_execute_suggestion",
    ),
    path(
        "api/suggestions/<int:suggestion_id>/reject/",
        api_views.reject_suggestion,
        name="api_reject_suggestion",
    ),
    path("api/orders/<str:order_id>/status/", api_views.get_order_status, name="api_order_status"),
    path("api/pending-orders/", api_views.get_pending_orders, name="api_pending_orders"),
    path("api/sync-positions/", api_views.sync_positions, name="api_sync_positions"),
    path("api/trades/<int:trade_id>/cancel", api_views.cancel_trade, name="api_cancel_trade"),
    # Greeks endpoints
    path(
        "api/positions/greeks/",
        api_views.get_all_positions_greeks,
        name="api_all_positions_greeks",
    ),
    path(
        "api/positions/<int:position_id>/greeks/",
        api_views.get_position_greeks,
        name="api_position_greeks",
    ),
    path("api/portfolio/greeks/", api_views.get_portfolio_greeks, name="api_portfolio_greeks"),
    path(
        "api/positions/<int:position_id>/details/",
        api_views.get_position_details,
        name="api_position_details",
    ),
    path(
        "api/positions/leg-symbols/",
        api_views.get_all_positions_leg_symbols,
        name="api_positions_leg_symbols",
    ),
    # Watchlist endpoints (Phase 0: Multi-Equity Suggestions)
    path("api/watchlist/search/", api_views.watchlist_symbol_search, name="api_watchlist_search"),
    path("api/watchlist/", api_views.watchlist_api, name="api_watchlist"),
    path("api/watchlist/<int:item_id>/", api_views.watchlist_remove, name="api_watchlist_item"),
    # Strategy endpoints
    path("api/strategy/trigger/", api_views.trigger_suggestion, name="trigger_suggestion"),
]
