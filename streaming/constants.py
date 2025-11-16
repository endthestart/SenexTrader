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
