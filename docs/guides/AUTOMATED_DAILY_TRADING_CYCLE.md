# Automated Daily Trading Cycle - Developer Guide

**Last Updated**: 2025-11-05
**Author**: System Documentation

---

## Table of Contents

1. [Overview](#overview)
2. [Schedule & Timing](#schedule--timing)
3. [Complete Workflow](#complete-workflow)
4. [Key Components](#key-components)
5. [Safeguards & Validation](#safeguards--validation)
6. [Configuration](#configuration)
7. [Debugging & Testing](#debugging--testing)
8. [Common Issues & Solutions](#common-issues--solutions)
9. [Monitoring & Logs](#monitoring--logs)

---

## Overview

The **Automated Daily Trading Cycle** is a Celery periodic task that automatically generates and executes Senex Trident positions for accounts with automation enabled.

### What It Does

1. **Checks** if user already traded today (prevents duplicates)
2. **Starts** real-time streaming for SPX and QQQ
3. **Waits** 3 seconds for data to stabilize (freshness verification)
4. **Generates** a Senex Trident suggestion using streaming data
5. **Retries** up to 3 times if generation fails (stale data, negative credits)
6. **Validates** risk limits and account constraints
7. **Applies** user's entry offset (e.g., -$0.04 from mid-price)
8. **Executes** the order via TastyTrade API
9. **Notifies** user via email (if enabled)

### Key Characteristics

- **Runs**: Every 15 minutes from 9:45 AM to 2:45 PM ET (22 opportunities/day)
- **Trades**: Only once per day per account (built-in safeguard)
- **Resilient**: Retries on failure, validates data quality
- **Conservative**: Uses worst-case bid/ask pricing for risk calculations

---

## Schedule & Timing

### Celery Beat Schedule

**File**: `senex_trader/settings/base.py:153-159`

```python
"automated-daily-trade-cycle": {
    "task": "trading.tasks.automated_daily_trade_cycle",
    "schedule": crontab(hour='9-14', minute='45,0,15,30', day_of_week='mon-fri'),
}
```

### Run Times (Eastern Time)

| Time | Notes |
|------|-------|
| 9:45 AM | First opportunity (15 min after market open) |
| 10:00 AM | Second opportunity |
| 10:15 AM | ... |
| ... | Every 15 minutes |
| 2:30 PM | ... |
| 2:45 PM | Last opportunity (15 min before market close) |

**Total**: 22 runs per day, but only 1 trade per account

### Why Every 15 Minutes?

1. **Resilience**: Multiple chances if data is bad at one time
2. **Market Open**: Avoid 9:30 AM volatility and wide spreads
3. **Debugging**: More opportunities to observe behavior
4. **No Duplicates**: Built-in `trade_exists_today` check prevents multiple trades

---

## Complete Workflow

### High-Level Flow

```
Celery Beat Trigger (every 15 min)
    ↓
automated_daily_trade_cycle() Task
    ↓
Check: Trade exists today? → YES → Skip (no duplicate)
    ↓ NO
AutomatedTradingService._a_process()
    ↓
Start Streaming (SPX, QQQ)
    ↓
Wait 3 seconds (data stabilization)
    ↓
Retry Loop (up to 3 attempts):
    ↓
    Generate Suggestion
        ↓
        Prepare Context (market analysis)
        ↓
        Build OCC Bundle (strikes → symbols)
        ↓
        Read Pricing from Cache
        ↓
        Validate: negative credits? → YES → Retry
        ↓ NO
        Create TradingSuggestion
    ↓
    Suggestion created? → NO → Retry (wait 5s)
    ↓ YES
Validate Risk Limits
    ↓
Calculate Entry Price (apply offset)
    ↓
Execute Order (TastyTrade API)
    ↓
Send Email Notification
    ↓
Stop Streaming (cleanup)
```

### Detailed Step-by-Step

#### 1. Task Entry Point

**File**: `trading/tasks.py:813-869`

```python
@shared_task(name="trading.tasks.automated_daily_trade_cycle")
def automated_daily_trade_cycle():
    """Run automated trading for all eligible accounts."""
    service = AutomatedTradingService()

    # Find accounts with automation enabled
    accounts = TradingAccount.objects.filter(
        is_active=True,
        is_automated_trading_enabled=True,
        is_token_valid=True
    )

    for account in accounts:
        result = service.process_account(account)
        # Track results...
```

#### 2. Check for Existing Trade

**File**: `trading/services/automated_trading_service.py:87-97`

```python
def _trade_exists_today() -> bool:
    return (
        Trade.objects.filter(user=user, submitted_at__date=today)
        .exclude(status__in=["cancelled", "rejected", "expired"])
        .exists()
    )
```

**Catches**: pending, submitted, routed, live, working, filled
**Ignores**: cancelled, rejected, expired

**Result**: If ANY non-failed trade exists today, skip this account

#### 3. Start Streaming & Data Stabilization

**File**: `trading/services/automated_trading_service.py:226-244`

```python
manager = await GlobalStreamManager.get_user_manager(user.id)
streaming_ready = await manager.ensure_streaming_for_automation(["SPX", "QQQ"])

# DATA FRESHNESS: Wait for streaming data to stabilize
DATA_STABILIZATION_DELAY = 3  # seconds
await asyncio.sleep(DATA_STABILIZATION_DELAY)
```

**Why 3 seconds?**
- Streaming needs time to subscribe to DXFeed
- First quotes may be stale or incomplete
- Allows cache to populate with fresh bid/ask data

#### 4. Retry Loop

**File**: `trading/services/automated_trading_service.py:99-159`

```python
MAX_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds

for attempt in range(1, MAX_ATTEMPTS + 1):
    suggestion = await self.a_generate_suggestion(user)
    if suggestion:
        break  # Success!
    if attempt < MAX_ATTEMPTS:
        await asyncio.sleep(RETRY_DELAY)  # Wait and retry
```

**Retries help with**:
- Negative credits (bad bid/ask data)
- Stale cache data
- Transient DXFeed issues
- Market volatility at open

#### 5. Suggestion Generation

**File**: `trading/services/automated_trading_service.py:219-283`

**Sub-steps**:

a. **Market Analysis** (`SenexTridentStrategy.a_prepare_suggestion_context()`)
   - Check SPX/QQQ conditions (IV rank, regime, etc.)
   - Select symbol (QQQ preferred, SPX fallback)
   - Choose expiration (45 DTE target)
   - Calculate strikes (622P/619P/622C/625C)

b. **OCC Bundle Build** (`OptionsService.build_occ_bundle()`)
   - Map strikes to OCC symbols
   - Example: 622P → `QQQ   251219P00622000`
   - Fetch option chain from API/cache

c. **Pricing Calculation** (`OptionsCache.build_pricing()`)
   - Read bid/ask from Redis cache
   - Convert OCC → streamer format (`.QQQ251219P622`)
   - Calculate natural credit: `bid(short) - ask(long)`
   - Calculate mid credit: `mid(short) - mid(long)`
   - **Validate**: Reject if natural credit ≤ 0

d. **Create Suggestion** (`SenexTridentStrategy.a_calculate_suggestion_from_cached_data()`)
   - Store pricing in `TradingSuggestion`
   - Set status = "approved" (automated)
   - Return suggestion object

#### 6. Risk Validation

**File**: `trading/services/automated_trading_service.py:172-196`

```python
validation = await RiskValidationService.validate_trade_risk(
    user=user, suggestion_id=suggestion.id
)
```

**Checks**:
- Max risk within limits
- Account buying power sufficient
- Risk utilization under threshold
- Position limits not exceeded

**Result**: If validation fails, skip and don't execute

#### 7. Entry Offset Application

**File**: `trading/services/automated_trading_service.py:322-414`

```python
custom_credit = self._calculate_automation_credit(account, suggestion)

# For credit spreads: subtract offset for better fill
adjusted = total_mid_credit - offset_value
# Floor at natural credit (prevent selling below bid)
adjusted = max(adjusted, natural_credit)
```

**Example** (user has 4¢ offset):
- Mid credit: $4.10
- Minus offset: $4.10 - $0.04 = $4.06
- Natural credit: $3.86
- Floor check: `max($4.06, $3.86)` = $4.06 ✓
- **Order sent at $4.06**

**Important**: Case-insensitive comparison (database stores "Credit", code compares "credit")

#### 8. Order Execution

**File**: `services/execution/order_service.py:execute_suggestion_async()`

**Sub-steps**:
1. Build order legs from suggestion
2. Validate OCC symbols and quantities
3. Create Position and Trade records (status="pending")
4. Submit order to TastyTrade API
5. Update records with broker order ID
6. Return execution result

#### 9. Email Notification

**File**: `trading/services/automated_trading_service.py:285-320`

**Sends email if**:
- User's `email_preference = "immediate"`
- Execution succeeded
- Email service available

**Email includes**:
- Symbol, expiration, strategy
- Entry price (with offset)
- Max risk, position details
- TastyTrade order link

#### 10. Cleanup

**File**: `trading/services/automated_trading_service.py:274-283`

```python
finally:
    if manager:
        await manager.stop_streaming()
```

**Critical**: Prevents `RecursionError` during event loop shutdown

---

## Key Components

### 1. AutomatedTradingService

**File**: `trading/services/automated_trading_service.py`

**Purpose**: Orchestrates the entire automation workflow

**Key Methods**:
- `process_account(account)` - Main entry point (sync wrapper)
- `_a_process(user, account)` - Core async logic
- `a_generate_suggestion(user)` - Streaming pipeline
- `_calculate_automation_credit()` - Apply entry offset
- `send_notification()` - Email alerts

### 2. GlobalStreamManager

**File**: `streaming/services/stream_manager.py`

**Purpose**: Manages DXFeed streaming connections per user

**Key Methods**:
- `get_user_manager(user_id)` - Get/create user's stream manager
- `ensure_streaming_for_automation()` - Start streaming for symbols
- `a_process_suggestion_request()` - Generate suggestion from cache
- `stop_streaming()` - Cleanup connections

### 3. SenexTridentStrategy

**File**: `services/senex_trident_strategy.py`

**Purpose**: Encapsulates Senex Trident strategy logic

**Key Methods**:
- `a_prepare_suggestion_context()` - Market analysis
- `a_calculate_suggestion_from_cached_data()` - Create suggestion
- `_select_strikes()` - Calculate ATM strikes
- `_select_even_strikes()` - Round to even strikes

### 4. OptionsCache

**File**: `services/streaming/options_cache.py`

**Purpose**: Read option pricing from Redis cache

**Key Methods**:
- `build_pricing(bundle)` - Calculate natural/mid credits
- `get_quote_payload(occ_symbol)` - Retrieve bid/ask from cache
- `_natural_credit()` - Conservative pricing formula
- `_mid_credit()` - Realistic pricing formula

**Validation** (added for negative credit bug):
```python
if put_credit <= 0 or call_credit <= 0 or total_credit <= 0:
    logger.error("❌ INVALID PRICING DETECTED")
    return None  # Triggers retry
```

### 5. OrderExecutionService

**File**: `services/execution/order_service.py`

**Purpose**: Submit orders to TastyTrade API

**Key Methods**:
- `execute_suggestion_async()` - Main execution flow
- `_build_order_structure()` - Convert suggestion to order
- `_submit_to_tastytrade()` - API submission

---

## Safeguards & Validation

### 1. Trade Exists Check

**Prevents**: Duplicate trades on same day

**Implementation**: Query `Trade` table for today's non-failed trades

**Catches**: pending, submitted, routed, live, working, filled

### 2. Market Open Check

**File**: `services/utils/trading_utils.py`

```python
if not is_market_open_now():
    return {"status": "skipped", "reason": "market_closed"}
```

**Prevents**: Trading outside market hours (9:30 AM - 4:00 PM ET)

### 3. Negative Credit Validation

**File**: `services/streaming/options_cache.py:304-349`

**Detects**: Bad streaming data (inverted bid/ask, stale cache, corrupted data)

**Action**: Returns `None` → triggers retry loop

**Logs**: Detailed diagnostics with bid/ask values and suspected causes

### 4. Risk Validation

**File**: `services/risk_validation.py`

**Checks**:
- Max risk < account risk limit
- Buying power sufficient
- Risk utilization < 100%
- Position count within limits

**Action**: Skips automation if validation fails

### 5. Token Validity Check

**File**: `trading/tasks.py:820-826`

```python
accounts = TradingAccount.objects.filter(
    is_active=True,
    is_automated_trading_enabled=True,
    is_token_valid=True  # Only accounts with valid OAuth tokens
)
```

**Prevents**: Attempting to trade with expired/invalid credentials

### 6. Data Freshness Check

**File**: `services/streaming/options_cache.py:327-332`

```python
if not pricing.is_fresh:
    logger.warning("❌ Pricing rejected as stale")
    return None
```

**Threshold**: 30 seconds (DEFAULT_MAX_AGE)

**Action**: Rejects stale pricing → triggers retry

### 7. Offset Floor Check

**File**: `trading/services/automated_trading_service.py:373-388`

```python
# Floor at natural credit (prevent selling below bid)
natural_credit = Decimal(suggestion.total_credit or "0")
adjusted = max(adjusted, natural_credit)
```

**Prevents**: Offset creating prices below worst-case bid

**Example**: If offset is 50¢ but spread is only 40¢, floor prevents negative credit

---

## Configuration

### Account-Level Settings

**Model**: `accounts.models.TradingAccount`

| Field | Type | Purpose |
|-------|------|---------|
| `is_automated_trading_enabled` | Boolean | Master switch for automation |
| `automated_entry_offset_cents` | Integer | Entry offset in cents (e.g., 4 = $0.04) |
| `is_token_valid` | Boolean | OAuth token status |
| `is_active` | Boolean | Account active status |
| `is_primary` | Boolean | Primary account flag |

### User-Level Settings

**Model**: `accounts.models.User`

| Field | Type | Purpose |
|-------|------|---------|
| `email_preference` | String | "immediate", "daily", "weekly", "never" |

### System-Level Settings

**File**: `senex_trader/settings/base.py`

| Setting | Value | Purpose |
|---------|-------|---------|
| `CELERY_BEAT_SCHEDULE` | crontab(...) | Task schedule |
| `CELERY_TIMEZONE` | "America/New_York" | Eastern Time |

### Constants

**File**: `trading/services/automated_trading_service.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_ATTEMPTS` | 3 | Retry attempts for suggestion generation |
| `RETRY_DELAY` | 5 | Seconds between retries |
| `DATA_STABILIZATION_DELAY` | 3 | Seconds to wait after streaming starts |

**File**: `services/streaming/options_cache.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_MAX_AGE` | 30 | Max age (seconds) for pricing data |

---

## Debugging & Testing

### Local Testing

#### 1. Trigger Task Manually

```bash
# Via Django shell
python manage.py shell

from trading.tasks import automated_daily_trade_cycle
result = automated_daily_trade_cycle()
print(result)
```

#### 2. Test Specific Account

```python
from trading.services.automated_trading_service import AutomatedTradingService
from accounts.models import TradingAccount

service = AutomatedTradingService()
account = TradingAccount.objects.get(account_number="ABC12345")

result = service.process_account(account)
print(result)
```

#### 3. Dry-Run Mode

Set `DRY_RUN = True` in order_service.py to simulate execution without submitting orders

### Production Debugging

#### 1. Check Schedule

```bash
# SSH to production
ssh root@your-domain.com

# Verify celery beat is running
su - senex -c 'podman ps | grep celery_beat'

# Check beat schedule
su - senex -c 'podman exec celery_beat celery -A senex_trader inspect scheduled'
```

#### 2. View Logs

```bash
# Celery worker logs (where task executes)
journalctl CONTAINER_NAME=celery_worker --since "2025-11-05 14:45:00" --no-pager

# Filter for automation
journalctl CONTAINER_NAME=celery_worker --since today | grep "automated.*cycle"

# Check for errors
journalctl CONTAINER_NAME=celery_worker --since today | grep -i "error\|failed"
```

#### 3. Check Task Status

```python
# Django shell on production
su - senex -c 'podman exec -i web python manage.py shell'

from django_celery_results.models import TaskResult
from django.utils import timezone

# Find recent automation tasks
tasks = TaskResult.objects.filter(
    task_name="trading.tasks.automated_daily_trade_cycle",
    date_created__date=timezone.now().date()
).order_by("-date_created")

for task in tasks:
    print(f"{task.date_created}: {task.status}")
    if task.result:
        print(f"  Result: {task.result}")
```

#### 4. Check Trade Records

```python
from trading.models import Trade
from django.utils import timezone

# Today's trades
trades = Trade.objects.filter(
    submitted_at__date=timezone.now().date()
).exclude(status__in=["cancelled", "rejected", "expired"])

for trade in trades:
    print(f"{trade.user.email}: {trade.status} at {trade.submitted_at}")
```

### Common Test Scenarios

#### Test Negative Credit Detection

1. Modify `build_pricing()` to return negative credit
2. Run automation
3. Verify retry logic triggers
4. Check logs for "INVALID PRICING DETECTED" error

#### Test Retry Logic

1. Add `return None` at start of `a_generate_suggestion()`
2. Run automation
3. Verify 3 attempts with 5-second delays
4. Check logs for retry messages

#### Test Offset Application

1. Set `automated_entry_offset_cents = 4`
2. Generate suggestion with `total_mid_credit = 4.10`
3. Verify order submitted at $4.06
4. Check logs for "Applying automation offset"

#### Test Duplicate Prevention

1. Run automation (creates trade)
2. Run again immediately
3. Verify second run skips with "already has trade today"

---

## Common Issues & Solutions

### Issue 1: Negative Natural Credits

**Symptom**: Suggestion generation fails with "INVALID PRICING DETECTED"

**Causes**:
- Stale DXFeed data at market open
- Corrupted Redis cache
- Inverted bid/ask values
- OCC symbols swapped during lookup

**Solution**:
- **Automatic**: Retry logic (3 attempts with 5s delay)
- **Manual**: Check logs for bid/ask values, verify OCC symbols
- **Prevention**: Data stabilization delay (3 seconds after streaming starts)

**Logs to check**:
```
🔍 PRICING DIAGNOSTIC - OCC Symbols and Values
  short_put: QQQ   251219P00622000 | bid=X, ask=Y
  long_put: QQQ   251219P00619000 | bid=X, ask=Y
📊 PUT SPREAD: short_put bid=$X, long_put ask=$Y
  → put_credit = X - Y = $Z
```

### Issue 2: Offset Not Applied

**Symptom**: Order submitted at mid-price instead of mid - offset

**Causes**:
- `price_effect` case mismatch ("Credit" vs "credit")
- `total_mid_credit` is None/empty
- `automated_entry_offset_cents` is 0 or None

**Solution**:
- **Fixed**: Case-insensitive comparison in code
- **Verify**: Check account setting has non-zero offset
- **Logs**: "Applying automation offset X¢: mid=$Y → limit=$Z"

### Issue 3: Task Not Running

**Symptom**: No logs for automation around expected times

**Causes**:
- Celery beat not running
- Schedule misconfigured
- Market closed
- No accounts with automation enabled

**Solution**:
```bash
# Check celery beat status
systemctl --user -M senex@ status celery-beat.service

# Verify schedule
podman exec celery_beat celery -A senex_trader inspect scheduled

# Check account settings
podman exec web python manage.py shell -c "
from accounts.models import TradingAccount
print(TradingAccount.objects.filter(is_automated_trading_enabled=True).count())
"
```

### Issue 4: Duplicate Trades

**Symptom**: Multiple trades created on same day

**Causes**:
- `trade_exists_today` check not working
- Race condition (two tasks running simultaneously)
- Trade status excluded from check (cancelled/rejected)

**Solution**:
- **Check**: Query `Trade` table for today's trades
- **Verify**: Task only runs once per 15 minutes (not overlapping)
- **Fix**: Ensure trade status is not "cancelled", "rejected", or "expired"

### Issue 5: Streaming Timeout

**Symptom**: "Failed to start streaming for automation"

**Causes**:
- DXFeed connection issues
- TastyTrade API down
- Network problems
- Too many concurrent streams

**Solution**:
- **Automatic**: Retry logic will attempt again in 15 minutes
- **Manual**: Check DXFeed connection in web interface
- **Logs**: Look for "ensure_streaming_for_automation" errors

---

## Monitoring & Logs

### Key Log Patterns

#### Success Path

```
🤖 Starting automated daily trade cycle for user user@example.com (account: ABC12345, offset: 4¢)
User 1: Starting streaming for SPX and QQQ...
User 1: Waiting 3.0 seconds for streaming data to stabilize...
User 1: Data stabilization period complete, proceeding...
✅ Suggestion generated successfully on attempt 1/3 [5.2s]
✅ Suggestion created for user@example.com: QQQ (expiry: 2025-12-19, credit: $4.10, risk: $190.00) [5.3s]
✅ Risk validation passed for user@example.com [0.04s]
Applying automation offset 4¢: mid=4.10 → limit=4.06
ORDER PRICING BREAKDOWN - Suggestion 130
  → Final Submitted Price: $4.06
✅ Order submitted successfully
🤖 Automated cycle complete. Processed: 1, Succeeded: 1, Failed: 0, Skipped: 0
```

#### Retry Path

```
User user@example.com: Generating suggestion (attempt 1/3)...
❌ INVALID PRICING DETECTED: Negative put spread credit
  Put credit: $-1.53 (should be POSITIVE for credit spread)
⚠️ Suggestion generation failed on attempt 1/3 (took 5.2s). Retrying in 5 seconds...
User user@example.com: Generating suggestion (attempt 2/3)...
✅ Suggestion generated successfully on attempt 2/3 [5.1s]
```

#### Skip Path

```
🤖 Starting automated daily trade cycle...
User user@example.com already has trade today. Skipping.
🤖 Automated cycle complete. Processed: 0, Succeeded: 0, Failed: 0, Skipped: 1
```

### Metrics to Monitor

| Metric | Query | Threshold |
|--------|-------|-----------|
| Success Rate | `succeeded / processed` | > 90% |
| Retry Rate | `attempts > 1` | < 20% |
| Skip Rate (no trade) | `skipped / total_runs` | < 50% |
| Execution Time | `suggestion_duration + execution_duration` | < 30s |
| Negative Credits | Count of "INVALID PRICING" errors | 0 per day ideal |

### Alerting Recommendations

**Critical Alerts**:
- Task failed for all accounts 3+ times in a day
- No successful trades in 5+ days (excluding weekends)
- Negative credits detected > 5 times per day

**Warning Alerts**:
- Retry rate > 30%
- Execution time > 45 seconds
- Risk validation failures > 20%

---

## Related Documentation

- [SENEX_TRIDENT_STRATEGY_DEFINITION.md](../specifications/SENEX_TRIDENT_STRATEGY_DEFINITION.md) - Strategy details
- [TASTYTRADE_SDK_BEST_PRACTICES.md](TASTYTRADE_SDK_BEST_PRACTICES.md) - API usage
- [REALTIME_DATA_FLOW_PATTERN.md](../patterns/REALTIME_DATA_FLOW_PATTERN.md) - Streaming architecture
- [PRODUCTION_DEBUGGING_GUIDE.md](PRODUCTION_DEBUGGING_GUIDE.md) - Production debugging (companion doc)

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-05 | 2.0 | Added retry logic, data stabilization, 15-minute schedule |
| 2025-11-04 | 1.1 | Fixed offset application bug, added negative credit validation |
| 2025-10-18 | 1.0 | Initial implementation (10am once per day) |
