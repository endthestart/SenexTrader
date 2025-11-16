# Async/Sync Patterns - Developer Guide

**Last Updated**: 2025-11-06
**Purpose**: Definitive guide to avoid async/sync context errors in Senex Trader

---

## The Core Problem

Senex Trader has **two conflicting requirements**:

| Component | Type | Why |
|-----------|------|-----|
| **Django ORM** | Sync-only | `Position.objects.get()`, `Trade.objects.filter()` |
| **TastyTrade SDK** | Async-only | `await session.get_account()`, `await account.a_delete_order()` |

**Mixing these incorrectly causes:**
```python
django.core.exceptions.SynchronousOnlyOperation:
You cannot call this from an async context - use a thread or sync_to_async.
```

---

## Pattern 1: Management Commands (RECOMMENDED)

### ✅ Correct Pattern: Pure Sync + Event Loop

```python
from django.core.management.base import BaseCommand
import asyncio
from trading.models import Position

class Command(BaseCommand):
    def handle(self, *args, **options):
        # ✅ Sync Django ORM - works directly
        position = Position.objects.get(id=33)

        # ✅ Call async functions via event loop
        result = self._call_async_api(position.user, order_id)

    def _call_async_api(self, user, order_id):
        """Wrapper for async API calls."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Run async code here
            session = loop.run_until_complete(get_oauth_session(user))
            account = loop.run_until_complete(get_primary_tastytrade_account(user))
            result = loop.run_until_complete(
                self._cancel_order_async(session, account, order_id)
            )
            return result
        finally:
            loop.close()  # CRITICAL: Always close the loop

    async def _cancel_order_async(self, session, account, order_id):
        """Pure async function - no Django ORM here!"""
        from tastytrade import Account

        tt_account = await Account.a_get(session, account.account_number)
        await tt_account.a_delete_order(session, int(order_id))
        return True
```

### ⚠️ When Async Helpers Need Django ORM

If your async helper needs to save to the database, use `sync_to_async`:

```python
from asgiref.sync import sync_to_async

class Command(BaseCommand):
    def handle(self, *args, **options):
        # Sync Django ORM
        position = Position.objects.get(id=33)

        # Call async helper that needs to save
        result = self._create_order_and_save(position)

    def _create_order_and_save(self, position):
        """Wrapper for async work that includes DB saves."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                self._async_create_order(position)
            )
            return result
        finally:
            loop.close()

    async def _async_create_order(self, position):
        """Async function that needs to save to DB."""
        # ✅ Async SDK work
        session = await get_oauth_session(position.user)
        order = await create_order(session)

        # ❌ WRONG: Direct ORM call
        # position.profit_target_details['new_order'] = order.id
        # position.save()  # ERROR!

        # ✅ CORRECT: Use sync_to_async
        position.profit_target_details['new_order'] = order.id
        await sync_to_async(position.save)()

        return order
```

**Why This Matters**: Even though you're using Pattern 1 (management command), once you're inside an `async def` function, ALL Django ORM calls must use `sync_to_async`.

**Key Rules:**
1. ✅ Django ORM calls stay in `handle()` or sync methods
2. ✅ Async SDK calls go in separate `async def` methods
3. ✅ Bridge them with `asyncio.new_event_loop()`
4. ✅ ALWAYS `loop.close()` in `finally` block
5. ⚠️ **CRITICAL**: If async helpers need Django ORM, use `sync_to_async`

### ❌ What NOT to Do

```python
# ❌ WRONG: Async function calling Django ORM
async def fix_position():
    position = Position.objects.get(id=33)  # ERROR!
    await cancel_order(order_id)

# ❌ WRONG: Mixing sync/async without proper loop
def handle(self):
    await cancel_order(order_id)  # ERROR!
```

---

## Pattern 2: Using run_async Helper

For simple cases, use our helper:

