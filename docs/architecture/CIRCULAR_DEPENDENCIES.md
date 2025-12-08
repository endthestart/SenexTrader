# Circular Dependencies Documentation

**Project**: Senex Trader
**Last Updated**: 2025-10-08
**Status**: Active Management

## Overview

This document catalogs all circular import dependencies in the Senex Trader codebase, explains current mitigation strategies, and provides guidelines for preventing new circular dependencies.

Circular dependencies occur when two or more modules import each other, creating an import cycle that can cause:
- Import errors at runtime
- Difficulty testing modules in isolation
- Tight coupling between modules
- Maintenance challenges

## Identified Circular Dependencies

### 1. services ↔ streaming (HIGH RISK)

**Impact**: High - Core business logic coupled with streaming infrastructure
**Mitigation**: Protocol-based abstractions + runtime imports
**Status**: Actively managed

#### Import Pattern

**services → streaming**:
- `services/strategy_selector.py` imports `streaming.services.stream_manager.GlobalStreamManager` (runtime import in methods)
- Used for suggestion generation and stream management coordination

**streaming → services**:
- `streaming/views.py` imports `services.utils.async_utils.async_get_user_id`
- `streaming/consumers.py` imports `services.logging_config.get_logger`
- `streaming/apps.py` imports `services.logging_config.get_logger`
- `streaming/tasks.py` imports `services.logging_config.get_logger`
- `streaming/services/stream_manager.py` imports `services.cache_management.CacheManager`
- `streaming/services/stream_manager.py` imports `services.logging_config.get_logger`
- `streaming/services/stream_manager.py` imports `services.utils.sdk_instruments.parse_occ_symbol`
- `streaming/services/enhanced_cache.py` imports `services.cache_config.CacheTTL`
- `streaming/services/auth_service.py` imports `services.logging_config.get_logger`

#### Current Mitigation Strategy

1. **Protocol-Based Abstractions** (`services/interfaces/streaming_interface.py`):
   - `StreamerProtocol` - Defines interface for streaming services
   - `SuggestionGeneratorProtocol` - Defines interface for suggestion generation
   - Allows services to depend on abstractions instead of concrete implementations

2. **Runtime Imports**:
   - `strategy_selector.py` imports `GlobalStreamManager` inside methods (lines 209, 330)
   - Avoids module-level circular import
   - Example:
     ```python
     async def _generate_auto(self, symbol: str, report: MarketConditionReport):
         # Import at runtime - breaks circular dependency
         from streaming.services.stream_manager import GlobalStreamManager
         stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
     ```

