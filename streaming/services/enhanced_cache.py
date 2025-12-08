"""
Enhanced caching wrapper for streaming infrastructure.

Provides async-first cache operations with error handling, retry logic,
monitoring, and batch operations to improve performance and reliability.
"""

import asyncio
import time
from typing import Any

from django.core.cache import cache

from services.core.cache import CacheTTL
from services.core.logging import get_logger
from streaming.constants import (
    CACHE_BASE_RETRY_DELAY,
    CACHE_DEFAULT_TTL,
    CACHE_MAX_RETRIES,
    HEARTBEAT_CACHE_TTL,
    STREAM_LEASE_TTL,
    THEO_CACHE_TTL,
    TRADE_CACHE_TTL,
)

logger = get_logger(__name__)


class CacheStats:
    """Track cache operation statistics for monitoring."""

    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.errors = 0
        self.sets = 0
        self.deletes = 0
        self.batch_operations = 0
        self.total_latency = 0.0
        self.operation_count = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    @property
    def average_latency(self) -> float:
        """Calculate average operation latency in milliseconds."""
        return (
            (self.total_latency / self.operation_count * 1000) if self.operation_count > 0 else 0.0
        )

    def get_stats(self) -> dict[str, int | float]:
        """Get all statistics as a dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "sets": self.sets,
            "deletes": self.deletes,
            "batch_operations": self.batch_operations,
            "hit_rate": self.hit_rate,
            "average_latency_ms": self.average_latency,
            "total_operations": self.operation_count,
        }


class EnhancedCache:
    """
    Enhanced async cache wrapper with error handling, retry logic, and monitoring.

    Provides a more robust caching layer over Django's cache framework with:
    - Async-first operations
    - Automatic retry logic for transient failures
    - Error handling and graceful degradation
    - Performance monitoring and statistics
    - Batch operations for efficiency
    - Smart TTL management
    """

    def __init__(
        self,
        max_retries: int = CACHE_MAX_RETRIES,
        base_retry_delay: float = CACHE_BASE_RETRY_DELAY,
    ):
        """
        Initialize enhanced cache wrapper.

        Args:
            max_retries: Maximum number of retry attempts for failed operations
            base_retry_delay: Base delay between retries in seconds
        """
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.stats = CacheStats()

        # TTL configurations for different data types (in seconds)
        self.ttl_config = {
            "quote": CacheTTL.QUOTE,
            "greeks": CacheTTL.GREEKS,
            "trade": TRADE_CACHE_TTL,
            "summary": CacheTTL.SUMMARY,
            "profile": CacheTTL.PROFILE,
            "theo": THEO_CACHE_TTL,
            "underlying": CacheTTL.QUOTE,
            "option_chain": CacheTTL.OPTION_CHAIN,
            "account_state": CacheTTL.ACCOUNT_STATE,
            "stream_lease": STREAM_LEASE_TTL,
            "heartbeat": HEARTBEAT_CACHE_TTL,
        }

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get value from cache with error handling and retries.

        Args:
            key: Cache key
            default: Default value if key not found or error occurs

        Returns:
            Cached value or default
        """
        return await self._retry_operation(self._get_operation, key, default)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        Set value in cache with automatic TTL management.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (auto-determined if None)

        Returns:
            True if successful, False otherwise
        """
        if ttl is None:
            ttl = self._determine_ttl(key)

        return await self._retry_operation(self._set_operation, key, value, ttl)

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if successful, False otherwise
        """
        return await self._retry_operation(self._delete_operation, key)

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Get multiple values from cache in a single operation.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary mapping keys to values (missing keys excluded)
        """
        return await self._retry_operation(self._get_many_operation, keys)

    async def set_many(self, data: dict[str, Any], ttl: int | None = None) -> bool:
        """
        Set multiple values in cache in a single operation.

        Args:
            data: Dictionary mapping keys to values
            ttl: Time to live in seconds (auto-determined if None)

        Returns:
            True if successful, False otherwise
        """
        return await self._retry_operation(self._set_many_operation, data, ttl)

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Key pattern with wildcards (e.g., "user:123:*")

        Returns:
            Number of keys deleted
        """
        return await self._retry_operation(self._delete_pattern_operation, pattern)

    async def _get_operation(self, key: str, default: Any = None) -> Any:
        """Internal get operation."""
        start_time = time.time()
        try:
            result = await asyncio.to_thread(cache.get, key, default)
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time

            if result == default:
                self.stats.misses += 1
            else:
                self.stats.hits += 1

            return result
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache get error for key {key}: {e}")
            return default

    async def _set_operation(self, key: str, value: Any, ttl: int) -> bool:
        """Internal set operation."""
        start_time = time.time()
        try:
            await asyncio.to_thread(cache.set, key, value, ttl)
            self.stats.sets += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            return True
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache set error for key {key}: {e}")
            return False

    async def _delete_operation(self, key: str) -> bool:
        """Internal delete operation."""
        start_time = time.time()
        try:
            await asyncio.to_thread(cache.delete, key)
            self.stats.deletes += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            return True
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    async def _get_many_operation(self, keys: list[str]) -> dict[str, Any]:
        """Internal get_many operation."""
        start_time = time.time()
        try:
            result = await asyncio.to_thread(cache.get_many, keys)
            self.stats.batch_operations += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time

            self.stats.hits += len(result)
            self.stats.misses += len(keys) - len(result)
            return result
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache get_many error: {e}")
            return {}

    async def _set_many_operation(self, data: dict[str, Any], ttl: int | None) -> bool:
        """Internal set_many operation."""
        start_time = time.time()
        try:
            # If no TTL provided, use the first key to determine TTL
            if ttl is None and data:
                first_key = next(iter(data.keys()))
                ttl = self._determine_ttl(first_key)

            await asyncio.to_thread(cache.set_many, data, ttl or 30)
            self.stats.batch_operations += 1
            self.stats.sets += len(data)
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            return True
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache set_many error: {e}")
            return False

    async def _delete_pattern_operation(self, pattern: str) -> int:
        """Internal delete pattern operation."""
        start_time = time.time()
        try:
            # Get keys matching pattern
            if hasattr(cache, "delete_pattern"):
                # Redis backend supports delete_pattern
                deleted = await asyncio.to_thread(cache.delete_pattern, pattern)
            # Fallback for other backends
            elif "*" in pattern:
                # Simple pattern matching for keys
                prefix = pattern.replace("*", "")
                keys = await asyncio.to_thread(cache._cache.keys, f"{prefix}*")
                deleted = len(keys)
                if keys:
                    await asyncio.to_thread(cache.delete_many, keys)
            else:
                # Single key deletion
                await asyncio.to_thread(cache.delete, pattern)
                deleted = 1

            self.stats.deletes += deleted
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            return deleted
        except Exception as e:
            self.stats.errors += 1
            self.stats.operation_count += 1
            self.stats.total_latency += time.time() - start_time
            logger.warning(f"Cache delete pattern error for '{pattern}': {e}")
            return 0

    def _determine_ttl(self, key: str) -> int:
        """
        Determine appropriate TTL based on key pattern.

        Args:
            key: Cache key

        Returns:
            TTL in seconds
        """
        for data_type, ttl in self.ttl_config.items():
            if data_type in key:
                return ttl

        # Default TTL
        return CACHE_DEFAULT_TTL

    async def _retry_operation(self, operation, *args, **kwargs):
        """
        Execute operation with retry logic.

        Args:
            operation: Function to execute
            *args: Arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Operation result
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.base_retry_delay * (2**attempt)  # Exponential backoff
                    logger.debug(
                        f"Cache operation failed (attempt {attempt + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Cache operation failed after {self.max_retries + 1} " f"attempts: {e}"
                    )

        # Return appropriate default for failed operations
        if operation == self._get_operation:
            return (
                kwargs.get("default") if "default" in kwargs else args[1] if len(args) > 1 else None
            )
        if operation in [
            self._set_operation,
            self._delete_operation,
            self._set_many_operation,
        ]:
            return False
        if operation == self._get_many_operation:
            return {}
        if operation == self._delete_pattern_operation:
            return 0
        raise last_exception

    def get_stats(self) -> dict[str, int | float]:
        """Get cache operation statistics."""
        return self.stats.get_stats()

    def reset_stats(self):
        """Reset cache statistics."""
        self.stats = CacheStats()


# Global instance for use across the application
enhanced_cache = EnhancedCache()