```python
from services.utils.async_utils import run_async

class Command(BaseCommand):
    def handle(self, *args, **options):
        # ✅ Django ORM - sync
        position = Position.objects.get(id=33)

        # ✅ Use run_async for async calls
        result = run_async(self._async_operation(position.user))

    async def _async_operation(self, user):
        """Pure async - no Django ORM!"""
        session = await get_oauth_session(user)
        return await session.get_account()
```

**When to use `run_async`:**
- ✅ Simple one-off async calls
- ✅ You want cleaner code
- ❌ Avoid for complex loops or error handling

---

## Pattern 3: Service Methods with _sync Versions

**Best practice for reusable code**: Provide both versions.

### In Service Class

```python
# services/execution/order_service.py

class OrderExecutionService:

    async def create_profit_targets(self, position, parent_order_id):
        """Async version - for use in async contexts."""
        # Implementation with async SDK calls
        pass

    def create_profit_targets_sync(self, position, parent_order_id):
        """
        Synchronous version - for management commands and Celery tasks.

        Uses run_async internally to bridge to async implementation.
        """
        from services.utils.async_utils import run_async
        return run_async(
            self.create_profit_targets(position, parent_order_id)
        )
```

### Usage in Management Command

```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        position = Position.objects.get(id=33)

        service = OrderExecutionService(position.user)
        # ✅ Use the _sync version
        result = service.create_profit_targets_sync(
            position,
            opening_trade.broker_order_id
        )
```

**Examples in codebase:**
- `OrderExecutionService.create_profit_targets_sync()`
- `MarketDataService.get_quote_sync()`
- `SenexTridentStrategy.get_profit_target_specifications_sync()`

---

## Pattern 4: Celery Tasks

Celery tasks run in sync context but often need async SDK calls.

```python
from celery import shared_task
from services.utils.async_utils import run_async

@shared_task
def sync_positions_task():
    """Celery task - sync function."""

    # ✅ Django ORM - direct access
    users = User.objects.filter(is_active=True)

    for user in users:
        # ✅ Use run_async for async operations
        result = run_async(_async_sync_user_positions(user))

async def _async_sync_user_positions(user):
    """Helper async function - no Django ORM here!"""
    session = await get_oauth_session(user)
    # ... async SDK calls
```

**Key Rules:**
1. ✅ Task function itself is sync (`def`, not `async def`)
2. ✅ Django ORM calls in task function
3. ✅ Async SDK calls in separate `async def` helpers
4. ✅ Use `run_async()` to bridge them

---

## Pattern 5: One-Off Scripts

One-off scripts follow the same pattern as management commands.

### Template for One-Off Scripts

```python
#!/usr/bin/env python
"""One-off script template."""
import asyncio
import os
import sys

# Django setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senex_trader.settings.production')

import django
django.setup()

from trading.models import Position
from services.data_access import get_oauth_session

def main():
    """Main sync function - Django ORM lives here."""
    print("Starting script...")

    # ✅ Django ORM - sync
    positions = Position.objects.filter(symbol='QQQ')

    for position in positions:
        # ✅ Call async via helper
        result = call_async_api(position.user, position.id)
        print(f"Position {position.id}: {result}")

def call_async_api(user, position_id):
    """Bridge to async API calls."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(_async_work(user, position_id))
        return result
    finally:
        loop.close()

async def _async_work(user, position_id):
    """Pure async function - NO Django ORM here!"""
    session = await get_oauth_session(user)
    # ... async SDK calls
    return {"status": "success"}

if __name__ == "__main__":
    main()  # NOT asyncio.run(main())!
```

**Critical Points:**
1. ✅ `main()` is sync (NOT `async def main()`)
2. ✅ Django setup before any imports
3. ✅ Use event loop pattern, not `asyncio.run()`
4. ❌ NEVER `if __name__ == "__main__": asyncio.run(main())`

---

## Pattern 6: When You Need Django ORM in Async Context

Sometimes you genuinely need to query the database from async code.

### Use sync_to_async

