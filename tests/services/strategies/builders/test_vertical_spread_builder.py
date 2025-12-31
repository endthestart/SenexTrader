"""
Integration tests for VerticalSpreadBuilder.

Tests all four vertical spread types:
- Bull Put Spread (BULLISH + PUT → credit)
- Bear Call Spread (BEARISH + CALL → credit)
- Bull Call Spread (BULLISH + CALL → debit)
- Bear Put Spread (BEARISH + PUT → debit)

These tests verify:
1. Correct spread structure (leg count, option types)
2. Credit/debit classification matches params
3. Leg sides (SHORT/LONG) based on spread type
4. BuildResult success/failure handling
5. build_from_strikes() explicit strike path
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.strategies.builders.vertical_spread_builder import (
    BuildResult,
    VerticalSpreadBuilder,
)
from services.strategies.core import (
    StrategyComposition,
    VerticalSpreadParams,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_user():
    """Create a mock Django user."""
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    return user


@pytest.fixture
def builder(mock_user) -> VerticalSpreadBuilder:
    """Create a VerticalSpreadBuilder instance."""
    return VerticalSpreadBuilder(mock_user)


@pytest.fixture
def bull_put_params() -> VerticalSpreadParams:
    """Bull Put Spread parameters (credit)."""
    return VerticalSpreadParams.bull_put_defaults(width_min=5, width_max=5)


@pytest.fixture
def bear_call_params() -> VerticalSpreadParams:
    """Bear Call Spread parameters (credit)."""
    return VerticalSpreadParams.bear_call_defaults(width_min=5, width_max=5)


@pytest.fixture
def bull_call_params() -> VerticalSpreadParams:
    """Bull Call Spread parameters (debit)."""
    return VerticalSpreadParams.bull_call_defaults(width_min=5, width_max=5)


@pytest.fixture
def bear_put_params() -> VerticalSpreadParams:
    """Bear Put Spread parameters (debit)."""
    return VerticalSpreadParams.bear_put_defaults(width_min=5, width_max=5)


# =============================================================================
# BuildResult Tests
# =============================================================================


class TestBuildResult:
    """Test BuildResult dataclass."""

    def test_success_result_creation(self):
        """Test creating a successful build result."""
        from services.strategies.quality import QualityScore

        composition = MagicMock(spec=StrategyComposition)
        expiration = date(2025, 1, 17)
        strikes = {"short_put": Decimal("580"), "long_put": Decimal("575")}
        quality = QualityScore(
            score=85.0,
            level="excellent",
            warnings=[],
            component_scores={"liquidity": 90.0},
        )

        result = BuildResult.success_result(
            composition=composition,
            expiration=expiration,
            strikes=strikes,
            quality=quality,
        )

        assert result.success is True
        assert result.composition == composition
        assert result.expiration == expiration
        assert result.strikes == strikes
        assert result.quality.score == 85.0
        assert result.error_message is None

    def test_failure_result_creation(self):
        """Test creating a failed build result."""
        result = BuildResult.failure_result("No suitable strikes found")

        assert result.success is False
        assert result.composition is None
        assert result.expiration is None
        assert result.strikes is None
        assert result.error_message == "No suitable strikes found"
        assert result.quality is None


# =============================================================================
# Spread Type Structure Tests
# =============================================================================


class TestBullPutSpreadStructure:
    """Test Bull Put Spread composition structure."""

    @pytest.mark.asyncio
    async def test_build_from_strikes_creates_two_legs(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Bull put spread should have exactly 2 legs."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        assert result.success is True
        assert result.composition is not None
        assert result.composition.leg_count == 2

    @pytest.mark.asyncio
    async def test_bull_put_has_all_put_legs(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Bull put spread should have all PUT legs."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        composition = result.composition
        assert len(composition.put_legs()) == 2
        assert len(composition.call_legs()) == 0

    @pytest.mark.asyncio
    async def test_bull_put_has_correct_leg_sides(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Bull put: SHORT higher strike, LONG lower strike."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        composition = result.composition
        short_legs = composition.short_legs()
        long_legs = composition.long_legs()

        assert len(short_legs) == 1
        assert len(long_legs) == 1
        assert short_legs[0].contract.strike == Decimal("580")
        assert long_legs[0].contract.strike == Decimal("575")


class TestBearCallSpreadStructure:
    """Test Bear Call Spread composition structure."""

    @pytest.mark.asyncio
    async def test_bear_call_has_all_call_legs(
        self, builder: VerticalSpreadBuilder, bear_call_params: VerticalSpreadParams
    ):
        """Bear call spread should have all CALL legs."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("600"),
            long_strike=Decimal("605"),
            params=bear_call_params,
        )

        composition = result.composition
        assert len(composition.call_legs()) == 2
        assert len(composition.put_legs()) == 0

    @pytest.mark.asyncio
    async def test_bear_call_has_correct_leg_sides(
        self, builder: VerticalSpreadBuilder, bear_call_params: VerticalSpreadParams
    ):
        """Bear call: SHORT lower strike, LONG higher strike."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("600"),
            long_strike=Decimal("605"),
            params=bear_call_params,
        )

        composition = result.composition
        short_legs = composition.short_legs()
        long_legs = composition.long_legs()

        assert len(short_legs) == 1
        assert len(long_legs) == 1
        assert short_legs[0].contract.strike == Decimal("600")
        assert long_legs[0].contract.strike == Decimal("605")


class TestBullCallSpreadStructure:
    """Test Bull Call Spread (debit) composition structure."""

    @pytest.mark.asyncio
    async def test_bull_call_has_all_call_legs(
        self, builder: VerticalSpreadBuilder, bull_call_params: VerticalSpreadParams
    ):
        """Bull call spread should have all CALL legs."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("605"),
            long_strike=Decimal("600"),
            params=bull_call_params,
        )

        composition = result.composition
        assert len(composition.call_legs()) == 2
        assert len(composition.put_legs()) == 0

    @pytest.mark.asyncio
    async def test_bull_call_has_correct_leg_sides(
        self, builder: VerticalSpreadBuilder, bull_call_params: VerticalSpreadParams
    ):
        """Bull call (debit): LONG lower strike, SHORT higher strike.

        Note: The builder uses short_strike/long_strike as dict keys referring
        to their position in strikes dict, but assigns sides based on spread type.
        For bull call (debit), the "short_strike" becomes LONG and "long_strike" becomes SHORT.
        """
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("605"),  # Will become LONG in debit spread
            long_strike=Decimal("600"),   # Will become SHORT in debit spread
            params=bull_call_params,
        )

        composition = result.composition
        short_legs = composition.short_legs()
        long_legs = composition.long_legs()

        assert len(short_legs) == 1
        assert len(long_legs) == 1
        # Builder assigns: short_strike -> LONG, long_strike -> SHORT for debit spreads
        assert long_legs[0].contract.strike == Decimal("605")
        assert short_legs[0].contract.strike == Decimal("600")


