# Technical Implementation Specification

**Version**: 1.0
**Date**: September 21, 2025
**Status**: Definitive Implementation Rules
**Purpose**: Engineer-ready specifications based on clarified requirements

---

## Strike Selection Algorithm (MANDATORY)

### Core Rules
```python
# PRIMARY RULE: Even strikes at the money
def calculate_base_strike(current_price):
    # Example: QQQ at 591 -> round(591/2)*2 = 592
    return round(float(current_price) / 2) * 2  # Closest even strike

# FALLBACK RULE: Higher strike for more credit
def select_strike_fallback(target_strike, available_strikes):
    higher_strikes = [s for s in available_strikes if s > target_strike]
    return min(higher_strikes) if higher_strikes else None

# NO TRADE RULE: Skip if no suitable strikes
if not selected_strike:
    return None  # Better no trade than wrong trade
```

### Senex Trident Structure (CRITICAL)
- **Put Spreads**: 2 IDENTICAL spreads (same strikes, quantity=2)
- **Call Spread**: 1 spread (quantity=1)
- **Example (3-point width)**:
  - QQQ at 591 -> Base strike 592
  - 2x Put spreads: Sell 592, Buy 589 (quantity=2)
  - 1x Call spread: Sell 592, Buy 595 (quantity=1)

### Spread Width Tiers (UPDATED)
```python
def get_spread_width(tradeable_capital: float) -> int:
    """
    Determine spread width based on tradeable capital (positions + buying power).
    UPDATED: Now uses tradeable capital instead of total account balance.
    """
    if tradeable_capital < 25000:
        return 3  # Under $25k: 3-point spreads
    elif tradeable_capital < 50000:
        return 5  # $25k-$50k: 5-point spreads
    elif tradeable_capital < 75000:
        return 7  # $50k-$75k: 7-point spreads
    else:
        return 9  # $75k+: 9-point spreads (max width)
```

### Overlap Prevention
- **Conflict Check**: Before creating new spread, verify no existing short/long strike conflicts
- **Example Conflict**: Existing 594/591 spread + proposed 592/589 spread = OK (no overlap)
- **Resolution**: Skip the conflicting trade entirely

---

## Market Analysis Implementation

### Bollinger Bands (Real-time)
```python
def calculate_bollinger_bands_realtime(symbol):
    # Get 19 historical daily closes
    historical_closes = get_daily_closes(symbol, days=19)

    # Get current intraday price
    current_price = get_current_quote(symbol).last

    # Combine for 20-period calculation
    prices = historical_closes + [current_price]

    # Standard 2 deviation bands
    mean = statistics.mean(prices)
    std_dev = statistics.stdev(prices)

    return {
        'upper': mean + (2 * std_dev),
        'middle': mean,
        'lower': mean - (2 * std_dev),
        'current': current_price
    }

def is_stressed_market(symbol):
    """Detect stressed market conditions (extensible for future indicators)."""
    bands = calculate_bollinger_bands_realtime(symbol)

    # Current implementation: Lower Bollinger Band only
    is_below_lower_band = bands['current'] <= bands['lower']

    # Future extensibility hooks
    # vix_level = get_vix_level()
    # is_high_vix = vix_level > 30
    # recent_volatility = calculate_recent_volatility(symbol)

    return is_below_lower_band  # Simple for now
```

### Update Schedule
- **Bollinger Bands**: Every 30 seconds during market hours
- **Include Current Price**: Always use latest intraday price as 20th data point

### Black-Scholes Implementation
```python
# Use existing library (NOT custom implementation)
from some_options_library import american_black_scholes

def get_risk_free_rate():
    # Priority order: TastyTrade -> Alpha Vantage -> Stooq -> Static
    try:
        return get_treasury_yield_api()  # 10-year Treasury
    except APIError:
        return settings.RISK_FREE_RATE_FALLBACK  # Static 4.5%

def calculate_greeks(option_data):
    risk_free_rate = get_risk_free_rate()
    return american_black_scholes(
        underlying_price=option_data.underlying_price,
        strike=option_data.strike,
        time_to_expiry=option_data.dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=option_data.iv
    )
```

---

## Order Execution Specifications

