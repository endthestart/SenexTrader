"""
Core strategy primitives and composition system.

This module provides the foundational building blocks for all
options strategies in the unified architecture.

Exports:
    Type Aliases:
        Strike, Premium, Delta, Quantity

    Enums:
        Direction, OptionType, Side, StrikeSelection, PriceEffect

    Core Classes:
        OptionContract - Immutable option contract specification
        StrategyLeg - Single leg of an options strategy
        StrategyComposition - Complete multi-leg strategy

    Constants:
        CONTRACT_MULTIPLIER - Standard 100 shares per contract

Usage:
    from services.strategies.core import (
        OptionContract, StrategyLeg, StrategyComposition,
        OptionType, Side, Direction, PriceEffect,
    )

    # Create a bull put spread
    short_put = StrategyLeg(
        contract=OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("580"),
            expiration=date(2025, 1, 17),
        ),
        side=Side.SHORT,
        quantity=1,
    )
    long_put = StrategyLeg(
        contract=OptionContract(
            symbol="SPY",
            option_type=OptionType.PUT,
            strike=Decimal("575"),
            expiration=date(2025, 1, 17),
        ),
        side=Side.LONG,
        quantity=1,
    )
    spread = StrategyComposition(legs=[short_put, long_put])
"""

from services.strategies.core.legs import StrategyLeg
from services.strategies.core.parameters import (
    BaseSpreadParams,
    GenerationMode,
    VerticalSpreadParams,
)
from services.strategies.core.primitives import OptionContract
from services.strategies.core.risk import (
    AutomationEligibility,
    MarginChecker,
    RiskClassifier,
    RiskProfile,
    RiskRequirements,
    get_risk_requirements,
)
from services.strategies.core.strategy import CONTRACT_MULTIPLIER, StrategyComposition
from services.strategies.core.types import (
    Delta,
    Direction,
    OptionType,
    Premium,
    PriceEffect,
    Quantity,
    Side,
    Strike,
    StrikeSelection,
)

__all__ = [
    "CONTRACT_MULTIPLIER",
    "AutomationEligibility",
    "BaseSpreadParams",
    "Delta",
    "Direction",
    "GenerationMode",
    "MarginChecker",
    "OptionContract",
    "OptionType",
    "Premium",
    "PriceEffect",
    "Quantity",
    "RiskClassifier",
    "RiskProfile",
    "RiskRequirements",
    "Side",
    "StrategyComposition",
    "StrategyLeg",
    "Strike",
    "StrikeSelection",
    "VerticalSpreadParams",
    "get_risk_requirements",
]