```python
from asgiref.sync import sync_to_async

async def async_function():
    """Async function that needs Django ORM."""

    # ❌ WRONG: Direct ORM call
    # position = Position.objects.get(id=33)

    # ✅ CORRECT: Wrap in sync_to_async
    position = await sync_to_async(Position.objects.get)(id=33)

    # Or for queries:
    positions = await sync_to_async(list)(
        Position.objects.filter(symbol='QQQ')
    )
```

**When to use:**
- Async views (Django Channels, ASGI)
- Async WebSocket consumers
- Stream processing pipelines

**When NOT to use:**
- Management commands (use Pattern 1)
- Celery tasks (use Pattern 4)
- One-off scripts (use Pattern 5)

---

## Common Mistakes & Fixes

### Mistake 1: Async Function Calling Django ORM

```python
# ❌ WRONG
async def fix_position():
    position = Position.objects.get(id=33)  # ERROR!
```

**Fix: Make it sync**
```python
# ✅ CORRECT
def fix_position():
    position = Position.objects.get(id=33)
    result = call_async_helper(position.user)
```

### Mistake 2: Using asyncio.run() in Scripts

```python
# ❌ WRONG
if __name__ == "__main__":
    asyncio.run(main())  # main() is async def
```

**Fix: Make main() sync**
```python
# ✅ CORRECT
def main():  # Sync function
    position = Position.objects.get(id=33)
    result = call_async_via_loop()

if __name__ == "__main__":
    main()  # Direct call
```

### Mistake 3: Forgetting to Close Event Loop

```python
# ❌ WRONG
def call_api():
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(async_call())
    # Loop never closed - memory leak!
    return result
```

**Fix: Always use try/finally**
```python
# ✅ CORRECT
def call_api():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(async_call())
        return result
    finally:
        loop.close()  # ALWAYS close
```

### Mistake 4: Mixing Contexts in Same Function

```python
# ❌ WRONG
async def process_position():
    position = Position.objects.get(id=33)  # Sync in async!
    await cancel_order(order_id)  # This won't even run
```

**Fix: Separate concerns OR use sync_to_async**
```python
# ✅ CORRECT Option 1: Keep ORM in sync functions
def process_position():
    position = Position.objects.get(id=33)  # Sync
    result = call_async_safely(position)  # Bridge
    return result

def call_async_safely(position):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_async_work(position.user))
    finally:
        loop.close()

async def _async_work(user):
    # Pure async - no ORM
    pass

# ✅ CORRECT Option 2: Use sync_to_async if async function needs ORM
from asgiref.sync import sync_to_async

async def process_position():
    # Bridge to sync for ORM
    position = await sync_to_async(Position.objects.get)(id=33)
    await cancel_order(order_id)

    # Save changes
    await sync_to_async(position.save)()
```

**When to use each**:
- Option 1: Management commands, scripts (Pattern 1)
- Option 2: Async views, consumers, when already in async context

---

## Decision Tree: Which Pattern to Use?

```
Are you writing...

├─ Management Command?
│  └─ Use Pattern 1 (Pure Sync + Event Loop)
│
├─ Celery Task?
│  └─ Use Pattern 4 (run_async helper)
│
├─ One-Off Script?
│  └─ Use Pattern 5 (Same as management command)
│
├─ Service Method?
│  └─ Use Pattern 3 (Provide both _sync and async)
│
├─ Async View/Consumer?
│  └─ Use Pattern 6 (sync_to_async for ORM)
│
└─ Quick Helper?
   └─ Use Pattern 2 (run_async helper)
```

---

## Real Examples from Codebase

### ✅ Working: fix_call_spread_profit_targets.py

```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        # Sync Django ORM
        positions = self._find_affected_positions()

        for position in positions:
            self._fix_position(position)  # Sync wrapper

    def _fix_position(self, position):
        # Cancel order via async bridge
        self._cancel_order_sync(position.user, old_order_id)

        # Create new targets via sync method
        service = OrderExecutionService(position.user)
        result = service.create_profit_targets_sync(...)

    def _cancel_order_sync(self, user, order_id):
        """Proper async bridge."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            session = loop.run_until_complete(get_oauth_session(user))
            # ... async work
        finally:
            loop.close()
```