3. **Lazy Property Pattern**:
   - `StrategySelector.streamer` property (lines 68-90)
   - **Investigation Finding**: Returns `None` as placeholder
   - **Status**: DEAD CODE - Property never used, import commented out
   - **Recommendation**: Remove this property entirely (see Investigation #2)

#### Risks

- Runtime imports can fail silently if not properly tested
- Protocol violations only caught at runtime, not by type checkers
- Testing requires careful mocking of cross-module dependencies

#### Future Refactoring Options

1. **Extract Suggestion Generation Service**:
   - Create `suggestion_generation` module independent of both services and streaming
   - Both modules depend on this new module (dependency inversion)
   - Eliminates circular dependency entirely

2. **Event-Based Communication**:
   - Use Django signals or message queue
   - Completely decouple services and streaming
   - More complex infrastructure but cleanest separation

---

### 2. services ↔ trading (HIGH RISK)

**Impact**: High - Core business logic coupled with Django app
**Mitigation**: TYPE_CHECKING pattern
**Status**: Actively managed

#### Import Pattern

**services → trading**:
- `services/senex_trident_strategy.py` imports `trading.models.StrategyConfiguration, TradingSuggestion`
- `services/position_sync.py` imports `trading.models.Position`
- `services/order_history_service.py` imports `trading.models.TastyTradeOrderHistory, CachedOrderChain, Position`
- `services/order_cancellation_service.py` imports `trading.models.Trade`
- `services/option_chain_service.py` imports `trading.models.Position`
- `services/strategies/base.py` imports `trading.models.Position`
- `services/interfaces/streaming_interface.py` imports `trading.models.TradingSuggestion`
- `services/position_lifecycle/profit_calculator.py` imports `trading.models.Position, Trade`
- `services/position_lifecycle/dte_manager.py` imports `trading.models.Position, Trade`
- `services/execution/order_service.py` imports `trading.models.Position, Trade, TradingSuggestion`

**trading → services**:
- `trading/views_strategy.py` imports `services.senex_trident_strategy.SenexTridentStrategy`
- `trading/views.py` imports `services.cache_management.CacheManager`
- `trading/views.py` imports `services.risk_manager.EnhancedRiskManager`
- `trading/tasks.py` imports `services.execution.order_service.OrderExecutionService`
- `trading/tasks.py` imports `services.position_lifecycle.dte_manager.DTEManager`
- `trading/api_views.py` imports `services.risk_manager.EnhancedRiskManager`
- `trading/api_views.py` imports `services.risk_validation.RiskValidationService`
- `trading/services/automated_trading_service.py` imports `services.execution.order_service.OrderExecutionService`
- Multiple other utility imports

#### Current Mitigation Strategy

1. **TYPE_CHECKING Pattern**:
   - Several modules use `if TYPE_CHECKING:` to import types without runtime dependency
   - Files using this pattern:
     - `services/strategy_selector.py`
     - `services/risk_manager.py`
     - `services/greeks_service.py`
     - `services/market_condition_validator.py`
   - Example:
     ```python
     from typing import TYPE_CHECKING

     if TYPE_CHECKING:
         from django.contrib.auth.models import AbstractBaseUser
         from trading.models import TradingSuggestion
     ```

2. **Direct Model Imports**:
   - Many services import `trading.models` directly at module level
   - Works because Django models can be imported before app initialization
   - Risk: Depends on Django's import system magic

#### Risks

- Services module becoming tightly coupled to Django app structure
- Difficult to reuse services in non-Django contexts
- Type hints less effective without runtime imports
- Changes to trading models ripple through services

#### Future Refactoring Options

1. **Extract Models to Shared Module**:
   - Create `core/models.py` with domain models
   - Both services and trading depend on core
   - Requires significant refactoring

2. **Use Django's Proxy Pattern**:
   - Create abstract base models in services
   - Trading models inherit from these bases
   - Maintains Django functionality while improving separation

---

### 3. services ↔ accounts (MEDIUM RISK)

**Impact**: Medium - Limited to specific services
**Mitigation**: Direct imports (Django models)
**Status**: Monitored

#### Import Pattern

**services → accounts**:
- `services/risk_manager.py` imports `accounts.models.OptionsAllocation`
- `services/position_sync.py` imports `accounts.models.TradingAccount`
- `services/order_history_service.py` imports `accounts.models.TradingAccount`
- `services/option_chain_service.py` imports `accounts.models.TradingAccount`
- `services/execution/order_service.py` imports `accounts.models.TradingAccount`

**accounts → services**:
- `accounts/settings_views.py` imports `services.account_state.AccountStateService`
- `accounts/settings_views.py` imports `services.risk_manager.EnhancedRiskManager`
- `accounts/api_views.py` imports `services.account_state.AccountStateService`
- `accounts/views_oauth.py` imports `services.brokers.tastytrade.TastyTradeOAuthClient`
- `accounts/views_oauth.py` imports `services.brokers.tastytrade_session.TastyTradeSessionService`
- `accounts/models.py` imports `services.exceptions.MissingSecretError, TokenExpiredError`

#### Current Mitigation Strategy

1. **Django Model Import Safety**:
   - Django models can be imported at module level safely
   - Apps framework handles initialization order
   - No special mitigation needed currently

2. **Service Layer Pattern**:
   - Views import services, services import models
   - Natural layering reduces risk

#### Risks

- Lower risk due to Django's app framework
- Models are data structures with minimal logic
- Services act as facade layer

#### Monitoring Guidelines

- Keep accounts models as data-only (no business logic)
- Services should not depend on accounts views
- If accounts logic grows complex, consider extracting to services

---

### 4. streaming ↔ trading (MEDIUM RISK)

**Impact**: Medium - WebSocket coordination with trading logic
**Mitigation**: Runtime imports
**Status**: Monitored

#### Import Pattern

**streaming → trading**:
- No direct module-level imports identified
- May have runtime imports in consumers/views

**trading → streaming**:
- `trading/views.py` imports `streaming.services.stream_manager.GlobalStreamManager`
- `trading/services/automated_trading_service.py` imports `streaming.services.stream_manager.GlobalStreamManager`

#### Current Mitigation Strategy

1. **One-Directional Dependency**:
   - Trading depends on streaming, not vice versa
   - Reduces circular dependency risk
   - Streaming broadcasts events, trading consumes them

2. **Event-Driven Architecture**:
   - WebSocket messages act as event bus
   - Loose coupling through message protocol

#### Risks

- Low risk due to one-directional flow
- Event-driven pattern naturally decouples modules

#### Best Practices

- Keep streaming focused on WebSocket management
- Trading should consume streaming events, not control streaming logic
- Use Protocol interfaces if streaming needs to call trading

---

### 5. accounts ↔ streaming (MEDIUM RISK)

**Impact**: Medium - OAuth reconnection coordination
**Mitigation**: Runtime imports
**Status**: Monitored

#### Import Pattern

**streaming → accounts**:
- No direct module-level imports identified

**accounts → streaming**:
- `accounts/views_oauth.py` imports `streaming.services.stream_manager.GlobalStreamManager`
- Used for reinitializing streaming after OAuth reconnection

#### Current Mitigation Strategy

1. **One-Directional Dependency**:
   - Accounts depends on streaming for reinitialization
   - Streaming doesn't need to know about accounts
   - Clean separation of concerns

2. **Post-OAuth Hook Pattern**:
   - After successful OAuth, accounts triggers stream reinitialization
   - Streaming handles its own state management

#### Risks

- Low risk due to one-directional flow
- OAuth is infrequent operation (not hot path)

#### Best Practices

- Keep OAuth logic in accounts
- Streaming should expose reinitialization API
- Avoid streaming knowing about OAuth state

---

## Mitigation Techniques Reference

### 1. TYPE_CHECKING Pattern

**Use When**: Type hints needed but runtime import causes circular dependency

**Example**:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.models import TradingSuggestion

def process_suggestion(suggestion: 'TradingSuggestion') -> None:
    # String annotation works without runtime import
    pass
```

**Pros**:
- Clean type hints for IDE/mypy
- No runtime import
- Standard Python typing pattern

**Cons**:
- Requires string annotations in Python <3.10
- Can't use type for isinstance checks
- Type checkers may miss some issues

### 2. Runtime (Lazy) Imports

**Use When**: Need actual class/function at runtime, but only in specific methods

**Example**:
```python
async def generate_suggestion(self):
    # Import inside method
    from streaming.services.stream_manager import GlobalStreamManager

    manager = await GlobalStreamManager.get_user_manager(self.user.id)
    return await manager.process_request(...)
```

**Pros**:
- Breaks module-level circular dependency
- Full access to imported class/function
- Can use isinstance, attributes, etc.

**Cons**:
- Slight performance overhead (import on each call)
- Less obvious what module depends on what
- Import errors only caught at runtime
- Makes testing harder (need to mock in right place)

### 3. Protocol-Based Abstractions

**Use When**: Need interface without concrete implementation dependency

**Example**:
```python
from typing import Protocol

class StreamerProtocol(Protocol):
    async def subscribe_symbols(self, symbols: list[str]) -> bool: ...

class StrategySelector:
    def __init__(self, streamer: StreamerProtocol):
        self.streamer = streamer  # Any object matching protocol works
```

**Pros**:
- Cleanest separation of concerns
- Easy to test (implement fake protocol)
- Type-safe with structural subtyping
- Follows SOLID principles

**Cons**:
- Requires careful protocol design
- More boilerplate code
- Runtime violations only caught in tests

### 4. Dependency Injection

**Use When**: Module needs other module's functionality but shouldn't import it

**Example**:
```python
class StrategySelector:
    def __init__(self, user: User, streamer: StreamerProtocol | None = None):
        self.user = user
        self._streamer = streamer  # Injected dependency
```

**Pros**:
- Extremely testable
- Clear dependencies
- Follows dependency inversion principle
- Easy to swap implementations

**Cons**:
- Requires coordination at call site
- More verbose initialization
- Need to pass dependencies through layers

### 5. Event-Based Communication

**Use When**: Modules need to react to each other's actions without tight coupling

**Example**:
```python
from django.dispatch import Signal

suggestion_generated = Signal()

# In services:
suggestion_generated.send(sender=self, suggestion=suggestion)

# In streaming:
@receiver(suggestion_generated)
def handle_suggestion(sender, suggestion, **kwargs):
    # React to suggestion
```

**Pros**:
- Complete decoupling
- Many-to-many relationships supported
- Easy to add new reactions
- Standard Django pattern

**Cons**:
- Harder to trace flow
- Debugging more complex
- Signal names must be managed
- Performance overhead

---

## Development Guidelines

### Preventing New Circular Dependencies

1. **Check Before Importing**:
   ```bash
   # Before adding import from module B to module A, check:
   grep -r "^from services" module_b/
   ```

2. **Layer Architecture**:
   ```
   Views (accounts, trading)
       ↓
   Services (services/)
       ↓
   Models (*.models)
       ↓
   Utils (services/utils)
   ```
   - Upper layers can import lower layers
   - Lower layers should NOT import upper layers

3. **Use Dependency Injection**:
   ```python
   # Bad
   def my_function():
       from other_module import OtherClass
       return OtherClass()

   # Good
   def my_function(other_instance: OtherClassProtocol):
       return other_instance.do_something()
   ```

4. **Prefer Protocols Over Concrete Classes**:
   ```python
   # Bad
   from streaming.services.stream_manager import GlobalStreamManager

   def process(manager: GlobalStreamManager): ...

   # Good
   from services.interfaces.streaming_interface import StreamerProtocol

   def process(manager: StreamerProtocol): ...
   ```

### When Adding New Imports

**Checklist**:
- [ ] Does this create a new circular dependency?
- [ ] Can I use TYPE_CHECKING instead?
- [ ] Can I use a Protocol?
- [ ] Can I inject this dependency?
- [ ] Can I move this import to method level?
- [ ] Is this import necessary at all?

### Testing Circular Dependencies

**Manual Check**:
```bash
# Test if modules can be imported independently
python -c "import services.strategy_selector"
python -c "import streaming.services.stream_manager"
```

**Automated Check** (add to CI):
```python
import importlib
import sys

def test_no_circular_imports():
    """Test that key modules can be imported independently."""
    modules = [
        'services.strategy_selector',
        'streaming.services.stream_manager',
        'trading.views',
        'accounts.views',
    ]

    for module_name in modules:
        # Clear previous imports
        for key in list(sys.modules.keys()):
            if key.startswith(module_name.split('.')[0]):
                del sys.modules[key]

        # Try importing fresh
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            pytest.fail(f"Circular import detected in {module_name}: {e}")
```

---

## Investigation Findings

### Investigation: Unused `trading.css` File

**File**: `/path/to/senextrader/static/css/trading.css`

**Findings**:
1. **File exists** with 344 lines of comprehensive trading interface styles
2. **No references found** in any template file
3. **Not linked** in `templates/trading/trading.html`
4. **Not linked** in `templates/base/base.html`

**File Contents Analysis**:
- Connection status indicators
- Status badges
- Trade table enhancements
- Action buttons
- Progress indicators
- Option legs table styling
- Risk/reward displays
- Alert enhancements
- Toast notifications
- Modal styling
- Animation classes (pulse, slideIn)
- Responsive design breakpoints
- P&L color coding
- Loading states
- Market data displays
- Execution timeline UI

**Current Template CSS Usage**:
- `templates/base/base.html` includes:
  - Bootstrap 5.3.2 CSS (CDN)
  - Bootstrap Icons (CDN)
  - `static/css/dark-theme.css` (custom)
- `templates/trading/trading.html`:
  - Uses Bootstrap classes throughout
  - No custom CSS file reference

**Recommendation**: **DELETE `static/css/trading.css`**

**Rationale**:
1. All trading page styling is handled by Bootstrap classes and `dark-theme.css`
2. No template references this file
3. File appears to be from Phase 6 planning (header comment) but was never integrated
4. Keeping unused CSS increases maintenance burden
5. If specific styles are needed later, can extract relevant pieces from this file

**Action Items**:
- [ ] Delete `/path/to/senextrader/static/css/trading.css`
- [ ] Verify trading page still displays correctly
- [ ] If any styles are needed, add them to `dark-theme.css` instead

---

### Investigation: Dead Code in `strategy_selector.py`

**File**: `/path/to/senextrader/services/strategy_selector.py`
**Lines**: 68-90
**Property**: `StrategySelector.streamer`

**Code Analysis**:
```python
@property
def streamer(self) -> StreamerProtocol | None:
    """
    Lazy-load streamer only when needed.

    This property uses runtime import to break circular dependency
    between services and streaming modules.

    Returns:
        StreamerProtocol instance or None
    """
    if self._streamer is None:
        # Import at runtime - breaks circular dependency
        try:
            from streaming.services.stream_manager import GlobalStreamManager

            # Get user manager asynchronously when needed
            # Caller must await this in async context
            return None  # Placeholder - actual usage would be async
        except ImportError:
            logger.warning("Could not import GlobalStreamManager")
            return None
    return self._streamer
```

**Findings**:

1. **Property never used** - No calls to `StrategySelector.streamer` in codebase:
   ```bash
   $ grep -r "StrategySelector.streamer" .
   # No results

   $ grep -r "\.streamer" services/
   # Only found in streaming_utils.py (different class)
   ```

2. **Incomplete implementation** - Always returns `None`:
   - Comment says "Placeholder - actual usage would be async"
   - Import happens but result discarded
   - Cannot actually use GlobalStreamManager even if imported

3. **Has alternative solution** - `_streamer` is injected via constructor:
   ```python
   def __init__(self, user: AbstractBaseUser, streamer: StreamerProtocol | None = None):
       self._streamer = streamer  # Injected dependency
   ```

4. **Runtime imports used elsewhere** - Strategy selector imports `GlobalStreamManager` inside methods (lines 209, 330):
   ```python
   # In _generate_auto() and _generate_forced()
   from streaming.services.stream_manager import GlobalStreamManager
   stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
   ```

**Git History Analysis**:
- Code added as part of circular dependency mitigation
- Intended as lazy-load pattern for optional streamer access
- Never completed or activated
- Superseded by direct runtime imports in generation methods

**Recommendation**: **DELETE the `streamer` property (lines 68-90)**

**Rationale**:
1. Dead code - never called, never will work
2. Confusing to maintainers (suggests functionality that doesn't exist)
3. Alternative solutions already in place:
   - Constructor injection for explicit streamer dependency
   - Runtime imports in generation methods for actual usage
4. No tests for this property
5. Documentation misleading (suggests async usage but sync property)

**Action Items**:
- [ ] Delete `streamer` property (lines 68-90) from `strategy_selector.py`
- [ ] Keep `self._streamer` field (used for dependency injection)
- [ ] Keep runtime imports in `_generate_auto()` and `_generate_forced()` methods
- [ ] Update any docstrings referencing this property (if any)
- [ ] Verify tests pass after removal

**Updated Class Structure**:
```python
class StrategySelector:
    def __init__(self, user: AbstractBaseUser, streamer: StreamerProtocol | None = None):
        self.user = user
        self.validator = MarketConditionValidator(user)
        self._streamer = streamer  # Keep for dependency injection
        # ... rest of init

    # Remove streamer property

    async def _generate_auto(self, symbol: str, report: MarketConditionReport):
        # Keep runtime import here
        from streaming.services.stream_manager import GlobalStreamManager
        stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
        # ...
```

---

## Summary

### Current State
- **5 circular dependency patterns** identified and documented
- **3 mitigation techniques** actively used (TYPE_CHECKING, runtime imports, protocols)
- **2 investigations** completed with recommendations

### Recommendations Priority

**HIGH PRIORITY**:
1. Delete `static/css/trading.css` (unused file)
2. Remove `StrategySelector.streamer` property (dead code)
3. Add circular dependency checks to CI/CD pipeline

**MEDIUM PRIORITY**:
4. Document protocol usage patterns in developer guide
5. Create examples of proper dependency injection
6. Audit all runtime imports for necessity

**LOW PRIORITY**:
7. Consider extracting suggestion generation to separate module
8. Evaluate event-based architecture for services ↔ streaming

### Maintenance
- Review this document quarterly
- Update when new patterns emerge
- Add examples from actual refactorings
- Track metrics: number of circular dependencies, mitigation techniques used

---

**Document Prepared By**: Claude (AI Assistant)
**Review Status**: Pending team review
**Next Review Date**: 2026-01-08
