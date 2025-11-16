# Error Handling Guide

## Overview

This project uses standardized error handling decorators to reduce duplication and ensure consistent logging across service methods.

## Available Decorators

### `@handle_errors`

Wraps methods in try/except with standardized logging.

**Location**: `services/decorators.py`

**When to Use**:
- ✅ New utility methods without complex error handling
- ✅ Methods that should fail gracefully with logging
- ✅ Methods where a simple return value on error is appropriate
- ❌ Methods with complex error recovery logic
- ❌ Methods that need specific exception types
- ❌ Methods with multiple error paths

**Examples**:

```python
from services.decorators import handle_errors

# Simple async method - returns None on error
@handle_errors("Failed to fetch market data")
async def a_fetch_market_data(self, symbol: str) -> dict | None:
    data = await self.client.get_data(symbol)
    return self._process(data)

# Method with custom return value
@handle_errors("Failed to calculate metrics", return_value={})
async def a_calculate_metrics(self) -> dict:
    return {"delta": self._get_delta(), "theta": self._get_theta()}

# Sync method example
@handle_errors("Failed to parse OCC symbol", return_value=None)
def parse_occ_symbol(self, symbol: str) -> dict | None:
    return {"ticker": symbol[:6].strip(), "strike": float(symbol[12:20])}
```

### `@require_session`

Auto-setup TastyTrade OAuth session for async methods.

**When to Use**:
- ✅ Async methods that need TastyTrade API access
- ✅ Methods that should fail gracefully if session unavailable
- ❌ Methods that need custom session error handling
- ❌ Sync methods (use `@require_session_sync` instead)

**Example**:

```python
@require_session(error_return={"error": "Session required"})
async def a_fetch_positions(self) -> dict:
    # self.session and self.account are automatically available
    positions = await self.session.get_positions(self.account.account_number)
    return self._format_positions(positions)
```

## Error Handling Patterns

### Pattern 1: Tuple Returns (Recommended for Critical Operations)

Use when callers need to distinguish between valid results and errors.

```python
async def a_get_tradeable_capital(self) -> tuple[Decimal, bool]:
    """
    Returns: (value, is_available)
    - value: Decimal amount (or Decimal("0") on error)
    - is_available: True if data valid, False if error occurred
    """
    try:
        account_state = await self.account_state_service.a_get(self.user)
        if not account_state.get("available"):
            logger.warning(f"Account state not available for user {self.user.id}")
            return Decimal("0"), False

        buying_power = Decimal(str(account_state.get("buying_power")))
        return buying_power, True

    except Exception as e:
        logger.error(f"Error getting tradeable capital: {e}", exc_info=True)
        return Decimal("0"), False
```

**When to use**: Financial calculations, risk management, critical business logic

### Pattern 2: Decorator-Based (Recommended for Utilities)

Use for simpler methods where None/empty dict/default value is acceptable.

```python
@handle_errors("Failed to fetch historical data", return_value=[])
async def a_fetch_historical_data(self, symbol: str, days: int) -> list[dict]:
    response = await self.client.get_history(symbol, days)
    return [self._parse_candle(c) for c in response.candles]
```

**When to use**: Data fetching, formatting, non-critical operations

### Pattern 3: Explicit Try/Except (for Complex Logic)

Use when you need multiple error paths or complex recovery.

```python
async def a_execute_order(self, order_spec: OrderSpec) -> dict:
    """Complex method with multiple failure modes."""
    try:
        # Validate pricing is current
        if not self._is_pricing_current(order_spec):
            logger.warning("Pricing is stale, aborting order")
            return {"status": "rejected", "reason": "stale_pricing"}

        # Create database records
        position = await self._create_pending_records(order_spec)

        try:
            # Submit to broker
            broker_order = await self._submit_order(order_spec)
            position.broker_order_id = broker_order.id
            await position.asave()
            return {"status": "submitted", "order_id": broker_order.id}

        except BrokerAPIException as e:
            # Specific handling for broker errors
            logger.error(f"Broker API error: {e}", exc_info=True)
            await position.adelete()  # Cleanup orphan
            return {"status": "error", "reason": "broker_api_failed"}

    except Exception as e:
        logger.error(f"Unexpected error executing order: {e}", exc_info=True)
        return {"status": "error", "reason": "unexpected_error"}
```

**When to use**: Order execution, complex workflows, multi-step operations

## Anti-Patterns to Avoid

### ❌ Silent Failures

```python
# BAD: Error swallowed, no logging
def get_data(self):
    try:
        return self.client.fetch()
    except:
        return None
```

```python
# GOOD: Use decorator or explicit logging
@handle_errors("Failed to fetch data")
def get_data(self):
    return self.client.fetch()
```

### ❌ Redundant Decorator + Try/Except

```python
# BAD: Decorator + try/except is redundant
@handle_errors("Failed")
async def fetch(self):
    try:
        return await self.client.get()
    except Exception as e:
        logger.error(f"Error: {e}")
        return None
```

```python
# GOOD: Use decorator OR try/except, not both
@handle_errors("Failed to fetch")
async def fetch(self):
    return await self.client.get()
```

### ❌ Generic Exception Messages

```python
# BAD: Vague error message
@handle_errors("Error occurred")
async def process(self):
    ...
```

```python
# GOOD: Specific, actionable message
@handle_errors("Failed to process market data for pricing")
async def process(self):
    ...
```

## Logging Best Practices

### 1. Use Structured Context

```python
logger.error(
    f"Failed to execute order - User: {self.user.id}, "
    f"Symbol: {order_spec.symbol}, Error: {e}",
    exc_info=True
)
```

### 2. Log at Appropriate Levels

- `logger.error()`: Operation failed, needs attention
- `logger.warning()`: Degraded operation, fallback used
- `logger.info()`: Normal operation, audit trail
- `logger.debug()`: Detailed troubleshooting info

### 3. Always Include `exc_info=True` for Exceptions

```python
except Exception as e:
    logger.error(f"Failed: {e}", exc_info=True)  # ← Includes stack trace
```

## Migration Guide

### Converting Existing Methods

**Before**:
```python
async def fetch_data(self, symbol: str):
    try:
        data = await self.client.get(symbol)
        return self._process(data)
    except Exception as e:
        logger.error(f"Error fetching data: {e}", exc_info=True)
        return None
```

**After**:
```python
@handle_errors("Failed to fetch data")
async def fetch_data(self, symbol: str):
    data = await self.client.get(symbol)
    return self._process(data)
```

**When NOT to convert**:
- Method already has multiple error paths
- Method needs specific exception handling
- Method returns tuple (value, bool) pattern
- Method has cleanup logic in exception handlers

## Testing Error Handling

### Unit Tests

```python
@pytest.mark.asyncio
async def test_method_handles_api_failure(mocker):
    """Verify decorator logs and returns None on API failure."""
    service = MyService(user=test_user)

    # Mock API to raise exception
    mocker.patch.object(service.client, 'get', side_effect=APIException("API down"))

    # Should return None, not raise
    result = await service.a_fetch_data("SPY")
    assert result is None

    # Should have logged error
    # (use caplog fixture to verify logging)
```

## Summary

- **Use `@handle_errors`**: For simple methods with straightforward error handling
- **Use tuple returns**: For critical financial/risk calculations
- **Use explicit try/except**: For complex multi-step operations
- **Always log errors**: Either via decorator or explicit `logger.error()`
- **Be specific**: Clear error messages aid debugging
- **Test error paths**: Verify both success and failure cases
