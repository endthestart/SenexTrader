# Streaming Services API

The TastyTrade Streaming API provides real-time market data and account updates through WebSocket connections. This is essential for live trading applications that need immediate data updates.

## Core Streaming Components

### DXLinkStreamer
The primary streaming interface for market data and account updates.

```python
from tastytrade import DXLinkStreamer

# Create streamer instance (no await needed)
streamer = DXLinkStreamer(session)

# Use as async context manager
async with streamer:
    # Streaming operations
    pass
```

### Data Types Available

| Data Type | Description | Use Case |
|-----------|-------------|----------|
| `Quote` | Bid/Ask prices and sizes | Real-time pricing |
| `Trade` | Executed trade data | Volume analysis |
| `Greeks` | Option Greeks and IV | Options trading |
| `Summary` | OHLC and volume summary | Market overview |
| `TimeAndSale` | Time & sales data | Trade flow analysis |
| `AccountUpdate` | Account balance changes | Portfolio monitoring |

## Market Data Streaming

### Real-time Quotes

#### Basic Quote Stream
```python
from tastytrade.dxfeed import Quote

streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to quote updates
    symbols = ['AAPL', 'GOOGL', 'MSFT']
    await streamer.subscribe(Quote, symbols)
    
    # Process quote updates
    async for quote in streamer.listen(Quote):
        print(f"{quote.symbol}: ${quote.bid_price} x ${quote.ask_price}")
        print(f"  Spread: ${quote.ask_price - quote.bid_price:.2f}")
        print(f"  Size: {quote.bid_size} x {quote.ask_size}")
```

#### Quote Processing with Logic
```python
async def process_quote_stream(session, symbols, quote_handler):
    """Process quotes with custom handler"""
    streamer = DXLinkStreamer(session)
    
    async with streamer:
        await streamer.subscribe(Quote, symbols)
        
        async for quote in streamer.listen(Quote):
            # Apply custom processing
            await quote_handler(quote)

# Custom quote handler
async def my_quote_handler(quote):
    # Check for tight spreads
    spread = quote.ask_price - quote.bid_price
    spread_pct = spread / quote.bid_price * 100 if quote.bid_price > 0 else 0
    
    if spread_pct < 0.1:  # Less than 0.1% spread
        print(f"Tight spread on {quote.symbol}: {spread_pct:.3f}%")
    
    # Check for large bid/ask sizes
    if quote.bid_size > 1000 or quote.ask_size > 1000:
        print(f"Large size on {quote.symbol}: {quote.bid_size} x {quote.ask_size}")

# Usage
watchlist = ['AAPL', 'SPY', 'QQQ']
await process_quote_stream(session, watchlist, my_quote_handler)
```

### Trade Stream

#### Live Trade Data
```python
from tastytrade.dxfeed import Trade

streamer = DXLinkStreamer(session)

async with streamer:
    await streamer.subscribe(Trade, ['AAPL'])
    
    async for trade in streamer.listen(Trade):
        print(f"AAPL Trade: {trade.size:,} @ ${trade.price:.2f}")
        print(f"  Time: {trade.time}")
        print(f"  Exchange: {trade.exchange_code}")
        print(f"  Conditions: {trade.trade_conditions}")
```

#### Volume Analysis
```python
class VolumeTracker:
    def __init__(self):
        self.volume_data = {}
        self.trade_count = {}
    
    async def track_trades(self, trade):
        symbol = trade.symbol
        
        # Initialize if new symbol
        if symbol not in self.volume_data:
            self.volume_data[symbol] = 0
            self.trade_count[symbol] = 0
        
        # Update counters
        self.volume_data[symbol] += trade.size
        self.trade_count[symbol] += 1
        
        # Check for unusual volume
        if trade.size > 10000:  # Large trade
            print(f"Large trade: {symbol} {trade.size:,} @ ${trade.price:.2f}")
    
    def get_stats(self, symbol):
        return {
            'total_volume': self.volume_data.get(symbol, 0),
            'trade_count': self.trade_count.get(symbol, 0),
            'avg_size': self.volume_data.get(symbol, 0) / max(1, self.trade_count.get(symbol, 1))
        }

# Usage
tracker = VolumeTracker()

streamer = DXLinkStreamer(session)
async with streamer:
    await streamer.subscribe(Trade, ['AAPL', 'SPY'])
    
    async for trade in streamer.listen(Trade):
        await tracker.track_trades(trade)
        
        # Print stats every 100 trades
        if tracker.trade_count.get(trade.symbol, 0) % 100 == 0:
            stats = tracker.get_stats(trade.symbol)
            print(f"{trade.symbol} Stats: {stats}")
```