### Order Configuration
```python
ORDER_SETTINGS = {
    'order_type': 'LIMIT',  # NEVER market orders
    'time_in_force': 'DAY',  # Auto-cancel at market close
    'all_or_nothing': True,  # Prevent partial fills when possible
}

# Manual approval pricing (user sees real-time bid/ask)
def get_manual_limit_price(bid, ask, user_input=None):
    mid = (bid + ask) / 2
    return user_input if user_input else mid  # User can override

# Automated execution pricing (system adds buffer)
def get_auto_limit_price(bid, ask, auto_offset_cents=0):
    mid = (bid + ask) / 2
    return mid + Decimal(str(auto_offset_cents / 100))  # e.g., 5 cents = 0.05
```

### Profit Target Orders (CRITICAL)
```python
# Senex Trident profit targets - SEPARATE orders for each spread
def create_profit_target_orders(position):
    targets = [
        {'spread': 'put_1', 'target_percent': 40},  # Close first put at 40%
        {'spread': 'put_2', 'target_percent': 60},  # Close second put at 60%
        {'spread': 'call', 'target_percent': 50},   # Close call at 50%
    ]

    for target in targets:
        create_gtc_closing_order(
            position=position,
            spread_id=target['spread'],
            limit_price=calculate_target_price(
                entry_credit=position.credit,
                target_percent=target['target_percent']
            )
        )
```

### Retry Logic
```python
async def execute_order_with_retry(order):
    delays = [1, 2, 4, 8, 16]  # Exponential backoff in seconds

    for attempt, delay in enumerate(delays):
        try:
            result = await submit_order(order)
            return result
        except (APIError, TimeoutError) as e:
            if attempt == len(delays) - 1:  # Last attempt
                raise OrderExecutionFailedError(f"Failed after {len(delays)} attempts")

            await asyncio.sleep(delay)

    # Fail immediately if TastyTrade API is down
    raise APIUnavailableError("TastyTrade API unavailable")
```

### Partial Fill Handling
```python
async def handle_partial_fill(order, fill_data):
    position = order.position

    # 1. Mark position as needs attention
    position.needs_attention = True
    position.is_app_managed = False
    position.save()

    # 2. Send notifications (all three)
    await send_email_alert(position.user, f"Partial fill: {position.symbol}")
    await send_ui_notification(position.user, "partial_fill", position.id)
    await update_dashboard_flag(position.user, "needs_attention")

    # 3. NO leg-in attempts - user must handle manually
    # Future: Add "leg into position" button in UI

    # 4. Log the event
    TradingLog.objects.create(
        user=position.user,
        operation="partial_fill_detected",
        status="needs_attention",
        position=position,
        request_data=fill_data
    )
```

---

## User Settings vs System Control

### User-Controlled Settings
```python
USER_SETTINGS = {
    'risk_tolerance': 'template',  # 3 template options (research reference app)
    'auto_execute': False,          # Toggle on/off
    'underlying_symbols': ['QQQ', 'SPY'],  # Limited to high-volume ETFs
    'email_notifications': {
        'fills': True,
        'partial_fills': True,
        'profit_targets': True,
        'needs_attention': True,
    },
    'limit_price_override': None,  # User can adjust in review modal
}
```

### System-Controlled (No User Override)
```python
SYSTEM_CONTROLLED = {
    'strike_selection': 'round(price/2)*2',  # Even strike algorithm
    'spread_width': 'auto_calculate',        # Based on account size
    'target_dte': 45,                        # Fixed target
    'profit_targets': [40, 60, 50],         # Fixed percentages
    'dte_closure': 7,                        # Auto-close at 7 DTE
    'order_retry': 'exponential_backoff',   # System managed
    'stressed_market': 'bollinger_bands',   # System detected
    'position_limit': 30,                    # Natural limit from DTE
}
```

---

## WebSocket Data Flow

