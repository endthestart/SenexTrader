"""
Streaming service constants - subscription limits, intervals, timeouts.

All magic numbers extracted from streaming services to centralize configuration
and improve maintainability.
"""

# Subscription Management
MAX_SUBSCRIPTIONS = 500  # Prevent runaway subscription growth
SUBSCRIPTION_CLEANUP_SECONDS = 3600  # 1 hour - remove old subscriptions

# Refresh Intervals (seconds)
QUOTE_REFRESH_INTERVAL = 0.5  # Market quote updates
GREEKS_REFRESH_INTERVAL = 1.0  # Greeks calculations
UNDERLYING_QUOTE_REFRESH_INTERVAL = 0.25  # Underlying symbols (SPY, QQQ)
SUMMARY_REFRESH_INTERVAL = 5.0  # Daily summary data

# Timing & Delays
SUBSCRIPTION_DELAY = 0.2  # Delay between subscription batches
CHANNEL_RACE_DELAY = 0.1  # Prevent DXFeed channel race conditions

# Timeouts (seconds)
AUTOMATION_TIMEOUT = 65  # Automated task streaming startup (60s AlertStreamer + 5s buffer)
STREAMING_DATA_WAIT_TIMEOUT = 15  # Wait for first data after connection
CACHE_WAIT_TIMEOUT = 30  # Wait for cache population
DXLINK_CONNECTION_TIMEOUT = 30  # DXLink WebSocket connection
STREAMER_CLOSE_TIMEOUT = 2.0  # Graceful streamer shutdown
METRICS_TASK_TIMEOUT = 2.0  # Metrics task cleanup
STREAMING_TASK_TIMEOUT = 5.0  # Main streaming task cleanup
CANCELLATION_TIMEOUT = 0.5  # Task cancellation in Python 3.13

# Update Intervals (seconds)
METRICS_UPDATE_INTERVAL = 30  # Position metrics broadcast frequency

# Cache TTLs (seconds)
QUOTE_CACHE_TTL = 360  # Quote data freshness - 6 minutes (exceeds 5-minute freshness check)
GREEKS_CACHE_TTL = 300  # Greeks data freshness - increased to 5min for stability
SUMMARY_CACHE_TTL = 3600  # 1 hour - daily summary data

# Activity Tracking (GlobalStreamManager)
INACTIVITY_TIMEOUT_SECONDS = 1800  # 30 minutes - mark inactive
CLEANUP_TIMEOUT_SECONDS = 3600  # 1 hour - remove inactive managers

# Automation Polling
AUTOMATION_READY_POLL_INTERVAL = 1  # Poll delay while waiting for data readiness

# Cache Defaults (seconds)
CACHE_DEFAULT_TTL = 30  # Fallback TTL for cache entries without explicit type
TRADE_CACHE_TTL = 30  # Real-time trade data TTL
THEO_CACHE_TTL = 60  # Theoretical pricing data TTL
STREAM_LEASE_TTL = 600  # Stream lease duration (10 minutes)
HEARTBEAT_CACHE_TTL = 30  # Heartbeat freshness
ACCOUNT_STATE_CACHE_TTL = 120  # Cached account/balance data TTL

# Retry Settings
CACHE_MAX_RETRIES = 2  # Enhanced cache retry attempts
CACHE_BASE_RETRY_DELAY = 0.1  # Initial delay for exponential backoff
STREAMING_AUTH_MAX_RETRIES = 2  # Streaming auth retry attempts

# Cleanup Grace Periods
STREAMING_CLEANUP_GRACE_PERIOD = 300  # 5 minutes - wait before tearing down streamers
