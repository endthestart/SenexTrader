"""
Strategy builders for unified strategy architecture.

This module provides composable builders that transform parameters
into executable StrategyComposition objects.

Builder Hierarchy:
    BaseBuilder - Common interface and utilities
    └── VerticalSpreadBuilder - Bull Put, Bear Call, Bull Call, Bear Put
    └── IronCondorBuilder - Composes two VerticalSpreadBuilders
    └── CalendarSpreadBuilder - Multi-expiration spreads

Each builder:
1. Takes parameters (VerticalSpreadParams, etc.)
2. Finds optimal strikes from available option chains
3. Returns StrategyComposition ready for execution

Usage:
    from services.strategies.builders import VerticalSpreadBuilder
    from services.strategies.core import VerticalSpreadParams, Direction, OptionType

    params = VerticalSpreadParams(
        direction=Direction.BULLISH,
        option_type=OptionType.PUT,
        width_min=5,
        width_max=5,
    )
    builder = VerticalSpreadBuilder(user)
    composition = await builder.build("QQQ", params)
"""

from services.strategies.builders.vertical_spread_builder import VerticalSpreadBuilder

__all__ = [
    "VerticalSpreadBuilder",
]
