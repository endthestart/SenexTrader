"""
Service layer constants - API timeouts, retry counts, sync intervals.

All magic numbers extracted from services to centralize configuration
and improve maintainability.
"""

# HTTP API Timeouts (seconds)
API_TIMEOUT = 30  # Standard HTTP request timeout (historical data, external APIs)
API_TIMEOUT_SHORT = 15  # Short timeout for broker API calls (TastyTrade)

# Cache TTLs (seconds) - Complement to cache_config.py for service-specific values
OPTION_CHAIN_CACHE_TTL = 300  # 5 minutes - option chain data
