# TastyTrade API Overview

**Base URLs**:
- Sandbox: `https://api.cert.tastyworks.com`
- Production: `https://api.tastyworks.com`

## API Conventions (REST/JSON)

### Request Format
All API requests use standard REST conventions with JSON payloads:

- **GET**: Retrieve data (query parameters for filters)
- **POST**: Create new resources
- **PUT**: Update existing resources
- **DELETE**: Remove resources

### Content Types
```http
Content-Type: application/json
Accept: application/json
```

### Authentication
All requests require authentication via OAuth 2.0 bearer tokens:

```http
Authorization: Bearer <access_token>
```

### Response Format
All responses follow a consistent envelope structure:

```json
{
  "data": {
    "items": [...],
    "context": "/accounts/ABC123"
  },
  "pagination": {
    "page-offset": 0,
    "total-pages": 1
  },
  "context": "/accounts/ABC123"
}
```

## API Versions

### Current Version: v1
All endpoints use version 1 of the API:

```
https://api.tastyworks.com/v1/{endpoint}
```

### Version Headers
Optional version specification via headers:

```http
API-Version: 1.0
```

### Backwards Compatibility
- Minor version updates maintain backwards compatibility
- Major version changes require code updates
- Deprecated features include sunset timeline in responses

## Authentication Patterns

### OAuth 2.0 Flow

#### Initial Authentication
```python
from tastytrade import OAuthSession

# Username/password authentication (first time only)
session = OAuthSession(
    username='your_username',
    password='your_password',
    is_test=True  # Use sandbox
)

# Extract refresh token for storage
refresh_token = session.refresh_token
```

#### Token-based Authentication (Recommended)
```python
# Use stored refresh token
session = OAuthSession(
    provider_secret='client_secret',
    refresh_token='stored_refresh_token',
    is_test=True
)
```

### Token Management

#### Access Token Lifecycle
- **Access tokens**: Short-lived (typically 24 hours)
- **Refresh tokens**: Long-lived (90 days)
- **Automatic refresh**: SDK handles token refresh automatically

#### Manual Token Refresh
```python
# Force token refresh
session.refresh()

# Check token validity
if hasattr(session, 'validate'):
    is_valid = session.validate()
```

### Session Security
- Store refresh tokens securely (encrypted database fields)
- Never log authentication tokens
- Use HTTPS for all API communications
- Implement token rotation policies

## TastyTrade Symbology

### Stock Symbols
Standard ticker symbols:
- `AAPL` - Apple Inc.
- `SPY` - SPDR S&P 500 ETF
- `QQQ` - Invesco QQQ Trust

### Options Symbology (OCC Standard)
Format: `ROOT + YYMMDD + C/P + STRIKE`

#### Examples
```
AAPL  250117C00150000  # AAPL Jan 17, 2025 $150.00 Call
SPY   241220P00400000  # SPY Dec 20, 2024 $400.00 Put
```

#### Breakdown
- **ROOT**: `AAPL` (6 chars, padded with spaces)
- **YYMMDD**: `250117` (Jan 17, 2025)
- **C/P**: `C` for Call, `P` for Put
- **STRIKE**: `00150000` (8 digits, $150.00)

### Futures Symbology
Format: `/ROOT + MONTH + YEAR`

#### Examples
```
/ESH25  # E-mini S&P 500, March 2025
/NQH25  # E-mini Nasdaq, March 2025
```

#### Month Codes
- **F**: January, **G**: February, **H**: March
- **J**: April, **K**: May, **M**: June
- **N**: July, **Q**: August, **U**: September
- **V**: October, **X**: November, **Z**: December

### Crypto Symbols
```
BTC/USD   # Bitcoin vs US Dollar
ETH/USD   # Ethereum vs US Dollar
```

## Error Codes

### HTTP Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request successful |
| 201 | Created | Resource created successfully |
| 400 | Bad Request | Invalid request format or parameters |
| 401 | Unauthorized | Authentication required or invalid |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource does not exist |
| 409 | Conflict | Resource conflict (duplicate, etc.) |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server-side error |
| 503 | Service Unavailable | Temporary service outage |

### Error Response Format
```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid order quantity",
    "details": {
      "field": "quantity",
      "value": "0",
      "constraint": "must be greater than 0"
    }
  }
}
```

### Common Error Scenarios

#### Authentication Errors
```python
# Token expired
{
  "error": {
    "code": "token_expired",
    "message": "Access token has expired"
  }
}

# Invalid credentials
{
  "error": {
    "code": "invalid_credentials",
    "message": "Username or password is incorrect"
  }
}
```