### Update Frequencies
```python
UPDATE_FREQUENCIES = {
    'high_priority': 1,     # Trading decisions (real-time quotes)
    'medium_priority': 10,  # Position monitoring (P&L updates)
    'low_priority': 30,     # Dashboard display (account balances)
}

# Context-based frequency selection
def get_update_frequency(context):
    if context == 'trading_decision':
        return UPDATE_FREQUENCIES['high_priority']  # Real-time
    elif context == 'position_monitoring':
        return UPDATE_FREQUENCIES['medium_priority']  # 10 seconds
    else:
        return UPDATE_FREQUENCIES['low_priority']  # 30 seconds

# Batched database writes
async def batch_position_updates():
    while True:
        await asyncio.sleep(10)  # Batch every 10 seconds

        if position_updates_cache:
            async with database_transaction():
                for position_id, data in position_updates_cache.items():
                    await Position.objects.filter(id=position_id).aupdate(**data)

            position_updates_cache.clear()
```

### UI Update Throttling
```javascript
// Prevent UI flicker with update throttling
const updateThrottler = {
    high: throttle(updateTradingData, 1000),    // 1 second
    medium: throttle(updatePositions, 10000),   // 10 seconds
    low: throttle(updateBalances, 30000)        // 30 seconds
};

function throttle(func, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
}
```

---

## Risk Management Implementation

### Stressed Market Detection
```python
def calculate_risk_tolerance(market_condition, user_base_tolerance):
    if market_condition == 'stressed':
        # MORE aggressive when volatility high (capture premium)
        return min(user_base_tolerance * 1.5, 0.60)  # Cap at 60%
    else:
        return user_base_tolerance  # Normal: 40% default

def is_stressed_market(symbol):
    """Detect stressed market conditions (extensible for future indicators)."""
    bands = calculate_bollinger_bands_realtime(symbol)

    # Current implementation: Lower Bollinger Band only
    is_below_lower_band = bands['current'] <= bands['lower']

    # Future extensibility hooks
    # vix_level = get_vix_level()
    # is_high_vix = vix_level > 30
    # recent_volatility = calculate_recent_volatility(symbol)

    return is_below_lower_band  # Simple for now
```

### Continuous Risk Calculation
```python
async def update_risk_budget_realtime(user):
    # Account stream provides real-time balance updates
    account_data = await get_account_stream_data(user)

    # Calculate immediately when account changes
    tradeable_capital = (
        account_data['buying_power'] +
        get_app_managed_position_risk(user)
    )

    market_condition = detect_market_condition()
    risk_tolerance = calculate_risk_tolerance(market_condition, user.risk_tolerance)

    available_risk = tradeable_capital * risk_tolerance

    # Update user's risk state
    await update_user_risk_state(user, {
        'available_risk': available_risk,
        'used_risk': get_current_risk_usage(user),
        'market_condition': market_condition
    })
```

---

## Data Consistency Rules

### Source of Truth Hierarchy
```python
DATA_SOURCE_PRIORITY = {
    'positions': 'tastytrade_api',     # Definitive source
    'account_data': 'tastytrade_api',  # Real-time via account stream
    'quotes': 'tastytrade_dxfeed',     # WebSocket streaming
    'local_database': 'cache_only'     # Never authoritative
}

async def sync_position_from_api(position_id):
    """Sync local position with TastyTrade API data."""
    api_position = await tastytrade_api.get_position(position_id)

    if not api_position:
        # Position closed externally
        local_position = await Position.objects.aget(id=position_id)
        local_position.is_active = False
        local_position.needs_attention = True
        await local_position.asave()

        await notify_user_position_closed_externally(local_position.user)
```

### Manual Override Prevention
```python
# NO manual position updates allowed
class PositionUpdatePolicy:
    @staticmethod
    def validate_update_source(update_request):
        if update_request.source != 'tastytrade_api':
            raise ValidationError("Manual position updates not allowed")

        if update_request.type == 'user_manual':
            raise ValidationError("All updates must come from API")
```

---

## Background Task Specifications

### Celery Usage Guidelines
```python
# ALLOWED in Celery
@shared_task
def daily_dte_update():
    """Short, discrete task - ALLOWED."""
    pass

@shared_task
def generate_trading_suggestions():
    """Scheduled task - ALLOWED."""
    pass

# FORBIDDEN in Celery
def streaming_quotes_processor():
    """Long-running WebSocket connection - FORBIDDEN."""
    # Use Django Channels instead
    pass
```

