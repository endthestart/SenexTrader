"""
TDD tests for Put Backspread Strategy.

Put Backspread (Ratio Put Backspread) - Advanced bearish strategy with unlimited profit.

Structure:
- Sell 1 ATM/ITM put (collect high premium)
- Buy 2 OTM puts (pay lower premium each)
- Ratio: 2:1 (buy 2, sell 1)
- Net result: Small credit or minimal debit

Risk Profile:
- Max loss occurs at long put strikes ("danger zone")
- Unlimited profit on large crash
- Small profit if price rallies significantly
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.market_data.analysis import MarketConditionReport


@pytest.fixture
def mock_user():
    """Create mock user."""
    user = MagicMock()
    user.id = 1
    return user


@pytest.fixture
def put_backspread_strategy(mock_user):
    """Create put backspread strategy instance."""
    from services.strategies.put_backspread_strategy import LongPutRatioBackspreadStrategy

    return LongPutRatioBackspreadStrategy(mock_user)


class TestPutBackspreadStrategyBasics:
    """Test basic strategy properties."""

    def test_strategy_name(self, put_backspread_strategy):
        """Strategy name should be long_put_ratio_backspread."""
        assert put_backspread_strategy.strategy_name == "long_put_ratio_backspread"

    def test_automation_disabled(self, put_backspread_strategy):
        """Put backspreads should have automation disabled (complex risk)."""
        assert put_backspread_strategy.automation_enabled_by_default() is False

    def test_profit_targets_enabled(self, put_backspread_strategy):
        """Profit targets should be enabled."""
        position = MagicMock()
        assert put_backspread_strategy.should_place_profit_targets(position) is True

    def test_dte_exit_threshold(self, put_backspread_strategy):
        """DTE exit threshold should be 21 days."""
        position = MagicMock()
        assert put_backspread_strategy.get_dte_exit_threshold(position) == 21

    def test_ratio_configuration(self, put_backspread_strategy):
        """Ratio should be 2:1 (buy 2, sell 1)."""
        assert put_backspread_strategy.SELL_QUANTITY == 1
        assert put_backspread_strategy.BUY_QUANTITY == 2
        assert put_backspread_strategy.RATIO == 2.0


class TestPutBackspreadStrikeSelection:
    """Test strike selection for put backspread."""

    def test_select_strikes_basic(self, put_backspread_strategy):
        """Select ATM short put and OTM long puts."""
        current_price = Decimal("550.00")
        strikes = put_backspread_strategy._select_strikes(current_price)

        # Short put should be ATM (rounded to even)
        assert strikes["short_put"] == Decimal("550")

        # Long puts should be 5% OTM (below current price)
        # 550 * 0.95 = 522.5, rounded to 522
        assert strikes["long_puts"] == Decimal("522")

        # Quantities
        assert strikes["quantity_short"] == 1
        assert strikes["quantity_long"] == 2

    def test_select_strikes_higher_price(self, put_backspread_strategy):
        """Strike selection at higher prices."""
        current_price = Decimal("600.00")
        strikes = put_backspread_strategy._select_strikes(current_price)

        assert strikes["short_put"] == Decimal("600")
        # 600 * 0.95 = 570
        assert strikes["long_puts"] == Decimal("570")

    def test_long_puts_always_below_short_put(self, put_backspread_strategy):
        """Long puts must always be below short put (further OTM)."""
        for price in [400, 500, 550, 600, 700]:
            strikes = put_backspread_strategy._select_strikes(Decimal(str(price)))
            assert strikes["long_puts"] < strikes["short_put"], (
                f"Long puts ({strikes['long_puts']}) should be below "
                f"short put ({strikes['short_put']}) for price {price}"
            )


class TestPutBackspreadRiskCalculations:
    """Test risk and profit calculations."""

    def test_danger_zone_calculation(self, put_backspread_strategy):
        """Max loss occurs at long put strikes."""
        short_strike = Decimal("550")
        long_strike = Decimal("520")
        credit = Decimal("1.50")  # Net credit received

        danger = put_backspread_strategy._calculate_danger_zone(
            short_strike, long_strike, credit
        )

        # Danger zone is at long put strike
        assert danger["danger_zone_price"] == Decimal("520")

        # Max loss = spread width - credit
        # At long strike: short put has $30 intrinsic, long puts worthless
        # Loss = $30 - $1.50 credit = $28.50
        expected_loss = (short_strike - long_strike) - credit
        assert danger["max_loss_per_spread"] == expected_loss

    def test_breakeven_calculation(self, put_backspread_strategy):
        """Calculate breakeven points."""
        short_strike = Decimal("550")
        long_strike = Decimal("520")
        credit = Decimal("2.00")

        lower_be, upper_be = put_backspread_strategy._calculate_breakevens(
            short_strike, long_strike, credit
        )

        # Upper breakeven: short strike - credit
        assert upper_be == short_strike - credit

        # Lower breakeven should be below long strike
        assert lower_be < long_strike


class TestPutBackspreadMarketConditionScoring:
    """Test market condition scoring for put backspread."""

    @pytest.fixture
    def bearish_low_iv_report(self):
        """Create ideal bearish, low IV market report."""
        report = MagicMock(spec=MarketConditionReport)
        report.macd_signal = "strong_bearish"
        report.iv_rank = 20.0
        report.adx = 30.0
        report.hv_iv_ratio = 1.3
        report.market_stress_level = 35.0
        report.recent_move_pct = -3.0
        report.current_price = 550.0
        return report

    @pytest.fixture
    def bullish_report(self):
        """Create bullish market report (unsuitable)."""
        report = MagicMock(spec=MarketConditionReport)
        report.macd_signal = "bullish"
        report.iv_rank = 30.0
        report.adx = 25.0
        report.hv_iv_ratio = 1.1
        report.market_stress_level = 40.0
        report.recent_move_pct = 2.0
        report.current_price = 550.0
        return report

    @pytest.fixture
    def high_iv_report(self):
        """Create high IV report (options expensive)."""
        report = MagicMock(spec=MarketConditionReport)
        report.macd_signal = "bearish"
        report.iv_rank = 65.0
        report.adx = 25.0
        report.hv_iv_ratio = 0.8
        report.market_stress_level = 50.0
        report.recent_move_pct = -1.0
        report.current_price = 550.0
        return report

    @pytest.mark.asyncio
    async def test_ideal_conditions_high_score(
        self, put_backspread_strategy, bearish_low_iv_report
    ):
        """Ideal conditions should score high."""
        score, explanation = await put_backspread_strategy.a_score_market_conditions(
            bearish_low_iv_report
        )
        assert score >= 70, f"Ideal conditions should score >= 70, got {score}"
        assert "bearish" in explanation.lower()

    @pytest.mark.asyncio
    async def test_bullish_conditions_zero_score(
        self, put_backspread_strategy, bullish_report
    ):
        """Bullish conditions should score zero (wrong direction)."""
        score, explanation = await put_backspread_strategy.a_score_market_conditions(
            bullish_report
        )
        assert score == 0, f"Bullish conditions should score 0, got {score}"
        assert "bearish" in explanation.lower() or "not" in explanation.lower()

    @pytest.mark.asyncio
    async def test_high_iv_penalized(
        self, put_backspread_strategy, high_iv_report
    ):
        """High IV should be penalized (options expensive to buy)."""
        score, explanation = await put_backspread_strategy.a_score_market_conditions(
            high_iv_report
        )
        # Should still be viable but penalized
        assert score < 60, f"High IV should reduce score below 60, got {score}"
        assert "expensive" in explanation.lower() or "iv" in explanation.lower()

    @pytest.mark.asyncio
    async def test_bearish_exhausted_rejected(self, put_backspread_strategy):
        """Bearish exhausted signal should be rejected (buying at bottom)."""
        report = MagicMock(spec=MarketConditionReport)
        report.macd_signal = "bearish_exhausted"
        report.iv_rank = 25.0
        report.adx = 25.0
        report.hv_iv_ratio = 1.2
        report.market_stress_level = 40.0
        report.recent_move_pct = -2.0
        report.current_price = 550.0

        score, explanation = await put_backspread_strategy.a_score_market_conditions(report)
        assert score == 0, "Bearish exhausted should score 0"


class TestPutBackspreadLegBuilding:
    """Test leg building for put backspread."""

    @pytest.mark.asyncio
    async def test_build_opening_legs_structure(self, put_backspread_strategy):
        """Opening legs should have correct structure."""
        with patch(
            "services.orders.utils.order_builder_utils.build_opening_spread_legs"
        ) as mock_build:
            mock_build.return_value = [MagicMock(), MagicMock()]

            context = {
                "session": MagicMock(),
                "underlying_symbol": "SPY",
                "expiration_date": "2025-02-21",
                "short_put": Decimal("550"),
                "long_puts": Decimal("520"),
                "quantity_short": 1,
                "quantity_long": 2,
            }

            await put_backspread_strategy.build_opening_legs(context)

            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["spread_type"] == "long_put_ratio_backspread"
            assert "short_put" in call_kwargs["strikes"]
            assert "long_put" in call_kwargs["strikes"]


class TestPutBackspreadFactoryIntegration:
    """Test factory integration."""

    def test_factory_creates_put_backspread(self, mock_user):
        """Factory should create put backspread strategy."""
        from services.strategies.factory import get_strategy

        strategy = get_strategy("long_put_ratio_backspread", mock_user)
        assert strategy is not None
        assert strategy.strategy_name == "long_put_ratio_backspread"

    def test_factory_lists_put_backspread(self):
        """Factory should list put backspread in available strategies."""
        from services.strategies.factory import list_strategies

        strategies = list_strategies()
        assert "long_put_ratio_backspread" in strategies


class TestPutBackspreadRiskModule:
    """Test integration with risk module."""

    def test_risk_profile_undefined(self, put_backspread_strategy):
        """Put backspread should have UNDEFINED risk (naked short put)."""
        from services.strategies.core.risk import RiskProfile

        # The strategy has a naked short put component
        # Risk is undefined on the downside beyond breakeven
        profile = put_backspread_strategy.get_risk_profile()
        assert profile == RiskProfile.UNDEFINED
