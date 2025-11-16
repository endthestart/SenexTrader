# Automated Trading Risk Analysis

## Executive Summary
Risk assessment for multi-leg option position management system with focus on iron condors (2 put spreads + 1 call spread), automated profit targets, and 7 DTE closing rules.

---

## Risk Scenario Analysis

### 1. Partial Fill Risks
**Scenario**: Put spread 1 fills at profit target, but put spread 2 remains open

**Assessment**:
- **Likelihood**: COMMON (30-40% of positions)
- **Financial Impact**: MEDIUM
- **Detection**: Monitor position deltas post-fill
- **Impact Details**: Creates directional exposure, converts neutral position to directional

**Mitigation Strategy**:
```python
# PRIORITY: P0 - CRITICAL
class PartialFillHandler:
    def on_spread_fill(self, filled_spread, remaining_spreads):
        # Calculate new position Greeks
        net_delta = calculate_position_delta(remaining_spreads)

        if abs(net_delta) > DELTA_THRESHOLD:  # e.g., 0.20
            # Option 1: Close remaining spreads immediately
            if market_conditions_favorable():
                close_remaining_spreads_market_order()

            # Option 2: Adjust profit targets on remaining
            else:
                adjust_profit_targets(remaining_spreads,
                                    reduction_factor=0.5)  # Take profit sooner
```

**Implementation Priority**: P0 - This WILL happen regularly

---

### 2. DTE (Days to Expiration) Risks
**Scenario**: Cannot close position at 7 DTE due to wide bid/ask spreads

**Assessment**:
- **Likelihood**: OCCASIONAL (10-15% of positions)
- **Financial Impact**: HIGH (gamma risk accelerates)
- **Detection**: Daily DTE scan with liquidity check

**Mitigation Strategy**:
```python
# PRIORITY: P0 - CRITICAL
class DTECloseHandler:
    def handle_7dte_close(self, position):
        bid_ask_spread = get_bid_ask_spread(position)
        mid_price = (bid + ask) / 2

        # Escalating close attempts
        close_attempts = [
            (7, mid_price * 0.95),      # Day 1: 5% below mid
            (6, mid_price * 0.90),      # Day 2: 10% below mid
            (5, mid_price * 0.85),      # Day 3: 15% below mid
            (4, "MARKET")                # Day 4: Market order
        ]

        for dte, price_strategy in close_attempts:
            if position.dte <= dte:
                if price_strategy == "MARKET":
                    return close_with_market_order(position)
                else:
                    return place_limit_order(position, price_strategy)
```

**Implementation Priority**: P0 - Essential for risk management

---

### 3. Slippage Risks
**Scenario**: Market orders at expiration result in poor fills

**Assessment**:
- **Likelihood**: COMMON (when using market orders)
- **Financial Impact**: LOW-MEDIUM (typically 0.02-0.05 per spread)
- **Detection**: Track fill price vs mid-price

**Mitigation Strategy**:
```python
# PRIORITY: P1 - IMPORTANT
class SlippageManager:
    MAX_SLIPPAGE_TOLERANCE = 0.10  # $10 per contract

    def smart_market_order(self, position):
        # Never use market orders in first/last 15 minutes
        if is_opening_15min() or is_closing_15min():
            return place_limit_order(position, aggressive=True)

        # Check spread width first
        spread_width = ask - bid
        if spread_width > MAX_SLIPPAGE_TOLERANCE:
            # Use limit order walk strategy
            return limit_order_walk(position)
        else:
            return place_market_order(position)
```

**Implementation Priority**: P1 - Impacts profitability

---

### 4. Assignment Risks
**Scenario**: Short options assigned early (American-style exercise)

**Assessment**:
- **Likelihood**: RARE (<1% for OTM options)
- **Financial Impact**: LOW (covered by long leg)
- **Detection**: Daily position reconciliation

**Mitigation Strategy**:
```python
# PRIORITY: P2 - NICE TO HAVE
class AssignmentMonitor:
    def daily_assignment_check(self):
        for position in get_open_positions():
            # Check for dividend risk (most common early assignment)
            if position.has_dividend_risk():
                if position.short_strike < stock_price - dividend:
                    alert("HIGH ASSIGNMENT RISK", position)
                    consider_closing(position)

            # Check for deep ITM shorts
            if position.short_delta > 0.90:
                alert("ITM ASSIGNMENT RISK", position)
```

**Implementation Priority**: P2 - Rare but worth monitoring

---

### 5. Orphaned Orders Risks
**Scenario**: Profit target orders remain active after manual position close

**Assessment**:
- **Likelihood**: OCCASIONAL (5-10%)
- **Financial Impact**: HIGH (could open new position)
- **Detection**: Order/position reconciliation

