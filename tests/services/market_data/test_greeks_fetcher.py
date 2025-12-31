"""
Tests for GreeksFetcher (Epic 50 Phase 3 Task 3.2).

Tests the Greeks fetching infrastructure for strike selection:
- Cache integration with TTL
- Streaming + historical fallback
- Market stress bypass
- Batch fetching for multiple OCC symbols
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# GreeksFetcher Core Tests
# =============================================================================


class TestGreeksFetcherCreation:
    """Test GreeksFetcher instantiation and configuration."""

    def test_create_with_defaults(self):
        """GreeksFetcher should be creatable with default settings."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        mock_user = MagicMock()
        fetcher = GreeksFetcher(user=mock_user)

        assert fetcher.user == mock_user
        assert fetcher.ttl_seconds == 90  # Default cache TTL
        assert fetcher.stress_threshold == 70.0  # Default stress bypass

    def test_create_with_custom_ttl(self):
        """GreeksFetcher should accept custom cache TTL."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        mock_user = MagicMock()
        fetcher = GreeksFetcher(user=mock_user, ttl_seconds=120)

        assert fetcher.ttl_seconds == 120

    def test_create_with_custom_stress_threshold(self):
        """GreeksFetcher should accept custom stress bypass threshold."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        mock_user = MagicMock()
        fetcher = GreeksFetcher(user=mock_user, stress_bypass_threshold=80.0)

        assert fetcher.stress_threshold == 80.0


# =============================================================================
# Fetch Greeks Tests
# =============================================================================


class TestFetchGreeks:
    """Test fetch_greeks() method."""

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def fetcher(self, mock_user):
        """Create GreeksFetcher with mocked dependencies."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        return GreeksFetcher(user=mock_user)

    @pytest.mark.asyncio
    async def test_fetch_returns_dict_mapping(self, fetcher):
        """fetch_greeks should return dict mapping OCC symbol to Greeks."""
        occ_symbols = [
            "SPY   251219P00580000",
            "SPY   251219P00575000",
        ]

        with patch("django.core.cache.cache.get", return_value=None):
            with patch("django.core.cache.cache.set"):
                with patch.object(
                    fetcher, "_read_streaming_greeks"
                ) as mock_streaming:
                    mock_streaming.return_value = {
                        "delta": -0.25,
                        "gamma": 0.02,
                        "theta": -0.15,
                        "vega": 0.30,
                        "rho": -0.05,
                    }

                    with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                        result = await fetcher.fetch_greeks(
                            symbol="SPY",
                            expiration=date(2025, 12, 19),
                            occ_symbols=occ_symbols,
                        )

                        assert isinstance(result, dict)
                        # Should have entries for symbols with data
                        assert len(result) <= len(occ_symbols)

    @pytest.mark.asyncio
    async def test_fetch_empty_symbols_returns_empty(self, fetcher):
        """Empty OCC symbols list should return empty dict."""
        result = await fetcher.fetch_greeks(
            symbol="SPY",
            expiration=date(2025, 12, 19),
            occ_symbols=[],
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_deduplicates_symbols(self, fetcher):
        """Duplicate OCC symbols should be deduplicated."""
        occ_symbols = [
            "SPY   251219P00580000",
            "SPY   251219P00580000",  # Duplicate
            "SPY   251219P00575000",
        ]

        with patch("django.core.cache.cache.get", return_value=None):
            with patch("django.core.cache.cache.set"):
                with patch.object(
                    fetcher, "_read_streaming_greeks"
                ) as mock_streaming:
                    mock_streaming.return_value = {"delta": -0.25}

                    with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                        await fetcher.fetch_greeks(
                            symbol="SPY",
                            expiration=date(2025, 12, 19),
                            occ_symbols=occ_symbols,
                        )

                        # Should only call for unique symbols (2, not 3)
                        assert mock_streaming.call_count == 2


# =============================================================================
# Cache Behavior Tests
# =============================================================================


class TestGreeksFetcherCache:
    """Test caching behavior."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def fetcher(self, mock_user):
        from services.market_data.greeks_fetcher import GreeksFetcher

        return GreeksFetcher(user=mock_user, ttl_seconds=90)

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_data(self, fetcher):
        """Should return cached data when available."""
        occ_symbol = "SPY   251219P00580000"
        cached_greeks = {"delta": -0.25, "gamma": 0.02}

        with patch("django.core.cache.cache.get") as mock_cache_get:
            mock_cache_get.return_value = cached_greeks

            with patch.object(
                fetcher, "_read_streaming_greeks"
            ) as mock_streaming:
                result = await fetcher.fetch_greeks(
                    symbol="SPY",
                    expiration=date(2025, 12, 19),
                    occ_symbols=[occ_symbol],
                )

                # Should not call streaming when cache hit
                mock_streaming.assert_not_called()
                assert result[occ_symbol] == cached_greeks

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_fresh(self, fetcher):
        """Should fetch fresh data on cache miss."""
        occ_symbol = "SPY   251219P00580000"
        fresh_greeks = {"delta": -0.30, "gamma": 0.03}

        with patch("django.core.cache.cache.get") as mock_cache_get:
            mock_cache_get.return_value = None  # Cache miss

            with patch.object(
                fetcher, "_read_streaming_greeks"
            ) as mock_streaming:
                mock_streaming.return_value = fresh_greeks

                with patch("django.core.cache.cache.set") as mock_cache_set:
                    result = await fetcher.fetch_greeks(
                        symbol="SPY",
                        expiration=date(2025, 12, 19),
                        occ_symbols=[occ_symbol],
                    )

                    # Should call streaming
                    mock_streaming.assert_called_once()
                    # Should cache the result
                    mock_cache_set.assert_called()

    @pytest.mark.asyncio
    async def test_cache_uses_correct_ttl(self, fetcher):
        """Cache should use configured TTL."""
        occ_symbol = "SPY   251219P00580000"

        with patch("django.core.cache.cache.get", return_value=None), patch.object(
            fetcher, "_read_streaming_greeks", return_value={"delta": -0.25}
        ), patch("django.core.cache.cache.set") as mock_cache_set:
            await fetcher.fetch_greeks(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                occ_symbols=[occ_symbol],
            )

            # Verify TTL is passed (90 seconds)
            call_args = mock_cache_set.call_args
            assert call_args[0][2] == 90  # Third arg is TTL


