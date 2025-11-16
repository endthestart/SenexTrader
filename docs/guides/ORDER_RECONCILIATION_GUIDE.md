# Order Reconciliation Guide for Developers

**Last Updated**: 2025-11-07  
**Purpose**: Comprehensive guide for diagnosing and fixing order synchronization issues between Senex Trader database and TastyTrade

---

## Overview

The Senex Trader system maintains profit target orders in both:
1. **Database**: `Position.profit_target_details` JSON field
2. **TastyTrade**: Live orders in the broker account

These can fall out of sync due to:
- Async/sync context errors during order creation
- Manual order cancellations in TastyTrade
- Failed order placement attempts
- System crashes/restarts during order processing
- Bulk update scripts with async issues
- DTE management failures

**Critical Learning**: Always use **sync** methods from TastyTrade SDK when accuracy matters more than speed. For one-off scripts and reconciliation, we don't need async - we need correctness.

---

## Symptoms of Desynchronization

### 1. Dashboard Shows Wrong Order Count
- `/trading/positions` shows X managed positions with Y spreads
- `/trading/orders` shows different number of orders
- Math doesn't add up (e.g., 16 positions × ~2 spreads ≠ 20 orders)

### 2. Orders Exist in TastyTrade but Not in Database
- TastyTrade shows working orders
- Database `profit_target_details` missing those order IDs
- These are "orphaned orders"

### 3. Database Has Order IDs That Don't Exist in TastyTrade
- `Position.profit_target_details` contains order IDs
- Those orders don't exist in TastyTrade (cancelled/filled without database update)
- These are "invalid order IDs"

### 4. Positions Missing Profit Targets Entirely
- `Position.profit_targets_created = False`
- No orders in TastyTrade for that position
- Usually caused by async errors during creation

---

## Diagnostic Tools

### Tool 1: TastyTrade CLI (Fastest & Most Reliable)

The tastytrade CLI is configured with encrypted credentials from the database.

#### Setup (One-Time)

```bash
# Install the CLI (should already be installed in venv)
cd ../../references/tastytrade-cli
pip install -e .

# Extract encrypted token from database
python manage.py shell <<EOF
from accounts.models import TradingAccount
account = TradingAccount.objects.first()
print(account.refresh_token)  # This is decrypted automatically
EOF

# Configure CLI with the token
tt config set refresh-token <TOKEN_FROM_ABOVE>
```

#### Usage

```bash
# View all live orders (most useful)
tt order live

# View all positions
tt pf positions

# View specific position details
tt pf position <SYMBOL>

# View order history
tt order history --days 30

# View filled orders
tt order filled --days 7
```

**Pros**: 
- ✅ Real-time data directly from TastyTrade
- ✅ No code required, fast iteration
- ✅ Shows exact order details, strikes, quantities
- ✅ Can filter by status (working, filled, cancelled)
- ✅ Shows actual positions vs our database state

**Cons**:
- Interactive (requires selection in menus)
- No automatic comparison with database
- Must manually count/cross-reference

**Best For**:
- Quick validation during reconciliation
- Confirming order counts match reality
- Verifying order IDs exist in TastyTrade

### Tool 2: Reconciliation Management Command

```bash
# Dry-run mode (read-only analysis)
python manage.py reconcile_qqq_orders --dry-run

# Show analysis with fixes
python manage.py reconcile_qqq_orders --dry-run --cancel-orphaned --clear-invalid
```

**Output shows**:
- ✅ Matched positions (orders correct)
- ⚠️ Positions with invalid orders
- 🔗 Orphaned orders (in TastyTrade, not in DB)
- ❌ Positions with no orders

**Pros**:
- Automated comparison
- Clear categorization of issues
- Built-in fix actions

### Tool 3: Django Shell Query

