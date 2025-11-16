"""
Streaming interface protocols to break circular dependencies.

This module defines Protocol classes that allow services to depend on
abstractions rather than concrete implementations, breaking circular
import dependencies between streaming and services modules.
"""

from typing import Protocol

from trading.models import TradingSuggestion


class StreamerProtocol(Protocol):
    """
    Protocol for streaming services - no concrete import needed.

    This allows strategy services to depend on streaming functionality
    without directly importing streaming modules.
    """

    async def subscribe_symbols(self, symbols: list[str]) -> bool:
        """
        Subscribe to symbols for streaming quotes.

        Args:
            symbols: List of symbols to subscribe to

        Returns:
            True if subscription successful
        """
        ...

    async def get_current_quote(self, symbol: str) -> dict | None:
        """
        Get current quote for symbol.

        Args:
            symbol: Symbol to get quote for

        Returns:
            Quote data dict or None
        """
        ...

    async def ensure_streaming_for_automation(self, symbols: list[str]) -> bool:
        """
        Ensure streaming is active for automated trading.

        Args:
            symbols: List of symbols to ensure streaming for

        Returns:
            True if streaming is active
        """
        ...


class SuggestionGeneratorProtocol(Protocol):
    """
    Protocol for suggestion generation - no concrete import needed.

    This allows streaming services to generate suggestions without
    importing strategy modules at module level.
    """

    async def a_process_suggestion_request(self, context: dict) -> TradingSuggestion | None:
        """
        Process suggestion request and return suggestion.

        Args:
            context: Request context with symbol, strategy, etc.

        Returns:
            TradingSuggestion or None
        """
        ...