### Options Data Streaming

#### Greeks and IV Updates
```python
from tastytrade.dxfeed import Greeks

# Monitor option Greeks in real-time
option_symbols = [
    'AAPL  250117C00150000',  # AAPL Call
    'AAPL  250117P00150000',  # AAPL Put
]

streamer = DXLinkStreamer(session)
async with streamer:
    await streamer.subscribe(Greeks, option_symbols)
    
    async for greeks in streamer.listen(Greeks):
        print(f"{greeks.symbol}:")
        print(f"  Delta: {greeks.delta:.3f}")
        print(f"  Gamma: {greeks.gamma:.4f}")
        print(f"  Theta: {greeks.theta:.3f}")
        print(f"  Vega: {greeks.vega:.3f}")
        print(f"  IV: {greeks.implied_volatility:.1%}")
        
        # Alert on significant Greek changes
        if abs(greeks.delta) > 0.7:
            print(f"  🚨 High Delta: {greeks.delta:.3f}")
        
        if greeks.implied_volatility > 0.5:  # 50% IV
            print(f"  🚨 High IV: {greeks.implied_volatility:.1%}")
```

#### Option Chain Monitoring
```python
class OptionChainMonitor:
    def __init__(self, underlying, expiration):
        self.underlying = underlying
        self.expiration = expiration
        self.strikes = {}
    
    def get_option_symbols(self, strikes):
        """Generate option symbols for strikes"""
        symbols = []
        exp_str = self.expiration.strftime('%y%m%d')
        
        for strike in strikes:
            strike_str = f"{int(strike * 1000):08d}"
            call_symbol = f"{self.underlying:<6}{exp_str}C{strike_str}"
            put_symbol = f"{self.underlying:<6}{exp_str}P{strike_str}"
            symbols.extend([call_symbol, put_symbol])
        
        return symbols
    
    async def monitor_chain(self, session, strikes):
        symbols = self.get_option_symbols(strikes)
        
        streamer = DXLinkStreamer(session)
        async with streamer:
            # Subscribe to both quotes and Greeks
            await streamer.subscribe(Quote, symbols)
            await streamer.subscribe(Greeks, symbols)
            
            # Process updates
            quote_task = asyncio.create_task(self._process_quotes(streamer))
            greeks_task = asyncio.create_task(self._process_greeks(streamer))
            
            await asyncio.gather(quote_task, greeks_task)
    
    async def _process_quotes(self, streamer):
        async for quote in streamer.listen(Quote):
            self.strikes[quote.symbol] = {
                **self.strikes.get(quote.symbol, {}),
                'bid': quote.bid_price,
                'ask': quote.ask_price,
                'last': quote.last_price
            }
    
    async def _process_greeks(self, streamer):
        async for greeks in streamer.listen(Greeks):
            self.strikes[greeks.symbol] = {
                **self.strikes.get(greeks.symbol, {}),
                'delta': greeks.delta,
                'gamma': greeks.gamma,
                'theta': greeks.theta,
                'vega': greeks.vega,
                'iv': greeks.implied_volatility
            }

# Usage
from datetime import datetime
expiration = datetime(2025, 1, 17)
monitor = OptionChainMonitor('AAPL', expiration)

# Monitor strikes around current price
strikes = [140, 145, 150, 155, 160]
await monitor.monitor_chain(session, strikes)
```

## Account Data Streaming

### Account Balance Updates
```python
from tastytrade.dxfeed import AccountUpdate

streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to account updates
    await streamer.subscribe(AccountUpdate, [account.account_number])
    
    async for update in streamer.listen(AccountUpdate):
        print(f"Account Update: {update.type}")
        
        if hasattr(update, 'net_liquidating_value'):
            print(f"  NLV: ${update.net_liquidating_value:,.2f}")
        
        if hasattr(update, 'buying_power'):
            print(f"  Buying Power: ${update.buying_power:,.2f}")
        
        if hasattr(update, 'cash_balance'):
            print(f"  Cash: ${update.cash_balance:,.2f}")
```