class TestBearPutSpreadStructure:
    """Test Bear Put Spread (debit) composition structure."""

    @pytest.mark.asyncio
    async def test_bear_put_has_all_put_legs(
        self, builder: VerticalSpreadBuilder, bear_put_params: VerticalSpreadParams
    ):
        """Bear put spread should have all PUT legs."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("575"),
            long_strike=Decimal("580"),
            params=bear_put_params,
        )

        composition = result.composition
        assert len(composition.put_legs()) == 2
        assert len(composition.call_legs()) == 0

    @pytest.mark.asyncio
    async def test_bear_put_has_correct_leg_sides(
        self, builder: VerticalSpreadBuilder, bear_put_params: VerticalSpreadParams
    ):
        """Bear put (debit): LONG higher strike, SHORT lower strike.

        Note: For bear put (debit), the builder assigns:
        - short_strike -> LONG side (buying the higher-priced option)
        - long_strike -> SHORT side (selling the lower-priced option)
        """
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("575"),  # Will become LONG in debit spread
            long_strike=Decimal("580"),   # Will become SHORT in debit spread
            params=bear_put_params,
        )

        composition = result.composition
        short_legs = composition.short_legs()
        long_legs = composition.long_legs()

        assert len(short_legs) == 1
        assert len(long_legs) == 1
        # Builder assigns: short_strike -> LONG, long_strike -> SHORT for debit spreads
        assert long_legs[0].contract.strike == Decimal("575")
        assert short_legs[0].contract.strike == Decimal("580")


# =============================================================================
# Credit/Debit Classification Tests
# =============================================================================


class TestCreditDebitClassification:
    """Test that params correctly identify credit vs debit spreads."""

    def test_bull_put_is_credit_spread(self, bull_put_params: VerticalSpreadParams):
        """Bull Put Spread (BULLISH + PUT) is a credit spread."""
        assert bull_put_params.is_credit_spread is True
        assert bull_put_params.is_debit_spread is False

    def test_bear_call_is_credit_spread(self, bear_call_params: VerticalSpreadParams):
        """Bear Call Spread (BEARISH + CALL) is a credit spread."""
        assert bear_call_params.is_credit_spread is True
        assert bear_call_params.is_debit_spread is False

    def test_bull_call_is_debit_spread(self, bull_call_params: VerticalSpreadParams):
        """Bull Call Spread (BULLISH + CALL) is a debit spread."""
        assert bull_call_params.is_credit_spread is False
        assert bull_call_params.is_debit_spread is True

    def test_bear_put_is_debit_spread(self, bear_put_params: VerticalSpreadParams):
        """Bear Put Spread (BEARISH + PUT) is a debit spread."""
        assert bear_put_params.is_credit_spread is False
        assert bear_put_params.is_debit_spread is True


class TestSpreadTypeNames:
    """Test human-readable spread type names."""

    def test_bull_put_spread_name(self, bull_put_params: VerticalSpreadParams):
        assert bull_put_params.spread_type_name == "Bull Put Spread"

    def test_bear_call_spread_name(self, bear_call_params: VerticalSpreadParams):
        assert bear_call_params.spread_type_name == "Bear Call Spread"

    def test_bull_call_spread_name(self, bull_call_params: VerticalSpreadParams):
        assert bull_call_params.spread_type_name == "Bull Call Spread"

    def test_bear_put_spread_name(self, bear_put_params: VerticalSpreadParams):
        assert bear_put_params.spread_type_name == "Bear Put Spread"


# =============================================================================
# Spread Width Tests
# =============================================================================


class TestSpreadWidth:
    """Test spread width calculations."""

    @pytest.mark.asyncio
    async def test_spread_width_matches_strikes(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Spread width should equal difference between strikes."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        composition = result.composition
        widths = composition.spread_widths()

        assert len(widths) == 1
        assert widths[0] == Decimal("5")

    @pytest.mark.asyncio
    async def test_max_spread_width(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """max_spread_width() should return the spread width."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("585"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        composition = result.composition
        assert composition.max_spread_width() == Decimal("10")