```python
from trading.models import Position

# Get all open QQQ positions with orders
positions = Position.objects.filter(
    symbol='QQQ',
    lifecycle_state__in=['open_full', 'open_partial']
).select_related('user')

for pos in positions:
    if not pos.profit_target_details:
        print(f"Position #{pos.id}: NO profit_target_details")
        continue
    
    for key in ['call_spread', 'put_spread_1', 'put_spread_2']:
        if key in pos.profit_target_details:
            detail = pos.profit_target_details[key]
            order_id = detail.get('order_id')
            status = detail.get('status', 'unknown')
            print(f"Position #{pos.id} {key}: {order_id} ({status})")
```

### Tool 4: Python with TastyTrade SDK (Sync Methods)

For custom analysis where you need programmatic access:

```python
#!/usr/bin/env python
import os, sys, django

# Django setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.production')
django.setup()

from tastytrade import Session, Account
from accounts.models import TradingAccount
from trading.models import Position

# Get credentials
account_model = TradingAccount.objects.first()

# IMPORTANT: Use sync Session, not async ProductionSession
session = Session(account_model.username, account_model.password)

# Get account using SYNC method
tt_account = Account.get_account(session, account_model.account_number)

# Get live orders using SYNC method
live_orders = tt_account.get_live_orders(session)

# Filter for QQQ
qqq_orders = [o for o in live_orders if 'QQQ' in o.underlying_symbol]

print(f"Found {len(qqq_orders)} live QQQ orders")

for order in qqq_orders:
    print(f"Order {order.id}: {order.status}")
    for leg in order.legs:
        print(f"  {leg.action} {leg.quantity}x {leg.symbol}")

# Get positions using SYNC method
positions = tt_account.get_positions(session)
qqq_positions = [p for p in positions if p.symbol == 'QQQ']

print(f"\nFound {len(qqq_positions)} QQQ positions")
for pos in qqq_positions:
    print(f"Position: {pos.quantity}x {pos.symbol}")
```

**Key Differences vs Async**:
- `Session` instead of `ProductionSession`
- `Account.get_account()` instead of `Account.a_get()`
- `account.get_live_orders()` instead of `account.a_get_live_orders()`
- No `await`, no event loops, no async context issues
- **SLOWER** but **MORE RELIABLE** for scripts

**When to Use Sync Methods**:
- ✅ One-off analysis scripts
- ✅ Reconciliation commands
- ✅ Management commands (Pattern 1 alternative)
- ✅ When accuracy > speed
- ✅ When debugging async issues

**When to Use Async Methods**:
- Real-time trading decisions
- High-frequency operations
- Production services with proper async context

---

## Reconciliation Process

### Step 1: Diagnose the Problem

```bash
# Run dry-run to see current state
ssh root@your-domain.com "su - senex -c 'podman exec -i web python manage.py reconcile_qqq_orders --dry-run'"
```

**This will show**:
- How many orders in TastyTrade
- How many positions in database
- Which positions have issues
- Which orders are orphaned

### Step 2: Validate with TastyTrade CLI

```bash
# Count actual orders in TastyTrade
tt order live
# (Select account, count QQQ orders)
```

**Cross-reference**:
- Order IDs from CLI should match database
- If discrepancies, note which order IDs

### Step 3: Execute Cleanup

```bash
# Clear invalid order IDs from database
python manage.py reconcile_qqq_orders --clear-invalid --yes

# Cancel orphaned orders in TastyTrade
python manage.py reconcile_qqq_orders --cancel-orphaned --yes

# Or do both at once
python manage.py reconcile_qqq_orders --clear-invalid --cancel-orphaned --yes
```

### Step 4: Create Missing Profit Targets

After cleanup, some positions will need new orders:

```bash
# For specific position
python manage.py create_profit_targets --position 45

# Let automated reconciliation task handle it (runs every 30 min)
# Or trigger manually
python manage.py fix_incomplete_profit_targets
```

### Step 5: Verify

```bash
# Re-run reconciliation to confirm
python manage.py reconcile_qqq_orders --dry-run
```

**Expected output**:
```
✅ Matched positions: X
⚠️  Positions with invalid orders: 0
❌ Positions with no orders: 0
🔗 Orphaned orders: 0
```

