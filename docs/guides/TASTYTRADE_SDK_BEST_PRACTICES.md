# TastyTrade SDK Best Practices for Senex Trader

**Last Updated:** 2025-10-19
**SDK Version:** tastytrade v10.3.0+

This document provides project-specific best practices for using the TastyTrade Python SDK in the Senex Trader codebase. These patterns have been battle-tested in production and align with the project's architecture.

---

## Table of Contents

1. [Session Management](#session-management)
2. [Instrument Handling](#instrument-handling)
3. [Order Construction](#order-construction)
4. [Error Handling](#error-handling)
5. [Async Patterns](#async-patterns)
6. [Testing & Sandbox](#testing--sandbox)
7. [Common Pitfalls](#common-pitfalls)
8. [Code Examples](#code-examples)

---

## Session Management

### ✅ DO: Use Singleton Pattern with Automatic Refresh

**Pattern:** `services/brokers/tastytrade_session.py:TastyTradeSessionService`

```python
from services.brokers.tastytrade_session import TastyTradeSessionService

# Get session for user (automatically creates/refreshes)
session_result = await TastyTradeSessionService.get_session_for_user(
    user_id=user.id,
    refresh_token=account.refresh_token,
    is_test=account.is_test
)

if session_result.get("success"):
    session = session_result.get("session")
    # Use session for API calls
else:
    # Handle error with details
    error_type = session_result.get("error_type")
    retry = session_result.get("retry_recommended")
```

**Why this matters:**
- Sessions expire after 15 minutes
- Singleton pattern prevents duplicate sessions per user
- Automatic background refresh prevents mid-task expirations
- Handles OAuth token rotation (user reconnection)
- Thread-safe for Celery tasks

### ✅ DO: Always Call `a_refresh()` After Creating Session

```python
from tastytrade import OAuthSession

session = OAuthSession(
    provider_secret=client_secret,
    refresh_token=refresh_token,
    is_test=is_test
)

# CRITICAL: Generates fresh 15-minute session_token
await session.a_refresh()
```

**Reference:** `services/brokers/tastytrade_session.py:159-165`

### ❌ DON'T: Create Sessions Directly in Strategy Code

**Bad:**
```python
# ❌ Creates orphaned sessions, no refresh, token waste
session = OAuthSession(secret, token)
```

**Good:**
```python
# ✅ Uses managed singleton with automatic lifecycle
session = await TastyTradeSessionService.get_session_for_user(...)
```

---

## Instrument Handling

### ✅ DO: Use SDK's `Option.a_get()` for Symbol Validation

**Pattern:** `services/utils/sdk_instruments.py:get_option_instrument()`

```python
from tastytrade.instruments import Option as TastytradeOption
from services.utils.sdk_instruments import get_option_instrument

# Fetch instrument with SDK validation
option = await get_option_instrument(
    session=session,
    underlying='SPY',
    expiration=date(2025, 11, 7),
    strike=Decimal('591.00'),
    option_type='P'  # 'C' or 'P'
)

# SDK-validated OCC symbol
occ_symbol = option.symbol  # 'SPY   251107P00591000'
```

**Why this matters:**
- SDK validates symbol format server-side
- Enriches data with market info (liquidity, greeks)
- Auto-updates if TastyTrade changes OCC format
- Type-safe Pydantic models

### ✅ DO: Batch Fetch Instruments for Multi-Leg Orders

**Pattern:** `services/utils/sdk_instruments.py:get_option_instruments_bulk()`

```python
specs = [
    {'underlying': 'SPY', 'expiration': exp, 'strike': Decimal('591'), 'option_type': 'P'},
    {'underlying': 'SPY', 'expiration': exp, 'strike': Decimal('586'), 'option_type': 'P'},
]

options = await get_option_instruments_bulk(session, specs)
# Returns List[TastytradeOption]
```

**Performance:** Single batch fetch vs N sequential fetches.

### ✅ DO: Use `build_occ_symbol()` for Backward Compatibility

**Pattern:** `services/utils/sdk_instruments.py:build_occ_symbol()`

```python
from services.utils.sdk_instruments import build_occ_symbol

# For database storage, display, or when SDK fetch not needed
occ = build_occ_symbol('SPY', date(2025, 11, 7), Decimal('591.00'), 'P')
# 'SPY   251107P00591000'
```

**Use cases:**
- Storing symbols in database
- Displaying symbols in UI
- Testing without API calls
- Symbol parsing/validation

### ❌ DON'T: Hand-Craft OCC Symbols with String Formatting

**Bad:**
```python
# ❌ Error-prone, no validation, breaks if format changes
symbol = f"{ticker}{exp_str}C{strike_int:08d}"
```

**Good:**
```python
# ✅ Uses tested utility with validation
symbol = build_occ_symbol(ticker, exp_date, strike, 'C')
```

---

## Order Construction

### ✅ DO: Use `tastytrade.order.Leg` for Order Legs

**Pattern:** `services/utils/order_builder_utils.py:build_opening_spread_legs()`

```python
from tastytrade.order import Leg, InstrumentType, OrderAction

# Create SDK Leg objects
leg = Leg(
    instrument_type=InstrumentType.EQUITY_OPTION,
    symbol=option.symbol,  # From SDK Option object
    action=OrderAction.SELL_TO_OPEN,
    quantity=contracts
)
```

**Reference:** `services/senex_trident_strategy.py:745-813`

### ✅ DO: Use Enums for Type Safety

```python
from tastytrade.order import InstrumentType, OrderAction, OrderType, OrderTimeInForce

# Instrument types
InstrumentType.EQUITY_OPTION  # For options
InstrumentType.EQUITY         # For stock

# Order actions
OrderAction.SELL_TO_OPEN   # Open short position
OrderAction.BUY_TO_OPEN    # Open long position
OrderAction.BUY_TO_CLOSE   # Close short position
OrderAction.SELL_TO_CLOSE  # Close long position

# Order types
OrderType.LIMIT            # Limit order
OrderType.MARKET           # Market order

# Time in force
OrderTimeInForce.DAY       # Good for day
OrderTimeInForce.GTC       # Good till cancelled
```

### ✅ DO: Use Shared Leg Builders

**Pattern:** `services/utils/order_builder_utils.py`

```python
from services.utils.order_builder_utils import build_opening_spread_legs

# For credit/debit spreads
legs = await build_opening_spread_legs(
    session=session,
    underlying_symbol='SPY',
    expiration_date=expiration,
    spread_type='put_spread',  # or 'call_spread'
    strikes={'short_put': Decimal('591'), 'long_put': Decimal('586')},
    quantity=contracts
)
```

**Benefits:**
- DRY principle (no duplicate leg construction)
- Strategies own strike/expiration logic
- Shared helper handles SDK plumbing
- Consistent across all strategies

### ✅ DO: Understand Credit vs Debit Price Effects

**Pattern:** `services/utils/trading_utils.py:PriceEffect`

```python
from services.utils.trading_utils import PriceEffect

# CREDIT = Receive money (positive price)
# Examples: Selling spreads, covered calls
net_credit = Decimal('2.50')
price = net_credit  # Positive for credits

# DEBIT = Pay money (negative price)
# Examples: Buying spreads, long straddles
net_debit = Decimal('3.00')
price = -net_debit  # Negative for debits

# Validate before order placement
effect = PriceEffect.CREDIT if price > 0 else PriceEffect.DEBIT
```

**Reference:** `services/execution/order_service.py:141-149`

### ❌ DON'T: Mix Up Credit/Debit Signs

**Bad:**
```python
# ❌ Credit order with negative price (SDK will reject)
order = NewOrder(price=-Decimal('2.50'), ...)  # Wrong!
```

**Good:**
```python
# ✅ Credit = positive, Debit = negative
credit_price = Decimal('2.50')   # Positive
debit_price = -Decimal('3.00')   # Negative
```

---

## Error Handling

### ✅ DO: Categorize Errors for Smart Retry Logic

**Pattern:** `services/brokers/tastytrade_session.py:categorize_error()`

```python
from services.brokers.session_helpers import (
    SessionErrorType,
    categorize_error,
    categorize_refresh_error
)

try:
    await session.a_refresh()
except Exception as e:
    error_type = categorize_refresh_error(e)

    if error_type == SessionErrorType.EXPIRED_TOKEN:
        # User must reconnect OAuth
        await mark_account_token_invalid(user_id)
    elif error_type in [SessionErrorType.NETWORK_ERROR, SessionErrorType.TEMPORARY_ERROR]:
        # Retry recommended
        await retry_with_backoff()
    else:
        # Log and fail gracefully
        logger.error(f"Unrecoverable error: {e}")
```

**Error categories:**
- `AUTHENTICATION_ERROR` - Bad credentials (no retry)
- `EXPIRED_TOKEN` - OAuth reconnection needed (no retry)
- `NETWORK_ERROR` - Transient failure (retry)
- `TIMEOUT_ERROR` - Took too long (retry with longer timeout)
- `RATE_LIMIT` - API throttled (retry with backoff)
- `TEMPORARY_ERROR` - Server issue (retry)
- `SDK_ERROR` - Bug or version mismatch (no retry)

### ✅ DO: Use Timeouts for All SDK Calls

**Pattern:** `services/brokers/tastytrade_session.py:163-172`

```python
import asyncio

try:
    async with asyncio.timeout(10):  # 10 second timeout
        await session.a_refresh()
except TimeoutError:
    logger.error("Session refresh timeout after 10s")
    # Handle timeout-specific logic
```

**Recommended timeouts:**
- Session creation/refresh: 10 seconds
- Session validation: 5 seconds
- Option chain fetch: 15 seconds
- Order placement: 10 seconds

### ✅ DO: Use Custom Exceptions for Business Logic

**Pattern:** `services/exceptions.py`

```python
from services.exceptions import (
    OAuthSessionError,
    StalePricingError,
    OrderBuildError,
    InvalidPriceEffectError
)

# Raise specific exceptions with context
if not session:
    raise OAuthSessionError(
        user_id=user.id,
        message="Unable to authenticate with TastyTrade"
    )

if pricing_age > max_age:
    raise StalePricingError(
        suggestion_id=suggestion.id,
        age_seconds=pricing_age
    )
```

**Reference:** `services/execution/order_service.py:85-103`

---

## Async Patterns

### ✅ DO: Use Async SDK Methods (Prefer `a_*` Methods)

**Pattern:** All async code paths

```python
# ✅ Async methods (preferred)
await session.a_refresh()
await session.a_validate()
option = await TastytradeOption.a_get(session, symbol)
accounts = await Account.a_get(session)

# ❌ Sync methods (avoid in async contexts)
session.refresh()  # Blocks event loop!
```

**Why:** Non-blocking I/O, better concurrency, Django Channels compatibility.

### ✅ DO: Handle Event Loop Lifecycle

**Pattern:** `services/brokers/tastytrade_session.py:429-458`

```python
# Detect closed event loops in cached sessions
if hasattr(session, '_session') and hasattr(session._session, '_loop'):
    loop = session._session._loop
    if loop and loop.is_closed():
        logger.warning("Session has closed event loop, creating new session")
        clear_session(user_id)
        # Create new session in current event loop
```

**Critical for:** Celery tasks, background workers, Django Channels consumers.

### ❌ DON'T: Mix Sync and Async Code

**Bad:**
```python
# ❌ Blocking in async function
def some_function():
    session.refresh()  # Sync call blocks event loop
```

**Good:**
```python
# ✅ Async all the way
async def some_function():
    await session.a_refresh()  # Non-blocking
```

---

## Testing & Sandbox

### ✅ DO: Use `is_test` Flag for Sandbox Mode

**Pattern:** `services/brokers/tastytrade_session.py:80-86`

```python
# Sandbox (no real money, test data)
session = OAuthSession(
    provider_secret=secret,
    refresh_token=token,
    is_test=True  # ← Uses cert.tastytrade.com
)

# Production (real money, real market)
session = OAuthSession(
    provider_secret=secret,
    refresh_token=token,
    is_test=False  # ← Uses api.tastytrade.com
)
```

**Controlled by:** `TradingAccount.is_test` field in database.

**Reference:** `services/execution/order_service.py:74-79`

### ✅ DO: Log Sandbox Mode Clearly

```python
if account.is_test:
    logger.warning(
        f"🧪 SANDBOX MODE: Order for {symbol} "
        f"will be submitted to TastyTrade sandbox environment"
    )
```

**Prevents:** Accidentally thinking sandbox orders are real trades.

### ✅ DO: Use `dry_run=True` for Order Validation

```python
from tastytrade.order import NewOrder

# Test order without placing it
response = account.place_order(session, order, dry_run=True)

# Check impact before committing
buying_power_impact = response.buying_power_effect.change_in_buying_power
if abs(buying_power_impact) > max_allowed:
    raise ValueError("Order exceeds buying power limits")

# Place for real
response = account.place_order(session, order, dry_run=False)
```

**Reference:** SDK skill doc - `skills/tastytrade-sdk/SKILL.md:106-111`

---

## Common Pitfalls

### ❌ PITFALL 1: Forgetting to Refresh New Sessions

**Problem:**
```python
session = OAuthSession(secret, token)
# ❌ No a_refresh() call - session_token might be stale
await TastytradeOption.a_get(session, symbol)  # May fail!
```

**Solution:**
```python
session = OAuthSession(secret, token)
await session.a_refresh()  # ✅ Generates fresh session_token
await TastytradeOption.a_get(session, symbol)
```

### ❌ PITFALL 2: Reusing Sessions Across Event Loops

**Problem:**
```python
# Celery Task A creates session
session = await create_session()

# Celery Task B tries to reuse session (different event loop)
await session.a_validate()  # ❌ RuntimeError: Event loop is closed
```

**Solution:**
```python
# Use singleton pattern that detects closed loops
session_result = await TastyTradeSessionService.get_session_for_user(user_id, token)
# ✅ Automatically creates new session if loop changed
```

**Reference:** `services/brokers/tastytrade_session.py:429-458`

### ❌ PITFALL 3: Ignoring OAuth Token Rotation

**Problem:**
```python
# User reconnects broker (new refresh token)
# Cached session still uses old token
await session.a_refresh()  # ❌ Fails: token invalid
```

**Solution:**
```python
# Session service detects token changes
if cached_token != database_token:
    logger.info("OAuth token changed - invalidating cached session")
    clear_session(user_id)
    # Create new session with new token
```

**Reference:** `services/brokers/tastytrade_session.py:414-422`

### ❌ PITFALL 4: Not Handling Session Expiration Mid-Task

**Problem:**
```python
session = get_session()
# Long-running task (20 minutes)
await process_data()  # Session expires after 15 minutes
await place_order(session)  # ❌ Session expired!
```

**Solution:**
```python
# Background refresh keeps sessions alive
await TastyTradeSessionService.start_background_refresh()

# Or: Get fresh session before each critical operation
session_result = await get_session_for_user(user_id, token)
await place_order(session_result['session'])
```

**Reference:** `services/brokers/tastytrade_session.py:863-1013`

### ❌ PITFALL 5: Incorrect Price Signs for Credit/Debit

**Problem:**
```python
# Selling a spread (credit)
net_credit = Decimal('2.50')
order = NewOrder(price=-net_credit, ...)  # ❌ Wrong sign!
```

**Solution:**
```python
# Credit = positive, Debit = negative
net_credit = Decimal('2.50')
order = NewOrder(price=net_credit, ...)  # ✅ Positive for credit

net_debit = Decimal('3.00')
order = NewOrder(price=-net_debit, ...)  # ✅ Negative for debit
```

---

## Code Examples

### Example 1: Complete Strategy Leg Building

**Pattern:** `services/utils/order_builder_utils.py:103-198`

```python
from services.utils.order_builder_utils import build_opening_spread_legs

async def prepare_bull_put_spread(session, symbol, expiration, contracts):
    """Build legs for bull put spread using shared utilities."""

    # Strategy determines strikes and quantity
    short_strike = await select_short_strike(symbol)
    long_strike = short_strike - Decimal('5')  # $5 wide

    strikes = {
        'short_put': short_strike,
        'long_put': long_strike
    }

    # Shared helper builds SDK Leg objects
    legs = await build_opening_spread_legs(
        session=session,
        underlying_symbol=symbol,
        expiration_date=expiration,
        spread_type='put_spread',
        strikes=strikes,
        quantity=contracts
    )

    return legs  # List[tastytrade.order.Leg]
```

### Example 2: Session Management in Strategy

**Pattern:** `services/strategies/base.py:146-183`

```python
from services.brokers.tastytrade_session import TastyTradeSessionService

class MyStrategy(BaseStrategy):

    async def a_prepare_suggestion_context(self, symbol, report, mode):
        """Prepare order legs with managed session."""

        # Get managed session (auto-refreshed)
        account = await get_primary_tastytrade_account(self.user)
        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=self.user.id,
            refresh_token=account.refresh_token,
            is_test=account.is_test
        )

        if not session_result.get("success"):
            raise OAuthSessionError(f"Session failed: {session_result.get('error')}")

        session = session_result.get("session")

        # Build legs using SDK instruments
        legs = await self._build_strategy_legs(session, symbol, expiration)

        return {
            'legs': legs,
            'symbol': symbol,
            'expiration': expiration
        }
```

### Example 3: Error Handling with Retry Logic

**Pattern:** `services/brokers/tastytrade_session.py:534-656`

```python
async def refresh_session_with_retry(user_id: int) -> dict:
    """Refresh session with exponential backoff."""

    max_retries = 3
    retry_delay = 1.0
    backoff = 2.0

    for attempt in range(max_retries):
        try:
            async with asyncio.timeout(10):
                await session.a_refresh()

            logger.info(f"Session refreshed successfully (attempt {attempt + 1})")
            return {"success": True}

        except TimeoutError:
            error_type = SessionErrorType.TIMEOUT_ERROR

        except Exception as e:
            error_type = categorize_refresh_error(e)

            # Don't retry auth failures
            if error_type in [SessionErrorType.EXPIRED_TOKEN, SessionErrorType.AUTHENTICATION_ERROR]:
                return {
                    "success": False,
                    "error": str(e),
                    "retry_recommended": False
                }

        # Retry with backoff
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= backoff

    return {
        "success": False,
        "error": f"Failed after {max_retries} attempts",
        "retry_recommended": True
    }
```

### Example 4: Bulk Instrument Fetch for Multi-Leg Orders

**Pattern:** `services/utils/sdk_instruments.py:79-131`

```python
from services.utils.sdk_instruments import get_option_instruments_bulk

async def fetch_iron_condor_instruments(session, symbol, expiration):
    """Fetch all 4 legs of iron condor efficiently."""

    # Define all 4 strikes
    specs = [
        {'underlying': symbol, 'expiration': expiration,
         'strike': Decimal('580'), 'option_type': 'P'},  # Long put
        {'underlying': symbol, 'expiration': expiration,
         'strike': Decimal('585'), 'option_type': 'P'},  # Short put
        {'underlying': symbol, 'expiration': expiration,
         'strike': Decimal('595'), 'option_type': 'C'},  # Short call
        {'underlying': symbol, 'expiration': expiration,
         'strike': Decimal('600'), 'option_type': 'C'},  # Long call
    ]

    # Single batch fetch (1 API call instead of 4)
    options = await get_option_instruments_bulk(session, specs)

    # Unpack in order
    long_put, short_put, short_call, long_call = options

    return {
        'long_put': long_put,
        'short_put': short_put,
        'short_call': short_call,
        'long_call': long_call
    }
```

---

## Quick Reference Table

| Task | Use This | Avoid This |
|------|----------|------------|
| Get session | `TastyTradeSessionService.get_session_for_user()` | `OAuthSession()` directly |
| Fetch option | `get_option_instrument()` | Hand-crafted OCC symbols |
| Build leg | `Leg(InstrumentType.EQUITY_OPTION, ...)` | Dict with strings |
| Multi-leg fetch | `get_option_instruments_bulk()` | Sequential `Option.a_get()` calls |
| Error handling | `categorize_error()` + retry logic | Bare `try/except` |
| Async calls | `await session.a_refresh()` | `session.refresh()` (sync) |
| Testing | `is_test=True` + clear logging | Hope for the best |
| Order validation | `dry_run=True` first | YOLO to production |

---

## Related Documentation

- **Session Management:** `services/brokers/tastytrade_session.py`
- **Instrument Utilities:** `services/utils/sdk_instruments.py`
- **Order Builders:** `services/utils/order_builder_utils.py`
- **Error Handling:** `services/brokers/session_helpers.py`
- **Execution Service:** `services/execution/order_service.py`
- **SDK Reference:** `skills/tastytrade-sdk/SKILL.md`

---

## Contributing

When adding new SDK usage patterns:

1. ✅ Use existing utilities (`get_option_instrument`, `build_opening_spread_legs`)
2. ✅ Add timeout handling for all SDK calls
3. ✅ Categorize errors and log with context
4. ✅ Test with both `is_test=True` and `is_test=False`
5. ✅ Document non-obvious SDK behaviors
6. ✅ Add examples to this guide

**Questions?** Use `/tastytrade:tt-check <function-name>` to verify SDK usage patterns.