# =============================================================================
# Market Stress Bypass Tests
# =============================================================================


class TestMarketStressBypass:
    """Test market stress cache bypass behavior."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def fetcher(self, mock_user):
        from services.market_data.greeks_fetcher import GreeksFetcher

        return GreeksFetcher(user=mock_user, stress_bypass_threshold=70.0)

    @pytest.mark.asyncio
    async def test_stress_above_threshold_bypasses_cache(self, fetcher):
        """High market stress should bypass cache."""
        occ_symbol = "SPY   251219P00580000"
        cached_greeks = {"delta": -0.25, "source": "cached"}
        fresh_greeks = {"delta": -0.30, "source": "fresh"}

        with patch("django.core.cache.cache.get") as mock_cache_get:
            mock_cache_get.return_value = cached_greeks

            with patch("django.core.cache.cache.set"), patch.object(
                fetcher, "_read_streaming_greeks"
            ) as mock_streaming:
                mock_streaming.return_value = fresh_greeks

                with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                    result = await fetcher.fetch_greeks(
                        symbol="SPY",
                        expiration=date(2025, 12, 19),
                        occ_symbols=[occ_symbol],
                        market_stress_level=75.0,  # Above 70 threshold
                    )

                    # Should bypass cache and fetch fresh
                    mock_streaming.assert_called_once()
                    assert result[occ_symbol]["source"] == "fresh"

    @pytest.mark.asyncio
    async def test_stress_below_threshold_uses_cache(self, fetcher):
        """Low market stress should use cache."""
        occ_symbol = "SPY   251219P00580000"
        cached_greeks = {"delta": -0.25, "source": "cached"}

        with patch("django.core.cache.cache.get") as mock_cache_get:
            mock_cache_get.return_value = cached_greeks

            with patch.object(
                fetcher, "_read_streaming_greeks"
            ) as mock_streaming:
                with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                    result = await fetcher.fetch_greeks(
                        symbol="SPY",
                        expiration=date(2025, 12, 19),
                        occ_symbols=[occ_symbol],
                        market_stress_level=50.0,  # Below 70 threshold
                    )

                    # Should use cache, not fetch fresh
                    mock_streaming.assert_not_called()
                    assert result[occ_symbol]["source"] == "cached"

    @pytest.mark.asyncio
    async def test_no_stress_level_uses_cache(self, fetcher):
        """No stress level provided should use cache normally."""
        occ_symbol = "SPY   251219P00580000"
        cached_greeks = {"delta": -0.25}

        with patch("django.core.cache.cache.get") as mock_cache_get:
            mock_cache_get.return_value = cached_greeks

            with patch.object(
                fetcher, "_read_streaming_greeks"
            ) as mock_streaming:
                with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                    result = await fetcher.fetch_greeks(
                        symbol="SPY",
                        expiration=date(2025, 12, 19),
                        occ_symbols=[occ_symbol],
                        market_stress_level=None,  # No stress info
                    )

                    mock_streaming.assert_not_called()


# =============================================================================
# Fallback Behavior Tests
# =============================================================================


class TestGreeksFallback:
    """Test streaming → historical fallback."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def fetcher(self, mock_user):
        from services.market_data.greeks_fetcher import GreeksFetcher

        return GreeksFetcher(user=mock_user)

    @pytest.mark.asyncio
    async def test_fallback_to_historical_on_streaming_miss(self, fetcher):
        """Should fall back to historical when streaming unavailable."""
        occ_symbol = "SPY   251219P00580000"
        historical_greeks = {
            "delta": -0.28,
            "source": "database_fallback",
            "age_seconds": 300,
        }

        with patch("django.core.cache.cache.get", return_value=None):
            with patch("django.core.cache.cache.set"):
                with patch.object(
                    fetcher, "_read_streaming_greeks", return_value=None
                ):
                    with patch.object(
                        fetcher, "_read_historical_greeks"
                    ) as mock_historical:
                        mock_historical.return_value = historical_greeks

                        with patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
                            result = await fetcher.fetch_greeks(
                                symbol="SPY",
                                expiration=date(2025, 12, 19),
                                occ_symbols=[occ_symbol],
                            )

                            mock_historical.assert_called_once()
                            assert result[occ_symbol]["source"] == "database_fallback"

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_for_symbol(self, fetcher):
        """No streaming or historical data should skip symbol in result."""
        occ_symbol = "SPY   251219P00580000"

        with patch("django.core.cache.cache.get", return_value=None), patch.object(
            fetcher, "_read_streaming_greeks", return_value=None
        ), patch.object(
            fetcher, "_read_historical_greeks", return_value=None
        ), patch.object(fetcher, "_ensure_subscription", new_callable=AsyncMock):
            result = await fetcher.fetch_greeks(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                occ_symbols=[occ_symbol],
            )

            # Symbol not in result when no data available
            assert occ_symbol not in result