---

## Common Scenarios

### Scenario 1: Async Bug Caused Missing Profit Targets

**Symptoms**:
- Position created successfully
- `profit_targets_created = False`
- No orders in TastyTrade

**Fix**:
```bash
python manage.py create_profit_targets --position <ID>
```

**Root Cause**: Async context error prevented order creation during position opening.

---

### Scenario 2: Manual Order Cancellation in TastyTrade

**Symptoms**:
- Database has order ID
- Order doesn't exist in TastyTrade
- Position shows order as "active"

**Fix**:
```bash
# Clear the invalid order ID
python manage.py reconcile_qqq_orders --clear-invalid --yes

# Recreate if needed
python manage.py create_profit_targets --position <ID>
```

**Root Cause**: Someone manually cancelled order in TastyTrade without updating database.

---

### Scenario 3: Failed Order Creation Script

**Symptoms**:
- Orders exist in TastyTrade
- Not linked to any position in database
- Orphaned orders

**Fix**:
```bash
# Cancel orphaned orders
python manage.py reconcile_qqq_orders --cancel-orphaned --yes

# Then recreate properly through position
python manage.py create_profit_targets --position <ID>
```

**Root Cause**: Script created orders in TastyTrade but failed to save order IDs to database.

---

### Scenario 4: Bulk Update Script Corruption

**Symptoms**:
- Multiple positions have wrong order IDs
- Orders in TastyTrade don't match database references
- Mixed valid/invalid order IDs

**Example from 2025-11-07**:
- Script tried to change all call spread profit targets from 50% to 40%
- Async errors caused order IDs to not save properly
- 7 positions ended up with invalid order IDs

**Fix**:
```bash
# 1. Clear all invalid order IDs
python manage.py reconcile_qqq_orders --clear-invalid --yes

# 2. Cancel orphaned orders from failed script
python manage.py reconcile_qqq_orders --cancel-orphaned --yes

# 3. Verify cleanup
python manage.py reconcile_qqq_orders --dry-run

# 4. Recreate missing orders
# (Let automated reconciliation handle it, or manual per position)
```

---

## Understanding the Reconciliation Command

### What It Does

The `reconcile_qqq_orders` command:

1. **Fetches** all active QQQ orders from TastyTrade (LIVE status only)
2. **Queries** all open QQQ positions from database
3. **Compares** order IDs between systems
4. **Categorizes** discrepancies:
   - Matched: Order ID in both systems
   - Invalid: Order ID in database but not in TastyTrade
   - Orphaned: Order ID in TastyTrade but not in database
   - Missing: Position has no order IDs at all

### Flags

```bash
--dry-run              # Read-only analysis (always run first)
--clear-invalid        # Remove invalid order IDs from database
--cancel-orphaned      # Cancel orphaned orders in TastyTrade
--yes                  # Skip confirmation prompts
```

### Example Usage

```bash
# Preview what would happen
python manage.py reconcile_qqq_orders --dry-run

# Execute fixes
python manage.py reconcile_qqq_orders --clear-invalid --cancel-orphaned --yes
```

### Async/Sync Pattern Used

The command follows **Pattern 1: Pure Sync + Event Loop** from `docs/guides/ASYNC_SYNC_PATTERNS.md`:

- Main `handle()` function is sync (Django ORM)
- TastyTrade API calls in separate `async def` functions
- Event loop wrapper pattern: `asyncio.new_event_loop()` + `try/finally` + `loop.close()`
- No `asyncio.run()` or `async def main()`

**Critical code pattern**:
```python
def _fetch_tastytrade_orders_sync(self, user, days_lookback):
    """Sync wrapper for async API calls."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(self._fetch_orders_async(user, days_lookback))
        return result
    finally:
        loop.close()  # CRITICAL: Always close

async def _fetch_orders_async(self, user, days_lookback):
    """Pure async - NO Django ORM here."""
    session = await get_oauth_session(user)
    account = await get_primary_tastytrade_account(user)
    # ... TastyTrade SDK calls
```

