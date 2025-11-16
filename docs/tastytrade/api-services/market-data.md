# Market Data API Service

The Market Data API provides comprehensive market information including real-time quotes, historical data, option chains, and market metrics.

## Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instruments/{symbol}/quote` | Current quote |
| GET | `/instruments/{symbol}/candles` | Historical OHLCV data |
| GET | `/instruments/{symbol}/option-chain` | Option chain |
| GET | `/instruments/{symbol}/greeks` | Option Greeks |
| GET | `/instruments/search` | Symbol search |
| GET | `/market-data/expirations/{symbol}` | Option expirations |
| GET | `/market-data/strikes/{symbol}/{expiration}` | Strike prices |

## Real-time Quotes

### Stock Quotes
```python
from tastytrade.instruments import EquityInstrument

# Get current stock quote
instrument = EquityInstrument.get_equity(session, 'AAPL')
quote = instrument.get_quote(session)

print(f"{quote.symbol}: ${quote.last}")
print(f"Bid: ${quote.bid} x {quote.bid_size}")
print(f"Ask: ${quote.ask} x {quote.ask_size}")
print(f"Volume: {quote.volume:,}")
print(f"Change: {quote.change:+.2f} ({quote.change_percent:+.1f}%)")
```

### Option Quotes
```python
from tastytrade.instruments import OptionInstrument

# Get option quote
option_symbol = 'AAPL  250117C00150000'
instrument = OptionInstrument.get_option(session, option_symbol)
quote = instrument.get_quote(session)

print(f"{quote.symbol}:")
print(f"Last: ${quote.last}")
print(f"Bid: ${quote.bid} x {quote.bid_size}")
print(f"Ask: ${quote.ask} x {quote.ask_size}")
print(f"Open Interest: {quote.open_interest:,}")
print(f"Volume: {quote.volume:,}")
```

### Multi-Symbol Quotes
```python
# Get quotes for multiple symbols
symbols = ['AAPL', 'GOOGL', 'MSFT', 'TSLA']
quotes = await get_quotes(session, symbols)

for symbol, quote in quotes.items():
    print(f"{symbol}: ${quote.last} ({quote.change_percent:+.1f}%)")
```

## Historical Data

### OHLCV Candles
```python
from datetime import datetime, timedelta

# Get daily candles for last 30 days
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

candles = instrument.get_candles(
    session,
    start_time=start_date,
    end_time=end_date,
    interval='1Day'
)

for candle in candles[-5:]:  # Last 5 days
    print(f"{candle.time}: O=${candle.open:.2f} H=${candle.high:.2f} L=${candle.low:.2f} C=${candle.close:.2f}")
    print(f"  Volume: {candle.volume:,}")
```

### Available Intervals
| Interval | Description |
|----------|-------------|
| `1min` | 1-minute candles |
| `5min` | 5-minute candles |
| `15min` | 15-minute candles |
| `30min` | 30-minute candles |
| `1h` | 1-hour candles |
| `4h` | 4-hour candles |
| `1Day` | Daily candles |
| `1Week` | Weekly candles |
| `1Month` | Monthly candles |

### Intraday Data
```python
# Get 5-minute candles for today
from datetime import datetime

today = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)  # Market open
end_time = datetime.now()

intraday_candles = instrument.get_candles(
    session,
    start_time=today,
    end_time=end_time,
    interval='5min'
)

for candle in intraday_candles:
    print(f"{candle.time.strftime('%H:%M')}: ${candle.close:.2f} Vol: {candle.volume}")
```

## Option Chains

### Complete Option Chain
```python
from tastytrade.instruments import get_option_chain

# Get full option chain
option_chain = await get_option_chain(session, 'AAPL')

print(f"AAPL option chain ({len(option_chain.expirations)} expirations):")
for expiry in option_chain.expirations:
    print(f"  {expiry}: {len(option_chain.strikes[expiry])} strikes")
```

### Specific Expiration
```python
# Get options for specific expiration
expiration = '2025-01-17'
strikes = option_chain.get_strikes(expiration)

print(f"Options expiring {expiration}:")
for strike in strikes:
    call = strike.call
    put = strike.put
    
    print(f"Strike ${strike.strike_price}:")
    if call:
        print(f"  Call: ${call.last} (Bid: ${call.bid}, Ask: ${call.ask})")
    if put:
        print(f"  Put:  ${put.last} (Bid: ${put.bid}, Ask: ${put.ask})")
```

### Filtered Option Chain
```python
# Get ATM options only
underlying_price = instrument.get_quote(session).last
atm_strikes = option_chain.get_atm_strikes(underlying_price, range_pct=5)  # Within 5%

for strike in atm_strikes:
    if abs(strike.strike_price - underlying_price) / underlying_price <= 0.05:
        print(f"ATM Strike ${strike.strike_price}:")
        print(f"  Call IV: {strike.call.implied_volatility:.1%}")
        print(f"  Put IV: {strike.put.implied_volatility:.1%}")
```

