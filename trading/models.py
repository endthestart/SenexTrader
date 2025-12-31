from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

User = get_user_model()


# Default Senex Trident parameters (matching reference application)
SENEX_TRIDENT_DEFAULTS = {
    "underlying_symbol": "QQQ",  # QQQ has both odd and even strikes
    "target_dte": 45,  # Target days to expiration
    "min_dte": 30,  # Minimum days to expiration
    "max_dte": 50,  # Maximum days to expiration (30-50 day window)
    # Market condition thresholds
    "min_iv_rank": 25,  # Minimum IV rank for premium selling
    "bollinger_period": 20,  # Bollinger Bands period (not 37)
    "bollinger_std": 2.0,  # Bollinger Bands standard deviations
    "range_bound_threshold": 3,  # Days of range detection threshold
    # Risk management
    "max_position_size": 10,  # Maximum number of Senex Trident positions
    "spread_width": None,  # Auto-calculate: 3, 5, or 7 based on account
    # Exit rules
    "profit_target_percent": 50.0,  # Overall position profit target
    "dte_close": 7,  # Close positions 7 DTE
    "put_spread_1_target": 40.0,  # First put spread profit target
    "put_spread_2_target": 60.0,  # Second put spread profit target
    "call_spread_target": 40.0,  # Call spread profit target
}


class StrategyConfiguration(models.Model):
    @staticmethod
    def get_strategy_choices():
        """Dynamically generate strategy choices from factory."""
        from services.strategies.factory import list_strategies

        strategies = list_strategies()
        return [(name, name.replace("_", " ").title()) for name in strategies]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    strategy_id = models.CharField(max_length=50)
    parameters = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["user", "strategy_id"]

    def __str__(self):
        strategy_name = self.strategy_id.replace("_", " ").title()
        return f"{self.user.email} - {strategy_name}"

    def get_senex_parameters(self):
        """Get Senex Trident parameters with defaults"""
        defaults = SENEX_TRIDENT_DEFAULTS.copy()
        defaults.update(self.parameters.get("senex_trident", {}))
        return defaults

    def get_strategy_parameters(self):
        """Generic method to get parameters for any strategy."""
        # Fallback to senex_trident defaults if strategy-specific params not found
        defaults = SENEX_TRIDENT_DEFAULTS.copy()
        strategy_params = self.parameters.get(self.strategy_id, {})
        defaults.update(strategy_params)
        return defaults

    def get_spread_width(self, tradeable_capital: Decimal) -> int:
        """Get spread width based on tradeable capital (positions + buying power).

        Formula: nearest_odd(sqrt(capital / 1000)), minimum 3
        Transitions occur at perfect squares × 1000: 4k, 16k, 36k, 64k, 100k, 144k
        """
        # Use manual override if specified
        manual_width = self.parameters.get("senex_trident", {}).get("spread_width")
        if manual_width and manual_width in [3, 5, 7, 9, 11, 13]:
            return manual_width

        # Auto-calculate: nearest_odd(sqrt(capital / 1000)), min 3
        # Thresholds: 3→16k, 5→36k, 7→64k, 9→100k, 11→144k
        if tradeable_capital < 16000:
            return 3
        if tradeable_capital < 36000:
            return 5
        if tradeable_capital < 64000:
            return 7
        if tradeable_capital < 100000:
            return 9
        if tradeable_capital < 144000:
            return 11
        return 13