### Daily Tasks
```python
@shared_task
def daily_position_maintenance():
    """Run daily at market close."""
    # Update DTE
    Position.objects.filter(is_active=True).update(
        current_dte=F('current_dte') - 1
    )

    # Check for positions requiring closure (7 DTE rule)
    positions_to_close = Position.objects.filter(
        is_active=True,
        current_dte__lte=7
    )

    for position in positions_to_close:
        await submit_closing_order(position)
```

---

## Error Recovery Specifications

### API Failure Handling
```python
async def handle_api_failure(api_call, *args, **kwargs):
    """Immediate failure for API outages - no queuing."""
    try:
        return await api_call(*args, **kwargs)
    except APIUnavailableError:
        # Fail immediately - real data or fail
        raise TradingSystemUnavailableError(
            "TastyTrade API unavailable. Trading suspended."
        )
    except (AuthenticationError, TokenExpiredError):
        # Retry auth errors with exponential backoff
        return await retry_with_backoff(api_call, *args, **kwargs)

async def retry_with_backoff(func, *args, **kwargs):
    delays = [1, 2, 4, 8, 16]  # 5 retries max

    for delay in delays:
        try:
            await refresh_oauth_session()
            return await func(*args, **kwargs)
        except AuthenticationError:
            await asyncio.sleep(delay)

    raise AuthenticationFailedError("Cannot authenticate after 5 retries")
```

---

## UI/UX Implementation Rules

### Trade Approval Workflow
```python
class TradingSuggestionWorkflow:
    ALLOWED_ACTIONS = ['approve', 'reject']  # NO modifications
    EXPIRY_HOURS = 24  # Auto-delete after 24 hours

    def process_approval(self, suggestion, action, user):
        if action not in self.ALLOWED_ACTIONS:
            raise ValidationError("Only approve/reject allowed")

        if action == 'approve':
            # Show review modal with real-time bid/ask
            # User sees mid price, can adjust if desired
            return self.show_review_modal_then_execute(suggestion)
        else:
            suggestion.status = 'REJECTED'
            suggestion.save()

    def cleanup_expired_suggestions(self):
        """Auto-delete suggestions older than 24 hours."""
        cutoff = timezone.now() - timedelta(hours=self.EXPIRY_HOURS)
        TradingSuggestion.objects.filter(
            created_at__lt=cutoff,
            status='pending'
        ).delete()  # Auto-delete, not archive

def handle_market_condition_change(suggestion):
    """No action needed - let market decide."""
    # If market changes between suggestion and approval:
    # - Order either fills immediately (good)
    # - Order doesn't fill (user notices)
    # - No intervention required
    pass
```

### Notification System
```python
NOTIFICATION_LEVELS = {
    'partial_fill': ['email', 'ui_banner', 'dashboard_flag'],
    'position_closed_externally': ['email', 'ui_banner'],
    'api_error': ['ui_banner', 'dashboard_flag'],
    'order_failed': ['email', 'ui_banner', 'dashboard_flag']
}

async def send_notification(user, event_type, data):
    levels = NOTIFICATION_LEVELS.get(event_type, ['ui_banner'])

    for level in levels:
        if level == 'email':
            await send_email_notification(user, event_type, data)
        elif level == 'ui_banner':
            await send_websocket_notification(user, event_type, data)
        elif level == 'dashboard_flag':
            await set_dashboard_flag(user, event_type, data)
```

---

## Testing Requirements

### Integration Test Scenarios
```python
class TechnicalImplementationTests:
    def test_strike_selection_no_overlap(self):
        """Verify strike selection prevents overlapping positions."""
        pass

    def test_bollinger_bands_realtime(self):
        """Verify current price inclusion in Bollinger calculations."""
        pass

    def test_limit_order_only(self):
        """Verify no market orders are ever created."""
        pass

    def test_partial_fill_handling(self):
        """Verify partial fill notification and status changes."""
        pass

    def test_api_failure_immediate_fail(self):
        """Verify immediate failure when TastyTrade API down."""
        pass

    def test_data_source_truth_hierarchy(self):
        """Verify TastyTrade API overrides local data."""
        pass
```

---

This specification provides engineer-ready implementation details based on all clarified requirements. Every rule has been tested through the clarification process and represents the definitive technical requirements for Senex Trader implementation.