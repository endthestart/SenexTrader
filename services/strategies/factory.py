"""
Strategy Factory - Simple factory for strategy instantiation.

Replaces the decorator-based registry pattern with explicit factory functions.
This provides clearer code flow and easier parameterized strategy support.

"""

from django.contrib.auth.models import AbstractBaseUser

from services.core.logging import get_logger
from services.strategies.base import BaseStrategy

logger = get_logger(__name__)


# Strategy type definitions - maps strategy_type to instantiation info
# Format varies by strategy type:
# - Vertical spreads: ("credit"|"debit", "BULLISH"|"BEARISH")
# - Straddles/Strangles: ("straddle"|"strangle", "LONG"|"SHORT")
# - Iron Condors: ("iron_condor", "LONG"|"SHORT")
# - Calendars: ("calendar", "CALL"|"PUT")
# - Standard: (module_path, class_name)
STRATEGY_DEFINITIONS: dict[str, tuple[str, str]] = {
    # Vertical Spreads - use CreditSpreadStrategy/DebitSpreadStrategy directly
    "short_put_vertical": ("credit", "BULLISH"),
    "short_call_vertical": ("credit", "BEARISH"),
    "long_call_vertical": ("debit", "BULLISH"),
    "long_put_vertical": ("debit", "BEARISH"),
    # Straddles - unified StraddleStrategy with direction
    "long_straddle": ("straddle", "LONG"),
    "short_straddle": ("straddle", "SHORT"),
    # Strangles - unified StrangleStrategy with direction
    "long_strangle": ("strangle", "LONG"),
    "short_strangle": ("strangle", "SHORT"),
    # Iron Condors - unified IronCondorStrategy with direction
    "short_iron_condor": ("iron_condor", "SHORT"),
    "long_iron_condor": ("iron_condor", "LONG"),
    # Calendars - unified CalendarSpreadStrategy with option_type
    "call_calendar": ("calendar", "CALL"),
    "put_calendar": ("calendar", "PUT"),
    # Iron Butterfly
    "iron_butterfly": (
        "services.strategies.iron_butterfly_strategy",
        "IronButterflyStrategy",
    ),
    # Covered Positions (deferred to Wheel algorithm phase)
    "covered_call": (
        "services.strategies.covered_call_strategy",
        "CoveredCallStrategy",
    ),
    "cash_secured_put": (
        "services.strategies.cash_secured_put_strategy",
        "CashSecuredPutStrategy",
    ),
    # Backspreads
    "long_call_ratio_backspread": (
        "services.strategies.call_backspread_strategy",
        "LongCallRatioBackspreadStrategy",
    ),
    "long_put_ratio_backspread": (
        "services.strategies.put_backspread_strategy",
        "LongPutRatioBackspreadStrategy",
    ),
    # Senex Trident (proprietary)
    "senex_trident": (
        "services.strategies.senex_trident_strategy",
        "SenexTridentStrategy",
    ),
}


def get_strategy(strategy_type: str, user: AbstractBaseUser) -> BaseStrategy:
    """
    Factory function to instantiate a strategy by type.

    Args:
        strategy_type: Strategy identifier (e.g., "short_put_vertical")
        user: User context for strategy

    Returns:
        Instantiated strategy object

    Raises:
        ValueError: If strategy_type is not known

    Example:
        >>> strategy = get_strategy("short_put_vertical", user)
        >>> score, explanation = await strategy.a_score_market_conditions(report)
    """
    if strategy_type not in STRATEGY_DEFINITIONS:
        available = ", ".join(sorted(STRATEGY_DEFINITIONS.keys()))
        raise ValueError(
            f"Unknown strategy type: '{strategy_type}'. Available strategies: {available}"
        )

    definition = STRATEGY_DEFINITIONS[strategy_type]
    strategy_category = definition[0]

    # Handle vertical spreads (credit/debit)
    if strategy_category in ("credit", "debit"):
        return _create_vertical_spread(strategy_type, user, definition)

    # Handle straddles (unified StraddleStrategy)
    if strategy_category == "straddle":
        return _create_straddle(user, definition)

    # Handle strangles (unified StrangleStrategy)
    if strategy_category == "strangle":
        return _create_strangle(user, definition)

    # Handle iron condors (unified IronCondorStrategy)
    if strategy_category == "iron_condor":
        return _create_iron_condor(user, definition)

    # Handle calendars (unified CalendarSpreadStrategy)
    if strategy_category == "calendar":
        return _create_calendar(user, definition)

    # Standard class-based instantiation
    import importlib

    module_path, class_name = definition
    module = importlib.import_module(module_path)
    strategy_class = getattr(module, class_name)

    logger.debug(f"Creating strategy instance: {strategy_type} -> {class_name}")

    return strategy_class(user)