### ✅ Working: trading/tasks.py

```python
@shared_task
def batch_sync_data_task(self):
    """Celery task - sync."""

    # Task 1: Sync positions
    try:
        logger.info("Syncing positions...")
        result = run_async(_async_sync_positions())  # ✅ run_async
    except Exception as e:
        logger.error(f"Failed: {e}")

async def _async_sync_positions():
    """Pure async helper."""
    # No Django ORM here!
    pass
```

---

## Testing Your Code

### Quick Test Checklist

1. **Can run standalone?**
   ```bash
   python scripts/my_script.py
   # OR
   python manage.py my_command
   ```

2. **No SynchronousOnlyOperation errors?**
   - Check logs for the error
   - If you see it, review patterns above

3. **Event loops closed?**
   - Check for `finally: loop.close()`
   - Run multiple times - no memory growth?

4. **Django ORM in sync context?**
   - All `.objects.get()` calls in sync functions?
   - No ORM in `async def` functions (unless using `sync_to_async`)?

---

## Quick Reference Card

| Context | Django ORM | TastyTrade SDK | Bridge |
|---------|-----------|----------------|--------|
| **Management Command** | Direct `Position.objects.get()` | `loop.run_until_complete()` | Event loop pattern |
| **Celery Task** | Direct `Position.objects.get()` | `run_async()` | `run_async` helper |
| **Service Method** | Direct (in `_sync` version) | In async version | Provide both |
| **One-Off Script** | Direct in `main()` | Event loop helper | Event loop pattern |
| **Async View** | `sync_to_async()` | Direct `await` | `sync_to_async` |

---

## Summary: Golden Rules

1. **Django ORM = Sync Context Only**
   - Never call `Position.objects.get()` in `async def` without `sync_to_async`
   - **Exception**: `async def` helpers CAN use ORM with `await sync_to_async(model.save)()`

2. **TastyTrade SDK = Async Only**
   - Never call SDK directly in sync context
   - Use event loop or `run_async()` helper

3. **Management Commands & Scripts = Sync Main, Async Helpers OK**
   - Main entry point is `def`, NOT `async def`
   - Use event loop pattern for async SDK calls
   - Async helpers can use `sync_to_async` for ORM needs

4. **Always Close Event Loops**
   - Use `try/finally` with `loop.close()`
   - Or use `run_async()` which handles it

5. **Provide _sync Methods in Services**
   - Makes life easier for management commands
   - Uses `run_async` internally

6. **When in Doubt, Separate Concerns**
   - Sync function for Django ORM (preferred)
   - Async function for SDK calls
   - Bridge function with event loop
   - Use `sync_to_async` only when necessary

7. **sync_to_async is Your Friend**
   - Not a code smell when used properly
   - Necessary for ORM access in async helpers
   - Better than contorting code to avoid it

---

## Getting Help

If you encounter async/sync issues:

1. **Check the error message**:
   - `SynchronousOnlyOperation` → Django ORM in async context
   - `RuntimeError: no running event loop` → Async call in sync context

2. **Review this guide** and match your pattern

3. **Look for working examples**:
   - `trading/management/commands/fix_call_spread_profit_targets.py`
   - `services/execution/order_service.py` (`_sync` methods)
   - `trading/tasks.py` (Celery patterns)

4. **Test incrementally**:
   - Add print statements
   - Run with `--dry-run` if available
   - Test one position/operation first

---

## Historical Lessons Learned

This guide consolidates years of hard-won lessons from production async/sync issues.

### Lesson 1: Event Loop Closure (Oct 2025)

**Problem**: After `run_async()` closed event loops, HTTP clients tried cleanup on closed loops.
```python
# ❌ WRONG: Validation after loop closes
session = run_async(get_session())
validate_session(session)  # Boom - loop already closed!
```