---

## Key Learnings from 2025-11-07 Incident

### What Went Wrong

1. **Bulk update script** tried to change profit target percentages
2. **Async context errors** prevented order IDs from saving
3. **7 positions** ended up with invalid order IDs
4. **Position #45** created during async bug period, got no profit targets

### How We Fixed It

1. Created `reconcile_qqq_orders` management command
2. Fixed order status filter (LIVE vs RECEIVED)
3. Implemented dynamic lookback window based on oldest position
4. Cleaned up:
   - Cancelled 2 orphaned orders
   - Cleared 3 invalid order IDs
   - Created profit targets for Position #45

### Result

- **20 orders in TastyTrade**
- **20 orders in database**
- **100% synchronization**

---

## Preventive Measures

### 1. Always Use Management Commands for Bulk Operations

❌ **DON'T**: Run scripts that directly manipulate orders without proper async patterns  
✅ **DO**: Use management commands that follow Pattern 1

### 2. Test Async Patterns in Development First

Before bulk operations:
```bash
# Test on single position
python manage.py your_command --position 1 --dry-run
```

### 3. Run Reconciliation After Bulk Operations

```bash
# After any bulk order operation
python manage.py reconcile_qqq_orders --dry-run
```

### 4. Monitor Automated Reconciliation

The `fix_incomplete_profit_targets` task runs every 30 minutes. Check logs for errors.

### 5. Add Error Tracking Fields (Future Enhancement)

```python
# Position model additions (requires migration)
profit_target_error = models.TextField(null=True, blank=True)
profit_target_last_attempt = models.DateTimeField(null=True, blank=True)
```

---

## Reference Materials

- **Async/Sync Patterns**: `docs/guides/ASYNC_SYNC_PATTERNS.md`
- **TastyTrade SDK**: `../../references/tastytrade/`
- **TastyTrade API Docs**: https://tastyworks-api.readthedocs.io/
- **Reconciliation Command**: `trading/management/commands/reconcile_qqq_orders.py`
- **Order Creation**: `trading/management/commands/create_profit_targets.py`

---

## Quick Reference Card

| Issue | Diagnostic | Fix |
|-------|-----------|-----|
| Orders in TT, not in DB | `reconcile --dry-run` | `reconcile --cancel-orphaned` |
| Orders in DB, not in TT | `reconcile --dry-run` | `reconcile --clear-invalid` |
| Position has no orders | `reconcile --dry-run` | `create_profit_targets --position X` |
| Wrong order count | `tt order live` + DB query | Full reconciliation |
| After bulk operation | Always run reconciliation | Cleanup + verify |

---

## When to Escalate

Escalate if:
- Reconciliation command itself fails
- Orders keep getting out of sync after fixes
- TastyTrade API errors during reconciliation
- Database corruption suspected (positions deleted but orders remain)

**First response**: Run reconciliation in read-only mode and document the state before attempting fixes.

---

## Advanced Topic: Sync vs Async TastyTrade SDK Methods

### The Hidden Power of Sync Methods

The TastyTrade SDK provides **both sync and async** versions of most methods. During the 2025-11-07 reconciliation, we discovered that sync methods are often **better for accuracy-critical operations**.

### Sync Methods (Recommended for Scripts & Reconciliation)

```python
from tastytrade import Session, Account

# Use Session (not ProductionSession)
session = Session(username, password)

# Use synchronous methods (no 'a_' prefix, no 'await')
account = Account.get_account(session, account_number)
live_orders = account.get_live_orders(session)
positions = account.get_positions(session)

# Can delete orders synchronously
account.delete_order(session, order_id)
```

**Advantages**:
- ✅ No async context issues
- ✅ No event loop management
- ✅ Direct Python - easier to debug
- ✅ Can use in simple scripts without Django setup complexity
- ✅ **More reliable for one-off operations**

