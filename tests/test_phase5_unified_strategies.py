"""
Phase 5 TDD Tests - Unified Strategy Classes.

Epic 50, Phase 5: Unify Straddle, Strangle, and Iron Condor strategies
with direction parameters (LONG/SHORT) following the Phase 4 vertical spread pattern.

Tests cover:
- Task 5.0: StraddleStrategy with direction parameter (LONG/SHORT)
- Task 5.1: StrangleStrategy with direction parameter (LONG/SHORT)
- Task 5.2: IronCondorStrategy with direction parameter (LONG/SHORT)
- Task 5.3: CalendarSpreadStrategy with option_type parameter (CALL/PUT)
- Task 5.4: Factory updates for parameterized instantiation
- Task 5.5: Legacy class removal verification
"""

from decimal import Decimal
from unittest.mock import Mock

from django.contrib.auth import get_user_model

import pytest

from tests.helpers.market_helpers import create_neutral_market_report

User = get_user_model()


# =============================================================================
# Task 5.0: StraddleStrategy with Direction Parameter
# =============================================================================


class TestStraddleStrategyDirection:
    """Test unified StraddleStrategy with LONG/SHORT direction."""

    def test_straddle_strategy_exists(self, mock_user):
        """Test that unified StraddleStrategy class exists."""
        from services.strategies.straddle_strategy import StraddleStrategy

        assert StraddleStrategy is not None

    def test_straddle_strategy_has_direction_parameter(self, mock_user):
        """Test StraddleStrategy accepts direction parameter."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        long_straddle = StraddleStrategy(mock_user, direction=Side.LONG)
        short_straddle = StraddleStrategy(mock_user, direction=Side.SHORT)

        assert long_straddle.direction == Side.LONG
        assert short_straddle.direction == Side.SHORT

    def test_long_straddle_strategy_name(self, mock_user):
        """Test long straddle has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        assert strategy.strategy_name == "long_straddle"

    def test_short_straddle_strategy_name(self, mock_user):
        """Test short straddle has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        assert strategy.strategy_name == "short_straddle"

    def test_long_straddle_automation_disabled(self, mock_user):
        """Test long straddle has automation disabled (timing critical)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        assert strategy.automation_enabled_by_default() is False

    def test_short_straddle_automation_disabled(self, mock_user):
        """Test short straddle has automation disabled (UNLIMITED RISK)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        assert strategy.automation_enabled_by_default() is False


@pytest.mark.asyncio
class TestStraddleScoringInversion:
    """Test that LONG/SHORT straddles have inverted IV preferences."""

    async def test_long_straddle_wants_low_iv(self, mock_user):
        """Test long straddle scores HIGH with LOW IV (buy cheap options)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        report = create_neutral_market_report()
        report.iv_rank = 18.0  # Very low IV - excellent for buying

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 70.0
        assert any("excellent" in r.lower() or "cheap" in r.lower() for r in reasons)

    async def test_long_straddle_avoids_high_iv(self, mock_user):
        """Test long straddle scores LOW with HIGH IV (options expensive)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        report = create_neutral_market_report()
        report.iv_rank = 75.0  # Very high IV - expensive

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score <= 40.0
        assert any("expensive" in r.lower() or "avoid" in r.lower() for r in reasons)

    async def test_short_straddle_wants_high_iv(self, mock_user):
        """Test short straddle scores HIGH with HIGH IV (sell expensive options)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        report = create_neutral_market_report()
        report.iv_rank = 75.0  # Very high IV - excellent for selling
        report.adx = 15.0  # Range-bound

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 70.0
        assert any("premium" in r.lower() or "excellent" in r.lower() for r in reasons)

    async def test_short_straddle_avoids_low_iv(self, mock_user):
        """Test short straddle scores LOW with LOW IV (insufficient premium)."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        report = create_neutral_market_report()
        report.iv_rank = 18.0  # Very low IV - poor premium

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Score should be notably lower than optimal (high IV would score 70+)
        assert score <= 50.0
        assert any("insufficient" in r.lower() or "low" in r.lower() for r in reasons)


# =============================================================================
# Task 5.1: StrangleStrategy with Direction Parameter
# =============================================================================


class TestStrangleStrategyDirection:
    """Test unified StrangleStrategy with LONG/SHORT direction."""

    def test_strangle_strategy_exists(self, mock_user):
        """Test that unified StrangleStrategy class exists."""
        from services.strategies.strangle_strategy import StrangleStrategy

        assert StrangleStrategy is not None

    def test_strangle_strategy_has_direction_parameter(self, mock_user):
        """Test StrangleStrategy accepts direction parameter."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        long_strangle = StrangleStrategy(mock_user, direction=Side.LONG)
        short_strangle = StrangleStrategy(mock_user, direction=Side.SHORT)

        assert long_strangle.direction == Side.LONG
        assert short_strangle.direction == Side.SHORT

    def test_long_strangle_strategy_name(self, mock_user):
        """Test long strangle has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.LONG)
        assert strategy.strategy_name == "long_strangle"

    def test_short_strangle_strategy_name(self, mock_user):
        """Test short strangle has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.SHORT)
        assert strategy.strategy_name == "short_strangle"

    def test_long_strangle_automation_disabled(self, mock_user):
        """Test long strangle has automation disabled (timing critical)."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.LONG)
        assert strategy.automation_enabled_by_default() is False

    def test_short_strangle_automation_disabled(self, mock_user):
        """Test short strangle has automation disabled (UNLIMITED RISK)."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.SHORT)
        assert strategy.automation_enabled_by_default() is False