**Fix**: Trust service layers. Don't add validation at call sites.
```python
# ✅ CORRECT: Service handles validation internally
session = await TastyTradeSessionService.get_session_for_user(...)
# Session is already validated, ready to use
```

### Lesson 2: ForeignKey Access in Async (Oct 2025)

**Problem**: `account.user` triggered sync DB query in async context.
```python
# ❌ WRONG
async def process():
    account = await get_account(user)
    email = account.user.email  # ERROR - sync query!
```

**Fix**: Use `select_related()` to prefetch.
```python
# ✅ CORRECT
async def get_account(user):
    return await TradingAccount.objects.select_related('user').afirst()
```

### Lesson 3: Data Corruption from Async Errors (Nov 2025)

**Problem**: Positions 33 & 34 corrupted because async script mixed Django ORM with async calls.
- Position 33: Wrong `child_order_ids`
- Position 34: Duplicate order references

**Root Cause**: Script used `async def main()` and `asyncio.run()`, triggering `SynchronousOnlyOperation` errors mid-execution.

**Fix**: Use Pattern 1 (Pure Sync + Event Loop) for scripts and management commands.

### Lesson 4: Redundant Validation Layers

**Anti-pattern**: Adding validation wrappers around services that already validate.
```python
# ❌ WRONG: Double validation
session = await get_session(user)
if not await validate(session):  # Service already did this!
    refresh()
```

**Principle**: **Trust the service layer.** If it returns success, it's valid.

### Lesson 5: Run_Async vs Event Loop Pattern

**When to use `run_async` helper**:
- ✅ Simple one-off async calls
- ✅ Celery tasks with clear error boundaries
- ✅ Service methods providing sync wrappers

**When to use `asyncio.new_event_loop()` pattern**:
- ✅ Management commands (better control)
- ✅ One-off scripts (explicit lifecycle)
- ✅ Complex error handling needs
- ✅ Multiple sequential async calls

### Lesson 6: Django ORM in Async Helpers (Nov 2025)

**Problem**: Management command using Pattern 1 added async helper that called `position.save()`.
```python
# ❌ WRONG: Even in Pattern 1, can't call ORM in async helpers
class Command(BaseCommand):
    def handle(self):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._async_work(position))

    async def _async_work(self, position):
        order = await create_order_at_tastytrade()
        position.profit_target_details['order_id'] = order.id
        position.save()  # ERROR: SynchronousOnlyOperation!
```

**Root Cause**: Once inside `async def`, you're in async context. Django ORM is sync-only.

**Fix**: Use `sync_to_async` for ORM calls within async functions.
```python
# ✅ CORRECT
from asgiref.sync import sync_to_async

async def _async_work(self, position):
    order = await create_order_at_tastytrade()
    position.profit_target_details['order_id'] = order.id
    await sync_to_async(position.save)()  # Proper bridge
```

**Key Insight**: Pattern 1 doesn't mean "never use sync_to_async". It means:
- Main `handle()` stays sync (pure Django ORM access)
- Event loop wrappers stay sync
- **But async helpers that need ORM use `sync_to_async`**

**Real-world case**: `fix_call_spread_profit_targets.py` management command (Nov 2025)
- 7 positions needed profit target fixes
- Service failed (missing TradingSuggestions)
- Fallback built orders manually in async helper
- Had to use `sync_to_async(position.save)()` to update database
- **Also learned**: Must use `.select_related('user')` when passing Position objects to async functions to avoid lazy-loading the user relation in async context

---

## Related Documentation

- `docs/patterns/REALTIME_DATA_FLOW_PATTERN.md` - Real-time data architecture
- `docs/guides/TASTYTRADE_SDK_BEST_PRACTICES.md` - TastyTrade SDK patterns
- `docs/architecture/ADR-043-Session-Per-Task-Pattern.md` - Session lifecycle management

---

**Remember**: When mixing Django ORM (sync) with TastyTrade SDK (async), **keep them in separate functions** and use proper bridges. That's the secret to avoiding async/sync hell.
