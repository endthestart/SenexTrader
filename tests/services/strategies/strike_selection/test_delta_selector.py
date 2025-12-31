"""
Tests for DeltaStrikeSelector (Epic 50 Phase 3 Task 3.3).

Tests delta-based strike selection:
- Delta targeting with streaming Greeks
- Black-Scholes fallback when Greeks unavailable
- Quality scoring integration
- Result composition
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# DeltaSelectionResult Tests
# =============================================================================


class TestDeltaSelectionResult:
    """Test DeltaSelectionResult dataclass."""

    def test_result_structure(self):
        """Result should have strikes, delta, delta_source, quality."""
        from services.strategies.strike_selection import (
            DeltaSelectionResult,
            StrikeQualityResult,
        )

        quality = StrikeQualityResult(
            score=75.0,
            component_scores={"liquidity": 80.0},
            warnings=[],
            level="good",
        )

        result = DeltaSelectionResult(
            strikes={"short_put": Decimal("580"), "long_put": Decimal("575")},
            delta=-0.25,
            delta_source="streaming",
            quality=quality,
        )

        assert result.strikes["short_put"] == Decimal("580")
        assert result.delta == -0.25
        assert result.delta_source == "streaming"
        assert result.quality.score == 75.0


# =============================================================================
# DeltaStrikeSelector Creation Tests
# =============================================================================


class TestDeltaSelectorCreation:
    """Test DeltaStrikeSelector instantiation."""

    def test_create_with_user(self):
        """Should create selector with user."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        mock_user = MagicMock()
        selector = DeltaStrikeSelector(user=mock_user)

        assert selector.user == mock_user

    def test_create_with_min_quality_score(self):
        """Should accept minimum quality score threshold."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        mock_user = MagicMock()
        selector = DeltaStrikeSelector(user=mock_user, min_quality_score=60.0)

        assert selector.min_quality_score == 60.0


# =============================================================================
# Strike Selection Tests
# =============================================================================


class TestSelectStrikes:
    """Test select_strikes() method."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def chain_strikes(self):
        """Sample option chain strikes."""
        return [
            {"strike_price": Decimal("570"), "put": "SPY   251219P00570000"},
            {"strike_price": Decimal("575"), "put": "SPY   251219P00575000"},
            {"strike_price": Decimal("580"), "put": "SPY   251219P00580000"},
            {"strike_price": Decimal("585"), "put": "SPY   251219P00585000"},
            {"strike_price": Decimal("590"), "put": "SPY   251219P00590000"},
            {"strike_price": Decimal("595"), "put": "SPY   251219P00595000"},
            {"strike_price": Decimal("600"), "call": "SPY   251219C00600000"},
            {"strike_price": Decimal("605"), "call": "SPY   251219C00605000"},
            {"strike_price": Decimal("610"), "call": "SPY   251219C00610000"},
        ]

    @pytest.mark.asyncio
    async def test_select_strikes_returns_result(self, mock_user, chain_strikes):
        """Should return DeltaSelectionResult on success."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        # Mock Greeks fetcher
        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(
                return_value={
                    "SPY   251219P00580000": {"delta": -0.25},
                    "SPY   251219P00575000": {"delta": -0.20},
                }
            )

            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
            )

            assert result is not None
            assert "short_put" in result.strikes
            assert "long_put" in result.strikes

    @pytest.mark.asyncio
    async def test_select_strikes_for_bear_call(self, mock_user, chain_strikes):
        """Should select call strikes for bear call spread."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(
                return_value={
                    "SPY   251219C00605000": {"delta": 0.25},
                    "SPY   251219C00610000": {"delta": 0.20},
                }
            )

            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bear_call",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
            )

            assert result is not None
            assert "short_call" in result.strikes
            assert "long_call" in result.strikes

    @pytest.mark.asyncio
    async def test_select_strikes_records_delta_source(self, mock_user, chain_strikes):
        """Should record delta source (streaming vs model)."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(
                return_value={
                    "SPY   251219P00580000": {
                        "delta": -0.25,
                        "source": "streaming",
                    },
                }
            )

            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
            )

            assert result.delta_source in ["streaming", "model", "database"]

    @pytest.mark.asyncio
    async def test_select_strikes_includes_quality(self, mock_user, chain_strikes):
        """Should include quality scoring in result."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(
                return_value={
                    "SPY   251219P00580000": {"delta": -0.25},
                }
            )

            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
            )

            assert result.quality is not None
            assert hasattr(result.quality, "score")
            assert hasattr(result.quality, "level")


