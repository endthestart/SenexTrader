from django.contrib import admin

from .models import Position, StrategyConfiguration, Trade, Watchlist


@admin.register(StrategyConfiguration)
class StrategyConfigurationAdmin(admin.ModelAdmin):
    list_display = ("user", "strategy_id", "is_active", "created_at")
    list_filter = ("strategy_id", "is_active", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "user",
        "strategy_type",
        "lifecycle_state",
        "unrealized_pnl",
        "total_realized_pnl",
        "opened_at",
    )
    list_filter = ("strategy_type", "lifecycle_state", "symbol", "opened_at")
    search_fields = ("user__email", "symbol")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = (
        "position",
        "trade_type",
        "status",
        "quantity",
        "executed_price",
        "lifecycle_event",
        "submitted_at",
    )
    list_filter = ("trade_type", "status", "lifecycle_event", "submitted_at")
    search_fields = ("broker_order_id", "position__symbol", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ("user", "symbol", "description", "order", "added_at")
    list_filter = ("added_at",)
    search_fields = ("user__email", "symbol", "description")
    readonly_fields = ("added_at", "updated_at")
    ordering = ("user", "order", "symbol")
