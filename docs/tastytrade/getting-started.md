# Getting Started with TastyTrade API

**Prerequisites**: TastyTrade account, Python 3.12+, tastytrade SDK >=10.3.0

## Quick Start Guide

This guide walks through the essential steps to integrate with the TastyTrade API, from account setup to placing your first order.

## 1. Create Sandbox Account

### Account Setup
1. Visit [TastyTrade Sandbox](https://app.cert.tastyworks.com)
2. Create a new account (separate from production)
3. Note your account credentials (username/password)
4. Apply for API access through customer service

### API Credentials
Once approved, you'll receive:
- **Client ID** (public identifier)
- **Client Secret** (private key - keep secure)
- **Account Number** (for API calls)

## 2. Login to Sandbox Account

### Initial Authentication
```python
from tastytrade import OAuthSession

# Create session with username/password (first time)
session = OAuthSession(
    username='your_username',
    password='your_password',
    is_test=True  # Use sandbox
)

# Get and store refresh token for future use
refresh_token = session.refresh_token
print(f"Save this refresh token: {refresh_token}")
```

### Subsequent Logins (Recommended)
```python
# Use stored refresh token for future sessions
session = OAuthSession(
    provider_secret='your_client_secret',
    refresh_token='saved_refresh_token',
    is_test=True
)

# Validate session
if hasattr(session, 'validate'):
    is_valid = session.validate()
    print(f"Session valid: {is_valid}")
```

## 3. Submit a Trade

### Simple Stock Purchase
```python
from tastytrade import Account
from tastytrade.orders import OrderBuilder, OrderType

# Get account
account = await Account.a_get(session, 'your_account_number')

# Build buy order
order = OrderBuilder.stock_order(
    symbol='AAPL',
    quantity=10,  # Buy 10 shares
    action='BUY',
    order_type=OrderType.MARKET
)

# Submit order
response = await account.a_place_order(session, order)
print(f"Order placed: {response.id}")
```

### Options Order Example
```python
# Options order (buying a call)
option_symbol = 'AAPL  250117C00150000'  # AAPL Jan 17 2025 $150 Call

order = OrderBuilder.option_order(
    symbol=option_symbol,
    quantity=1,  # 1 contract
    action='BUY_TO_OPEN',
    order_type=OrderType.MARKET
)

response = await account.a_place_order(session, order)
```

## 4. Fetch Balance and Positions

### Account Balances
```python
# Get current balances
balances = await account.a_get_balances(session)
print(f"Net liquidating value: ${balances.net_liquidating_value:,.2f}")
print(f"Cash balance: ${balances.cash_balance:,.2f}")
print(f"Buying power: ${balances.buying_power:,.2f}")
```

### Current Positions
```python
# Get all positions
positions = await account.a_get_positions(session)

for position in positions:
    print(f"{position.symbol}: {position.quantity} shares")
    print(f"  Market value: ${position.market_value:,.2f}")
    print(f"  P&L: ${position.realized_day_gain:,.2f}")
```

## 5. Stream Market Data

### Real-time Quotes
```python
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Quote

# Create streamer (no await needed for constructor)
streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to symbols
    await streamer.subscribe(Quote, ['AAPL', 'SPY', 'QQQ'])
    
    # Listen for quote updates
    async for quote in streamer.listen(Quote):
        print(f"{quote.symbol}: ${quote.bid_price} x ${quote.ask_price}")
        
        # Break after a few updates for demo
        if quote.symbol == 'AAPL':
            break
```

## 6. Fetch Market Data (REST)

### Current Quote Data
```python
from tastytrade.instruments import EquityInstrument

# Get current quote for a stock
instrument = EquityInstrument.get_equity(session, 'AAPL')
quote = instrument.get_quote(session)

print(f"AAPL: ${quote.bid} x ${quote.ask}")
print(f"Last: ${quote.last}, Volume: {quote.volume:,}")
```

### Historical Data
```python
from datetime import datetime, timedelta

# Get historical candles (last 5 days)
end_date = datetime.now()
start_date = end_date - timedelta(days=5)

candles = instrument.get_candles(
    session,
    start_time=start_date,
    end_time=end_date,
    interval='1Day'
)

for candle in candles:
    print(f"{candle.time}: O=${candle.open} H=${candle.high} L=${candle.low} C=${candle.close}")
```

## 7. Stream Account Updates

### Real-time Account Changes
```python
from tastytrade.dxfeed import AccountUpdate

streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to account updates
    await streamer.subscribe(AccountUpdate, [account.account_number])
    
    # Listen for account changes
    async for update in streamer.listen(AccountUpdate):
        print(f"Account update: {update.type}")
        if hasattr(update, 'net_liquidating_value'):
            print(f"  NLV: ${update.net_liquidating_value:,.2f}")
```

## 8. Close a Position

### Sell Existing Stock Position
```python
# Get current position
positions = await account.a_get_positions(session)
aapl_position = next((p for p in positions if p.symbol == 'AAPL'), None)

if aapl_position and aapl_position.quantity > 0:
    # Create sell order to close position
    close_order = OrderBuilder.stock_order(
        symbol='AAPL',
        quantity=aapl_position.quantity,
        action='SELL',
        order_type=OrderType.MARKET
    )
    
    response = await account.a_place_order(session, close_order)
    print(f"Position closing order: {response.id}")
```

## 9. Fetch Option Chain

### Get Available Options
```python
from tastytrade.instruments import get_option_chain

# Get option chain for AAPL
option_chain = await get_option_chain(session, 'AAPL')

# Display calls for next expiration
next_expiry = option_chain.expirations[0]
calls = [opt for opt in option_chain.strikes if opt.call]

print(f"AAPL Calls expiring {next_expiry}:")
for call_option in calls[:5]:  # First 5 strikes
    print(f"  ${call_option.strike}: {call_option.call.symbol}")
    print(f"    Bid: ${call_option.call.bid} Ask: ${call_option.call.ask}")
```

## Error Handling

### Robust Implementation
```python
from tastytrade.exceptions import TastyTradeError
import asyncio

async def safe_api_call():
    try:
        account = await Account.a_get(session, account_number)
        balances = await account.a_get_balances(session)
        return balances
    
    except TastyTradeError as e:
        print(f"API Error: {e}")
        if 'authentication' in str(e).lower():
            # Refresh session
            session.refresh()
            # Retry once
            account = await Account.a_get(session, account_number)
            return await account.a_get_balances(session)
        raise
    
    except asyncio.TimeoutError:
        print("Request timed out")
        return None
    
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
```

## Environment Configuration

### Django Settings
```python
# settings.py
TASTYTRADE_CLIENT_SECRET = 'your_client_secret'
TASTYTRADE_IS_TEST = True  # False for production
TASTYTRADE_BASE_URL = 'https://api.cert.tastyworks.com'  # sandbox

# Production URL: https://api.tastyworks.com
```

### Environment Variables
```bash
# .env file
TASTYTRADE_CLIENT_SECRET=your_client_secret
TASTYTRADE_REFRESH_TOKEN=your_refresh_token
TASTYTRADE_IS_TEST=true
```

## Next Steps

1. **Explore API Services**: Review [API Overview](./api-overview.md) for comprehensive endpoint coverage
2. **Learn Streaming**: Study [Streaming Services](./api-services/streaming.md) for real-time data
3. **Risk Management**: Implement [Risk Parameters](./api-services/risk-parameters.md)
4. **Production Setup**: Follow [Authentication Guide](./authentication.md) for secure production deployment

## Help and Resources

- **TastyTrade Support**: support@tastyworks.com
- **API Documentation**: [developer.tastyworks.com](https://developer.tastyworks.com)
- **SDK Issues**: [GitHub Issues](https://github.com/tastyware/tastytrade)
- **Community**: TastyTrade Discord/Reddit communities

---

**⚠️ Important**: Always test in sandbox environment before production deployment. Never use production credentials in development.