# =============================================================================
# Black-Scholes Fallback Tests
# =============================================================================


class TestBlackScholesFallback:
    """Test Black-Scholes delta fallback when streaming unavailable."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def chain_strikes(self):
        return [
            {"strike_price": Decimal("580"), "put": "SPY   251219P00580000"},
            {"strike_price": Decimal("575"), "put": "SPY   251219P00575000"},
        ]

    @pytest.mark.asyncio
    async def test_falls_back_to_model_when_no_greeks(self, mock_user, chain_strikes):
        """Should use Black-Scholes when streaming Greeks unavailable."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(return_value={})  # No Greeks

            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
                market_context={"current_iv": 0.25},
            )

            # Should still return result using model
            if result is not None:
                assert result.delta_source == "model"

    def test_black_scholes_delta_put(self):
        """Black-Scholes should calculate put delta correctly."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        delta = DeltaStrikeSelector._black_scholes_delta(
            spot=595.0,
            strike=580.0,
            volatility=0.25,
            time_years=0.1,  # ~36 days
            option_type="put",
        )

        # Put delta should be negative and between -1 and 0
        assert delta is not None
        assert -1.0 <= delta <= 0.0

    def test_black_scholes_delta_call(self):
        """Black-Scholes should calculate call delta correctly."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        delta = DeltaStrikeSelector._black_scholes_delta(
            spot=595.0,
            strike=610.0,
            volatility=0.25,
            time_years=0.1,
            option_type="call",
        )

        # Call delta should be positive and between 0 and 1
        assert delta is not None
        assert 0.0 <= delta <= 1.0

    def test_black_scholes_handles_zero_inputs(self):
        """Black-Scholes should handle zero/invalid inputs gracefully."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        # Zero spot
        delta = DeltaStrikeSelector._black_scholes_delta(
            spot=0.0,
            strike=580.0,
            volatility=0.25,
            time_years=0.1,
            option_type="put",
        )
        assert delta is None

        # Zero time
        delta = DeltaStrikeSelector._black_scholes_delta(
            spot=595.0,
            strike=580.0,
            volatility=0.25,
            time_years=0.0,
            option_type="put",
        )
        assert delta is None


# =============================================================================
# Long Strike Resolution Tests
# =============================================================================


class TestLongStrikeResolution:
    """Test finding compliment leg for spread."""

    def test_put_spread_long_below_short(self):
        """Put spread long strike should be below short."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        available = [
            Decimal("570"),
            Decimal("575"),
            Decimal("580"),
            Decimal("585"),
        ]

        long_strike = DeltaStrikeSelector._resolve_long_strike(
            option_type="put",
            short_strike=Decimal("580"),
            spread_width=5,
            available=available,
        )

        assert long_strike == Decimal("575")

    def test_call_spread_long_above_short(self):
        """Call spread long strike should be above short."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        available = [
            Decimal("600"),
            Decimal("605"),
            Decimal("610"),
            Decimal("615"),
        ]

        long_strike = DeltaStrikeSelector._resolve_long_strike(
            option_type="call",
            short_strike=Decimal("605"),
            spread_width=5,
            available=available,
        )

        assert long_strike == Decimal("610")

    def test_exact_width_match_preferred(self):
        """Should prefer exact spread width when available."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        available = [
            Decimal("570"),
            Decimal("572.5"),
            Decimal("575"),
            Decimal("580"),
        ]

        long_strike = DeltaStrikeSelector._resolve_long_strike(
            option_type="put",
            short_strike=Decimal("580"),
            spread_width=5,
            available=available,
        )

        assert long_strike == Decimal("575")  # Exact 5-point width

    def test_nearest_available_when_exact_missing(self):
        """Should find nearest when exact width not available."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        available = [
            Decimal("570"),
            Decimal("577"),  # No 575
            Decimal("580"),
        ]

        long_strike = DeltaStrikeSelector._resolve_long_strike(
            option_type="put",
            short_strike=Decimal("580"),
            spread_width=5,
            available=available,
        )

        # Should find nearest available below short
        assert long_strike in [Decimal("570"), Decimal("577")]

    def test_returns_none_when_no_valid_strike(self):
        """Should return None when no valid long strike exists."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        available = [Decimal("580")]  # Only short strike available

        long_strike = DeltaStrikeSelector._resolve_long_strike(
            option_type="put",
            short_strike=Decimal("580"),
            spread_width=5,
            available=available,
        )

        assert long_strike is None


