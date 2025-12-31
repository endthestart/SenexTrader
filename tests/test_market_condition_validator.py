"""
Unit tests for Market Analyzer (MarketConditionReport + a_analyze_market_conditions)

Tests the generic market analysis infrastructure.
Formerly test_market_condition_validator.py - updated for Epic 32 consolidation.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.market_data.analysis import MarketAnalyzer, MarketConditionReport, RegimeType


class TestMarketConditionReport:
    """Test MarketConditionReport dataclass"""

    def test_can_trade_with_no_reasons(self):
        """Test that trading is allowed when no hard stops"""
        report = MarketConditionReport(symbol="SPY", current_price=450.0, no_trade_reasons=[])
        assert report.can_trade() is True

    def test_can_trade_with_reasons(self):
        """Test that trading is blocked with hard stops"""
        report = MarketConditionReport(
            symbol="SPY", current_price=450.0, no_trade_reasons=["data_stale", "exchange_closed"]
        )
        assert report.can_trade() is False

    def test_get_no_trade_explanation(self):
        """Test no-trade explanation generation"""
        report = MarketConditionReport(
            symbol="SPY", current_price=450.0, no_trade_reasons=["data_stale"]
        )
        explanation = report.get_no_trade_explanation()
        assert "data_stale" in explanation
        assert "No trade" in explanation

    def test_context_fields_calculated(self):
        """Test that context fields are calculated in __post_init__"""
        # Test bullish regime
        report = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            adx=35.0,
            macd_signal="bullish",
            rsi=55.0,
            bollinger_position="within_bands",
        )
        assert report.regime_primary == RegimeType.BULL
        assert report.is_overbought is False
        assert report.is_oversold is False

        # Test overbought (Epic 32: requires 3+ warnings for extreme flag)
        report_overbought = MarketConditionReport(
            symbol="SPY",
            current_price=500.0,
            sma_20=450.0,  # Price 11% above SMA = 1 warning
            rsi=85.0,  # RSI > 70 and > 80 = 2 warnings
            bollinger_position="above_upper",  # Bollinger = 1 warning
        )
        # Total: 4 warnings (3+ threshold met)
        assert report_overbought.overbought_warnings >= 3
        assert report_overbought.is_overbought is True

        # Test oversold (Epic 32: requires 3+ warnings for extreme flag)
        report_oversold = MarketConditionReport(
            symbol="SPY",
            current_price=400.0,
            sma_20=450.0,  # Price 11% below SMA = 1 warning
            rsi=15.0,  # RSI < 30 and < 20 = 2 warnings
            bollinger_position="below_lower",  # Bollinger = 1 warning
        )
        # Total: 4 warnings (3+ threshold met)
        assert report_oversold.oversold_warnings >= 3
        assert report_oversold.is_oversold is True

        # Test sideways regime
        report_sideways = MarketConditionReport(
            symbol="SPY",
            current_price=450.0,
            is_range_bound=True,
        )
        assert report_sideways.regime_primary == RegimeType.RANGE


@pytest.mark.asyncio
class TestMarketConditionValidator:
    """Test MarketConditionValidator service"""

    @pytest.fixture
    def mock_user(self):
        """Create mock user"""
        user = MagicMock()
        user.id = 1
        return user

    @pytest.fixture
    def validator(self, mock_user):
        """Create validator instance"""
        return MarketAnalyzer(mock_user)

    async def test_analyze_market_conditions_success(self, validator, mock_user):
        """Test successful market analysis"""
        from django.utils import timezone

        # Mock dependencies
        mock_quote = {
            "bid": 449.0,
            "ask": 451.0,
            "last": 450.0,
            "open": 445.0,
            "timestamp": timezone.now().isoformat(),
        }

        mock_metrics = {"iv_rank": 65.0, "iv_percentile": 68.0, "iv_30_day": 0.25}

        mock_technical = {
            "rsi": 55.0,
            "macd_signal": "bullish",
            "bollinger_position": "within_bands",
            "sma_20": 445.0,
            "support_level": 440.0,
            "resistance_level": 460.0,
            "recent_move_pct": 1.5,
            "current_price": 450.0,
            "open_price": 445.0,
        }

        # market_snapshot with range-bound data (from MarketAnalyzer)
        market_snapshot = {"is_range_bound": False, "range_bound_days": 0}

        # Create async mocks
        async def mock_get_quote(symbol):
            return mock_quote

        async def mock_get_metrics(symbol):
            return mock_metrics

        async def mock_calc_indicators(user, symbol, snapshot):
            return mock_technical

        # Patch dependencies
        with (
            patch.object(validator.market_service, "get_quote", side_effect=mock_get_quote),
            patch.object(
                validator.market_service, "get_market_metrics", side_effect=mock_get_metrics
            ),
            patch(
                "services.market_data.indicators.TechnicalIndicatorCalculator.a_calculate_indicators",
                side_effect=mock_calc_indicators,
            ),
        ):

            report = await validator.a_analyze_market_conditions(mock_user, "SPY", market_snapshot)

            # Verify report structure
            assert isinstance(report, MarketConditionReport)
            assert report.current_price == 450.0
            assert report.open_price == 445.0
            assert report.iv_rank == 65.0
            assert report.rsi == 55.0
            assert report.macd_signal == "bullish"
            assert report.is_range_bound is False
            assert report.can_trade() is True

    async def test_analyze_market_conditions_stale_data(self, validator, mock_user):
        """Test that stale data triggers no-trade condition"""
        from datetime import timedelta

        from django.utils import timezone

        # Create stale quote (10 minutes old)
        stale_time = timezone.now() - timedelta(minutes=10)
        mock_quote = {"bid": 449.0, "ask": 451.0, "timestamp": stale_time.isoformat()}

        mock_metrics = {"iv_rank": 50.0, "iv_percentile": 50.0, "iv_30_day": 0.25}

        market_snapshot = {"is_range_bound": False, "range_bound_days": 0}

        async def mock_get_quote(symbol):
            return mock_quote

        async def mock_get_metrics(symbol):
            return mock_metrics

        async def mock_calc_indicators(user, symbol, snapshot):
            return {}

        with (
            patch.object(validator.market_service, "get_quote", side_effect=mock_get_quote),
            patch.object(
                validator.market_service, "get_market_metrics", side_effect=mock_get_metrics
            ),
            patch(
                "services.market_data.indicators.TechnicalIndicatorCalculator.a_calculate_indicators",
                side_effect=mock_calc_indicators,
            ),
        ):

            report = await validator.a_analyze_market_conditions(mock_user, "SPY", market_snapshot)

            # Verify stale data is detected
            assert report.is_data_stale is True
            assert "data_stale" in report.no_trade_reasons
            assert report.can_trade() is False

    async def test_analyze_market_conditions_no_quote(self, validator, mock_user):
        """Test handling when no quote available"""

        async def mock_get_quote(symbol):
            return None

        async def mock_get_metrics(symbol):
            return None

        async def mock_calc_indicators(user, symbol, snapshot):
            return {}

        market_snapshot = {"is_range_bound": False, "range_bound_days": 0}

        with (
            patch.object(validator.market_service, "get_quote", side_effect=mock_get_quote),
            patch.object(
                validator.market_service, "get_market_metrics", side_effect=mock_get_metrics
            ),
            patch(
                "services.market_data.indicators.TechnicalIndicatorCalculator.a_calculate_indicators",
                side_effect=mock_calc_indicators,
            ),
        ):

            report = await validator.a_analyze_market_conditions(mock_user, "SPY", market_snapshot)

            # Verify defaults are used
            assert report.current_price == 0.0
            assert report.iv_rank == 50.0  # Default
            assert report.is_data_stale is True

    def test_check_data_quality_fresh(self, validator):
        """Test data quality check with fresh data"""
        from django.utils import timezone

        fresh_quote = {"bid": 450.0, "timestamp": timezone.now().isoformat()}

        quality = validator._check_data_quality(fresh_quote)

        assert quality["is_stale"] is False
        assert quality["last_update"] is not None

    def test_check_data_quality_stale(self, validator):
        """Test data quality check with stale data"""
        from datetime import timedelta

        from django.utils import timezone

        stale_time = timezone.now() - timedelta(minutes=10)
        stale_quote = {"bid": 450.0, "timestamp": stale_time.isoformat()}

        quality = validator._check_data_quality(stale_quote)

        assert quality["is_stale"] is True

    def test_check_data_quality_no_quote(self, validator):
        """Test data quality check with no quote"""
        quality = validator._check_data_quality(None)

        assert quality["is_stale"] is True
        assert quality["last_update"] is None

    def test_check_data_quality_fresh_updated_at(self, validator):
        """Test data quality check with fresh data using updated_at (streaming format)"""
        from django.utils import timezone

        fresh_quote = {"bid": 450.0, "updated_at": timezone.now().isoformat()}

        quality = validator._check_data_quality(fresh_quote)

        assert quality["is_stale"] is False
        assert quality["last_update"] is not None