@pytest.mark.asyncio
class TestStrangleScoringInversion:
    """Test that LONG/SHORT strangles have inverted IV preferences."""

    async def test_long_strangle_wants_very_low_iv(self, mock_user):
        """Test long strangle scores HIGH with VERY LOW IV (stricter than straddle)."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.LONG)
        report = create_neutral_market_report()
        report.iv_rank = 15.0  # Very low IV - exceptional for buying OTM

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 75.0
        assert any("exceptional" in r.lower() or "dirt cheap" in r.lower() for r in reasons)

    async def test_short_strangle_wants_high_iv(self, mock_user):
        """Test short strangle scores HIGH with HIGH IV (sell expensive OTM)."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.SHORT)
        report = create_neutral_market_report()
        report.iv_rank = 70.0  # High IV - excellent premium
        report.adx = 15.0  # Range-bound

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 70.0
        assert any("premium" in r.lower() or "excellent" in r.lower() for r in reasons)


# =============================================================================
# Task 5.2: IronCondorStrategy with Direction Parameter
# =============================================================================


class TestIronCondorStrategyDirection:
    """Test unified IronCondorStrategy with LONG/SHORT direction."""

    def test_iron_condor_strategy_exists(self, mock_user):
        """Test that unified IronCondorStrategy class exists."""
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        assert IronCondorStrategy is not None

    def test_iron_condor_strategy_has_direction_parameter(self, mock_user):
        """Test IronCondorStrategy accepts direction parameter."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        short_ic = IronCondorStrategy(mock_user, direction=Side.SHORT)
        long_ic = IronCondorStrategy(mock_user, direction=Side.LONG)

        assert short_ic.direction == Side.SHORT
        assert long_ic.direction == Side.LONG

    def test_short_iron_condor_strategy_name(self, mock_user):
        """Test short iron condor has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        assert strategy.strategy_name == "short_iron_condor"

    def test_long_iron_condor_strategy_name(self, mock_user):
        """Test long iron condor has correct strategy name."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.LONG)
        assert strategy.strategy_name == "long_iron_condor"

    def test_iron_condor_automation_disabled(self, mock_user):
        """Test both iron condor directions have automation disabled."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        short_ic = IronCondorStrategy(mock_user, direction=Side.SHORT)
        long_ic = IronCondorStrategy(mock_user, direction=Side.LONG)

        assert short_ic.automation_enabled_by_default() is False
        assert long_ic.automation_enabled_by_default() is False