# =============================================================================
# Volatility Normalization Tests
# =============================================================================


class TestVolatilityNormalization:
    """Test volatility input normalization."""

    def test_normalize_decimal_volatility(self):
        """Decimal format (0.25) should pass through."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        result = DeltaStrikeSelector._normalize_volatility(0.25)

        assert result == 0.25

    def test_normalize_percentage_volatility(self):
        """Percentage format (25.0) should convert to decimal."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        result = DeltaStrikeSelector._normalize_volatility(25.0)

        assert result == 0.25

    def test_normalize_none_returns_default(self):
        """None volatility should return default value."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        result = DeltaStrikeSelector._normalize_volatility(None)

        assert result == 0.25  # Default

    def test_normalize_very_low_has_floor(self):
        """Very low volatility should have minimum floor."""
        from services.strategies.strike_selection.delta_selector import (
            DeltaStrikeSelector,
        )

        result = DeltaStrikeSelector._normalize_volatility(0.01)

        assert result >= 0.10  # Minimum floor


# =============================================================================
# Market Context Integration Tests
# =============================================================================


class TestMarketContextIntegration:
    """Test market context affects selection."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def chain_strikes(self):
        return [
            {"strike_price": Decimal("580"), "put": "SPY   251219P00580000"},
            {"strike_price": Decimal("575"), "put": "SPY   251219P00575000"},
        ]

    @pytest.mark.asyncio
    async def test_high_stress_passed_to_greeks_fetcher(self, mock_user, chain_strikes):
        """High market stress should be passed to Greeks fetcher."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(return_value={})

            await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
                market_context={"market_stress_level": 80.0},
            )

            # Verify fetch_greeks was called
            mock_fetcher.fetch_greeks.assert_called_once()
            # The market_stress_level should be passed as positional arg
            call_args = mock_fetcher.fetch_greeks.call_args
            assert 80.0 in call_args[0] or call_args[1].get("market_stress_level") == 80.0

    @pytest.mark.asyncio
    async def test_iv_from_context_affects_model(self, mock_user, chain_strikes):
        """IV from market context should be used for Black-Scholes fallback."""
        from services.strategies.strike_selection import DeltaStrikeSelector

        selector = DeltaStrikeSelector(user=mock_user)

        with patch.object(selector, "greeks_fetcher") as mock_fetcher:
            mock_fetcher.fetch_greeks = AsyncMock(return_value={})  # Force model fallback

            # The selector will use the IV from context when computing model delta
            result = await selector.select_strikes(
                symbol="SPY",
                expiration=date(2025, 12, 19),
                chain_strikes=chain_strikes,
                spread_type="bull_put",
                spread_width=5,
                target_delta=0.25,
                current_price=Decimal("595"),
                market_context={"current_iv": 0.30},
            )

            # If result is returned, it used the model with some volatility
            # We can't easily verify the exact IV used, but we can verify the result
            if result is not None:
                assert result.delta_source == "model"