### Position Change Monitoring
```python
class PositionMonitor:
    def __init__(self):
        self.positions = {}
        self.alerts = []
    
    async def monitor_positions(self, session, account_number):
        streamer = DXLinkStreamer(session)
        
        async with streamer:
            await streamer.subscribe(AccountUpdate, [account_number])
            
            async for update in streamer.listen(AccountUpdate):
                await self._process_account_update(update)
    
    async def _process_account_update(self, update):
        if update.type == 'POSITION_UPDATE':
            symbol = getattr(update, 'symbol', None)
            quantity = getattr(update, 'quantity', None)
            market_value = getattr(update, 'market_value', None)
            
            if symbol and quantity is not None:
                old_quantity = self.positions.get(symbol, {}).get('quantity', 0)
                
                self.positions[symbol] = {
                    'quantity': quantity,
                    'market_value': market_value,
                    'last_update': datetime.now()
                }
                
                # Check for significant position changes
                if abs(quantity - old_quantity) >= 100:  # 100+ share change
                    self.alerts.append({
                        'type': 'POSITION_CHANGE',
                        'symbol': symbol,
                        'old_quantity': old_quantity,
                        'new_quantity': quantity,
                        'change': quantity - old_quantity
                    })
    
    def get_alerts(self):
        alerts = self.alerts.copy()
        self.alerts.clear()
        return alerts

# Usage
monitor = PositionMonitor()

# Run in background
position_task = asyncio.create_task(
    monitor.monitor_positions(session, account.account_number)
)

# Check for alerts periodically
while True:
    alerts = monitor.get_alerts()
    for alert in alerts:
        print(f"Position Alert: {alert}")
    
    await asyncio.sleep(5)
```

## Advanced Streaming Patterns

### Multi-Symbol Streaming with Filtering
```python
class SmartStreamer:
    def __init__(self, session):
        self.session = session
        self.filters = []
        self.handlers = {}
    
    def add_filter(self, filter_func):
        """Add a filter function to screen data"""
        self.filters.append(filter_func)
    
    def add_handler(self, data_type, handler_func):
        """Add a handler for specific data type"""
        if data_type not in self.handlers:
            self.handlers[data_type] = []
        self.handlers[data_type].append(handler_func)
    
    async def start_streaming(self, subscriptions):
        """Start streaming with filters and handlers"""
        streamer = DXLinkStreamer(self.session)
        
        async with streamer:
            # Subscribe to all requested data types
            for data_type, symbols in subscriptions.items():
                await streamer.subscribe(data_type, symbols)
            
            # Process all data types
            tasks = []
            for data_type in subscriptions.keys():
                task = asyncio.create_task(
                    self._process_data_type(streamer, data_type)
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks)
    
    async def _process_data_type(self, streamer, data_type):
        async for data in streamer.listen(data_type):
            # Apply filters
            if self._should_process(data):
                # Call handlers
                for handler in self.handlers.get(data_type, []):
                    try:
                        await handler(data)
                    except Exception as e:
                        print(f"Handler error: {e}")
    
    def _should_process(self, data):
        """Check if data passes all filters"""
        for filter_func in self.filters:
            if not filter_func(data):
                return False
        return True

# Usage example
smart_streamer = SmartStreamer(session)

# Add filters
smart_streamer.add_filter(lambda data: hasattr(data, 'symbol') and data.symbol in ['AAPL', 'SPY'])
smart_streamer.add_filter(lambda data: hasattr(data, 'volume') and data.volume > 1000)

# Add handlers
async def quote_handler(quote):
    print(f"Filtered quote: {quote.symbol} ${quote.last_price}")

async def trade_handler(trade):
    print(f"Large trade: {trade.symbol} {trade.size}")

smart_streamer.add_handler(Quote, quote_handler)
smart_streamer.add_handler(Trade, trade_handler)

# Start streaming
subscriptions = {
    Quote: ['AAPL', 'SPY', 'QQQ'],
    Trade: ['AAPL', 'SPY']
}

await smart_streamer.start_streaming(subscriptions)
```

