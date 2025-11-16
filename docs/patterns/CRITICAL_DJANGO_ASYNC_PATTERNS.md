# CRITICAL: Django Async Patterns - Management Commands & ORM

**⚠️ CRITICAL DOCUMENTATION - READ BEFORE IMPLEMENTING ASYNC IN DJANGO**

## Executive Summary

Django management commands encounter **critical async/sync boundary issues** when using `asyncio.run()` with the Django ORM. The solution is to use **synchronous execution** for management commands, even when calling async services.

## The Problem: Django ORM vs Asyncio Event Loop

### What Went Wrong

When implementing the `create_profit_targets` management command, we initially tried:

```python
# ❌ FAILED APPROACH
class Command(BaseCommand):
    def handle(self, *args, **options):
        asyncio.run(self._async_handle(options))

    async def _async_handle(self, options):
        position = await sync_to_async(Position.objects.get)(id=1)
        # Error: "You cannot call this from an async context"
```

### The Root Cause

1. **Django ORM is synchronous** - Database operations are fundamentally sync
2. **`asyncio.run()` creates a new event loop** - Conflicts with Django's internal handling
3. **`sync_to_async` has limitations** - Not all Django ORM operations work reliably
4. **Management commands run in a special context** - Different from web requests

### The Error Messages

```
SynchronousOnlyOperation: You cannot call this from an async context - use a thread or sync_to_async
```

This occurs when Django detects you're in an async context but trying to perform sync database operations.

## The Solution: Synchronous Execution Pattern

### Working Pattern for Management Commands

```python
# ✅ CORRECT APPROACH
class Command(BaseCommand):
    def handle(self, *args, **options):
        """Handle the command execution synchronously."""
        # Direct synchronous execution
        position = Position.objects.get(id=options['position'])
        service = OrderExecutionService(position.user)
        result = service.create_profit_targets_sync(position, order_id)
```

### Key Implementation Details

1. **Service Layer Pattern**: Create separate sync methods in services
```python
class OrderExecutionService:
    # Async version for web requests
    async def create_profit_targets(self, position, order_id):
        # Async implementation

    # Sync version for management commands
    def create_profit_targets_sync(self, position, order_id):
        # Synchronous implementation
        # Uses sync_to_async() for specific OAuth operations
```

2. **OAuth Session Handling**: Use `async_to_sync` for specific async operations
```python
from asgiref.sync import async_to_sync

# Convert async OAuth session retrieval to sync
session_result = async_to_sync(TastyTradeSessionService.get_session_for_user)(
    user.id, refresh_token
)
```

3. **Environment Variable Loading**: Load dotenv in manage.py
```python
# manage.py
from pathlib import Path
from dotenv import load_dotenv

def main():
    # Load .env BEFORE Django settings
    BASE_DIR = Path(__file__).resolve().parent
    load_dotenv(BASE_DIR / ".env")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")
```

## When to Use Each Pattern

### Use Synchronous Pattern When:
- **Django Management Commands** - Always use sync
- **Database Migrations** - Always sync
- **Admin Commands** - Sync by default
- **Simple Scripts** - Sync is simpler and reliable

### Use Async Pattern When:
- **Web Views/API Endpoints** - Can benefit from async
- **WebSocket Consumers** - Async required
- **Streaming Operations** - Async for real-time data
- **External API Calls** - Async for concurrent requests

## Common Pitfalls & Solutions

### Pitfall 1: Mixing Sync/Async in Management Commands
```python
# ❌ WRONG - Causes "cannot call from async context"
def handle(self):
    asyncio.run(self.async_method())

# ✅ CORRECT - Pure synchronous
def handle(self):
    self.sync_method()
```

### Pitfall 2: Using sync_to_async with Complex Queries
```python
# ❌ UNRELIABLE - Complex queries may fail
positions = await sync_to_async(
    lambda: Position.objects.filter(user=user).select_related('trade_set')
)()

# ✅ RELIABLE - Simple queries or sync execution
positions = Position.objects.filter(user=user).select_related('trade_set')
```

### Pitfall 3: Database Updates in Async Context
```python
# ❌ WRONG - Database writes in async context
async def update_position():
    position.lifecycle_state = 'closed'
    await sync_to_async(position.save)()  # May fail

# ✅ CORRECT - Synchronous database updates
def update_position():
    position.lifecycle_state = 'closed'
    position.save()  # Reliable
```

## The run_async Pattern

For cases where you need to call async code from sync context:

```python
from services.utils.async_utils import run_async

# Existing pattern in codebase
def sync_method():
    # Call async function from sync context
    result = run_async(async_function())
```

However, for management commands, **prefer pure synchronous implementation** over run_async wrapper.

## Real Example: Profit Target Creation

### Original Problem
- Manual Senex position needed automated GTC closing orders
- Management command required to create profit targets
- Initial async approach failed with Django ORM errors

### Solution Applied
1. Created `create_profit_targets_sync()` method in OrderExecutionService
2. Used synchronous Django ORM queries throughout
3. Converted only OAuth session calls using `async_to_sync`
4. Successfully created real TastyTrade orders (IDs: 409855296, 409855297, 409855298)

### Code Structure
```
management/commands/create_profit_targets.py  # Synchronous command
    ↓ calls
OrderExecutionService.create_profit_targets_sync()  # Sync method
    ↓ uses
- Django ORM directly (sync)
- async_to_sync(OAuth operations) when needed
```

## Testing Considerations

### Test Mode Database Updates
```python
# Ensure test mode doesn't update database
if not self.is_test:
    position.profit_targets_created = True
    position.save()
```

### Price Rounding Requirements
```python
# Different options require different increments
from services.utils.pricing_utils import round_option_price

# SPX options: $0.05 increments
# Regular options: $0.01 increments
target_price = round_option_price(raw_price, underlying_symbol)
```

## Key Takeaways

1. **Django management commands should be synchronous** - Avoid asyncio.run()
2. **Create separate sync methods in services** - Don't force async everywhere
3. **Load environment variables early** - In manage.py before Django settings
4. **Use async_to_sync sparingly** - Only for specific async operations
5. **Test both sync and async paths** - They may behave differently
6. **Document the pattern** - Future developers need to understand why

## When This Matters

- **Every Django management command** - Follow sync pattern
- **Data migration scripts** - Use synchronous execution
- **Batch processing jobs** - Sync is more reliable
- **Integration with async services** - Create sync wrapper methods

## References

- Django async views documentation
- asgiref sync/async conversion utilities
- Original implementation: PR for Senex position #37 profit targets
- TastyTrade API order creation patterns

---

**REMEMBER**: When in doubt with Django management commands, **choose synchronous execution**. It's simpler, more reliable, and avoids the complex async/sync boundary issues that Django's ORM presents.