class Position(models.Model):
    LIFECYCLE_CHOICES = [
        ("pending_entry", "Pending Entry"),
        ("open_full", "Open - Full Size"),
        ("open_partial", "Open - Partial"),
        ("closing", "Closing - Exit Submitted"),
        ("closed", "Closed"),
        ("rolled", "Rolled Into New Position"),
        ("adjusted", "Adjusted"),
        ("expired", "Expired"),
    ]
    STRATEGY_CHOICES = [
        ("senex_trident", "Senex Trident"),
        ("short_put_vertical", "Short Put Vertical"),
        ("short_call_vertical", "Short Call Vertical"),
        ("long_call_vertical", "Long Call Vertical"),
        ("long_put_vertical", "Long Put Vertical"),
        ("stock_holding", "Stock Holding"),
    ]
    PRICE_EFFECT_CHOICES = [
        ("Credit", "Credit"),  # SDK uses capitalized values
        ("Debit", "Debit"),
    ]
    INSTRUMENT_TYPE_CHOICES = [
        ("Equity", "Equity"),  # Stock
        ("Equity Option", "Equity Option"),  # Options
        ("Future", "Future"),
        ("Future Option", "Future Option"),
        ("Cryptocurrency", "Cryptocurrency"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    trading_account = models.ForeignKey("accounts.TradingAccount", on_delete=models.CASCADE)

    instrument_type = models.CharField(
        max_length=20,
        choices=INSTRUMENT_TYPE_CHOICES,
        default="Equity Option",
        help_text="TastyTrade instrument type (Equity, Equity Option, etc.)",
    )
    strategy_type = models.CharField(
        max_length=50,
        choices=STRATEGY_CHOICES,
        null=True,
        blank=True,
        help_text="Strategy type (null for simple stock holdings)",
    )
    symbol = models.CharField(max_length=20)
    lifecycle_state = models.CharField(
        max_length=25,
        choices=LIFECYCLE_CHOICES,
        default="pending_entry",
    )
    quantity = models.IntegerField(default=0)
    avg_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unrealized_pnl = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_realized_pnl = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    metadata = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Risk tracking
    is_app_managed = models.BooleanField(
        default=True, help_text="Whether position was created by our app"
    )
    is_automated_entry = models.BooleanField(
        default=False,
        help_text="Whether position was opened by automated trading (vs manual)",
    )
    initial_risk = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Initial risk amount (max loss)",
    )
    spread_width = models.IntegerField(
        null=True, blank=True, help_text="Width of spread in dollars"
    )
    number_of_spreads = models.IntegerField(default=1, help_text="Number of spread contracts")

    # Transaction type tracking
    opening_price_effect = models.CharField(
        max_length=10,
        choices=PRICE_EFFECT_CHOICES,
        default="Credit",  # SDK uses capitalized values
        help_text="Whether position was opened for credit or debit",
    )

    # Profit Target Management
    profit_targets_created = models.BooleanField(
        default=False, help_text="Whether profit targets have been created for this position"
    )
    profit_target_details = models.JSONField(
        default=dict,
        encoder=DjangoJSONEncoder,
        help_text="Details of profit target orders by spread type",
    )

    # TastyTrade Order Tracking - PRIMARY LINK for position isolation
    opening_order_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        unique=True,
        help_text="TastyTrade order ID that opened this position (PlacedOrder.id). "
        "This is the PRIMARY KEY for isolating duplicate positions with same strikes.",
    )
    opening_complex_order_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="TastyTrade complex order ID if opened via OTOCO",
    )

    # Closure tracking
    closure_reason = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Reason position was closed: profit_target, manual_close, "
        "assignment, expired_worthless, exercise, unknown",
    )
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when option was assigned (if applicable)",
    )

    # Sync metadata
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this position was synced with TastyTrade",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "lifecycle_state"]),
            models.Index(fields=["trading_account", "lifecycle_state"]),
            models.Index(fields=["symbol", "lifecycle_state"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["lifecycle_state", "-created_at"]),
            # Position isolation indexes
            models.Index(fields=["opening_order_id"]),
            models.Index(fields=["opening_complex_order_id"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.strategy_type} - {self.lifecycle_state}"

    def get_risk_amount(self):
        """Calculate position risk (Decimal)"""
        from decimal import Decimal

        if self.initial_risk is not None:
            return Decimal(str(self.initial_risk))
        if self.spread_width and self.number_of_spreads:
            return Decimal(self.spread_width) * Decimal(self.number_of_spreads) * Decimal("100")
        return Decimal("0")


class Trade(models.Model):
    TRADE_TYPES = [
        ("open", "Open Position"),
        ("close", "Close Position"),
        ("adjustment", "Position Adjustment"),
    ]
    EXECUTION_STATUS = [
        ("pending", "Pending"),
        ("submitted", "Submitted"),
        ("routed", "Routed"),
        ("live", "Live/Working"),
        ("working", "Working"),
        ("filled", "Filled"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="trades")
    trading_account = models.ForeignKey("accounts.TradingAccount", on_delete=models.CASCADE)
    broker_order_id = models.CharField(max_length=100, unique=True)
    trade_type = models.CharField(max_length=20, choices=TRADE_TYPES)
    order_legs = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    executed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity = models.IntegerField()
    status = models.CharField(max_length=20, choices=EXECUTION_STATUS, default="pending")
    submitted_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    # Order relationship tracking
    parent_order_id = models.CharField(max_length=100, blank=True)
    child_order_ids = models.JSONField(default=list, encoder=DjangoJSONEncoder)  # Profit targets

    # Execution details
    filled_at = models.DateTimeField(null=True, blank=True)
    fill_price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    commission = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lifecycle_event = models.CharField(
        max_length=30,
        blank=True,
        help_text="Lifecycle event recorded when this trade executed",
    )
    lifecycle_snapshot = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text="Lifecycle metadata captured at execution time",
    )

    # Order management
    order_type = models.CharField(max_length=20, default="LIMIT")  # 'LIMIT', 'MARKET'
    time_in_force = models.CharField(max_length=20, default="DAY")  # 'DAY', 'GTC'

    # Metadata for tracking cancellation attempts, race conditions, etc.
    metadata = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["broker_order_id"]),
            models.Index(fields=["position", "trade_type"]),
            models.Index(fields=["user", "-submitted_at"]),
            models.Index(fields=["status", "-submitted_at"]),
        ]

    def __str__(self):
        return f"{self.position.symbol} {self.trade_type} - {self.status}"

    @property
    async def position_async(self):
        return await Position.objects.aget(id=self.position_id)

    @property
    async def user_async(self):
        return await User.objects.aget(id=self.user_id)

    @property
    async def trading_account_async(self):
        from accounts.models import TradingAccount

        return await TradingAccount.objects.aget(id=self.trading_account_id)