### Connection Management and Reconnection
```python
class RobustStreamer:
    def __init__(self, session, max_retries=5):
        self.session = session
        self.max_retries = max_retries
        self.subscriptions = {}
        self.is_running = False
    
    async def add_subscription(self, data_type, symbols):
        """Add subscription to be maintained across reconnections"""
        if data_type not in self.subscriptions:
            self.subscriptions[data_type] = set()
        self.subscriptions[data_type].update(symbols)
    
    async def start_streaming(self, data_handler):
        """Start streaming with automatic reconnection"""
        self.is_running = True
        retry_count = 0
        
        while self.is_running and retry_count < self.max_retries:
            try:
                await self._stream_with_reconnect(data_handler)
                retry_count = 0  # Reset on successful connection
            
            except Exception as e:
                retry_count += 1
                wait_time = min(2 ** retry_count, 60)  # Exponential backoff, max 60s
                
                print(f"Stream error (attempt {retry_count}): {e}")
                print(f"Reconnecting in {wait_time} seconds...")
                
                await asyncio.sleep(wait_time)
        
        if retry_count >= self.max_retries:
            raise Exception(f"Failed to maintain stream after {self.max_retries} attempts")
    
    async def _stream_with_reconnect(self, data_handler):
        streamer = DXLinkStreamer(self.session)
        
        async with streamer:
            # Re-establish all subscriptions
            for data_type, symbols in self.subscriptions.items():
                await streamer.subscribe(data_type, list(symbols))
            
            print("Stream connected, processing data...")
            
            # Process data from all subscriptions
            async for data in self._listen_all_types(streamer):
                await data_handler(data)
    
    async def _listen_all_types(self, streamer):
        """Listen to all subscribed data types"""
        tasks = []
        queue = asyncio.Queue()
        
        # Create tasks for each data type
        for data_type in self.subscriptions.keys():
            task = asyncio.create_task(
                self._listen_and_queue(streamer, data_type, queue)
            )
            tasks.append(task)
        
        # Yield data as it arrives
        try:
            while True:
                data = await queue.get()
                if data is None:  # Shutdown signal
                    break
                yield data
        finally:
            # Clean up tasks
            for task in tasks:
                task.cancel()
    
    async def _listen_and_queue(self, streamer, data_type, queue):
        """Listen to specific data type and queue results"""
        try:
            async for data in streamer.listen(data_type):
                await queue.put(data)
        except Exception as e:
            await queue.put(None)  # Signal shutdown
            raise
    
    def stop(self):
        """Stop streaming"""
        self.is_running = False

# Usage
robust_streamer = RobustStreamer(session, max_retries=10)

# Add subscriptions
await robust_streamer.add_subscription(Quote, ['AAPL', 'SPY'])
await robust_streamer.add_subscription(Trade, ['AAPL'])

# Define data handler
async def handle_stream_data(data):
    if isinstance(data, Quote):
        print(f"Quote: {data.symbol} ${data.last_price}")
    elif isinstance(data, Trade):
        print(f"Trade: {data.symbol} {data.size} @ ${data.price}")

# Start streaming (will maintain connection)
await robust_streamer.start_streaming(handle_stream_data)
```

## Performance Optimization