# =============================================================================
# Build Method Tests
# =============================================================================


class TestBuildFromStrikes:
    """Test build_from_strikes() method."""

    @pytest.mark.asyncio
    async def test_build_from_strikes_sets_correct_expiration(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Expiration should match the provided date."""
        target_expiration = date(2025, 2, 21)
        result = await builder.build_from_strikes(
            symbol="QQQ",
            expiration=target_expiration,
            short_strike=Decimal("500"),
            long_strike=Decimal("495"),
            params=bull_put_params,
        )

        assert result.expiration == target_expiration
        assert result.composition.expiration == target_expiration

    @pytest.mark.asyncio
    async def test_build_from_strikes_sets_correct_symbol(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Underlying symbol should be set correctly."""
        result = await builder.build_from_strikes(
            symbol="IWM",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("220"),
            long_strike=Decimal("215"),
            params=bull_put_params,
        )

        assert result.composition.underlying == "IWM"

    @pytest.mark.asyncio
    async def test_build_from_strikes_returns_strikes_dict(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Result should include strikes dictionary."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        assert result.strikes is not None
        assert "short_put" in result.strikes
        assert "long_put" in result.strikes
        assert result.strikes["short_put"] == Decimal("580")
        assert result.strikes["long_put"] == Decimal("575")

    @pytest.mark.asyncio
    async def test_build_from_strikes_call_spread_strike_keys(
        self, builder: VerticalSpreadBuilder, bear_call_params: VerticalSpreadParams
    ):
        """Call spreads should use call strike keys."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("600"),
            long_strike=Decimal("605"),
            params=bear_call_params,
        )

        assert "short_call" in result.strikes
        assert "long_call" in result.strikes


# =============================================================================
# OCC Symbol Tests
# =============================================================================


class TestOCCSymbols:
    """Test OCC symbol generation for legs."""

    @pytest.mark.asyncio
    async def test_occ_symbols_generated_correctly(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Verify OCC symbols are correctly formatted."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        occ_symbols = result.composition.occ_symbols()
        assert len(occ_symbols) == 2

        # Check format: SPY   YYMMDDP00SSSSS0
        for symbol in occ_symbols:
            assert symbol.startswith("SPY")
            assert "250117P" in symbol  # Jan 17, 2025 Put

    @pytest.mark.asyncio
    async def test_call_spread_occ_symbols(
        self, builder: VerticalSpreadBuilder, bear_call_params: VerticalSpreadParams
    ):
        """Call spread OCC symbols should have 'C' for call."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("600"),
            long_strike=Decimal("605"),
            params=bear_call_params,
        )

        occ_symbols = result.composition.occ_symbols()
        for symbol in occ_symbols:
            assert "250117C" in symbol  # Jan 17, 2025 Call


# =============================================================================
# Quantity Tests
# =============================================================================


class TestQuantityHandling:
    """Test quantity propagation through builder."""

    @pytest.mark.asyncio
    async def test_quantity_propagates_to_legs(
        self, builder: VerticalSpreadBuilder
    ):
        """Quantity from params should propagate to all legs."""
        params = VerticalSpreadParams.bull_put_defaults(
            width_min=5, width_max=5, quantity=3
        )

        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=params,
        )

        for leg in result.composition.legs:
            assert leg.quantity == 3

    @pytest.mark.asyncio
    async def test_total_quantity(self, builder: VerticalSpreadBuilder):
        """Total quantity should be 2x single leg quantity for vertical spread."""
        params = VerticalSpreadParams.bull_put_defaults(
            width_min=5, width_max=5, quantity=2
        )

        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=params,
        )

        # 2 legs x 2 contracts each = 4 total
        assert result.composition.total_quantity() == 4


