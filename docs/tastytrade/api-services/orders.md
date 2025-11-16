# Orders API Service

The Orders API provides comprehensive order management capabilities including order placement, modification, cancellation, and status tracking.

## Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/accounts/{account_number}/orders` | Place new order |
| GET | `/accounts/{account_number}/orders` | Get order history |
| GET | `/accounts/{account_number}/orders/{order_id}` | Get specific order |
| PATCH | `/accounts/{account_number}/orders/{order_id}` | Modify order |
| DELETE | `/accounts/{account_number}/orders/{order_id}` | Cancel order |
| GET | `/accounts/{account_number}/orders/live` | Get working orders |

## Order Placement

### Stock Orders

#### Market Buy Order
```python
from tastytrade.orders import OrderBuilder, OrderType

# Simple market buy
order = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='BUY',
    order_type=OrderType.MARKET
)

# Place order
response = await account.a_place_order(session, order)
order_id = response.id
print(f"Order placed: {order_id}")
```

#### Limit Buy Order
```python
# Limit buy with specific price
order = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='BUY',
    order_type=OrderType.LIMIT,
    price=150.00
)

response = await account.a_place_order(session, order)
```

#### Stop Loss Order
```python
# Stop loss to limit downside
order = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='SELL',
    order_type=OrderType.STOP,
    stop_price=145.00
)

response = await account.a_place_order(session, order)
```

### Option Orders

#### Buy to Open (Long Option)
```python
# Buy call option
option_symbol = 'AAPL  250117C00150000'  # AAPL Jan 17, 2025 $150 Call

order = OrderBuilder.option_order(
    symbol=option_symbol,
    quantity=1,  # 1 contract
    action='BUY_TO_OPEN',
    order_type=OrderType.LIMIT,
    price=5.50  # Premium per share
)

response = await account.a_place_order(session, order)
```

#### Sell to Close (Close Long Position)
```python
# Close existing long call
order = OrderBuilder.option_order(
    symbol=option_symbol,
    quantity=1,
    action='SELL_TO_CLOSE',
    order_type=OrderType.LIMIT,
    price=7.00
)

response = await account.a_place_order(session, order)
```

### Multi-Leg Orders (Spreads)

#### Iron Condor
```python
# 4-leg iron condor
order = OrderBuilder.iron_condor(
    underlying='SPY',
    expiration='2025-01-17',
    long_call_strike=420,
    short_call_strike=410,
    short_put_strike=390,
    long_put_strike=380,
    quantity=1,
    net_credit=2.50  # Target credit
)

response = await account.a_place_order(session, order)
```

#### Covered Call
```python
# Stock + short call
order = OrderBuilder.covered_call(
    symbol='AAPL',
    stock_quantity=100,
    call_symbol='AAPL  250117C00160000',
    call_quantity=1,
    net_debit=149.50  # Net cost per share
)

response = await account.a_place_order(session, order)
```

## Order Management

### Get Order Status
```python
# Get specific order
order = await account.a_get_order(session, order_id)

print(f"Order {order.id}:")
print(f"  Status: {order.status}")
print(f"  Symbol: {order.symbol}")
print(f"  Quantity: {order.quantity}")
print(f"  Filled: {order.filled_quantity}")
print(f"  Price: ${order.price}")
```

### Get Working Orders
```python
# Get all active orders
working_orders = await account.a_get_live_orders(session)

for order in working_orders:
    print(f"{order.symbol}: {order.quantity} @ ${order.price}")
    print(f"  Status: {order.status}")
    print(f"  Time in Force: {order.time_in_force}")
```

### Order History
```python
from datetime import datetime, timedelta

# Get orders from last 30 days
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

orders = await account.a_get_orders(
    session,
    start_date=start_date,
    end_date=end_date
)

for order in orders:
    print(f"{order.created_at}: {order.symbol} {order.action} {order.quantity}")
    print(f"  Status: {order.status}, Filled: {order.filled_quantity}")
```

### Modify Orders

#### Change Order Price
```python
# Modify existing limit order price
modified_order = await account.a_modify_order(
    session,
    order_id,
    price=152.00  # New limit price
)

print(f"Order modified: {modified_order.id}")
```

#### Change Order Quantity
```python
# Reduce order quantity
modified_order = await account.a_modify_order(
    session,
    order_id,
    quantity=50  # Reduce from 100 to 50 shares
)
```

### Cancel Orders

#### Cancel Specific Order
```python
# Cancel single order
cancelled_order = await account.a_cancel_order(session, order_id)
print(f"Order {order_id} cancelled")
```

#### Cancel All Working Orders
```python
# Cancel all active orders for account
result = await account.a_cancel_all_orders(session)
print(f"Cancelled {result.cancelled_count} orders")
```

#### Cancel Orders by Symbol
```python
# Cancel all AAPL orders
working_orders = await account.a_get_live_orders(session)
aapl_orders = [o for o in working_orders if o.symbol == 'AAPL']

for order in aapl_orders:
    await account.a_cancel_order(session, order.id)
    print(f"Cancelled AAPL order {order.id}")
```

## Order Types and Parameters

### Order Types

| Type | Description | Required Parameters |
|------|-------------|--------------------|
| `MARKET` | Execute at current market price | quantity, action |
| `LIMIT` | Execute at specified price or better | quantity, action, price |
| `STOP` | Market order when stop price hit | quantity, action, stop_price |
| `STOP_LIMIT` | Limit order when stop price hit | quantity, action, price, stop_price |

