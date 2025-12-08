"""
Tests to validate no circular dependencies exist in the codebase.

Phase 1 of the refactoring plan breaks circular dependencies between
streaming and services modules using runtime imports and dependency injection.
"""

import pytest


def test_no_circular_imports_services():
    """Verify services modules can be imported without circular dependency."""
    # If any of these imports fail with circular import error, test fails
    import services.brokers.tastytrade  # noqa: F401
    import services.core.data_access  # noqa: F401
    import services.market_data.service  # noqa: F401
    import services.strategies.selector  # noqa: F401

    assert True, "All service modules imported successfully"


def test_no_circular_imports_streaming():
    """Verify streaming modules can be imported without circular dependency."""
    # If any of these imports fail with circular import error, test fails
    import streaming.consumers
    import streaming.services.stream_manager  # noqa: F401

    assert True, "Streaming modules imported successfully"


def test_no_circular_imports_cross_module():
    """Verify cross-module imports work without circular dependency."""
    # Import both streaming and services together
    import services.strategies.selector  # noqa: F401
    import streaming.services.stream_manager  # noqa: F401

    assert True, "Cross-module imports work without circular dependency"


def test_streaming_interface_protocol_exists():
    """Verify StreamerProtocol interface is available."""
    from services.interfaces.streaming_interface import StreamerProtocol

    # Verify protocol has required methods
    assert hasattr(StreamerProtocol, "subscribe_symbols")
    assert hasattr(StreamerProtocol, "get_current_quote")
    assert hasattr(StreamerProtocol, "ensure_streaming_for_automation")


def test_suggestion_generator_protocol_exists():
    """Verify SuggestionGeneratorProtocol interface is available."""
    from services.interfaces.streaming_interface import SuggestionGeneratorProtocol

    # Verify protocol has required methods
    assert hasattr(SuggestionGeneratorProtocol, "a_process_suggestion_request")


@pytest.mark.asyncio
async def test_strategy_selector_dependency_injection():
    """Test that StrategySelector accepts dependency injection."""
    from unittest.mock import AsyncMock, MagicMock

    from services.interfaces.streaming_interface import StreamerProtocol
    from services.strategies.selector import StrategySelector

    # Create mock user
    mock_user = MagicMock()
    mock_user.id = 1

    # Create mock streamer that conforms to Protocol
    mock_streamer = AsyncMock(spec=StreamerProtocol)
    mock_streamer.subscribe_symbols.return_value = True

    # Test that we can inject the streamer
    selector = StrategySelector(mock_user, streamer=mock_streamer)

    assert selector._streamer is mock_streamer
    assert selector.streamer is mock_streamer


def test_strategy_selector_lazy_loading():
    """Test that StrategySelector can work without injected streamer."""
    from unittest.mock import MagicMock

    from services.strategies.selector import StrategySelector

    # Create mock user
    mock_user = MagicMock()
    mock_user.id = 1

    # Test that we can create selector without streamer
    selector = StrategySelector(mock_user)

    assert selector._streamer is None
    # Accessing streamer property should not raise error
    # (it will return None since we can't async load in property)
    assert selector.streamer is None