## Option Greeks

### Individual Option Greeks
```python
from tastytrade.instruments import get_option_greeks

# Get Greeks for specific option
greeks = await get_option_greeks(session, option_symbol)

print(f"Greeks for {option_symbol}:")
print(f"Delta: {greeks.delta:.3f}")
print(f"Gamma: {greeks.gamma:.3f}")
print(f"Theta: {greeks.theta:.3f}")
print(f"Vega: {greeks.vega:.3f}")
print(f"Rho: {greeks.rho:.3f}")
print(f"IV: {greeks.implied_volatility:.1%}")
```

### Position Greeks (Portfolio)
```python
# Calculate net Greeks for option positions
async def calculate_position_greeks(account, session):
    positions = await account.a_get_positions(session)
    
    total_delta = 0
    total_gamma = 0
    total_theta = 0
    total_vega = 0
    
    for position in positions:
        if position.instrument_type == 'option':
            greeks = await get_option_greeks(session, position.symbol)
            quantity = position.quantity
            
            total_delta += greeks.delta * quantity
            total_gamma += greeks.gamma * quantity
            total_theta += greeks.theta * quantity
            total_vega += greeks.vega * quantity
    
    return {
        'delta': total_delta,
        'gamma': total_gamma,
        'theta': total_theta,
        'vega': total_vega
    }

portfolio_greeks = await calculate_position_greeks(account, session)
print(f"Portfolio Greeks: {portfolio_greeks}")
```

## Symbol Search

### Equity Search
```python
from tastytrade.instruments import search_symbols

# Search for symbols
results = await search_symbols(session, 'apple')

for result in results:
    print(f"{result.symbol}: {result.description}")
    print(f"  Exchange: {result.exchange}")
    print(f"  Type: {result.instrument_type}")
```

### Filtered Search
```python
# Search with filters
results = await search_symbols(
    session,
    query='tech',
    instrument_type='equity',
    limit=10
)

for result in results:
    print(f"{result.symbol}: {result.description}")
```

## Market Hours and Status

### Trading Sessions
```python
from tastytrade.market import get_market_sessions

# Get market hours for date
from datetime import date
today = date.today()

sessions = await get_market_sessions(session, today)

for session_info in sessions:
    print(f"{session_info.market}:")
    print(f"  Pre-market: {session_info.premarket_start} - {session_info.premarket_end}")
    print(f"  Regular: {session_info.regular_start} - {session_info.regular_end}")
    print(f"  After-hours: {session_info.afterhours_start} - {session_info.afterhours_end}")
```

### Market Status
```python
from tastytrade.market import get_market_status

# Check if market is open
status = await get_market_status(session)

print(f"Market Status: {status.status}")  # OPEN, CLOSED, PRE_MARKET, AFTER_HOURS
print(f"Next open: {status.next_open}")
print(f"Next close: {status.next_close}")
```

## Streaming Market Data

### Real-time Quote Stream
```python
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Quote

# Stream real-time quotes
streamer = DXLinkStreamer(session)

async with streamer:
    # Subscribe to symbols
    symbols = ['AAPL', 'GOOGL', 'MSFT']
    await streamer.subscribe(Quote, symbols)
    
    # Process quote updates
    async for quote in streamer.listen(Quote):
        print(f"{quote.symbol}: ${quote.bid_price} x ${quote.ask_price}")
        print(f"  Last: ${quote.last_price} Vol: {quote.volume}")
        
        # Process specific symbols
        if quote.symbol == 'AAPL':
            await process_aapl_quote(quote)
```

### Option Stream
```python
from tastytrade.dxfeed import Greeks

# Stream option Greeks
async with streamer:
    option_symbols = ['AAPL  250117C00150000', 'AAPL  250117P00150000']
    await streamer.subscribe(Greeks, option_symbols)
    
    async for greeks in streamer.listen(Greeks):
        print(f"{greeks.symbol}:")
        print(f"  Delta: {greeks.delta:.3f}, IV: {greeks.implied_volatility:.1%}")
```

### Trade Stream
```python
from tastytrade.dxfeed import Trade

# Stream trade data
async with streamer:
    await streamer.subscribe(Trade, ['AAPL'])
    
    async for trade in streamer.listen(Trade):
        print(f"AAPL Trade: {trade.size} @ ${trade.price}")
        print(f"  Time: {trade.time}, Exchange: {trade.exchange_code}")
```

## Market Data Utilities