@pytest.mark.asyncio
class TestIronCondorScoringInversion:
    """Test that LONG/SHORT iron condors have inverted IV preferences."""

    async def test_short_iron_condor_wants_high_iv(self, mock_user):
        """Test short iron condor scores HIGH with HIGH IV (sell premium)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        report = create_neutral_market_report()
        report.iv_rank = 75.0  # High IV - excellent premium
        report.adx = 18.0  # Range-bound

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 100.0
        assert any("exceptional premium" in r.lower() for r in reasons)

    async def test_short_iron_condor_hard_stop_low_iv(self, mock_user):
        """Test short iron condor penalizes LOW IV (insufficient premium)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        report = create_neutral_market_report()
        report.iv_rank = 30.0  # Low IV - insufficient premium

        score, reasons = await strategy._score_market_conditions_impl(report)

        # Score should be notably lower than optimal (high IV would score 90+)
        assert score <= 60.0
        assert any("insufficient" in r.lower() for r in reasons)

    async def test_long_iron_condor_wants_low_iv(self, mock_user):
        """Test long iron condor scores HIGH with LOW IV (buy cheap)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.LONG)
        report = create_neutral_market_report()
        report.iv_rank = 18.0  # Very low IV - cheap options
        report.adx = 15.0  # Range-bound

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score >= 100.0
        assert any("exceptionally cheap" in r.lower() or "ideal" in r.lower() for r in reasons)

    async def test_long_iron_condor_hard_stop_high_iv(self, mock_user):
        """Test long iron condor HARD STOP with HIGH IV (use short instead)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.LONG)
        report = create_neutral_market_report()
        report.iv_rank = 55.0  # High IV - use SHORT instead

        score, reasons = await strategy._score_market_conditions_impl(report)

        assert score == 0.0  # HARD STOP
        assert any("SHORT Iron Condor" in r for r in reasons)


# =============================================================================
# Task 5.3: CalendarSpreadStrategy with Option Type Parameter
# =============================================================================


@pytest.mark.skip(reason="CalendarSpreadStrategy needs interface refactor - Phase 5.3 deferred")
class TestCalendarSpreadStrategyOptionType:
    """Test CalendarSpreadStrategy with CALL/PUT option_type parameter."""

    def test_calendar_strategy_exists(self, mock_user):
        """Test that CalendarSpreadStrategy class exists."""
        from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

        assert CalendarSpreadStrategy is not None

    def test_calendar_strategy_has_option_type_parameter(self, mock_user):
        """Test CalendarSpreadStrategy accepts option_type parameter."""
        from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

        call_calendar = CalendarSpreadStrategy(mock_user, option_type="CALL")
        put_calendar = CalendarSpreadStrategy(mock_user, option_type="PUT")

        assert call_calendar.option_type == "CALL"
        assert put_calendar.option_type == "PUT"

    def test_call_calendar_strategy_name(self, mock_user):
        """Test call calendar has correct strategy name."""
        from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

        strategy = CalendarSpreadStrategy(mock_user, option_type="CALL")
        assert strategy.strategy_name == "call_calendar"

    def test_put_calendar_strategy_name(self, mock_user):
        """Test put calendar has correct strategy name."""
        from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

        strategy = CalendarSpreadStrategy(mock_user, option_type="PUT")
        assert strategy.strategy_name == "put_calendar"

    def test_calendar_default_option_type(self, mock_user):
        """Test calendar defaults to CALL option type."""
        from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

        strategy = CalendarSpreadStrategy(mock_user)
        assert strategy.option_type == "CALL"


# =============================================================================
# Task 5.4: Factory Updates for Parameterized Instantiation
# =============================================================================