def _create_vertical_spread(
    strategy_type: str, user: AbstractBaseUser, definition: tuple[str, str]
) -> BaseStrategy:
    """
    Create a vertical spread strategy with parameters.

    Args:
        strategy_type: The strategy name (e.g., "short_put_vertical")
        user: User context
        definition: Tuple of (spread_type, direction) where spread_type is "credit" or "debit"

    Returns:
        Instantiated CreditSpreadStrategy or DebitSpreadStrategy
    """
    spread_type, direction = definition

    if spread_type == "credit":
        from services.strategies.core.types import Direction
        from services.strategies.credit_spread_strategy import CreditSpreadStrategy

        direction_enum = (
            Direction.BULLISH if direction == "BULLISH" else Direction.BEARISH
        )
        logger.debug(f"Creating credit spread: {strategy_type} ({direction})")
        return CreditSpreadStrategy(user, direction=direction_enum, strategy_name=strategy_type)

    # debit
    from services.strategies.core.types import Direction
    from services.strategies.debit_spread_strategy import DebitSpreadStrategy

    direction_enum = (
        Direction.BULLISH if direction == "BULLISH" else Direction.BEARISH
    )
    logger.debug(f"Creating debit spread: {strategy_type} ({direction})")
    return DebitSpreadStrategy(user, direction=direction_enum, strategy_name=strategy_type)


def _create_straddle(user: AbstractBaseUser, definition: tuple[str, str]) -> BaseStrategy:
    """
    Create a straddle strategy with direction parameter.

    Args:
        user: User context
        definition: Tuple of ("straddle", "LONG"|"SHORT")

    Returns:
        Instantiated StraddleStrategy
    """
    from services.strategies.core.types import Side
    from services.strategies.straddle_strategy import StraddleStrategy

    _, direction = definition
    direction_enum = Side.LONG if direction == "LONG" else Side.SHORT
    logger.debug(f"Creating straddle: {direction}")
    return StraddleStrategy(user, direction=direction_enum)


def _create_strangle(user: AbstractBaseUser, definition: tuple[str, str]) -> BaseStrategy:
    """
    Create a strangle strategy with direction parameter.

    Args:
        user: User context
        definition: Tuple of ("strangle", "LONG"|"SHORT")

    Returns:
        Instantiated StrangleStrategy
    """
    from services.strategies.core.types import Side
    from services.strategies.strangle_strategy import StrangleStrategy

    _, direction = definition
    direction_enum = Side.LONG if direction == "LONG" else Side.SHORT
    logger.debug(f"Creating strangle: {direction}")
    return StrangleStrategy(user, direction=direction_enum)


def _create_iron_condor(user: AbstractBaseUser, definition: tuple[str, str]) -> BaseStrategy:
    """
    Create an iron condor strategy with direction parameter.

    Args:
        user: User context
        definition: Tuple of ("iron_condor", "LONG"|"SHORT")

    Returns:
        Instantiated IronCondorStrategy
    """
    from services.strategies.core.types import Side
    from services.strategies.iron_condor_strategy import IronCondorStrategy

    _, direction = definition
    direction_enum = Side.LONG if direction == "LONG" else Side.SHORT
    logger.debug(f"Creating iron condor: {direction}")
    return IronCondorStrategy(user, direction=direction_enum)


def _create_calendar(user: AbstractBaseUser, definition: tuple[str, str]) -> BaseStrategy:
    """
    Create a calendar spread strategy with option_type parameter.

    Args:
        user: User context
        definition: Tuple of ("calendar", "CALL"|"PUT")

    Returns:
        Instantiated CalendarSpreadStrategy
    """
    from services.strategies.calendar_spread_strategy import CalendarSpreadStrategy

    _, option_type = definition
    logger.debug(f"Creating calendar spread: {option_type}")
    return CalendarSpreadStrategy(user, option_type=option_type)


def list_strategies() -> list[str]:
    """
    Get sorted list of all available strategy types.

    Returns:
        Sorted list of strategy type keys

    Example:
        >>> strategies = list_strategies()
        >>> print(strategies)
        ['cash_secured_put', 'covered_call', 'iron_butterfly', ...]
    """
    return sorted(STRATEGY_DEFINITIONS.keys())


def is_strategy_registered(strategy_type: str) -> bool:
    """
    Check if a strategy type is available.

    Args:
        strategy_type: Strategy identifier

    Returns:
        True if available, False otherwise
    """
    return strategy_type in STRATEGY_DEFINITIONS


def get_all_strategies(user: AbstractBaseUser) -> dict[str, BaseStrategy]:
    """
    Instantiate all available strategies.

    Args:
        user: User context for strategies

    Returns:
        Dictionary mapping strategy_type -> instantiated strategy

    Example:
        >>> strategies = get_all_strategies(user)
        >>> for name, strategy in strategies.items():
        ...     score, _ = await strategy.a_score_market_conditions(report)
    """
    return {name: get_strategy(name, user) for name in STRATEGY_DEFINITIONS}

