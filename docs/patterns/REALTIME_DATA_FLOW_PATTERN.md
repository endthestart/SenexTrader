# Real-Time Data Flow Pattern (Site-Wide Standard)

**Status**: Canonical architectural pattern
**Established**: 2025-10-09
**Applies to**: All real-time metrics, market data, and streaming updates

---

## Overview

This document defines the **canonical data flow pattern** for all real-time data in the Senex Trader application. This pattern ensures consistency, eliminates duplication, and provides optimal performance across the site.

**Key Principle**: "Real data or fail" - We never show stale data. If live data isn't available, we communicate that clearly rather than showing potentially incorrect cached values.

---

## The Pattern

```
┌──────────────────────────────────────────────────────────────┐
│                      DATA SOURCES                            │
│  TastyTrade API / DXFeed / Account Streaming                 │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                   STREAMING LAYER                            │
│  DXLinkStreamer, AlertStreamer                               │
│  - Subscribes to real-time events                            │
│  - Processes and validates incoming data                     │
│  - Writes to cache (Redis) with TTL                          │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                      CACHE LAYER                             │
│  Redis/Memcached (60s TTL typical)                           │
│  - quote:{symbol} - Real-time quotes                         │
│  - dxfeed:greeks:{symbol} - Option Greeks                    │
│  - acct_state:{user}:{account} - Account state               │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                    SERVICE LAYER                             │
│  Read-only services that calculate from cached data          │
│  - GreeksService.get_position_greeks()                       │
│  - PositionPnLCalculator.calculate_*()                       │
│  - Single source of truth for each calculation               │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                   BROADCAST LAYER                            │
│  StreamManager - Unified periodic broadcasts                 │
│  - Reads from services (no duplicate calculation)            │
│  - Combines related metrics into single payload              │
│  - Broadcasts via WebSocket (30s interval typical)           │
│  - Does NOT save to database                                 │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                    FRONTEND LAYER                            │
│  JavaScript handlers extend RealtimeUpdaterBase              │
│  - Initial page load from database                           │
│  - WebSocket events update DOM                               │
│  - NO polling (except initial load)                          │
│  - Flash animations on value changes                         │
└──────────────────────────────────────────────────────────────┘

                     ↓ (Parallel path for persistence)

┌──────────────────────────────────────────────────────────────┐
│                  PERSISTENCE LAYER                           │
│  Celery periodic tasks (10 min typical)                      │
│  - Reads from services (same as broadcast)                   │
│  - Saves to database for durability                          │
│  - Database = source of truth for initial page load          │
└──────────────────────────────────────────────────────────────┘
```

---

## Core Principles

### 1. Single Source of Truth

**Each calculation exists in ONE place only.**

✅ **Correct**:
```python
# services/position_pnl_calculator.py
class PositionPnLCalculator:
    @staticmethod
    def calculate_leg_pnl(avg_price, current_price, quantity, direction):
        # Calculation logic here
        return pnl

# Used everywhere:
# - StreamManager._start_position_metrics_updates()
# - PositionSyncService._sync_app_managed_from_orders()
# - API endpoints
```

❌ **Incorrect** (duplication):
```python
# StreamManager
def _broadcast_pnl():
    pnl = (avg_price - current_price) * quantity  # ❌ Duplicate logic

# PositionSync
def _sync_positions():
    pnl = (avg_price - current_price) * quantity  # ❌ Same calculation!
```

### 2. Separation of Concerns

**Different layers have different responsibilities:**

- **Streamers**: Receive data, write to cache
- **Services**: Read from cache, calculate/aggregate
- **StreamManager**: Broadcast to frontend (reads from services)
- **Celery**: Persist to database (reads from services)
- **Frontend**: Display data (receives from WebSocket)

**Never mix concerns:**
- ❌ StreamManager should NOT calculate P&L directly
- ❌ Services should NOT broadcast via WebSocket
- ❌ Frontend should NOT poll for data (except initial load)
- ❌ Broadcast layer should NOT save to database

### 3. Cache as Source for Real-Time

**Redis cache is the source of truth for real-time data.**