**Mitigation Strategy**:
```python
# PRIORITY: P0 - CRITICAL
class OrderReconciliation:
    def reconcile_orders_with_positions(self):
        """Run every 30 minutes during market hours"""
        active_orders = get_all_active_orders()
        open_positions = get_all_positions()

        for order in active_orders:
            if not has_matching_position(order, open_positions):
                logger.warning(f"ORPHANED ORDER: {order.id}")
                cancel_order(order)

    def on_position_close(self, position, close_method):
        """Hook into all position close events"""
        if close_method == "MANUAL":
            cancel_all_related_orders(position)
```

**Implementation Priority**: P0 - Prevents accidental position entry

---

### 6. Market Close Risks
**Scenario**: Positions approaching expiration after regular trading hours

**Assessment**:
- **Likelihood**: RARE (most liquid options trade until 4:15 PM)
- **Financial Impact**: HIGH (weekend gap risk)
- **Detection**: Check positions at 3:30 PM ET on expiration Friday

**Mitigation Strategy**:
```python
# PRIORITY: P1 - IMPORTANT
class ExpirationDayHandler:
    CLOSE_TIME_FRIDAY = "15:30"  # 3:30 PM ET

    def expiration_friday_check(self):
        if is_expiration_friday() and time_now() >= CLOSE_TIME_FRIDAY:
            expiring_positions = get_positions_expiring_today()

            for position in expiring_positions:
                if not position.is_closed:
                    # Force close with market order
                    emergency_close(position, reason="EXPIRATION_RISK")
```

**Implementation Priority**: P1 - Prevents weekend gap exposure

---

### 7. Gap Risks
**Scenario**: Weekend price gaps through strike prices

**Assessment**:
- **Likelihood**: OCCASIONAL (5-10% of weekends have significant gaps)
- **Financial Impact**: MEDIUM-HIGH
- **Detection**: Compare Friday close to Monday open

**Mitigation Strategy**:
```python
# PRIORITY: P1 - IMPORTANT
class WeekendRiskManager:
    def friday_afternoon_check(self):
        """Run at 3:00 PM ET on Fridays"""
        for position in get_open_positions():
            # Check if any strikes are within 2% of current price
            if position.has_strikes_near_money(threshold=0.02):
                if position.dte <= 7:
                    # Close or reduce position
                    reduce_position_size(position, reduction=0.50)
                    alert(f"WEEKEND GAP RISK: {position}")
```

**Implementation Priority**: P1 - Significant tail risk

---

### 8. Liquidity Risks
**Scenario**: Cannot exit position at reasonable price due to low liquidity

**Assessment**:
- **Likelihood**: OCCASIONAL (depends on underlying selection)
- **Financial Impact**: MEDIUM-HIGH
- **Detection**: Monitor bid-ask spreads and volume

**Mitigation Strategy**:
```python
# PRIORITY: P0 - CRITICAL (Prevention focused)
class LiquidityFilter:
    MIN_VOLUME = 100  # contracts per strike
    MAX_BID_ASK_SPREAD = 0.20  # 20 cents

    def validate_entry_liquidity(self, strikes):
        """Check BEFORE entering position"""
        for strike in strikes:
            volume = get_daily_volume(strike)
            spread = get_bid_ask_spread(strike)

            if volume < MIN_VOLUME or spread > MAX_BID_ASK_SPREAD:
                raise LiquidityException(f"Insufficient liquidity: {strike}")

        return True

    def handle_illiquid_exit(self, position):
        """When stuck in illiquid position"""
        # Option 1: Leg out over time
        # Option 2: Use combo orders
        # Option 3: Wait for expiration (if OTM)
```

**Implementation Priority**: P0 - Prevention is key

---

### 9. System Failure Risks
**Scenario**: AlertStreamer down, miss profit target fill notification

**Assessment**:
- **Likelihood**: RARE (1-2%)
- **Financial Impact**: MEDIUM (miss profit, hold to expiration)
- **Detection**: Heartbeat monitoring, redundant checks

**Mitigation Strategy**:
```python
# PRIORITY: P1 - IMPORTANT
class SystemMonitoring:
    def setup_redundant_monitoring(self):
        # Primary: WebSocket streaming
        primary_monitor = AlertStreamer()

        # Backup: Polling every 5 minutes
        backup_monitor = PositionPoller(interval=300)

        # Reconciliation: Compare both sources
        def reconcile():
            streaming_positions = primary_monitor.get_positions()
            polled_positions = backup_monitor.get_positions()

            if positions_differ(streaming_positions, polled_positions):
                alert("POSITION MISMATCH DETECTED")
                use_polled_data()  # Polling is source of truth

        schedule_task(reconcile, interval=300)
```

**Implementation Priority**: P1 - Critical for production

---

### 10. Race Condition Risks
**Scenario**: Multiple spreads filling simultaneously causing conflicting actions

**Assessment**:
- **Likelihood**: RARE (but increases with position count)
- **Financial Impact**: LOW-MEDIUM
- **Detection**: Transaction log analysis