**Disadvantages**:
- ❌ Slower (blocking I/O)
- ❌ Can't parallelize multiple requests
- ❌ Not suitable for high-frequency operations

### Async Methods (For Production Services)

```python
from tastytrade import ProductionSession, Account
import asyncio

async def main():
    session = ProductionSession(username, password)
    account = await Account.a_get(session, account_number)
    live_orders = await account.a_get_live_orders(session)
    # ...

# Must run with event loop
asyncio.run(main())
```

**Advantages**:
- ✅ Fast (non-blocking I/O)
- ✅ Can parallelize requests
- ✅ Better for high-frequency operations

**Disadvantages**:
- ❌ Async/sync context issues
- ❌ Event loop management complexity
- ❌ Harder to debug
- ❌ **Can fail silently if context incorrect**

### Recommendation for Reconciliation

**Use sync methods when**:
- Writing management commands for reconciliation
- Creating one-off diagnostic scripts
- Fixing data issues
- Accuracy matters more than speed
- You want simple, debuggable code

**Use async methods when**:
- Building production services (like real-time trade execution)
- Handling high-frequency market data
- Managing multiple concurrent operations
- Speed is critical

### Example: Reconciliation Script with Sync Methods

```python
#!/usr/bin/env python
"""
Simple reconciliation using SYNC methods.
No async, no event loops, just straightforward Python.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.production')

import django
django.setup()

from tastytrade import Session, Account
from accounts.models import TradingAccount
from trading.models import Position

def main():
    # Get account credentials
    account_model = TradingAccount.objects.first()
    
    # Create SYNC session
    session = Session(account_model.username, account_model.password)
    
    # Get TastyTrade account (SYNC)
    tt_account = Account.get_account(session, account_model.account_number)
    
    # Get live orders (SYNC)
    live_orders = tt_account.get_live_orders(session)
    qqq_orders = [o for o in live_orders if 'QQQ' in o.underlying_symbol]
    
    print(f"TastyTrade has {len(qqq_orders)} live QQQ orders")
    
    # Get database positions
    db_positions = Position.objects.filter(
        symbol='QQQ',
        lifecycle_state__in=['open_full', 'open_partial']
    )
    
    print(f"Database has {db_positions.count()} open QQQ positions")
    
    # Compare
    tt_order_ids = {str(o.id) for o in qqq_orders}
    db_order_ids = set()
    
    for pos in db_positions:
        if pos.profit_target_details:
            for spread_type, details in pos.profit_target_details.items():
                if 'order_id' in details:
                    db_order_ids.add(details['order_id'])
    
    # Find discrepancies
    orphaned = tt_order_ids - db_order_ids
    invalid = db_order_ids - tt_order_ids
    
    print(f"\nOrphaned orders (in TT, not in DB): {len(orphaned)}")
    print(f"Invalid order IDs (in DB, not in TT): {len(invalid)}")
    
    # Fix orphaned orders
    if orphaned:
        print("\nCancelling orphaned orders...")
        for order_id in orphaned:
            try:
                tt_account.delete_order(session, int(order_id))
                print(f"  Cancelled order {order_id}")
            except Exception as e:
                print(f"  Failed to cancel {order_id}: {e}")
    
    print("\nReconciliation complete!")

if __name__ == "__main__":
    main()  # NOT asyncio.run(main())!
```

**Why This Works**:
- No async context errors
- Simple, readable code
- Easy to debug with print statements
- Can run directly: `python script.py`
- No Django async patterns needed

**When This Was Discovered**:
During 2025-11-07 reconciliation, we struggled with async patterns in the `reconcile_qqq_orders` command. Switching to sync methods would have been simpler and more reliable for this one-off operation.

---

## Future Improvements

See `docs/guides/DATA_MODEL_IMPROVEMENTS_PLAN.md` for comprehensive plan including:
- Trading activity log for full audit trail
- Proper Order model (replacing JSON fields)
- Individual spread tracking
- Enhanced P&L calculations
- Self-healing reconciliation system
