# Daily Trade Suggestions Task - Implementation Guide

## Overview

The daily trade suggestions task (`generate_and_email_daily_suggestions`) analyzes user watchlists, scores strategies, and emails top opportunities. This guide covers critical implementation details for avoiding rate limits and ensuring efficient operation.

## TastyTrade API Limits

**Critical Limits:**
- Market data requests: **2 requests/sec per IP** ⚠️
- Default API limit: 250 requests/sec per IP
- Order requests: 40 requests/sec per IP
- DXFeed subscriptions: Up to 100,000 concurrent
- DXFeed updates: 8,000 events/candle data points

**Key Takeaway:** Market data API is the bottleneck - use streaming cache instead.

## Architecture

### Data Flow
```
User Watchlist (19 symbols)
    ↓
Streaming Initialization (ALL symbols) ← CRITICAL
    ↓
Cache Population (quote:{symbol})
    ↓
Parallel Processing (Semaphore(5))
    ↓
Strategy Scoring → get_quote() → Cache Hit ✅
    ↓
Email Generation
```

### Three-Layer Data Access
1. **Streaming Cache** (primary) - Redis, 1-min TTL
2. **Historical DB** (technical indicators) - PostgreSQL
3. **API Fallback** (emergency only) - TastyTrade API

## Critical Implementation Details

### 1. Subscribe to ALL Watchlist Symbols

**Wrong ❌:**
```python
streaming_ready = await manager.ensure_streaming_for_automation(symbols[:5])
# Only subscribes first 5, but processes all 19 → 429 errors
```

**Correct ✅:**
```python
streaming_ready = await manager.ensure_streaming_for_automation(symbols)
# Subscribes ALL symbols → cache populated → no API calls
```

**Location:** `trading/tasks.py:658`

**Why:** If symbols aren't subscribed to streaming, cache is empty → API fallback → rate limit exceeded.

### 2. Wait for Data Stabilization

```python
await manager.ensure_streaming_for_automation(symbols)
await asyncio.sleep(3)  # Wait for cache population
```

**Why:** Streaming connection may be established but data not yet received. 3 seconds ensures cache has data before processing starts.

### 3. Use Correct Quote API

**Wrong ❌:**
```python
from tastytrade.instruments import Equity
equity = await Equity.a_get(session, [symbol])  # Returns metadata, not quotes
```

**Correct ✅:**
```python
from tastytrade.market_data import a_get_market_data
market_data = await a_get_market_data(session, symbol, InstrumentType.EQUITY)
```

**Location:** `services/market_data_service.py:156`

**Why:** `Equity.a_get()` returns instrument metadata. Real-time quotes require `a_get_market_data()`.

### 4. Validate Historical Data Freshness

```python
records = HistoricalPrice.objects.filter(symbol=symbol).aggregate(
    count=models.Count("id"),
    latest=models.Max("date")
)
is_fresh = latest_date >= today - timedelta(days=1)
```

**Location:** `services/historical_data_provider.py:86-96`

**Why:** Old data may exist in DB but be stale. Check both count AND freshness to avoid using outdated data for technical indicators.

### 5. Handle Division by Zero

```python
# Defensive check before division
if report.sma_20 and report.sma_20 > 0:
    price_pct = ((current_price - report.sma_20) / report.sma_20) * 100
else:
    # Handle missing data gracefully
    score_adjustment += 10  # Partial score without percentage
```

**Location:** `services/debit_spread_strategy.py:143-156`

**Why:** Technical indicators may be None or zero when historical data is insufficient.

## Common Pitfalls

### Pitfall 1: Subscription Gap
**Problem:** Subscribing to fewer symbols than you process
**Result:** Cache misses, API fallback, 429 errors
**Fix:** Subscribe to ALL symbols in watchlist

### Pitfall 2: Cache Key Mismatch
**Problem:** Streaming writes `quote:.{symbol}` but service reads `quote:{symbol}`
**Result:** Cache misses despite streaming being active
**Fix:** Use `CacheManager.quote(symbol)` consistently (produces `quote:{symbol}`)

### Pitfall 3: Racing Cache Population
**Problem:** Reading cache before streaming writes complete
**Result:** Intermittent cache misses
**Fix:** 3-second stabilization delay after `ensure_streaming_for_automation()`

### Pitfall 4: Ignoring Data Staleness
**Problem:** Using old historical data for technical indicators
**Result:** Inaccurate RSI/MACD/SMA calculations
**Fix:** Check `latest_date >= today - timedelta(days=1)`

## Rate Limit Management

### Current Protection
- Task-local `Semaphore(5)` limits concurrent symbol processing
- Streaming cache prevents 99%+ of API calls
- Graceful degradation on cache miss

### Scaling Considerations
- **1-10 users:** Current implementation safe
- **50+ users:** Consider Redis-backed distributed semaphore
- **100+ users:** Market data API (2 req/sec) becomes bottleneck without streaming

### Monitoring
Watch for these patterns:
```python
# Good - cache hits
"No cached data, fetching quote from API for SPY" ← Should be RARE

# Bad - API fallback
"HTTP Request: GET https://api.tastyworks.com/market-data/" ← Should be < 1/min

# Critical - rate limits
"429 Too Many Requests" ← Indicates subscription gap or cache failure
```

## Testing Locally

```python
from trading.tasks import _async_generate_and_email_daily_suggestions
import asyncio

result = asyncio.run(_async_generate_and_email_daily_suggestions())
print(result)  # {'emails_sent': 1, 'failed': 0, 'skipped': 0}
```

**Verify:**
1. No "429 Too Many Requests" errors
2. Streaming subscriptions: `{count}/500` logs
3. Cache hits for all symbols
4. Email generated successfully

## Key Takeaways for Developers

1. **Streaming is not optional** - Required to avoid rate limits
2. **Subscribe to what you process** - If analyzing 19 symbols, subscribe to 19
3. **Wait for cache** - 3-second delay after streaming initialization
4. **Use correct APIs** - `a_get_market_data()` for quotes, not `Equity.a_get()`
5. **Validate data freshness** - Don't assume DB data is current
6. **Defensive coding** - Check for None/zero before division

## Related Documentation

- `AUTOMATED_DAILY_TRADING_CYCLE.md` - Automated execution task
- `TASTYTRADE_SDK_BEST_PRACTICES.md` - SDK usage patterns
- `PRODUCTION_DEBUGGING_GUIDE.md` - Troubleshooting in production