### Subscription Management
```python
class SubscriptionManager:
    def __init__(self, session):
        self.session = session
        self.active_subscriptions = {}
        self.streamer = None
    
    async def start(self):
        """Start the streaming connection"""
        if not self.streamer:
            self.streamer = DXLinkStreamer(self.session)
            await self.streamer.__aenter__()
    
    async def stop(self):
        """Stop the streaming connection"""
        if self.streamer:
            await self.streamer.__aexit__(None, None, None)
            self.streamer = None
    
    async def subscribe(self, data_type, symbols):
        """Add symbols to subscription"""
        if not self.streamer:
            await self.start()
        
        if data_type not in self.active_subscriptions:
            self.active_subscriptions[data_type] = set()
        
        new_symbols = set(symbols) - self.active_subscriptions[data_type]
        if new_symbols:
            await self.streamer.subscribe(data_type, list(new_symbols))
            self.active_subscriptions[data_type].update(new_symbols)
    
    async def unsubscribe(self, data_type, symbols):
        """Remove symbols from subscription"""
        if data_type in self.active_subscriptions:
            symbols_to_remove = set(symbols) & self.active_subscriptions[data_type]
            if symbols_to_remove:
                await self.streamer.unsubscribe(data_type, list(symbols_to_remove))
                self.active_subscriptions[data_type] -= symbols_to_remove
    
    async def listen(self, data_type):
        """Listen for data of specific type"""
        if self.streamer:
            async for data in self.streamer.listen(data_type):
                yield data

# Usage
manager = SubscriptionManager(session)

# Dynamic subscription management
await manager.subscribe(Quote, ['AAPL'])

# Later add more symbols
await manager.subscribe(Quote, ['SPY', 'QQQ'])

# Remove symbols when no longer needed
await manager.unsubscribe(Quote, ['AAPL'])

# Listen for data
async for quote in manager.listen(Quote):
    print(f"Quote: {quote.symbol}")
```

### Data Rate Limiting
```python
class ThrottledStreamer:
    def __init__(self, session, max_updates_per_second=100):
        self.session = session
        self.rate_limit = 1.0 / max_updates_per_second
        self.last_update = {}
    
    async def stream_with_throttle(self, data_type, symbols, handler):
        """Stream data with rate limiting per symbol"""
        streamer = DXLinkStreamer(self.session)
        
        async with streamer:
            await streamer.subscribe(data_type, symbols)
            
            async for data in streamer.listen(data_type):
                symbol = getattr(data, 'symbol', 'unknown')
                now = time.time()
                
                # Check if enough time has passed since last update
                last_time = self.last_update.get(symbol, 0)
                if now - last_time >= self.rate_limit:
                    self.last_update[symbol] = now
                    await handler(data)

# Usage with throttling
throttled = ThrottledStreamer(session, max_updates_per_second=10)

async def handle_throttled_quote(quote):
    print(f"Throttled quote: {quote.symbol} ${quote.last_price}")

await throttled.stream_with_throttle(
    Quote, 
    ['AAPL', 'SPY'], 
    handle_throttled_quote
)
```

## Error Handling and Monitoring

### Stream Health Monitoring
```python
class StreamHealthMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.message_counts = defaultdict(int)
        self.last_message_time = {}
        self.errors = []
    
    def record_message(self, data_type, symbol=None):
        """Record a received message"""
        key = f"{data_type}_{symbol}" if symbol else str(data_type)
        self.message_counts[key] += 1
        self.last_message_time[key] = time.time()
    
    def record_error(self, error):
        """Record an error"""
        self.errors.append({
            'time': time.time(),
            'error': str(error),
            'type': type(error).__name__
        })
    
    def get_stats(self):
        """Get streaming statistics"""
        now = time.time()
        uptime = now - self.start_time
        
        total_messages = sum(self.message_counts.values())
        messages_per_second = total_messages / uptime if uptime > 0 else 0
        
        # Check for stale streams (no data in last 30 seconds)
        stale_streams = []
        for key, last_time in self.last_message_time.items():
            if now - last_time > 30:
                stale_streams.append(key)
        
        return {
            'uptime': uptime,
            'total_messages': total_messages,
            'messages_per_second': messages_per_second,
            'error_count': len(self.errors),
            'stale_streams': stale_streams,
            'message_breakdown': dict(self.message_counts)
        }

# Integration with streaming
monitor = StreamHealthMonitor()

async def monitored_stream_handler(data):
    try:
        # Record the message
        data_type = type(data).__name__
        symbol = getattr(data, 'symbol', None)
        monitor.record_message(data_type, symbol)
        
        # Process the data
        await process_stream_data(data)
        
    except Exception as e:
        monitor.record_error(e)
        raise

# Print stats periodically
async def print_stream_stats():
    while True:
        await asyncio.sleep(60)  # Every minute
        stats = monitor.get_stats()
        print(f"Stream Stats: {stats}")

# Run monitoring in background
stats_task = asyncio.create_task(print_stream_stats())
```

This comprehensive streaming documentation covers the essential patterns for real-time data processing with the TastyTrade API. The examples show production-ready patterns for connection management, error handling, and performance optimization.