class TradingSuggestion(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("approved", "Approved for Execution"),
        ("executed", "Executed"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]

    # Core identification
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    strategy_id = models.CharField(max_length=50)
    strategy_configuration = models.ForeignKey(
        StrategyConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional: Only required for strategies with configuration (e.g., senex_trident)",
    )
    underlying_symbol = models.CharField(
        max_length=10, default="SPY"
    )  # Default to SPY per reference
    underlying_price = models.DecimalField(max_digits=10, decimal_places=2)
    expiration_date = models.DateField()

    # Senex Trident Strike Prices (Even Strike Requirement)
    # Strike fields: nullable to support all strategy types
    # - Senex Trident: has both puts and calls
    # - Bull Put Spread: has puts only (calls are null)
    # - Bear Call Spread: has calls only (puts are null)
    short_put_strike = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    long_put_strike = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    short_call_strike = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    long_call_strike = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Spread Quantities (strategy-specific, not globally defaulted)
    put_spread_quantity = models.IntegerField(default=0)  # Set by strategy
    call_spread_quantity = models.IntegerField(default=0)  # Set by strategy

    # Real Streaming Pricing (NEVER MOCK VALUES)
    # Natural credit (conservative for risk calculations)
    put_spread_credit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    call_spread_credit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    total_credit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Mid-price credit (realistic for UI display)
    put_spread_mid_credit = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    call_spread_mid_credit = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    total_mid_credit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    max_risk = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Pricing clarity fields
    price_effect = models.CharField(
        max_length=10,
        choices=[("Credit", "Credit"), ("Debit", "Debit")],  # SDK uses capitalized values
        default="Credit",
        help_text="Whether this position receives credit or pays debit",
    )
    max_profit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum profit potential for this position",
    )

    # Market Conditions at Generation (Real Data)
    iv_rank = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_near_bollinger_band = models.BooleanField(default=False)
    is_range_bound = models.BooleanField(default=False)
    market_stress_level = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    market_conditions = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    # Status and Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()  # Suggestions expire if not executed
    executed_position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL
    )

    # Streaming Data Availability Tracking
    has_real_pricing = models.BooleanField(default=False)
    pricing_source = models.CharField(max_length=50, blank=True)  # 'dxfeed_stream', 'cached', etc.
    streaming_latency_ms = models.IntegerField(null=True, blank=True)  # Track data freshness

    # Automation tracking
    is_automated = models.BooleanField(
        default=False, help_text="True if generated by automated trading system"
    )

    # Metadata
    generation_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["underlying_symbol", "expiration_date"]),
            models.Index(fields=["generated_at"]),
            models.Index(fields=["user", "-generated_at"]),
            models.Index(fields=["status", "-generated_at"]),
        ]
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.underlying_symbol} Senex Trident - {self.expiration_date} ({self.status})"

    @property
    def is_expired(self):
        from django.utils import timezone

        return timezone.now() > self.expires_at

    @property
    def is_complete_trident(self):
        """Check if this is a complete Senex Trident (2 put spreads + 1 call spread)"""
        return self.call_spread_quantity > 0 and self.short_call_strike is not None

    def to_dict(self):
        """Serialize TradingSuggestion to dictionary for API responses"""

        # Helper to get leg expiration (with override support)
        def get_leg_exp(leg_name):
            if self.market_conditions and "leg_expiration_overrides" in self.market_conditions:
                override = self.market_conditions["leg_expiration_overrides"].get(leg_name)
                if override:
                    return override
            return self.expiration_date

        # Helper to get DTE for an expiration date
        def get_dte_for_exp(exp_date):
            # First check if DTE is stored in market_conditions (for calendar spreads)
            if self.market_conditions:
                exp_str = (
                    exp_date.strftime("%Y-%m-%d")
                    if hasattr(exp_date, "strftime")
                    else str(exp_date)
                )
                near_exp = self.market_conditions.get("near_expiration")
                far_exp = self.market_conditions.get("far_expiration")

                if near_exp and exp_str == near_exp:
                    return self.market_conditions.get("near_dte")
                if far_exp and exp_str == far_exp:
                    return self.market_conditions.get("far_dte")

            # If not found, calculate DTE from today
            from datetime import date as datetime_date

            today = datetime_date.today()
            if hasattr(exp_date, "date"):
                exp_date = exp_date.date()
            elif isinstance(exp_date, str):
                from datetime import datetime

                exp_date = datetime.strptime(exp_date, "%Y-%m-%d").date()

            if isinstance(exp_date, datetime_date):
                delta = exp_date - today
                return delta.days

            return None

        # Build legs array (TastyTrade style)
        legs = []

        # Put legs
        if self.short_put_strike is not None:
            exp = get_leg_exp("short_put")
            legs.append(
                {
                    "action": "sell",
                    "quantity": self.put_spread_quantity or 1,
                    "expiration": (
                        exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)
                    ),
                    "dte": get_dte_for_exp(exp),
                    "strike": float(self.short_put_strike),
                    "option_type": "put",
                    "leg_type": "short_put",
                }
            )

        if self.long_put_strike is not None:
            exp = get_leg_exp("long_put")
            legs.append(
                {
                    "action": "buy",
                    "quantity": self.put_spread_quantity or 1,
                    "expiration": (
                        exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)
                    ),
                    "dte": get_dte_for_exp(exp),
                    "strike": float(self.long_put_strike),
                    "option_type": "put",
                    "leg_type": "long_put",
                }
            )

        # Call legs
        if self.short_call_strike is not None:
            exp = get_leg_exp("short_call")
            legs.append(
                {
                    "action": "sell",
                    "quantity": self.call_spread_quantity or 1,
                    "expiration": (
                        exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)
                    ),
                    "dte": get_dte_for_exp(exp),
                    "strike": float(self.short_call_strike),
                    "option_type": "call",
                    "leg_type": "short_call",
                }
            )

        if self.long_call_strike is not None:
            exp = get_leg_exp("long_call")
            legs.append(
                {
                    "action": "buy",
                    "quantity": self.call_spread_quantity or 1,
                    "expiration": (
                        exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)
                    ),
                    "dte": get_dte_for_exp(exp),
                    "strike": float(self.long_call_strike),
                    "option_type": "call",
                    "leg_type": "long_call",
                }
            )

        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "price_effect": self.price_effect,
            "underlying_symbol": self.underlying_symbol,
            "underlying_price": float(self.underlying_price),
            "expiration_date": self.expiration_date.strftime("%Y-%m-%d"),
            "short_put_strike": (float(self.short_put_strike) if self.short_put_strike else None),
            "long_put_strike": (float(self.long_put_strike) if self.long_put_strike else None),
            "short_call_strike": (
                float(self.short_call_strike) if self.short_call_strike else None
            ),
            "long_call_strike": (float(self.long_call_strike) if self.long_call_strike else None),
            "put_spread_quantity": self.put_spread_quantity,
            "call_spread_quantity": self.call_spread_quantity,
            "put_spread_credit": (
                float(self.put_spread_credit) if self.put_spread_credit else None
            ),
            "call_spread_credit": (
                float(self.call_spread_credit) if self.call_spread_credit else None
            ),
            "total_credit": float(self.total_credit) if self.total_credit else None,
            "put_spread_mid_credit": (
                float(self.put_spread_mid_credit) if self.put_spread_mid_credit else None
            ),
            "call_spread_mid_credit": (
                float(self.call_spread_mid_credit) if self.call_spread_mid_credit else None
            ),
            "total_mid_credit": (float(self.total_mid_credit) if self.total_mid_credit else None),
            "max_risk": float(self.max_risk) if self.max_risk else None,
            "max_profit": float(self.max_profit) if self.max_profit else None,
            "iv_rank": float(self.iv_rank) if self.iv_rank else None,
            "is_range_bound": self.is_range_bound,
            "market_stress_level": (
                float(self.market_stress_level) if self.market_stress_level else None
            ),
            "status": self.status,
            "legs": legs,  # TastyTrade-style legs array
        }


