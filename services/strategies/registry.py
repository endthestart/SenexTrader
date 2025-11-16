"""
Strategy Registry - Central registry for all strategy types.

Follows Open/Closed Principle: Add new strategies to registry without
modifying lookup code.

Epic 22 Architecture Pattern:
- Replaces hardcoded if/elif chains in GlobalStreamManager
- Maps strategy_type -> strategy class
- Supports auto-registration via decorator
"""


from django.contrib.auth.models import AbstractBaseUser

from services.core.logging import get_logger
from services.strategies.base import BaseStrategy

logger = get_logger(__name__)


# Strategy Registry - Maps strategy_type -> strategy class
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(strategy_type: str):
    """
    Decorator to register a strategy in the global registry.

    Args:
        strategy_type: Strategy identifier (e.g., "bull_call_spread")

    Usage:
        @register_strategy("bull_call_spread")
        class BullCallSpreadStrategy(BaseStrategy):
            ...

    The strategy class is automatically registered when the module is imported.
    """

    def decorator(strategy_class: type[BaseStrategy]):
        if strategy_type in STRATEGY_REGISTRY:
            logger.warning(
                f"Strategy '{strategy_type}' already registered, overwriting "
                f"(old: {STRATEGY_REGISTRY[strategy_type].__name__}, "
                f"new: {strategy_class.__name__})"
            )
        STRATEGY_REGISTRY[strategy_type] = strategy_class
        logger.debug(f"Registered strategy: {strategy_type} -> {strategy_class.__name__}")
        return strategy_class

    return decorator


def get_strategy(strategy_type: str, user: AbstractBaseUser) -> BaseStrategy:
    """
    Factory function to instantiate strategy by type.

    Args:
        strategy_type: Strategy identifier (e.g., "bull_call_spread", "bull_put_spread")
        user: User context for strategy

    Returns:
        Instantiated strategy object

    Raises:
        ValueError: If strategy_type not registered

    Example:
        >>> strategy = get_strategy("bull_put_spread", user)
        >>> score, explanation = await strategy.a_score_market_conditions(report)
    """
    strategy_class = STRATEGY_REGISTRY.get(strategy_type)

    if not strategy_class:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys()))
        raise ValueError(
            f"Unknown strategy type: '{strategy_type}'. Available strategies: {available}"
        )

    logger.debug(f"Creating strategy instance: {strategy_type}")

    return strategy_class(user)


def list_registered_strategies() -> list[str]:
    """
    Get list of all registered strategy types.

    Returns:
        Sorted list of strategy type keys
    """
    return sorted(STRATEGY_REGISTRY.keys())


def is_strategy_registered(strategy_type: str) -> bool:
    """
    Check if a strategy type is registered.

    Args:
        strategy_type: Strategy identifier

    Returns:
        True if registered, False otherwise
    """
    return strategy_type in STRATEGY_REGISTRY


def get_all_strategies() -> dict[str, type[BaseStrategy]]:
    """
    Get all registered strategies.

    Returns:
        Dictionary mapping strategy_type -> strategy class

    Example:
        >>> strategies = get_all_strategies()
        >>> for name, cls in strategies.items():
        ...     print(f"{name}: {cls.__name__}")
    """
    return STRATEGY_REGISTRY.copy()