# =============================================================================
# Order Conversion Tests
# =============================================================================


class TestOrderConversion:
    """Test conversion to order legs."""

    @pytest.mark.asyncio
    async def test_to_order_legs_opening(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Opening order legs should have correct actions."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        order_legs = result.composition.to_order_legs(opening=True)
        actions = {leg.action for leg in order_legs}

        assert "sell_to_open" in actions  # Short leg
        assert "buy_to_open" in actions  # Long leg

    @pytest.mark.asyncio
    async def test_to_order_legs_closing(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Closing order legs should have correct actions."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        order_legs = result.composition.to_order_legs(opening=False)
        actions = {leg.action for leg in order_legs}

        assert "buy_to_close" in actions  # Close short
        assert "sell_to_close" in actions  # Close long


# =============================================================================
# Build Method with Market Data Tests
# =============================================================================


class TestBuildWithMarketData:
    """Test build() method that uses market data."""

    @pytest.mark.asyncio
    async def test_build_returns_failure_when_no_price(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Build should fail gracefully when price unavailable."""
        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = None

            result = await builder.build("SPY", bull_put_params)

            assert result.success is False
            assert "current price" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_build_returns_failure_when_no_strikes_found(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Build should fail gracefully when no suitable strikes found."""
        with patch.object(
            builder, "_get_current_price", new_callable=AsyncMock
        ) as mock_price:
            mock_price.return_value = Decimal("590.00")

            with patch(
                "services.market_data.utils.expiration_utils."
                "find_expiration_with_optimal_strikes",
                new_callable=AsyncMock,
            ) as mock_find:
                mock_find.return_value = None

                result = await builder.build("SPY", bull_put_params)

                assert result.success is False
                assert "no expiration found" in result.error_message.lower()


# =============================================================================
# Closing Composition Tests
# =============================================================================


class TestClosingComposition:
    """Test closing composition generation."""

    @pytest.mark.asyncio
    async def test_closing_composition_reverses_sides(
        self, builder: VerticalSpreadBuilder, bull_put_params: VerticalSpreadParams
    ):
        """Closing composition should reverse all leg sides."""
        result = await builder.build_from_strikes(
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            params=bull_put_params,
        )

        opening = result.composition
        closing = opening.closing_composition()

        # Original: 1 short, 1 long
        assert len(opening.short_legs()) == 1
        assert len(opening.long_legs()) == 1

        # Closing: sides reversed
        assert len(closing.short_legs()) == 1
        assert len(closing.long_legs()) == 1

        # Strikes should match
        opening_strikes = {leg.contract.strike for leg in opening.legs}
        closing_strikes = {leg.contract.strike for leg in closing.legs}
        assert opening_strikes == closing_strikes
