"""
Centralized technical indicator calculations.

Single source of truth for all technical indicators to eliminate code duplication.
All calculations follow consistent patterns and return Decimal types for precision.
"""

import statistics
from decimal import Decimal


def calculate_bollinger_bands(
    prices: list[float], period: int = 20, std_dev: float = 2.0
) -> dict[str, Decimal | None]:
    """
    Calculate Bollinger Bands - single source of truth.

    Uses pure Python (no pandas dependency) for consistent behavior across
    sync and async contexts. Returns position determination included.

    Args:
        prices: List of closing prices (most recent last)
        period: Moving average period (default 20)
        std_dev: Standard deviation multiplier (default 2.0)

    Returns:
        Dict with keys:
        - upper: Upper band (Decimal or None)
        - middle: Middle band / SMA (Decimal or None)
        - lower: Lower band (Decimal or None)
        - current_price: Most recent price (Decimal or None)
        - position: 'above_upper', 'below_lower', 'within_bands', or 'unknown'

    Examples:
        >>> prices = [100.0, 101.0, 102.0, 103.0, 104.0]
        >>> bands = calculate_bollinger_bands(prices, period=5)
        >>> print(bands['middle'])
        Decimal('102.00')
        >>> print(bands['position'])
        'within_bands'
    """
    if not prices or len(prices) < period:
        return {
            "upper": None,
            "middle": None,
            "lower": None,
            "current_price": None,
            "position": "unknown",
        }

    # Use last 'period' prices for calculation
    window = prices[-period:]

    # Calculate mean and standard deviation
    mean = statistics.mean(window)
    std = statistics.stdev(window) if len(window) > 1 else 0.0

    # Calculate bands
    upper = mean + (std * std_dev)
    lower = mean - (std * std_dev)
    current_price = prices[-1]

    # Determine position
    if current_price >= upper:
        position = "above_upper"
    elif current_price <= lower:
        position = "below_lower"
    else:
        position = "within_bands"

    return {
        "upper": Decimal(str(round(upper, 2))),
        "middle": Decimal(str(round(mean, 2))),
        "lower": Decimal(str(round(lower, 2))),
        "current_price": Decimal(str(round(current_price, 2))),
        "position": position,
    }


def calculate_bollinger_bands_pandas(
    prices_series, period: int = 20, std_dev: float = 2.0
) -> tuple[float, float, float]:
    """
    Calculate Bollinger Bands using pandas Series.

    Used by TechnicalIndicatorCalculator for performance with large datasets.
    Returns only the numeric values (upper, middle, lower) as floats.

    Args:
        prices_series: pandas Series of closing prices
        period: Moving average period (default 20)
        std_dev: Standard deviation multiplier (default 2.0)

    Returns:
        Tuple of (upper_band, middle_band, lower_band) as floats

    Examples:
        >>> import pandas as pd
        >>> prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
        >>> upper, middle, lower = calculate_bollinger_bands_pandas(prices, period=5)
        >>> print(f"{middle:.2f}")
        102.00
    """
    middle_band = prices_series.rolling(window=period).mean()
    std = prices_series.rolling(window=period).std()
    upper_band = middle_band + (std_dev * std)
    lower_band = middle_band - (std_dev * std)

    return (float(upper_band.iloc[-1]), float(middle_band.iloc[-1]), float(lower_band.iloc[-1]))


def determine_bollinger_position(current_price: float, upper: float, lower: float) -> str:
    """
    Determine price position relative to Bollinger Bands.

    Args:
        current_price: Current price
        upper: Upper band value
        lower: Lower band value

    Returns:
        One of: 'above_upper', 'below_lower', 'within_bands'

    Examples:
        >>> determine_bollinger_position(105.0, 104.0, 98.0)
        'above_upper'
        >>> determine_bollinger_position(100.0, 104.0, 98.0)
        'within_bands'
    """
    if current_price >= upper:
        return "above_upper"
    if current_price <= lower:
        return "below_lower"
    # Some code uses 'within_bands', some uses 'middle'
    # Return 'within_bands' as it's more descriptive
    return "within_bands"


def is_near_bollinger_band(
    current_price: float, upper: float, lower: float, threshold: float = 0.02
) -> bool:
    """
    Check if current price is near a Bollinger band.

    Used to determine if positions should be excluded based on proximity
    to support/resistance indicated by the bands.

    Args:
        current_price: Current price
        upper: Upper band value
        lower: Lower band value
        threshold: Distance threshold as percentage (default 0.02 = 2%)

    Returns:
        True if price is within threshold% of either band

    Examples:
        >>> is_near_bollinger_band(100.0, 102.0, 98.0, threshold=0.02)
        True
        >>> is_near_bollinger_band(100.0, 110.0, 90.0, threshold=0.02)
        False
    """
    if not current_price or not lower or not upper:
        return False

    # Check if within threshold percentage of either band
    lower_distance = abs(current_price - lower) / current_price
    upper_distance = abs(current_price - upper) / current_price

    return lower_distance <= threshold or upper_distance <= threshold