# =============================================================================
# Data Format Tests
# =============================================================================


class TestGreeksDataFormat:
    """Test Greeks data format and serialization."""

    def test_serialize_snapshot_formats_correctly(self):
        """Snapshot serialization should produce correct dict format."""
        from decimal import Decimal

        from services.market_data.greeks_fetcher import GreeksFetcher
        from services.streaming.dataclasses import OptionGreeks

        snapshot = OptionGreeks(
            occ_symbol="SPY   251219P00580000",
            delta=Decimal("-0.25"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.15"),
            vega=Decimal("0.30"),
            rho=Decimal("-0.05"),
            implied_volatility=Decimal("0.25"),
            as_of=datetime.now(UTC),
            source="streaming",
        )

        result = GreeksFetcher._serialize_snapshot(snapshot)

        assert result["delta"] == -0.25
        assert result["gamma"] == 0.02
        assert result["theta"] == -0.15
        assert result["vega"] == 0.30
        assert result["rho"] == -0.05
        assert result["implied_volatility"] == 0.25
        assert result["source"] == "streaming"

    def test_serialize_handles_none_values(self):
        """Serialization should handle None values gracefully."""
        from decimal import Decimal

        from services.market_data.greeks_fetcher import GreeksFetcher
        from services.streaming.dataclasses import OptionGreeks

        snapshot = OptionGreeks(
            occ_symbol="SPY   251219P00580000",
            delta=Decimal("-0.25"),
            gamma=None,  # Missing
            theta=None,  # Missing
            vega=Decimal("0.30"),
            rho=None,  # Missing
            implied_volatility=None,
            as_of=datetime.now(UTC),
            source="streaming",
        )

        result = GreeksFetcher._serialize_snapshot(snapshot)

        assert result["delta"] == -0.25
        assert result["gamma"] is None
        assert result["theta"] is None
        assert result["vega"] == 0.30


# =============================================================================
# Expiration Normalization Tests
# =============================================================================


class TestExpirationNormalization:
    """Test expiration date normalization."""

    def test_normalize_date_object(self):
        """date object should pass through unchanged."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        input_date = date(2025, 12, 19)
        result = GreeksFetcher._normalize_expiration(input_date)

        assert result == input_date

    def test_normalize_datetime_object(self):
        """datetime should be converted to date."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        input_datetime = datetime(2025, 12, 19, 10, 30, 0)
        result = GreeksFetcher._normalize_expiration(input_datetime)

        assert result == date(2025, 12, 19)

    def test_normalize_none_returns_none(self):
        """None expiration should return None."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        result = GreeksFetcher._normalize_expiration(None)

        assert result is None

    def test_normalize_iso_string(self):
        """ISO format string should be converted to date."""
        from services.market_data.greeks_fetcher import GreeksFetcher

        result = GreeksFetcher._normalize_expiration("2025-12-19")

        assert result == date(2025, 12, 19)