class HistoricalPrice(models.Model):
    """
    Store historical daily prices for technical analysis.
    Required for Bollinger Bands (20-day) and market analysis.
    Data sourced from Stooq.com for unlimited free access.
    """

    symbol = models.CharField(max_length=20, db_index=True)
    date = models.DateField()
    open = models.DecimalField(max_digits=12, decimal_places=4)
    high = models.DecimalField(max_digits=12, decimal_places=4)
    low = models.DecimalField(max_digits=12, decimal_places=4)
    close = models.DecimalField(max_digits=12, decimal_places=4)  # Adjusted close from Stooq
    volume = models.BigIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ["symbol", "date"]
        indexes = [
            models.Index(fields=["symbol", "-date"]),  # Recent data first
            models.Index(fields=["symbol", "date"]),  # Historical queries
        ]

    def __str__(self):
        return f"{self.symbol} {self.date}: ${self.close}"


class HistoricalGreeks(models.Model):
    """
    Store historical option Greeks from streaming data with progressive aggregation.

    Single table approach (KISS principle):
    - Stores Greeks at multiple resolutions (1s, 1min, 5min)
    - Timestamp precision indicates resolution (microseconds=0 for aggregated)
    - Aggregation reduces storage while preserving historical data indefinitely

    Resolution strategy:
    - 0-30 days: 1-second resolution (raw streaming data)
    - 30 days - 1 year: 1-minute resolution (aggregated)
    - 1+ years: 5-minute resolution (aggregated)

    Shared data - no user FK (multi-user architecture).
    """

    option_symbol = models.CharField(max_length=50, db_index=True)
    underlying_symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)

    # Greeks
    delta = models.DecimalField(max_digits=6, decimal_places=4)
    gamma = models.DecimalField(max_digits=8, decimal_places=6)
    theta = models.DecimalField(max_digits=6, decimal_places=4)
    vega = models.DecimalField(max_digits=6, decimal_places=4)
    rho = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    implied_volatility = models.DecimalField(max_digits=6, decimal_places=4)

    # Strike/Expiration for reference
    strike = models.DecimalField(max_digits=10, decimal_places=2)
    expiration_date = models.DateField()
    option_type = models.CharField(max_length=4)  # CALL or PUT

    class Meta:
        unique_together = ["option_symbol", "timestamp"]
        indexes = [
            models.Index(fields=["underlying_symbol", "-timestamp"]),
            models.Index(fields=["option_symbol", "-timestamp"]),
            models.Index(fields=["expiration_date", "strike"]),
        ]
        verbose_name_plural = "Historical Greeks"

    def __str__(self):
        return f"{self.option_symbol} {self.timestamp}: Δ={self.delta}"