#### Validation Errors
```python
# Invalid order parameters
{
  "error": {
    "code": "validation_error",
    "message": "Order validation failed",
    "details": {
      "quantity": "Must be a positive integer",
      "symbol": "Invalid symbol format"
    }
  }
}
```

#### Rate Limiting
```python
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Too many requests",
    "retry_after": 60  # Retry after 60 seconds
  }
}
```

### Error Handling Best Practices

```python
from tastytrade.exceptions import TastyTradeError
import time

async def robust_api_call(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        
        except TastyTradeError as e:
            if e.status_code == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', 60)
                await asyncio.sleep(retry_after)
                continue
            
            elif e.status_code == 401:  # Unauthorized
                # Refresh token and retry once
                if attempt == 0:
                    session.refresh()
                    continue
            
            # Don't retry for other errors
            raise
        
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise
    
    raise Exception(f"Max retries ({max_retries}) exceeded")
```

## High-level Concepts

### Account Structure

#### Account Hierarchy
```
Customer
├── Account 1 (Individual)
│   ├── Positions
│   ├── Orders
│   └── Balances
└── Account 2 (IRA)
    ├── Positions
    ├── Orders
    └── Balances
```

#### Account Types
- **Individual**: Standard brokerage account
- **IRA**: Individual Retirement Account
- **Roth IRA**: Roth Individual Retirement Account
- **Entity**: Corporate/LLC accounts

### Order Lifecycle

#### Order States
1. **Received**: Order accepted by system
2. **Routed**: Order sent to exchange
3. **Working**: Order active on exchange
4. **Filled**: Order completely executed
5. **Partial**: Order partially executed
6. **Cancelled**: Order cancelled
7. **Rejected**: Order rejected by exchange

#### Order Types
- **Market**: Execute immediately at current market price
- **Limit**: Execute only at specified price or better
- **Stop**: Convert to market order when stop price reached
- **Stop Limit**: Convert to limit order when stop price reached

### Position Management

#### Position Types
- **Long**: Owning shares/contracts
- **Short**: Owing shares/contracts
- **Complex**: Multi-leg option strategies

#### Position Calculations
```python
# P&L Calculations
realized_pnl = position.realized_day_gain + position.realized_today
unrealized_pnl = position.market_value - position.average_open_price * position.quantity
total_pnl = realized_pnl + unrealized_pnl
```

### Risk Management

#### Account Risk Metrics
- **Net Liquidating Value (NLV)**: Total account value if all positions closed
- **Buying Power**: Available funds for new positions
- **Day Trading Buying Power**: Intraday buying power for day trades
- **Maintenance Requirement**: Minimum equity required

#### Position Risk
- **Delta**: Price sensitivity to underlying movement
- **Gamma**: Rate of change of delta
- **Theta**: Time decay of option value
- **Vega**: Sensitivity to implied volatility changes

### Market Data

#### Data Types
- **Level 1**: Best bid/ask, last trade, volume
- **Level 2**: Full order book depth
- **Time & Sales**: Historical trade data
- **Greeks**: Option risk metrics
- **Implied Volatility**: Market-derived volatility

#### Data Feeds
- **Real-time**: Live market data during trading hours
- **Delayed**: 15-minute delayed quotes (free)
- **Historical**: Past market data for analysis
- **Streaming**: Continuous real-time updates

### Trading Sessions

#### Market Hours
- **Pre-market**: 4:00 AM - 9:30 AM ET
- **Regular**: 9:30 AM - 4:00 PM ET
- **After-hours**: 4:00 PM - 8:00 PM ET

#### Order Routing
- **Smart routing**: Best execution across venues
- **Directed routing**: Specific exchange routing
- **Dark pools**: Hidden liquidity venues

---

## SDK Implementation Patterns

### Async Context Management
```python
# Preferred pattern for streaming
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Quote

streamer = DXLinkStreamer(session)  # No await
async with streamer:
    await streamer.subscribe(Quote, ['AAPL'])
    async for quote in streamer.listen(Quote):
        process_quote(quote)
```

### Sync vs Async Methods
```python
# Synchronous methods
account = Account.get(session, account_number)
balances = account.get_balances(session)

# Asynchronous methods (preferred in async contexts)
account = await Account.a_get(session, account_number)
balances = await account.a_get_balances(session)
```

### Error Handling Integration
```python
from tastytrade.exceptions import TastyTradeError

try:
    positions = await account.a_get_positions(session)
except TastyTradeError as e:
    if e.status_code == 401:
        # Handle authentication error
        session.refresh()
        positions = await account.a_get_positions(session)
    else:
        raise
```

This overview provides the foundational knowledge needed to work effectively with the TastyTrade API. For specific implementation examples, refer to the individual service documentation.