class TestFactoryParameterizedInstantiation:
    """Test factory creates strategies with correct parameters."""

    def test_factory_creates_long_straddle(self, mock_user):
        """Test factory creates long straddle with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_straddle", mock_user)

        assert strategy.strategy_name == "long_straddle"
        assert strategy.direction == Side.LONG

    def test_factory_creates_short_straddle(self, mock_user):
        """Test factory creates short straddle with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_straddle", mock_user)

        assert strategy.strategy_name == "short_straddle"
        assert strategy.direction == Side.SHORT

    def test_factory_creates_long_strangle(self, mock_user):
        """Test factory creates long strangle with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_strangle", mock_user)

        assert strategy.strategy_name == "long_strangle"
        assert strategy.direction == Side.LONG

    def test_factory_creates_short_strangle(self, mock_user):
        """Test factory creates short strangle with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_strangle", mock_user)

        assert strategy.strategy_name == "short_strangle"
        assert strategy.direction == Side.SHORT

    def test_factory_creates_short_iron_condor(self, mock_user):
        """Test factory creates short iron condor with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("short_iron_condor", mock_user)

        assert strategy.strategy_name == "short_iron_condor"
        assert strategy.direction == Side.SHORT

    def test_factory_creates_long_iron_condor(self, mock_user):
        """Test factory creates long iron condor with correct direction."""
        from services.strategies.core.types import Side
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_iron_condor", mock_user)

        assert strategy.strategy_name == "long_iron_condor"
        assert strategy.direction == Side.LONG

    @pytest.mark.skip(reason="CalendarSpreadStrategy needs interface refactor - Phase 5.3 deferred")
    def test_factory_creates_call_calendar(self, mock_user):
        """Test factory creates call calendar with correct option type."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("call_calendar", mock_user)

        assert strategy.strategy_name == "call_calendar"
        assert strategy.option_type == "CALL"

    @pytest.mark.skip(reason="CalendarSpreadStrategy needs interface refactor - Phase 5.3 deferred")
    def test_factory_creates_put_calendar(self, mock_user):
        """Test factory creates put calendar with correct option type."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("put_calendar", mock_user)

        assert strategy.strategy_name == "put_calendar"
        assert strategy.option_type == "PUT"

    def test_factory_lists_all_new_strategies(self, mock_user):
        """Test factory lists all new strategy types."""
        from services.strategies.factory import list_strategies

        strategies = list_strategies()

        # Verify new strategies are listed
        assert "long_straddle" in strategies
        assert "short_straddle" in strategies
        assert "long_strangle" in strategies
        assert "short_strangle" in strategies
        assert "short_iron_condor" in strategies
        assert "long_iron_condor" in strategies
        assert "call_calendar" in strategies
        assert "put_calendar" in strategies


# =============================================================================
# Task 5.5: Legacy Class Removal Verification
# =============================================================================


class TestLegacyClassRemoval:
    """Verify legacy classes are removed (no backward compatibility)."""

    def test_long_straddle_strategy_removed(self):
        """Test LongStraddleStrategy class no longer exists as separate class."""
        with pytest.raises(ImportError):
            from services.strategies.long_straddle_strategy import (
                LongStraddleStrategy,  # noqa: F401
            )

    def test_long_strangle_strategy_removed(self):
        """Test LongStrangleStrategy class no longer exists as separate class."""
        with pytest.raises(ImportError):
            from services.strategies.long_strangle_strategy import (
                LongStrangleStrategy,  # noqa: F401
            )

    def test_short_iron_condor_strategy_removed(self):
        """Test ShortIronCondorStrategy class no longer exists as separate class."""
        with pytest.raises(ImportError):
            from services.strategies.short_iron_condor_strategy import (
                ShortIronCondorStrategy,  # noqa: F401
            )

    def test_long_iron_condor_strategy_removed(self):
        """Test LongIronCondorStrategy class no longer exists as separate class."""
        with pytest.raises(ImportError):
            from services.strategies.long_iron_condor_strategy import (
                LongIronCondorStrategy,  # noqa: F401
            )

    def test_long_call_calendar_strategy_removed(self):
        """Test LongCallCalendarStrategy class no longer exists as separate class."""
        with pytest.raises(ImportError):
            from services.strategies.calendar_spread_strategy import (
                LongCallCalendarStrategy,  # noqa: F401
            )


# =============================================================================
# Calculation Method Tests (Shared Between Directions)
# =============================================================================


class TestStraddleCalculations:
    """Test calculation methods work correctly for both directions."""

    def test_find_atm_strike(self, mock_user):
        """Test ATM strike selection."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        current_price = Decimal("550.00")
        strike = strategy._find_atm_strike(current_price)

        assert strike == Decimal("550")
        assert strike % 2 == 0

    def test_calculate_breakevens(self, mock_user):
        """Test breakeven calculation for straddle."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.LONG)
        strike = Decimal("100.00")
        total_premium = Decimal("8.00")

        be_up, be_down = strategy._calculate_breakevens(strike, total_premium)

        assert be_up == Decimal("108.00")  # Strike + premium
        assert be_down == Decimal("92.00")  # Strike - premium


class TestStrangleCalculations:
    """Test calculation methods work correctly for both directions."""

    def test_find_otm_strikes(self, mock_user):
        """Test OTM strike selection (5% on each side)."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.LONG)
        current_price = Decimal("100.00")
        call_strike, put_strike = strategy._find_otm_strikes(current_price)

        assert call_strike > current_price  # 5% above
        assert put_strike < current_price  # 5% below
        assert call_strike % 2 == 0
        assert put_strike % 2 == 0

    def test_calculate_breakevens(self, mock_user):
        """Test breakeven calculation for strangle."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.LONG)
        call_strike = Decimal("105.00")
        put_strike = Decimal("95.00")
        total_premium = Decimal("4.50")

        be_up, be_down = strategy._calculate_breakevens(call_strike, put_strike, total_premium)

        assert be_up == Decimal("109.50")  # Call strike + premium
        assert be_down == Decimal("90.50")  # Put strike - premium


class TestIronCondorCalculations:
    """Test calculation methods work correctly for both directions."""

    def test_calculate_short_strikes(self, mock_user):
        """Test short strike calculation (16 delta targets)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        current_price = Decimal("100.00")
        put_short, call_short = strategy._calculate_short_strikes(current_price)

        assert put_short < current_price
        assert call_short > current_price
        assert put_short % 2 == 0
        assert call_short % 2 == 0

    def test_calculate_max_profit_short(self, mock_user):
        """Test max profit for short iron condor (credit received)."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        credit_received = Decimal("2.50")

        max_profit = strategy._calculate_max_profit(credit_received, quantity=1)

        assert max_profit == Decimal("250.00")  # 2.50 × 100

    def test_calculate_max_loss_short(self, mock_user):
        """Test max loss for short iron condor."""
        from services.strategies.core.types import Side
        from services.strategies.iron_condor_strategy import IronCondorStrategy

        strategy = IronCondorStrategy(mock_user, direction=Side.SHORT)
        wing_width = 5
        credit_received = Decimal("2.50")

        max_loss = strategy._calculate_max_loss(wing_width, credit_received, quantity=1)

        assert max_loss == Decimal("250.00")  # (5 - 2.50) × 100


# =============================================================================
# Short Strategy Risk Tests (UNLIMITED LOSS POTENTIAL)
# =============================================================================


class TestShortStrategyRiskProperties:
    """Test short strategies have proper risk warnings and settings."""

    def test_short_straddle_dte_exit_threshold(self, mock_user):
        """Test short straddle exits early to manage gamma risk."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        mock_position = Mock()

        threshold = strategy.get_dte_exit_threshold(mock_position)
        assert threshold >= 21  # Exit early for risk management

    def test_short_strangle_dte_exit_threshold(self, mock_user):
        """Test short strangle exits early to manage gamma risk."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.SHORT)
        mock_position = Mock()

        threshold = strategy.get_dte_exit_threshold(mock_position)
        assert threshold >= 21  # Exit early for risk management

    def test_short_straddle_profit_target(self, mock_user):
        """Test short straddle has profit targets enabled."""
        from services.strategies.core.types import Side
        from services.strategies.straddle_strategy import StraddleStrategy

        strategy = StraddleStrategy(mock_user, direction=Side.SHORT)
        mock_position = Mock()

        assert strategy.should_place_profit_targets(mock_position) is True

    def test_short_strangle_profit_target(self, mock_user):
        """Test short strangle has profit targets enabled."""
        from services.strategies.core.types import Side
        from services.strategies.strangle_strategy import StrangleStrategy

        strategy = StrangleStrategy(mock_user, direction=Side.SHORT)
        mock_position = Mock()

        assert strategy.should_place_profit_targets(mock_position) is True