class MarketMetricsHistory(models.Model):
    """
    Store historical market metrics (IV Rank, IV Percentile).
    Shared data - no user FK (multi-user architecture).
    Prevents data loss - metrics are now persisted permanently instead of 1-minute cache TTL.
    """

    symbol = models.CharField(max_length=20, db_index=True)
    date = models.DateField()

    # IV metrics
    iv_rank = models.DecimalField(max_digits=5, decimal_places=2)  # 0-100
    iv_percentile = models.DecimalField(max_digits=5, decimal_places=2)  # 0-100
    iv_30_day = models.DecimalField(max_digits=6, decimal_places=4)

    # Optional: HV metrics if available
    # max_digits=7 allows up to 999.9999% (market crashes can exceed 100%)
    hv_30_day = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)

    class Meta:
        unique_together = ["symbol", "date"]
        indexes = [
            models.Index(fields=["symbol", "-date"]),
        ]
        verbose_name_plural = "Market Metrics History"

    def __str__(self):
        return f"{self.symbol} {self.date}: IV Rank={self.iv_rank}%"


class TastyTradeOrderHistory(models.Model):
    """
    TastyTrade order history - single source of truth for all orders placed via TastyTrade.

    Note: Previously named CachedOrder. Renamed for clarity as this is comprehensive
    order history storage, not just cached data.

    **Purpose:**
    Stores complete order history from TastyTrade to enable accurate position reconstruction
    and lifecycle tracking. This cache eliminates reliance on TastyTrade's live API for
    historical order data and enables offline analysis.

    **Data Source:**
    - Synced from TastyTrade API every 15 minutes via OrderHistoryService.sync_order_history()
    - Includes all order types: opening orders, profit targets, closing orders, rolls
    - Stores complete PlacedOrder object in order_data JSONField for full fidelity

    **Key Relationships:**
    - parent_order_id: Links profit target/closing orders to their opening order
    - complex_order_id: Groups multi-leg orders (e.g., Senex Trident = 1 complex order, 6 legs)
    - replaces_order_id/replacing_order_id: Tracks order modifications and cancellations

    **Usage:**
    - Position reconstruction: OrderHistoryService.reconstruct_position_from_orders()
    - Opening order lookup: OrderHistoryService.get_opening_order_for_position()
    - Profit target reconciliation: PositionSyncService._reconcile_profit_target_fills()
    - Fill price calculations: OrderHistoryService.calculate_fill_price()

    **Data Integrity:**
    - broker_order_id is unique and indexed (database-level constraint)
    - Compound index on (status, broker_order_id) for fast profit target queries
    - Updated via upsert pattern to handle re-syncs and late fills

    **Example Query:**
    ```python
    # Find all filled profit targets for a position
    filled_targets = TastyTradeOrderHistory.objects.filter(
        broker_order_id__in=position.profit_target_order_ids,
        status="Filled"
    )
    ```
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    trading_account = models.ForeignKey("accounts.TradingAccount", on_delete=models.CASCADE)

    # TastyTrade order identifiers
    broker_order_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="TastyTrade's unique order ID (e.g., '410555589'). Globally unique across all accounts.",
    )
    complex_order_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    parent_order_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    replaces_order_id = models.CharField(max_length=50, null=True, blank=True)
    replacing_order_id = models.CharField(max_length=50, null=True, blank=True)

    # Order core data
    underlying_symbol = models.CharField(max_length=20, db_index=True)
    order_type = models.CharField(max_length=20)  # Limit, Market, Stop, etc.
    status = models.CharField(max_length=20, db_index=True)  # Filled, Cancelled, etc.
    price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    price_effect = models.CharField(max_length=10)  # Credit, Debit

    # Timestamps (from TastyTrade)
    received_at = models.DateTimeField(null=True, blank=True)
    live_at = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    terminal_at = models.DateTimeField(null=True, blank=True)

    # Full order data as JSON (complete PlacedOrder object serialized)
    order_data = models.JSONField()

    # Cache metadata
    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tastytrade_order_history"  # Previously "cached_orders"
        indexes = [
            models.Index(fields=["user", "underlying_symbol", "filled_at"]),
            models.Index(fields=["trading_account", "status"]),
            models.Index(fields=["broker_order_id"]),
            models.Index(
                fields=["status", "broker_order_id"],
                name="idx_tt_order_status_broker",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["broker_order_id"],
                name="unique_tt_order_broker_id",
            )
        ]
        ordering = ["-filled_at", "-received_at"]

    def __str__(self):
        order_info = f"{self.underlying_symbol} {self.order_type} {self.status}"
        return f"{order_info} - {self.broker_order_id}"


class CachedOrderChain(models.Model):
    """
    Local cache of TastyTrade order chains - tracks complete position lifecycle.

    **Purpose:**
    Represents the full lifecycle of a symbol's trading activity across multiple orders:
    opening trade → rolls (adjustments) → closing trade. Provides aggregated P&L and
    commission data for complete position analysis.

    **Data Source:**
    - Synced from TastyTrade API every 15 minutes via OrderHistoryService.sync_order_history()
    - TastyTrade generates one chain per underlying symbol per "position lifetime"
    - Chain continues through rolls; closes when position fully exits

    **Key Fields:**
    - chain_id: TastyTrade's unique identifier for this order chain (unique per account)
    - realized_pnl: Total P&L for closed portions of the chain
    - unrealized_pnl: Current P&L for open portions
    - total_commissions/fees: Cumulative costs across all orders in chain

    **Usage:**
    - Historical P&L analysis: Query chains by symbol/date range
    - Position lifecycle tracking: Monitor rolls and adjustments
    - Performance metrics: Calculate win rate, average P&L per chain

    **Data Integrity:**
    - Unique constraint on (trading_account, chain_id)
    - Indexed by (user, underlying_symbol) for fast lookups
    - chain_data JSONField preserves complete TastyTrade OrderChain object

    **Example Query:**
    ```python
    # Get all chains for SPX in last 30 days
    recent_chains = CachedOrderChain.objects.filter(
        user=user,
        underlying_symbol="SPX",
        created_at__gte=timezone.now() - timedelta(days=30)
    ).order_by('-created_at')
    ```
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    trading_account = models.ForeignKey("accounts.TradingAccount", on_delete=models.CASCADE)

    # OrderChain identifiers
    chain_id = models.IntegerField(
        db_index=True,
        help_text="TastyTrade's unique chain ID. Unique per trading account, tracks position lifecycle.",
    )
    underlying_symbol = models.CharField(max_length=20, db_index=True)
    description = models.TextField()

    # Computed P/L data (from TastyTrade)
    total_commissions = models.DecimalField(max_digits=12, decimal_places=4)
    total_fees = models.DecimalField(max_digits=12, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=12, decimal_places=4)
    unrealized_pnl = models.DecimalField(max_digits=12, decimal_places=4)

    # Full chain data as JSON (complete OrderChain object serialized)
    chain_data = models.JSONField()

    # Timestamps
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cached_order_chains"
        unique_together = [["trading_account", "chain_id"]]
        indexes = [
            models.Index(fields=["user", "underlying_symbol"]),
        ]

    def __str__(self):
        return f"{self.underlying_symbol} Chain {self.chain_id} - {self.description}"