### Quote Comparison
```python
def compare_quotes(quotes_dict):
    """Compare quotes across symbols"""
    sorted_quotes = sorted(
        quotes_dict.items(),
        key=lambda x: x[1].change_percent,
        reverse=True
    )
    
    print("Top performers:")
    for symbol, quote in sorted_quotes[:5]:
        print(f"  {symbol}: {quote.change_percent:+.1f}%")
    
    print("\nBottom performers:")
    for symbol, quote in sorted_quotes[-5:]:
        print(f"  {symbol}: {quote.change_percent:+.1f}%")
```

### Volatility Analysis
```python
def analyze_option_volatility(option_chain, expiration):
    """Analyze implied volatility across strikes"""
    strikes = option_chain.get_strikes(expiration)
    
    call_ivs = []
    put_ivs = []
    
    for strike in strikes:
        if strike.call and strike.call.implied_volatility:
            call_ivs.append(strike.call.implied_volatility)
        if strike.put and strike.put.implied_volatility:
            put_ivs.append(strike.put.implied_volatility)
    
    if call_ivs:
        avg_call_iv = sum(call_ivs) / len(call_ivs)
        print(f"Average Call IV: {avg_call_iv:.1%}")
    
    if put_ivs:
        avg_put_iv = sum(put_ivs) / len(put_ivs)
        print(f"Average Put IV: {avg_put_iv:.1%}")
    
    return {
        'call_iv': avg_call_iv if call_ivs else None,
        'put_iv': avg_put_iv if put_ivs else None
    }
```

### Volume Analysis
```python
def analyze_volume(candles):
    """Analyze volume patterns"""
    volumes = [candle.volume for candle in candles if candle.volume]
    
    if not volumes:
        return None
    
    avg_volume = sum(volumes) / len(volumes)
    recent_volume = volumes[-1] if volumes else 0
    
    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 0
    
    return {
        'average_volume': avg_volume,
        'recent_volume': recent_volume,
        'volume_ratio': volume_ratio,
        'is_high_volume': volume_ratio > 1.5
    }
```

## Error Handling

### Market Data Errors
```python
from tastytrade.exceptions import TastyTradeError

async def get_quote_with_fallback(session, symbol):
    """Get quote with fallback handling"""
    try:
        instrument = EquityInstrument.get_equity(session, symbol)
        return instrument.get_quote(session)
    
    except TastyTradeError as e:
        if e.status_code == 404:
            print(f"Symbol {symbol} not found")
            return None
        elif e.status_code == 429:
            print(f"Rate limited, waiting...")
            await asyncio.sleep(1)
            return await get_quote_with_fallback(session, symbol)
        else:
            raise
    
    except Exception as e:
        print(f"Unexpected error getting quote for {symbol}: {e}")
        return None
```

### Stream Error Handling
```python
async def robust_market_stream(session, symbols):
    """Market data stream with error recovery"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            streamer = DXLinkStreamer(session)
            async with streamer:
                await streamer.subscribe(Quote, symbols)
                
                async for quote in streamer.listen(Quote):
                    await process_quote(quote)
                    
        except Exception as e:
            retry_count += 1
            print(f"Stream error (attempt {retry_count}): {e}")
            
            if retry_count < max_retries:
                await asyncio.sleep(2 ** retry_count)  # Exponential backoff
            else:
                print("Max retries exceeded for market stream")
                raise
```

## Performance Optimization

### Batch Quote Requests
```python
async def get_multiple_quotes_efficiently(session, symbols):
    """Get quotes for multiple symbols efficiently"""
    # Use asyncio.gather for concurrent requests
    tasks = []
    
    for symbol in symbols:
        task = get_quote_with_fallback(session, symbol)
        tasks.append(task)
    
    quotes = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions and None results
    valid_quotes = {}
    for symbol, quote in zip(symbols, quotes):
        if not isinstance(quote, Exception) and quote is not None:
            valid_quotes[symbol] = quote
    
    return valid_quotes
```

### Caching Strategy
```python
from datetime import datetime, timedelta

class QuoteCache:
    def __init__(self, ttl_seconds=5):
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)
    
    async def get_quote(self, session, symbol):
        now = datetime.now()
        
        # Check cache
        if symbol in self.cache:
            cached_quote, timestamp = self.cache[symbol]
            if now - timestamp < self.ttl:
                return cached_quote
        
        # Fetch fresh quote
        quote = await get_quote_with_fallback(session, symbol)
        if quote:
            self.cache[symbol] = (quote, now)
        
        return quote

# Usage
cache = QuoteCache(ttl_seconds=5)
quote = await cache.get_quote(session, 'AAPL')
```

This Market Data API documentation provides comprehensive coverage of quote retrieval, historical data access, option chains, and streaming capabilities essential for trading applications.