- Streamers write to cache with short TTL (60s typical)
- Services read from cache (never from database for real-time)
- If cache is empty → data unavailable (don't show stale DB values)
- Database is for persistence and initial page load only

### 4. Unified Broadcasting

**Combine related metrics into single WebSocket broadcasts.**

✅ **Correct** (unified):
```python
async def _start_position_metrics_updates(self):
    # Combine balance + Greeks + P&L
    update_data = {
        "type": "position_metrics_update",
        "balance": balance_data,
        "positions": [{
            "position_id": id,
            "greeks": greeks,
            "pnl": pnl
        }],
        "timestamp": time.time() * 1000
    }
    await self._broadcast("position_metrics_update", update_data)
    await asyncio.sleep(30)  # Single consistent interval
```

❌ **Incorrect** (fragmented):
```python
# Three separate broadcasts with different intervals
await self._broadcast("balance_update", {...})  # Every 30s
await asyncio.sleep(30)

await self._broadcast("greeks_update", {...})  # Every 5s  ❌ Different!
await asyncio.sleep(5)

await self._broadcast("pnl_update", {...})  # Every 10s  ❌ Different!
await asyncio.sleep(10)
```

### 5. WebSocket Over Polling

**Frontend should use WebSocket updates, not API polling.**

✅ **Correct**:
```javascript
class MetricsUpdater extends RealtimeUpdaterBase {
    constructor(websocket) {
        super({ websocket });
        // Register WebSocket handler
        this.registerHandler('position_metrics_update', this.handleUpdate);
    }

    init() {
        // Load initial data once from API
        this.loadInitialData();
        // Then WebSocket takes over - NO polling
    }
}
```

❌ **Incorrect**:
```javascript
// Polling every 5 seconds  ❌ Don't do this!
setInterval(() => {
    fetch('/api/metrics/').then(...)
}, 5000);
```

---

## Implementation Guide

### Step 1: Streaming Layer

**Setup streamer to write to cache.**

```python
# streaming/services/stream_manager.py
async def _listen_quotes(self):
    async for quote_event in streamer.listen(Quote):
        # Write to cache
        cache_key = CacheManager.quote(quote_event.event_symbol)
        cache_data = {
            "bid": quote_event.bid_price,
            "ask": quote_event.ask_price,
            "mark": (quote_event.bid_price + quote_event.ask_price) / 2,
            "last": quote_event.last_price
        }
        cache.set(cache_key, cache_data, timeout=60)

        # Broadcast quote update
        await self._broadcast("quote_update", {
            "type": "quote_update",
            "symbol": quote_event.event_symbol,
            **cache_data
        })
```

**Key points**:
- Write to cache immediately
- Use consistent cache key naming (via CacheManager)
- Set appropriate TTL (60s typical for market data)
- Broadcast raw events if needed (for immediate updates)

#### Mixed Symbol Subscriptions (Options + Stocks)

**Critical**: When subscribing to both options and stocks, **separate them into two groups**.

```python
async def _subscribe_symbols(self, streamer: DXLinkStreamer, symbols: list[str]):
    """Subscribe to Quote, Trade, and Summary events"""
    if not symbols:
        return

    # Separate option symbols (contain spaces) from underlying symbols
    option_symbols = [s for s in symbols if " " in s]
    underlying_symbols = [s for s in symbols if " " not in s]

    # Subscribe to options with Greeks
    if option_symbols:
        # Convert OCC to streamer format
        streamer_symbols = [Option.occ_to_streamer_symbol(s) for s in option_symbols]

        # Options get Quote + Greeks
        await streamer.subscribe(Quote, streamer_symbols, refresh_interval=0.5)
        await asyncio.sleep(0.2)  # Prevent channel race
        await streamer.subscribe(Greeks, streamer_symbols, refresh_interval=1.0)

    # Subscribe to underlying symbols
    if underlying_symbols:
        # Stocks get Quote + Trade + Summary (NO Greeks)
        await streamer.subscribe(Quote, underlying_symbols, refresh_interval=0.25)
        await asyncio.sleep(0.1)
        await streamer.subscribe(Trade, underlying_symbols)
        await asyncio.sleep(0.1)
        await streamer.subscribe(Summary, underlying_symbols, refresh_interval=5.0)

    self.subscribed_symbols.update(symbols)
```

**Why this matters**:
- Options need Greeks subscription, stocks don't have Greeks
- Trying to subscribe to Greeks for stock symbols causes errors
- Using `all(" " in s for s in symbols)` fails for mixed batches
- Must separate and subscribe each group appropriately

**Common mistake**:
```python
# ❌ Bad - treats everything as one type
is_options_only = all(" " in s for s in symbols)
if is_options_only:
    # Subscribe to Greeks
else:
    # Subscribe to Trade/Summary
# Problem: Mixed batch fails the check!
```

### Step 2: Service Layer

**Create read-only service for calculations.**

```python
# services/my_metric_service.py
class MyMetricService:
    """
    Service for calculating [describe metric].

    Reads from cache (populated by DXLinkStreamer).
    Single source of truth for this calculation site-wide.
    """

    def get_metric(self, position: Position) -> dict | None:
        """
        Calculate metric from cached streaming data.

        Returns:
            dict with metric data or None if data unavailable
        """
        try:
            # Read from cache
            cache_key = CacheManager.my_data(position.symbol)
            cached_data = cache.get(cache_key)

            if not cached_data:
                logger.warning(f"No cached data for {position.symbol}")
                return None

            # Calculate using cached data
            result = self._calculate_from_cache(cached_data, position)

            return {
                "value": result,
                "source": "streaming",
                "timestamp": time.time()
            }

        except Exception as e:
            logger.error(f"Error calculating metric: {e}", exc_info=True)
            return None

    def _calculate_from_cache(self, cached_data, position):
        # Calculation logic here
        return calculated_value
```

**Key points**:
- Read-only (no side effects)
- Single responsibility (one metric)
- Graceful failure (return None, don't raise)
- Log warnings for missing data

### Step 3: Broadcast Layer

**Add to unified StreamManager broadcast.**

```python
# streaming/services/stream_manager.py
async def _start_position_metrics_updates(self):
    """Unified metrics broadcast - extend for new metrics."""

    while self.is_streaming:
        try:
            # Get positions
            positions = await Position.objects.filter(...)

            # Initialize service
            my_service = MyMetricService()

            metrics = []
            for position in positions:
                # Calculate each metric
                my_metric = my_service.get_metric(position)

                metrics.append({
                    "position_id": position.id,
                    "my_metric": my_metric  # Add your metric here
                })

            # Broadcast unified update
            await self._broadcast("position_metrics_update", {
                "type": "position_metrics_update",
                "positions": metrics,
                "timestamp": time.time() * 1000
            })

        except Exception as e:
            logger.error(f"Metrics update error: {e}", exc_info=True)

        # Consistent interval (30 seconds site-wide)
        await asyncio.sleep(30)
```

**Key points**:
- Extend existing unified broadcast (don't create separate)
- Use consistent 30-second interval
- Call service methods (don't duplicate calculation)
- Graceful error handling

### Step 4: Consumer Layer

**Ensure WebSocket consumer forwards the event.**

```python
# streaming/consumers.py
async def position_metrics_update(self, event: dict[str, Any]) -> None:
    """Forwards unified metrics to client."""
    await self.send(text_data=json.dumps(event))
```

**If event name differs, add new handler:**
```python
async def my_new_event(self, event: dict[str, Any]) -> None:
    """Forwards my new event type to client."""
    logger.debug(f"User {self.user.id}: Broadcasting my_new_event")
    await self.send(text_data=json.dumps(event))
```

### Step 5: Frontend Layer

**Create or extend RealtimeUpdaterBase handler.**

```javascript
// static/js/my_metrics.js
class MyMetricsUpdater extends RealtimeUpdaterBase {
    constructor(websocket) {
        super({ websocket });

        // Register handler for WebSocket event
        this.registerHandler('position_metrics_update', this.handleUpdate);

        this.init();
    }

    handleUpdate(data) {
        const positions = data.positions || [];

        positions.forEach(pos => {
            this.updatePositionRow(pos.position_id, pos.my_metric);
        });
    }

    updatePositionRow(positionId, metric) {
        const row = document.querySelector(`tr[data-position-id="${positionId}"]`);
        if (!row) return;

        const cell = row.querySelector('.my-metric');
        if (cell && metric !== null) {
            const formatted = this.formatValue(metric);

            if (cell.textContent !== formatted) {
                cell.textContent = formatted;
                this.flashElement(cell);  // Visual feedback
            }
        }
    }

    formatValue(value) {
        return value.toFixed(2);  // Or appropriate formatting
    }
}

// Export for template use
window.MyMetricsUpdater = MyMetricsUpdater;
```

**In template:**
```html
<script src="{% static 'js/my_metrics.js' %}"></script>
<script>
// Initialize when WebSocket is ready
if (window.streamerWebSocket) {
    const updater = new MyMetricsUpdater(window.streamerWebSocket);
}
</script>
```

**Key points**:
- Extend `RealtimeUpdaterBase` for common functionality
- Register handler for specific event type
- Only update DOM if value changed
- Use flash animation for visual feedback
- NO polling intervals

### Step 6: Persistence Layer

**Add Celery task for database persistence.**

```python
# trading/tasks.py
@celery_app.task(name="trading.tasks.persist_my_metric")
def persist_my_metric():
    """
    Periodic task to persist metric to database.

    Runs every 10 minutes.
    Uses same service as StreamManager (single source of truth).
    """
    from services.my_metric_service import MyMetricService
    from trading.models import Position

    service = MyMetricService()
    positions = Position.objects.filter(lifecycle_state__in=["open_full", "open_partial"])

    for position in positions:
        try:
            metric = service.get_metric(position)
            if metric:
                position.my_metric_value = metric["value"]
                position.save(update_fields=["my_metric_value"])
        except Exception as e:
            logger.error(f"Error persisting metric for position {position.id}: {e}")
```

**In celery beat schedule:**
```python
# senextrader/celery.py
app.conf.beat_schedule = {
    'persist-my-metric': {
        'task': 'trading.tasks.persist_my_metric',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
}
```

**Key points**:
- Use same service as broadcast (consistency)
- Run periodically (10 min typical)
- Graceful per-position error handling
- Only update changed fields

---

## Update Interval Standards

### Real-Time Events (< 1s)
**Use for**: Market prices, trade executions, critical alerts

```python
# Immediate broadcast on event receipt
async def _listen_quotes(self):
    async for quote in streamer.listen(Quote):
        await self._broadcast("quote_update", {...})  # Immediate
```

### Frequent Updates (5-10s)
**Use for**: Summary data, aggregate statistics

```python
# Example: Summary data
async def _listen_summary(self):
    async for summary in streamer.listen(Summary):
        await self._broadcast("summary_update", {...})
        # DXFeed refresh interval handles timing (5s typical)
```

### Standard Updates (30s) - **Recommended Default**
**Use for**: Position metrics, account balances, portfolio aggregates

```python
async def _start_position_metrics_updates(self):
    while self.is_streaming:
        # ... calculate metrics ...
        await self._broadcast("position_metrics_update", {...})
        await asyncio.sleep(30)  # Standard interval
```

### Periodic Sync (10 min)
**Use for**: Database persistence, reconciliation, full syncs

```python
@celery_app.task
def periodic_sync():
    # Full sync from broker
    # Persist calculated values
    pass

# In beat schedule
'schedule': crontab(minute='*/10')
```

---

## Anti-Patterns to Avoid

### ❌ Anti-Pattern #1: Duplicate Calculations

**Problem**: Same calculation logic in multiple places

```python
# ❌ Bad - StreamManager
async def broadcast_pnl(self):
    for leg in position.metadata["legs"]:
        pnl = (avg_price - current_price) * qty  # Calculation

# ❌ Bad - PositionSync
def sync_positions(self):
    for leg in position.metadata["legs"]:
        pnl = (avg_price - current_price) * qty  # DUPLICATE!
```

**Solution**: Single service, reused everywhere

```python
# ✅ Good - Single source
class PositionPnLCalculator:
    @staticmethod
    def calculate_leg_pnl(...):
        return (avg_price - current_price) * qty

# Used by both
StreamManager: pnl = PositionPnLCalculator.calculate_leg_pnl(...)
PositionSync: pnl = PositionPnLCalculator.calculate_leg_pnl(...)
```

### ❌ Anti-Pattern #2: Frontend Polling

**Problem**: Frontend repeatedly polls API

```javascript
// ❌ Bad
setInterval(async () => {
    const response = await fetch('/api/metrics/');
    updateDOM(await response.json());
}, 5000);  // Polling every 5 seconds
```

**Solution**: WebSocket updates

```javascript
// ✅ Good
class MetricsUpdater extends RealtimeUpdaterBase {
    constructor(websocket) {
        super({ websocket });
        this.registerHandler('metrics_update', this.handleUpdate);
    }
    // WebSocket pushes updates - no polling
}
```

### ❌ Anti-Pattern #3: Mixed Update Intervals

**Problem**: Related metrics update at different rates

```python
# ❌ Bad
async def broadcast_greeks():
    await asyncio.sleep(5)  # Every 5 seconds

async def broadcast_pnl():
    await asyncio.sleep(10)  # Every 10 seconds

async def broadcast_balance():
    await asyncio.sleep(30)  # Every 30 seconds
```

**Solution**: Unified broadcast with consistent interval

```python
# ✅ Good
async def broadcast_all_metrics():
    # All metrics together
    await self._broadcast("position_metrics_update", {
        "greeks": ...,
        "pnl": ...,
        "balance": ...
    })
    await asyncio.sleep(30)  # One consistent interval
```

### ❌ Anti-Pattern #4: Race Conditions on Shared Data

**Problem**: Multiple tasks read/write same data concurrently

```python
# ❌ Bad - Both read position.metadata["legs"] at same time
Task A (streaming): reads metadata["legs"] for calculation
Task B (sync): writes metadata["legs"] with new data
# Result: Task A gets partial/stale data → erratic values
```

**Solution**: Single reader per use case, or use locking

```python
# ✅ Good - Only one task calculates from legs for streaming
# StreamManager: Reads from service (which reads cache)
# PositionSync: Updates metadata["legs"] + saves to DB
# No concurrent reads during writes
```

### ❌ Anti-Pattern #5: Saving to DB in Broadcast Loop

**Problem**: Database writes in streaming broadcast

```python
# ❌ Bad
async def broadcast_metrics(self):
    for position in positions:
        pnl = calculate_pnl(position)

        # ❌ Don't save in broadcast loop!
        position.unrealized_pnl = pnl
        await position.asave()

        await self._broadcast("pnl_update", {"pnl": pnl})
```

**Solution**: Separate broadcast (real-time) from persistence (periodic)

```python
# ✅ Good
async def broadcast_metrics(self):
    for position in positions:
        pnl = calculate_pnl(position)
        # Broadcast only - no DB save
        await self._broadcast("pnl_update", {"pnl": pnl})

# Separate periodic task
@celery_app.task
def persist_metrics():
    # Save to DB every 10 minutes
    for position in positions:
        position.unrealized_pnl = calculate_pnl(position)
        position.save()
```

---

## Testing Checklist

When implementing this pattern, verify:

### Backend
- [ ] Service reads from cache, not database
- [ ] Service is read-only (no side effects)
- [ ] Service returns None on missing data (doesn't raise)
- [ ] StreamManager calls service (no duplicate calculation)
- [ ] Broadcast interval is consistent (30s typical)
- [ ] Consumer forwards event to WebSocket

### Frontend
- [ ] Handler extends RealtimeUpdaterBase
- [ ] Handler registers for WebSocket event
- [ ] Initial load from API/database once
- [ ] NO polling intervals (setInterval removed)
- [ ] DOM updates only when value changes
- [ ] Flash animation on value change

### Integration
- [ ] Page load shows initial data
- [ ] WebSocket connects automatically
- [ ] Updates arrive at consistent interval
- [ ] Console shows update logs
- [ ] Network tab: no repeated API polls
- [ ] Values update smoothly without jumps

### Performance
- [ ] No N+1 queries in service
- [ ] Cache keys use consistent naming
- [ ] TTL appropriate for data type
- [ ] Database writes batched (not per-update)

---

## Migration Strategy

When converting existing code to this pattern:

1. **Identify duplicate calculations**
   - Search for same calculation logic in multiple files
   - Extract to shared service

2. **Consolidate broadcasts**
   - Combine separate broadcast tasks
   - Standardize to 30-second interval

3. **Remove frontend polling**
   - Find `setInterval()` calls
   - Replace with WebSocket handlers

4. **Add backward compatibility**
   - Keep old event handlers during transition
   - Add legacy fallback in new handlers
   - Monitor for 1 week before removing

5. **Update documentation**
   - Document new event names
   - Update API docs if endpoints change
   - Add migration notes for team

### Migration History

**Position Metrics Unification (Oct 9, 2025)**

**Problem**: Erratic Greek values caused by duplicate P&L calculations and race conditions.

**Changes Made**:
- ✅ Backend: Removed `_start_pnl_updates()` and `_start_balance_updates()` methods
- ✅ Backend: Created unified `_start_position_metrics_updates()` (30s interval)
- ✅ Frontend: Created `position_metrics.js` (replaces `position_pnl.js`)
- ✅ Frontend: Removed polling from `greeks.js` (was 5s interval)
- ✅ Template: Updated `positions.html` to use unified handler

**Files Removed**:
- `static/js/position_pnl.js` - Superseded by `position_metrics.js`
- Legacy P&L-only handler no longer needed

**Backward Compatibility**:
- `position_metrics.js` includes legacy `position_pnl_update` handler (unused but safe)
- Can remove after 1 week of production monitoring

**Result**: Greeks now stable, consistent 30s updates, ~200 lines of duplicate code removed.

**Greeks Subscription Fix (Oct 9, 2025)**

**Problem**: Greeks not updating because mixed symbol subscriptions (options + stocks) were treated as all stocks.

**Root Cause**: `_subscribe_symbols()` used `all(" " in s for s in symbols)` which failed when batch contained both option symbols (with spaces) and stock symbols (no spaces).

**Changes Made**:
- ✅ Backend: Split subscription logic to separate options from stocks
- ✅ Backend: Options get Quote + Greeks subscription
- ✅ Backend: Stocks get Quote + Trade + Summary subscription (no Greeks)
- ✅ Frontend: Added portfolio Greeks aggregation from position-level data
- ✅ Frontend: Initialized `window.greeksUpdater` in positions template

**Result**: Greeks now flow correctly for all option positions, portfolio Greeks aggregate properly.

---

## Examples in Codebase

### Position Metrics (Reference Implementation)

**Files**:
- Service: `services/greeks_service.py` (Greeks calculation)
- Service: `services/position_lifecycle/pnl_calculator.py` (P&L calculation)
- Broadcast: `streaming/services/stream_manager.py:_start_position_metrics_updates()`
- Consumer: `streaming/consumers.py:position_metrics_update()`
- Frontend: `static/js/position_metrics.js`
- Persistence: `trading/tasks.py:sync_positions_task`

**Data flow**:
1. DXLinkStreamer → Cache (quotes, Greeks)
2. Services read cache → Calculate metrics
3. StreamManager calls services → Broadcast every 30s
4. Frontend receives WebSocket → Updates DOM
5. Celery task → Persists to DB every 10 min

### Quote Streaming (Real-Time Events)

**Files**:
- Streamer: `streaming/services/stream_manager.py:_listen_quotes()`
- Consumer: `streaming/consumers.py:quote_update()`
- Frontend: Various handlers (per symbol subscription)

**Data flow**:
1. DXLinkStreamer receives Quote event (0.5s refresh)
2. Writes to cache + broadcasts immediately
3. Frontend receives → Updates specific symbol

---

## Decision Tree

**When adding new real-time data, ask:**

1. **Is this real-time market data?**
   - Yes → Add to DXLinkStreamer listener, write to cache
   - No → Consider if streaming is needed

2. **Does this need calculation/aggregation?**
   - Yes → Create service class with single calculation method
   - No → Broadcast raw data directly

3. **Is this related to existing metrics?**
   - Yes → Add to existing unified broadcast (position_metrics_update)
   - No → Create new broadcast (only if truly separate concern)

4. **How often should this update?**
   - Critical (< 1s) → Broadcast on event receipt
   - Standard → Add to 30-second unified broadcast
   - Rare (> 1 min) → Periodic task only

5. **Does this need persistence?**
   - Yes → Add Celery task (10 min interval)
   - No → Broadcast only (ephemeral data)

---

## References

### Internal Documentation
- `docs/WORKING_STREAMING_IMPLEMENTATION.md` - Streaming setup
- `docs/CRITICAL_DJANGO_ASYNC_PATTERNS.md` - Async best practices
- `docs/PERFORMANCE_ANALYSIS.md` - Performance considerations

### Code Examples
- Position Metrics: `streaming/services/stream_manager.py:1066-1271`
- Greeks Service: `services/greeks_service.py`
- Frontend Handler: `static/js/position_metrics.js`

### Related Patterns
- **Service Layer**: All calculations in dedicated service classes
- **Cache Keys**: Consistent naming via `CacheManager`
- **Error Handling**: Graceful failures, never show stale data
- **Testing**: Each layer tested independently

---

## Maintenance

### Updating This Pattern

This pattern should evolve as we learn. Update when:
- New requirements emerge
- Better approaches are discovered
- Team feedback identifies gaps

**Process**:
1. Discuss changes with team
2. Update this document
3. Update CLAUDE.md reference
4. Notify team of changes

### Pattern Reviews

Review this pattern:
- Quarterly (or when major issues arise)
- After each significant streaming feature
- When onboarding new team members

---

**Questions?** Refer to the reference implementation (Position Metrics) or consult this document.

**Last Updated**: 2025-10-09