class TastyTradeTransaction(models.Model):
    """
    Store raw transaction data from TastyTrade for historical reference.

    **Purpose:**
    Transactions are the ground truth for what actually executed - every fill,
    assignment, dividend, and fee is recorded as a transaction. This complements
    TastyTradeOrderHistory (what was requested) with what actually happened.

    **Data Source:**
    - Synced from TastyTrade API via Account.get_history()
    - Includes: Trade fills, assignments, exercises, dividends, fees
    - Each transaction has a unique ID that never changes

    **Key Fields:**
    - transaction_id: TastyTrade's unique identifier
    - order_id: Links to the TastyTradeOrderHistory that generated this transaction
    - action: "Buy to Open", "Sell to Close", etc.
    - Symbol/quantity/price for the specific fill

    **Usage:**
    - Position P&L calculation from actual fills
    - Assignment/exercise detection
    - Linking fills to specific Position via order_id → opening_order_id
    - Partial close tracking

    **Relationship to Position:**
    - related_position is set when we match transaction.order_id to
      Position.opening_order_id
    - Multiple transactions can relate to one Position (multi-leg fills)
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tt_transactions")
    trading_account = models.ForeignKey(
        "accounts.TradingAccount",
        on_delete=models.CASCADE,
        related_name="tt_transactions",
    )

    # TastyTrade IDs
    transaction_id = models.BigIntegerField(unique=True, db_index=True)
    order_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    # Transaction details
    transaction_type = models.CharField(max_length=50)  # "Trade", "Receive Deliver"
    transaction_sub_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )  # "Buy to Open", "Assignment"
    description = models.TextField(null=True, blank=True)
    action = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )  # OrderAction value

    # Financial data
    value = models.DecimalField(max_digits=15, decimal_places=4)
    net_value = models.DecimalField(max_digits=15, decimal_places=4)
    commission = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    clearing_fees = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    regulatory_fees = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Symbol and quantity
    symbol = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    underlying_symbol = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
    )
    instrument_type = models.CharField(max_length=50)
    quantity = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Timestamps
    executed_at = models.DateTimeField(db_index=True)

    # Raw data preservation
    raw_data = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    # Link to Position (set during position matching)
    related_position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tastytrade_transactions"
        ordering = ["-executed_at"]
        indexes = [
            models.Index(fields=["user", "executed_at"]),
            models.Index(
                fields=["trading_account", "underlying_symbol", "executed_at"],
            ),
            models.Index(fields=["order_id"]),
        ]

    def __str__(self):
        action = self.transaction_sub_type or self.transaction_type
        return f"{action} {self.symbol} @ {self.executed_at}"


class TechnicalIndicatorCache(models.Model):
    """
    Cache for technical indicator calculations.

    Stores calculated technical indicators (Bollinger Bands, RSI, MACD)
    to reduce CPU-intensive recalculations and API calls.

    Cache Strategy:
    - Memory cache (5 min TTL) for hot data
    - Database persistence for historical reference
    - Shared across users (no user FK)
    """

    symbol = models.CharField(max_length=10, db_index=True)
    indicator_type = models.CharField(max_length=50)  # 'bollinger', 'rsi', 'macd'
    timeframe = models.CharField(max_length=20, default="1D")
    calculated_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(encoder=DjangoJSONEncoder)

    class Meta:
        indexes = [
            models.Index(fields=["symbol", "indicator_type", "-calculated_at"]),
        ]
        unique_together = ["symbol", "indicator_type", "timeframe"]

    def __str__(self):
        return f"{self.symbol} {self.indicator_type} ({self.timeframe}) - {self.calculated_at}"


class Watchlist(models.Model):
    """
    User's watchlist of tracked equities.

    Used for:
    - Daily trade suggestions (pulls symbols from watchlist)
    - Portfolio tracking (future)
    - Price alerts (future)
    - Custom screeners (future)
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlist_items")

    symbol = models.CharField(max_length=10, help_text="Equity symbol (e.g., SPY, AAPL, GOOGL)")

    description = models.CharField(
        max_length=255, blank=True, help_text="Symbol description from TastyTrade API"
    )

    order = models.IntegerField(
        default=0, help_text="Display order in watchlist (lower = higher priority)"
    )

    def save(self, *args, **kwargs):
        """Enforce 20-symbol limit per user at database level."""
        if not self.pk:  # Only check for new instances
            from django.core.exceptions import ValidationError

            # Count existing watchlist items for this user
            existing_count = Watchlist.objects.filter(user=self.user).count()
            if existing_count >= 20:
                raise ValidationError(
                    "Maximum 20 symbols allowed per user. Remove a symbol before adding another."
                )
        super().save(*args, **kwargs)

    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["user", "symbol"]
        ordering = ["order", "symbol"]
        indexes = [
            models.Index(fields=["user", "order"]),
            models.Index(fields=["user", "symbol"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.symbol}"
