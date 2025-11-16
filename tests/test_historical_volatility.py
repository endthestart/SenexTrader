"""
Unit tests for Historical Volatility and HV/IV Ratio calculations.

Epic 05, Task 002-003: Historical Volatility and HV/IV Ratio
"""

import pandas as pd
import pytest

from services.market_data.analysis import MarketConditionReport
from services.market_data.indicators import TechnicalIndicatorCalculator


class TestHistoricalVolatility:
    """Test Historical Volatility calculation."""

    @pytest.fixture
    def calculator(self):
        """Create calculator instance."""
        return TechnicalIndicatorCalculator()

    def test_hv_with_stable_prices(self, calculator):
        """Test HV with low volatility (stable prices)."""
        # Simulate stable prices with minimal movement
        prices = pd.Series(
            [
                100.0,
                100.5,
                100.2,
                100.3,
                100.1,
                100.4,
                100.3,
                100.2,
                100.5,
                100.4,
                100.3,
                100.6,
                100.5,
                100.4,
                100.7,
                100.6,
                100.5,
                100.8,
                100.7,
                100.6,
                100.9,
                100.8,
                100.7,
                101.0,
                100.9,
                100.8,
                101.1,
                101.0,
                100.9,
                101.2,
                101.1,
            ]
        )

        hv = calculator._calculate_historical_volatility(prices, period=30)

        # Low volatility should produce low HV (< 20%)
        assert isinstance(hv, float)
        assert hv >= 0
        assert hv < 20, f"Stable prices should have HV < 20%, got {hv:.2f}%"

    def test_hv_with_volatile_prices(self, calculator):
        """Test HV with high volatility (large price swings)."""
        # Simulate volatile prices
        prices = pd.Series(
            [
                100.0,
                105.0,
                98.0,
                107.0,
                95.0,
                110.0,
                93.0,
                112.0,
                90.0,
                115.0,
                88.0,
                118.0,
                85.0,
                120.0,
                83.0,
                122.0,
                80.0,
                125.0,
                78.0,
                128.0,
                75.0,
                130.0,
                73.0,
                132.0,
                70.0,
                135.0,
                68.0,
                138.0,
                65.0,
                140.0,
                63.0,
            ]
        )

        hv = calculator._calculate_historical_volatility(prices, period=30)

        # High volatility should produce high HV (> 50%)
        assert isinstance(hv, float)
        assert hv > 50, f"Volatile prices should have HV > 50%, got {hv:.2f}%"

    def test_hv_with_moderate_volatility(self, calculator):
        """Test HV with moderate volatility."""
        # Simulate moderate price movement (typical stock)
        prices = pd.Series(
            [
                100.0,
                101.5,
                99.8,
                102.3,
                100.5,
                103.2,
                101.8,
                104.1,
                102.5,
                105.0,
                103.3,
                106.2,
                104.8,
                107.5,
                106.0,
                108.8,
                107.2,
                110.0,
                108.5,
                111.3,
                109.8,
                112.5,
                111.0,
                113.8,
                112.3,
                115.0,
                113.5,
                116.2,
                114.8,
                117.5,
                116.0,
            ]
        )

        hv = calculator._calculate_historical_volatility(prices, period=30)

        # Moderate volatility typically 20-50%
        assert isinstance(hv, float)
        assert 20 < hv < 50, f"Moderate volatility should have HV 20-50%, got {hv:.2f}%"

    def test_hv_with_insufficient_data(self, calculator):
        """Test HV returns 0 with insufficient data."""
        prices = pd.Series([100.0])

        hv = calculator._calculate_historical_volatility(prices, period=30)

        assert hv == 0.0

    def test_hv_returns_percentage(self, calculator):
        """Test HV returns annualized percentage."""
        prices = pd.Series([100.0 + i * 0.5 for i in range(35)])

        hv = calculator._calculate_historical_volatility(prices, period=30)

        # Should be annualized percentage (not decimal)
        assert isinstance(hv, float)
        assert hv >= 0
        assert hv < 200  # Sanity check - HV rarely > 200%

    def test_hv_different_periods(self, calculator):
        """Test HV with different lookback periods."""
        prices = pd.Series([100.0 + i * 0.3 for i in range(100)])

        hv_10 = calculator._calculate_historical_volatility(prices, period=10)
        hv_30 = calculator._calculate_historical_volatility(prices, period=30)
        hv_60 = calculator._calculate_historical_volatility(prices, period=60)

        # All should be valid
        assert isinstance(hv_10, float)
        assert isinstance(hv_30, float)
        assert isinstance(hv_60, float)
        assert hv_10 >= 0
        assert hv_30 >= 0
        assert hv_60 >= 0


class TestHVIVRatio:
    """Test HV/IV Ratio calculation in MarketConditionReport."""

    def test_hv_iv_ratio_with_high_iv(self):
        """Test ratio when IV is high relative to HV."""
        # HV = 20%, IV = 30% (0.30) → ratio = 20/30 = 0.67 (< 0.8 = good for selling)
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=20.0,
            current_iv=0.30,  # 30%
        )

        assert report.hv_iv_ratio < 0.8
        assert report.hv_iv_ratio > 0.6

    def test_hv_iv_ratio_with_low_iv(self):
        """Test ratio when IV is low relative to HV."""
        # HV = 30%, IV = 20% (0.20) → ratio = 30/20 = 1.5 (> 1.2 = bad for selling)
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=30.0,
            current_iv=0.20,  # 20%
        )

        assert report.hv_iv_ratio > 1.2

    def test_hv_iv_ratio_balanced(self):
        """Test ratio when HV and IV are balanced."""
        # HV = 25%, IV = 25% (0.25) → ratio = 1.0 (neutral)
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=25.0,
            current_iv=0.25,  # 25%
        )

        assert 0.95 < report.hv_iv_ratio < 1.05

    def test_hv_iv_ratio_with_zero_iv(self):
        """Test ratio defaults to 1.0 when IV is zero."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=20.0,
            current_iv=0.0,
        )

        assert report.hv_iv_ratio == 1.0

    def test_hv_iv_ratio_with_zero_hv(self):
        """Test ratio defaults to 1.0 when HV is zero."""
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=0.0,
            current_iv=0.25,
        )

        assert report.hv_iv_ratio == 1.0

    def test_hv_iv_ratio_premium_selling_opportunity(self):
        """Test identifying good premium selling opportunities."""
        # IV much higher than realized vol = great for selling premium
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=15.0,
            current_iv=0.25,  # 25% IV vs 15% HV
        )

        # Ratio should be < 0.8 (good for premium selling)
        assert report.hv_iv_ratio < 0.8
        assert report.hv_iv_ratio == pytest.approx(0.6, rel=0.1)

    def test_hv_iv_ratio_poor_premium_selling(self):
        """Test identifying poor premium selling conditions."""
        # IV much lower than realized vol = bad for selling premium
        report = MarketConditionReport(
            symbol="SPY",
            current_price=100.0,
            historical_volatility=40.0,
            current_iv=0.25,  # 25% IV vs 40% HV
        )

        # Ratio should be > 1.2 (poor for premium selling)
        assert report.hv_iv_ratio > 1.2
        assert report.hv_iv_ratio == pytest.approx(1.6, rel=0.1)
