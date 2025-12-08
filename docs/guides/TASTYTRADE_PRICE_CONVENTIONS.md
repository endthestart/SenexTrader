# TastyTrade API Price Conventions

**Last Updated**: 2025-11-06
**Status**: Critical - Production Bug Fix

---

## The Critical Rule

TastyTrade SDK uses the **sign of the price** to determine whether an order is a credit or debit:

| Price Sign | Order Type | Example | When Used |
|------------|------------|---------|-----------|
| **Positive** (`+`) | Credit | `price=1.50` | Opening credit spreads (you receive money) |
| **Negative** (`-`) | Debit | `price=-1.50` | Closing credit spreads (you pay money) |

**There is NO separate `price_effect` parameter in `NewOrder`**. The sign IS the price effect.

---

## Real-World Incident (Nov 2025)

### The Bug

Created 7 closing orders for call spread profit targets:

```python
# WRONG CODE
new_order = NewOrder(
    time_in_force=OrderTimeInForce.GTC,
    order_type=OrderType.LIMIT,
    legs=legs,
    price=1.06,  # Positive price
    price_effect=PriceEffect.DEBIT  # This parameter doesn't exist!
)
```

**Result**: All 7 orders were rejected by TastyTrade with "invalid price" because:
- We were CLOSING a credit spread (should be debit)
- But passed a POSITIVE price (TastyTrade interpreted as credit)
- The orders were inconsistent and rejected

### The Fix

```python
# CORRECT CODE
new_order = NewOrder(
    time_in_force=OrderTimeInForce.GTC,
    order_type=OrderType.LIMIT,
    legs=legs,
    price=-abs(float(target_price))  # NEGATIVE for debit
)
```

**Key Insight**: Remove the non-existent `price_effect` parameter and use negative price.

---

## How to Determine Price Sign

### Opening Credit Spreads

When you **open** a credit spread (sell the spread):
- You receive money = CREDIT
- Use **positive price**
- Example: Sell QQQ call spread for $1.50 → `price=1.50`

```python
# Opening a credit spread
new_order = NewOrder(
    legs=[
        Leg(symbol=short_call, action=OrderAction.SELL_TO_OPEN, quantity=1),
        Leg(symbol=long_call, action=OrderAction.BUY_TO_OPEN, quantity=1)
    ],
    price=1.50  # Positive = credit received
)
```

### Closing Credit Spreads (Profit Targets)

When you **close** a credit spread (buy the spread back):
- You pay money = DEBIT
- Use **negative price**
- Example: Buy back QQQ call spread for $0.90 → `price=-0.90`

```python
# Closing a credit spread (profit target)
new_order = NewOrder(
    legs=[
        Leg(symbol=short_call, action=OrderAction.BUY_TO_CLOSE, quantity=1),
        Leg(symbol=long_call, action=OrderAction.SELL_TO_CLOSE, quantity=1)
    ],
    price=-0.90  # Negative = debit paid
)
```

---

## Working Examples in Codebase

### From `services/execution/order_service.py`

```python
# Lines 1181-1190
# Set the price based on the price_effect
# TastyTrade SDK Convention:
# - Credit orders: positive price (money received)
# - Debit orders: negative price (money paid)
if price_effect == PriceEffect.DEBIT.value:
    # For debit orders, use negative price to indicate payment
    order_kwargs["price"] = -abs(round(float(order_spec.limit_price), 2))
else:
    # For credit orders, use positive price to indicate receipt
    order_kwargs["price"] = abs(round(float(order_spec.limit_price), 2))
```

### From Fixed Management Command

```python
# trading/management/commands/fix_call_spread_profit_targets.py
new_order = NewOrder(
    time_in_force=OrderTimeInForce.GTC,
    order_type=OrderType.LIMIT,
    legs=legs,
    price=-abs(float(target_price))  # NEGATIVE for debit (closing)
)
```

---

## Testing Checklist

Before submitting orders to TastyTrade:

1. **Determine operation**: Opening or closing?
2. **Determine cash flow**: Do you receive (credit) or pay (debit)?
3. **Set price sign**:
   - Credit → Positive price
   - Debit → Negative price
4. **Verify in logs**: Check submitted price before API call
5. **Check order status**: Verify order wasn't rejected

---

## Common Mistakes

### Mistake 1: Using `price_effect` Parameter

```python
# WRONG: price_effect doesn't exist in NewOrder
new_order = NewOrder(
    legs=legs,
    price=1.50,
    price_effect=PriceEffect.DEBIT  # This does nothing!
)
```

### Mistake 2: Using Positive Price for Debits

```python
# WRONG: Closing (debit) but positive price
new_order = NewOrder(
    legs=[...],  # BUY_TO_CLOSE / SELL_TO_CLOSE
    price=1.06  # Positive = credit (WRONG!)
)
```

**Fix**: Use negative price
```python
# CORRECT
price=-1.06  # Negative = debit
```

### Mistake 3: Forgetting `abs()` with Negative Price

```python
# WRONG: If target_price is negative, double negative = positive
price = -float(target_price)  # If target_price = -1.06, price = 1.06!
```

**Fix**: Always use `abs()`
```python
# CORRECT
price = -abs(float(target_price))  # Always negative for debit
```

---

## Price Effect Helper (Internal)

Our codebase uses `PriceEffect` enum internally for clarity:

```python
from services.utils.trading_utils import PriceEffect

# Internal representation
PriceEffect.CREDIT  # "credit"
PriceEffect.DEBIT   # "debit"

# Conversion to TastyTrade price:
if price_effect == PriceEffect.DEBIT.value:
    api_price = -abs(price)
else:
    api_price = abs(price)
```

**This is an internal abstraction only.** TastyTrade API only understands price sign.

---

## Summary

| Operation | You... | Price Sign | Example |
|-----------|--------|------------|---------|
| Open credit spread | Receive money | `+` Positive | `price=1.50` |
| Close credit spread | Pay money | `-` Negative | `price=-0.90` |
| Open debit spread | Pay money | `-` Negative | `price=-2.50` |
| Close debit spread | Receive money | `+` Positive | `price=1.80` |

**Remember**: TastyTrade price sign = cash flow direction. Positive = you receive, Negative = you pay.

---

## Related

- `services/execution/order_service.py` (lines 1181-1190) - Price sign conversion logic
- `services/utils/trading_utils.py` - `PriceEffect` enum definition
- `docs/guides/TASTYTRADE_SDK_BEST_PRACTICES.md` - General SDK usage patterns