**Mitigation Strategy**:
```python
# PRIORITY: P1 - IMPORTANT
class RaceConditionHandler:
    def __init__(self):
        self.position_locks = {}

    async def handle_fill_event(self, fill_event):
        position_id = fill_event.position_id

        # Acquire lock for this position
        async with self.acquire_lock(position_id):
            # Reload position state (fresh data)
            position = await get_position(position_id)

            # Check if action still needed
            if position.needs_adjustment():
                await adjust_position(position)

            # Update state atomically
            await update_position_state(position)

    def acquire_lock(self, position_id):
        if position_id not in self.position_locks:
            self.position_locks[position_id] = asyncio.Lock()
        return self.position_locks[position_id]
```

**Implementation Priority**: P1 - Prevents costly errors

---

## Implementation Roadmap

### Phase 1: Critical (P0) - Implement Immediately
1. **Partial Fill Handler** (1 day)
   - Delta monitoring
   - Automatic rebalancing logic

2. **DTE Close Handler** (1 day)
   - Escalating close attempts
   - Force close at 4 DTE

3. **Order Reconciliation** (0.5 day)
   - Orphaned order detection
   - Automatic cancellation

4. **Liquidity Filter** (0.5 day)
   - Pre-entry validation
   - Minimum volume/spread requirements

**Total: 3 days**

### Phase 2: Important (P1) - Implement Soon
1. **System Monitoring** (1 day)
   - Redundant position checking
   - Heartbeat monitoring

2. **Race Condition Handler** (1 day)
   - Position-level locking
   - Atomic state updates

3. **Weekend Risk Manager** (0.5 day)
   - Friday afternoon checks
   - Near-money position reduction

4. **Expiration Day Handler** (0.5 day)
   - 3:30 PM forced closes
   - Emergency exit procedures

5. **Slippage Manager** (0.5 day)
   - Smart order routing
   - Limit order walking

**Total: 3.5 days**

### Phase 3: Nice to Have (P2) - Future Enhancement
1. **Assignment Monitor** (0.5 day)
   - Dividend risk checking
   - Deep ITM monitoring

**Total: 0.5 days**

---

## Risk Metrics Dashboard

```python
class RiskMetricsDashboard:
    """Real-time risk monitoring"""

    def calculate_metrics(self):
        return {
            # Position Metrics
            "open_positions": count_open_positions(),
            "positions_near_money": count_near_money(threshold=0.02),
            "positions_approaching_expiry": count_dte_less_than(7),

            # Order Metrics
            "orphaned_orders": detect_orphaned_orders(),
            "pending_profit_targets": count_pending_targets(),

            # Risk Metrics
            "portfolio_delta": calculate_portfolio_delta(),
            "portfolio_gamma": calculate_portfolio_gamma(),
            "max_loss_today": calculate_max_loss(),

            # System Health
            "streamer_status": check_streamer_health(),
            "last_position_sync": get_last_sync_time(),
            "failed_orders_today": count_failed_orders(),

            # Liquidity Metrics
            "avg_bid_ask_spread": calculate_avg_spread(),
            "positions_illiquid": count_illiquid_positions()
        }
```

---

## R-Multiple Tracking

```python
class RMultipleTracker:
    """Track all trades in R-multiples for consistent risk management"""

    def __init__(self, risk_per_trade=100):  # 1R = $100
        self.risk_per_trade = risk_per_trade

    def calculate_r_multiple(self, trade):
        if trade.is_loss:
            return -abs(trade.pnl) / self.risk_per_trade
        else:
            return trade.pnl / self.risk_per_trade

    def calculate_expectancy(self, trades):
        r_multiples = [self.calculate_r_multiple(t) for t in trades]
        return sum(r_multiples) / len(r_multiples) if r_multiples else 0

    def position_size(self, account_value, risk_percent=0.01):
        """Calculate position size based on 1% risk"""
        risk_amount = account_value * risk_percent
        contracts = risk_amount / self.risk_per_trade
        return int(contracts)  # Round down for safety
```

---

## Critical Success Factors

1. **Automate P0 Items First**: These WILL cause losses if not handled
2. **Monitor Everything**: You can't manage what you don't measure
3. **Fail Safe, Not Optimally**: Better to close early than hold through expiration
4. **Test with Small Size**: Start with 1-contract positions
5. **Have Manual Override**: Always maintain ability to intervene

---

## Recommended Stop-Loss Rules

```python
STOP_LOSS_RULES = {
    "max_position_loss": 2.0,  # 2R max loss per position
    "daily_loss_limit": 3.0,    # 3R max daily loss
    "delta_threshold": 0.30,    # Close if position delta exceeds
    "dte_force_close": 4,        # Force close at 4 DTE
    "spread_width_max": 0.30,    # Don't trade if spread > 30 cents
}
```

---

## Conclusion

The highest priority risks are:
1. **Partial fills** (P0) - Will happen frequently
2. **DTE close failures** (P0) - Gamma risk is severe
3. **Orphaned orders** (P0) - Could open unwanted positions
4. **Liquidity filters** (P0) - Prevention is everything

Focus on these four areas first. They represent 80% of your real-world risk. The remaining scenarios, while important, are either rare or have lower financial impact.

Remember: In production trading, boring and reliable beats clever and complex every time.