### Time in Force

| Value | Description |
|-------|-------------|
| `DAY` | Valid for current trading day |
| `GTC` | Good Till Cancelled |
| `IOC` | Immediate or Cancel |
| `FOK` | Fill or Kill |

### Order Actions

#### Stock Actions
- `BUY` - Purchase shares
- `SELL` - Sell shares
- `SELL_SHORT` - Short sell shares
- `BUY_TO_COVER` - Cover short position

#### Option Actions
- `BUY_TO_OPEN` - Open long option position
- `BUY_TO_CLOSE` - Close short option position
- `SELL_TO_OPEN` - Open short option position
- `SELL_TO_CLOSE` - Close long option position

## Order Validation

### Pre-submission Validation
```python
def validate_order(order, account_balances):
    """Validate order before submission"""
    errors = []
    
    # Check buying power
    if order.action in ['BUY', 'BUY_TO_OPEN']:
        cost = order.quantity * order.price
        if cost > account_balances.buying_power:
            errors.append(f"Insufficient buying power: ${cost} > ${account_balances.buying_power}")
    
    # Check quantity
    if order.quantity <= 0:
        errors.append("Quantity must be positive")
    
    # Check price for limit orders
    if order.order_type == OrderType.LIMIT and order.price <= 0:
        errors.append("Limit price must be positive")
    
    return errors

# Validate before placing
balances = await account.a_get_balances(session)
errors = validate_order(order, balances)

if errors:
    for error in errors:
        print(f"Validation Error: {error}")
else:
    response = await account.a_place_order(session, order)
```

### Order Rejection Handling
```python
from tastytrade.exceptions import TastyTradeError

try:
    response = await account.a_place_order(session, order)
except TastyTradeError as e:
    if e.status_code == 400:
        print(f"Order rejected: {e.message}")
        # Handle specific rejection reasons
        if 'buying power' in e.message.lower():
            print("Insufficient funds")
        elif 'market closed' in e.message.lower():
            print("Market is closed")
    else:
        raise
```

## Advanced Order Features

### Bracket Orders
```python
# Parent order with profit target and stop loss
parent_order = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='BUY',
    order_type=OrderType.LIMIT,
    price=150.00
)

# Profit target (sell limit)
profit_target = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='SELL',
    order_type=OrderType.LIMIT,
    price=160.00,
    parent_order_id=parent_order.id
)

# Stop loss
stop_loss = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=100,
    action='SELL',
    order_type=OrderType.STOP,
    stop_price=140.00,
    parent_order_id=parent_order.id
)

# Submit bracket order
bracket_response = await account.a_place_bracket_order(
    session, 
    parent_order, 
    profit_target, 
    stop_loss
)
```

### Conditional Orders
```python
# Order triggered by another symbol's price
conditional_order = OrderBuilder.conditional_order(
    symbol='QQQ',
    quantity=100,
    action='BUY',
    order_type=OrderType.MARKET,
    trigger_symbol='SPY',
    trigger_price=400.00,
    trigger_condition='ABOVE'  # Trigger when SPY > $400
)

response = await account.a_place_order(session, conditional_order)
```

## Order Monitoring and Alerts

### Real-time Order Updates
```python
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import OrderUpdate

streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to order updates
    await streamer.subscribe(OrderUpdate, [account.account_number])
    
    async for update in streamer.listen(OrderUpdate):
        print(f"Order {update.order_id}: {update.status}")
        if update.status == 'FILLED':
            print(f"  Filled {update.filled_quantity} @ ${update.fill_price}")
```

### Fill Notifications
```python
async def monitor_order_fills(account, session):
    """Monitor and process order fills"""
    streamer = DXLinkStreamer(session)
    
    async with streamer:
        await streamer.subscribe(OrderUpdate, [account.account_number])
        
        async for update in streamer.listen(OrderUpdate):
            if update.status == 'FILLED':
                # Process fill
                await process_order_fill(update)
            elif update.status == 'REJECTED':
                # Handle rejection
                await handle_order_rejection(update)

async def process_order_fill(fill_update):
    """Process completed order fill"""
    print(f"Order filled: {fill_update.symbol}")
    print(f"Quantity: {fill_update.filled_quantity}")
    print(f"Price: ${fill_update.fill_price}")
    
    # Update position tracking
    # Send notifications
    # Update risk metrics
```

## Error Handling Best Practices

### Comprehensive Error Handling
```python
async def place_order_with_retry(account, session, order, max_retries=3):
    """Place order with retry logic and comprehensive error handling"""
    for attempt in range(max_retries):
        try:
            response = await account.a_place_order(session, order)
            return response
        
        except TastyTradeError as e:
            if e.status_code == 429:  # Rate limited
                await asyncio.sleep(1)
                continue
            
            elif e.status_code == 400:  # Bad request
                print(f"Order validation failed: {e.message}")
                break  # Don't retry validation errors
            
            elif e.status_code == 401:  # Unauthorized
                if attempt == 0:  # Refresh token once
                    session.refresh()
                    continue
                else:
                    raise
            
            else:
                raise
        
        except asyncio.TimeoutError:
            print(f"Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
    
    raise Exception(f"Failed to place order after {max_retries} attempts")
```

This Orders API documentation covers the essential patterns for order management in the TastyTrade platform. Always test order placement in the sandbox environment before production use.