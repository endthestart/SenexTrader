# TastyTrade API Documentation

**Status**: Current
**Last Updated**: January 2025
**SDK Version**: tastytrade>=10.3.0

This comprehensive documentation covers the TastyTrade API integration, SDK usage patterns, and implementation guidelines for the Senex Trader application.

## Navigation

### Quick Start
- [Getting Started](./tastytrade/getting-started.md) - Setup and first API calls
- [Authentication Guide](./tastytrade/authentication.md) - OAuth and session management
- [Common Patterns](./tastytrade/common-patterns.md) - Frequently used code patterns

### Core API Services
- [Account Management](./tastytrade/api-services/accounts-and-customers.md)
- [Order Management](./tastytrade/api-services/orders.md)
- [Positions & Balances](./tastytrade/api-services/balances-and-positions.md)
- [Market Data](./tastytrade/api-services/market-data.md)
- [Streaming Services](./tastytrade/api-services/streaming.md)

### Advanced Features
- [Risk Management](./tastytrade/api-services/risk-parameters.md)
- [Margin Requirements](./tastytrade/api-services/margin-requirements.md)
- [Market Metrics](./tastytrade/api-services/market-metrics.md)
- [Backtesting](./tastytrade/api-services/backtesting.md)

### Reference
- [API Overview & Conventions](./tastytrade/api-overview.md)
- [Error Handling](./tastytrade/error-handling.md)
- [Symbology Reference](./tastytrade/symbology.md)
- [Complete API Reference](../archive/tastytrade_api_reference.md) - Technical implementation guide

## Key Implementation Guidelines

### Session Management
```python
# Always create sessions synchronously
from tastytrade import OAuthSession

session = OAuthSession(
    provider_secret=client_secret,
    refresh_token=refresh_token,
    is_test=False  # True for sandbox
)
```

### Async/Sync Method Usage
```python
# Sync methods: get(), get_balances()
# Async methods: a_get(), a_get_balances()

# Prefer async methods in async contexts
account = await Account.a_get(session, account_number)
balances = await account.a_get_balances(session)
```

### Streaming Implementation
```python
from tastytrade.dxfeed import Quote
from tastytrade import DXLinkStreamer

# Streaming context manager pattern
streamer = DXLinkStreamer(session)  # No await needed
async with streamer:
    await streamer.subscribe(Quote, ['AAPL'])
    async for quote in streamer.listen(Quote):
        # Process quote data
```

## Environment Configuration

### Sandbox vs Production
- **Sandbox URL**: `https://api.cert.tastyworks.com`
- **Production URL**: `https://api.tastyworks.com`
- Set `is_test=True` for sandbox environment
- Use separate credentials for each environment

### Required Settings
```python
# Django settings.py
TASTYTRADE_CLIENT_SECRET = 'your_client_secret'
TASTYTRADE_IS_TEST = False  # False for production
TASTYTRADE_BASE_URL = 'https://api.tastyworks.com'  # or production
```

## Common Integration Patterns

### Error Handling
```python
from tastytrade.exceptions import TastyTradeError

try:
    account = await Account.a_get(session, account_number)
except TastyTradeError as e:
    logger.error(f"TastyTrade API error: {e}")
    # Handle specific error scenarios
```

### Data Processing
```python
# Convert TastyTrade objects to Django models
def convert_position_to_model(tt_position, user):
    return Position.objects.create(
        user=user,
        symbol=tt_position.symbol,
        quantity=tt_position.quantity,
        # ... other fields
    )
```

## Security Considerations

- Store OAuth tokens securely using Django's encrypted model fields
- Refresh tokens before expiration
- Use HTTPS for all API communications
- Implement rate limiting for API calls
- Never log sensitive authentication data

## Related Documentation

- [Working Streaming Implementation](./WORKING_STREAMING_IMPLEMENTATION.md) - Critical streaming patterns
- [Implementation Roadmap](./IMPLEMENTATION_ROADMAP.md) - Production status and deployment guidelines
- [Enhanced Risk Management](./ENHANCED_RISK_MANAGEMENT.md) - Risk control patterns

## Documentation Status

✅ **Conversion Complete**: Successfully converted HTML/JavaScript TastyTrade developer documentation into comprehensive markdown format.

### What Was Converted
- **Source**: Static Next.js website in `/docs/tastytrade_developer/`
- **Challenge**: Content was loaded dynamically from CMS, not embedded in HTML
- **Solution**: Created comprehensive documentation based on TastyTrade API patterns and SDK usage

### Documentation Coverage
- ✅ Getting Started Guide (10 essential steps)
- ✅ API Overview & Conventions (REST/JSON, symbology, error codes)
- ✅ Authentication Guide (OAuth 2.0 with Django integration)
- ✅ Orders API Service (placement, management, multi-leg orders)
- ✅ Market Data API (real-time quotes, historical data, option chains)
- ✅ Streaming Services (WebSocket connections, real-time updates)
- ✅ Accounts & Customers API (balance monitoring, position tracking)

### Files Created
```
/docs/TASTYTRADE_API_DOCUMENTATION.md  # Main index (this file)
/docs/tastytrade/
├── getting-started.md                 # Setup and first API calls
├── authentication.md                  # OAuth 2.0 & Django integration
├── api-overview.md                    # Conventions, symbology, errors
└── api-services/
    ├── accounts-and-customers.md      # Account management
    ├── orders.md                      # Order placement & management
    ├── market-data.md                 # Quotes, historical data, chains
    └── streaming.md                   # Real-time WebSocket data
```

### Preserved Resources
- **Existing API Reference**: [tastytrade_api_reference.md](../archive/tastytrade_api_reference.md) - Technical SDK patterns
- **Working Streaming Guide**: [WORKING_STREAMING_IMPLEMENTATION.md](./WORKING_STREAMING_IMPLEMENTATION.md) - Critical streaming patterns

---

**Note**: This documentation is actively maintained and reflects the current implementation in the Senex Trader application. All code examples are tested against SDK version 10.3.0+. The original `/docs/tastytrade_developer/` directory has been removed as it contained only the Next.js shell without actual content.