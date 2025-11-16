# Working Streaming Implementation Reference

**Status**: PRODUCTION READY
**Date**: September 21, 2025
**Critical**: This document contains the ONLY working patterns for TastyTrade streaming

## Table of Contents
1. [OAuth Session Management](#oauth-session-management)
2. [DXLinkStreamer Setup](#dxlinkstreamer-setup)
3. [WebSocket Architecture](#websocket-architecture)
4. [UI Integration](#ui-integration)
5. [Critical Patterns](#critical-patterns)
6. [Common Pitfalls](#common-pitfalls)

## OAuth Session Management

### Working OAuth Pattern (from accounts/models.py)

```python
def get_oauth_session(self):
    """Simple OAuth session creation that works."""
    from tastytrade import OAuthSession
    from django.conf import settings

    session = OAuthSession(
        provider_secret=settings.TASTYTRADE_CLIENT_SECRET,
        refresh_token=self.refresh_token,
        is_test=False  # ALWAYS False for production
    )
    session.refresh()  # ALWAYS refresh for fresh token
    return session
```

### Key OAuth Facts
- **Token Lifetime**: 900 seconds (15 minutes) per SDK
- **Refresh Required**: Must refresh BEFORE expiry
- **Simple Pattern**: Create new session and refresh immediately - don't cache
- **Async Usage**: `await sync_to_async(trading_account.get_oauth_session)()`

### Session Refresh Implementation

```python
async def _refresh_session(self):
    """Refresh OAuth session every 10 minutes to prevent expiry."""
    while self.is_streaming:
        try:
            # Wait 10 minutes (refresh before 15 min expiry)
            await asyncio.sleep(600)  # 10 minutes

            if not self.oauth_session:
                break

            # Try to refresh existing session
            try:
                await self.oauth_session.a_refresh()
                logger.info(f"Refreshed OAuth session for user {self.user_id}")
            except Exception as e:
                # Get completely new session if refresh fails
                new_session = await self._get_fresh_session()
                if new_session:
                    self.oauth_session = new_session
```

## DXLinkStreamer Setup

### CRITICAL: Async Context Manager Pattern

**THIS IS THE ONLY WORKING PATTERN:**

```python
async def _run_streaming(self, session, symbols: List[str]):
    """Run streaming inside proper async context manager."""
    try:
        async with DXLinkStreamer(session) as streamer:  # MUST use async with
            self.context.data_streamer = streamer
            self.is_streaming = True

            # Subscribe to symbols
            await self._subscribe_symbols(streamer, symbols)

            # Run all listeners concurrently inside context
            await asyncio.gather(
                self._listen_quotes(),
                self._listen_trades(),
                self._listen_greeks(),
                self._listen_theo(),
                self._listen_summary(),
                self._listen_underlying(),
                return_exceptions=True  # Don't fail if one listener fails
            )
    except Exception as e:
        logger.error(f"Streaming error: {e}")
    finally:
        self.context.data_streamer = None
        self.is_streaming = False
```

### What DOESN'T Work

```python
# ❌ WRONG - Creates object but never connects
self.context.data_streamer = DXLinkStreamer(session)

# ❌ WRONG - Tries to await constructor
self.context.data_streamer = await DXLinkStreamer(session)

# ❌ WRONG - Missing async context manager
streamer = DXLinkStreamer(session)
await streamer.subscribe(Quote, symbols)
```

### DXLinkStreamer Internals (from SDK)

```python
# tastytrade/streamer.py lines 495-504
async def __aenter__(self) -> DXLinkStreamer:
    self._connect_task = asyncio.create_task(self._connect())
    # ... waits for authentication ...
    return self

# Line 551: self._websocket = websocket  # Created ONLY after entering context
```

The `_websocket` attribute is ONLY created inside `__aenter__` after connection.

## WebSocket Architecture

### Consumer Pattern (streaming/consumers.py)

```python
class StreamingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        await self.accept()

        # Get user's stream manager
        self.global_manager = GlobalStreamManager()
        self.user_manager = await self.global_manager.get_user_manager(self.user.id)

        # Add this WebSocket to user's manager
        await self.user_manager.add_websocket(self.channel_name)

    async def quote_update(self, event):
        """Receive quote update from UserStreamManager and send to frontend."""
        # Forward the quote data with type field for frontend handling
        quote_data = event.get('data', {})
        quote_data['type'] = 'quote_update'
        await self.send(text_data=json.dumps(quote_data))
```

### Channel Layer Message Flow

1. **DXLinkStreamer** → receives market data
2. **Stream Manager** → processes and formats data
3. **Channel Layer** → broadcasts to WebSocket connections
4. **Consumer** → forwards to frontend
5. **JavaScript** → updates UI

### Message Types

```python
# Quote Update
await self._send_to_websockets("quote_update", {
    "symbol": "QQQ",
    "last": 450.25,
    "bid": 450.24,
    "ask": 450.26,
    "updated_at": "2025-09-21T10:30:00Z",
    "source": "dxfeed_stream"
})

# Balance Update
message = {
    'type': 'balance_update',
    'balance': 100000.00,  # net_liquidating_value
    'buying_power': 50000.00,
    'timestamp': 1726919400000  # milliseconds
}
```

## UI Integration

### JavaScript WebSocket Handler (templates/accounts/settings.html)

```javascript
function connectStreamingWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/streaming/`;

    streamingWs = new WebSocket(wsUrl);

    streamingWs.onopen = function(e) {
        // Subscribe to QQQ quotes immediately
        streamingWs.send(JSON.stringify({
            type: 'subscribe_quotes',
            symbols: ['QQQ']
        }));
    };

    streamingWs.onmessage = function(e) {
        const data = JSON.parse(e.data);

        if (data.type === 'quote_update') {
            handleQuoteUpdate(data);
        } else if (data.type === 'balance_update') {
            handleBalanceUpdate(data);
        }
    };
}
```

### Quote Update Handler

```javascript
function handleQuoteUpdate(data) {
    if (data.symbol === 'QQQ') {
        // Use correct field names from backend
        const currentPrice = data.bid || data.ask || data.last || 0;
        if (currentPrice > 0) {
            updateQQQPrice(currentPrice, lastQQQPrice);
            lastQQQPrice = currentPrice;
        }
    }
}
```

### Balance Update Handler

```javascript
function handleBalanceUpdate(data) {
    if (data.balance !== null && data.balance !== undefined) {
        updateAccountBalance(data.balance);

        // Update timestamp (milliseconds from backend)
        const timestamp = new Date(data.timestamp).toLocaleTimeString();
        const timeElement = document.getElementById('balance-update-time');
        if (timeElement) {
            timeElement.textContent = `(${timestamp})`;
        }
    }
}
```

## Critical Patterns

### 1. Always Use Async Context Manager for DXLinkStreamer

```python
# ✅ CORRECT
async with DXLinkStreamer(session) as streamer:
    await streamer.subscribe(Quote, symbols)
    async for quote in streamer.listen(Quote):
        process_quote(quote)

# ❌ WRONG
streamer = DXLinkStreamer(session)
await streamer.subscribe(Quote, symbols)  # Will fail - no _websocket
```

### 2. Session Refresh Before Token Expiry

```python
# Refresh every 10 minutes (token expires at 15)
await asyncio.sleep(600)  # 10 minutes
await session.a_refresh()
```

### 3. Field Name Consistency

Backend sends:
- `bid`, `ask`, `last` (not `bid_price`, `ask_price`)
- `timestamp` in milliseconds (not seconds)

### 4. Balance Polling Pattern

```python
async def _poll_balance(self):
    """Poll with auth error recovery."""
    while self.is_streaming:
        try:
            account = await Account.a_get(self.oauth_session, self.account_number)
            balances = await account.a_get_balances(self.oauth_session)

            # Extract real values - DO NOT default to 0
            net_liquidating_value = getattr(balances, 'net_liquidating_value', None)

            if net_liquidating_value is not None:
                await self._handle_balance_update({...})
        except Exception as api_error:
            if "unauthorized" in str(api_error).lower():
                # Refresh session immediately
                new_session = await self._get_fresh_session()
```

### 5. Initial Data Send

```python
# Send initial balance immediately after connection
async def _send_initial_balance(self):
    await asyncio.sleep(1)  # Give streamer moment to stabilize

    account = await Account.a_get(self.oauth_session, self.account_number)
    balances = await account.a_get_balances(self.oauth_session)

    await self._handle_balance_update({...})
```

## Common Pitfalls

### 1. Wrong Import Paths
```python
# ❌ WRONG
from tastytrade import Quote

# ✅ CORRECT
from tastytrade.dxfeed import Quote, Greeks, Trade
```

### 2. Assuming Token Doesn't Expire
```python
# ❌ WRONG - Token expires after 15 minutes
session = get_oauth_session()
# Use same session for 30+ minutes

# ✅ CORRECT - Refresh before expiry
# Refresh every 10 minutes or get new session
```

### 3. Using Old TastyTrade SDK Methods
```python
# ❌ WRONG (old SDK pattern)
await sync_to_async(Account.get)(session, account_number)

# ✅ CORRECT (new SDK has async methods)
await Account.a_get(session, account_number)
```

### 4. Not Handling WebSocket Reconnection
```python
# ✅ CORRECT - Implement reconnection logic
streamingWs.onclose = function(e) {
    if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        setTimeout(connectStreamingWebSocket, delay);
    }
};
```

### 5. Defaulting Missing Values to 0
```python
# ❌ WRONG - Creates fake data
net_liquidating_value = getattr(balances, 'net_liquidating_value', 0)

# ✅ CORRECT - Handle None properly
net_liquidating_value = getattr(balances, 'net_liquidating_value', None)
if net_liquidating_value is not None:
    # Process real value
```

## Testing the Implementation

### Manual Test Procedure

1. **Start the server**: `python manage.py runserver`
2. **Navigate to**: `/accounts/settings`
3. **Verify**:
   - QQQ price updates every few seconds
   - Account balance shows immediately
   - Balance updates every 30 seconds
   - No "Invalid Date" errors
   - Streaming survives 20+ minutes (token refresh works)

### Test Commands

```python
# Test streaming connection
from streaming.services.stream_manager import UserStreamManager
import asyncio

manager = UserStreamManager(1)
asyncio.run(manager.start_streaming(['QQQ']))

# Monitor for 20+ minutes to verify refresh
# Check logs for:
# - "Refreshed OAuth session for user X" (at 10 minutes)
# - No "unauthorized" errors after 15 minutes
# - Continuous quote updates
```

## Reference: tastytrade-cli Patterns

All streaming patterns in tastytrade-cli follow the async context manager:

```python
# From ttcli/option.py
async with DXLinkStreamer(sesh) as streamer:
    await streamer.subscribe(Quote, symbols)
    async for quote in streamer.listen(Quote):
        # Process quote

# From ttcli/utils.py
async with DXLinkStreamer(session) as streamer:
    await streamer.subscribe(Greeks, [symbol])
    greeks = await anext(streamer.listen(Greeks))
```

**NEVER** does tastytrade-cli use DXLinkStreamer without `async with`.

## Summary

The working implementation relies on:
1. **Simple OAuth pattern**: Create session, refresh immediately
2. **Async context manager**: ALWAYS use `async with DXLinkStreamer`
3. **Token refresh**: Every 10 minutes to prevent 15-minute expiry
4. **Correct field names**: `bid`/`ask` not `bid_price`/`ask_price`
5. **Immediate data send**: Send balance on connection for better UX
6. **Error recovery**: Handle auth errors by getting fresh session

This implementation has been tested to:
- Stream quotes continuously
- Update balances every 30 seconds
- Survive 20+ minute sessions with automatic token refresh
- Handle reconnections gracefully
- Display data correctly in the UI

**This document represents the ONLY working patterns. Any deviation will likely break streaming.**