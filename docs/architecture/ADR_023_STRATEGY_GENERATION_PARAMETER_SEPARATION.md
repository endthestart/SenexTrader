# ADR 023: Strategy Generation and Market Analysis Separation

**Status**: Proposed  
**Date**: 2025-11-02  
**Deciders**: Lead Developer, Product Owner  
**Related Epic**: Epic 23 - Strategy Generation & Market Analysis Separation

---

## Context

Strategy generation is currently tightly coupled with market analysis. The `a_prepare_suggestion_context()` method in all strategy classes requires a `MarketConditionReport` and derives all generation parameters (DTE, spread width, OTM percentage, strikes) from market data. This creates several problems:

1. **Force mode doesn't truly force** - Even with `force_generation=True`, the system returns `None` if strikes fail quality gates (5% in normal mode, 15% in force mode)

2. **No manual parameter control** - Users cannot specify custom DTE ranges, spread widths, or OTM percentages independent of market conditions

3. **Poor testability** - Testing strike selection requires mocking the entire market analysis layer

4. **Future-blocked** - Adding UI controls for parameters (sliders for DTE, width, etc.) requires major refactoring

5. **Confusion about algorithms vs strategies**:
   - **Senex Trident** is an algorithm - fixed approach to managing positions
   - **Credit spreads, iron condors, etc.** are strategies - market analysis determines viability, but parameters can be manual

### Example of Current Problem

When a user clicks "Force Generate Bull Put Spread" with poor market conditions:

```
Current: "Cannot Generate: No strikes within 15% deviation threshold"
Expected: Shows suggestion with best available strikes + warning "Quality deviation 22%"
```

---

## Decision

We will **separate strategy generation into five distinct layers**:

### Layer Architecture

```
1. Market Analysis (unchanged)
   └── MarketAnalyzer → MarketConditionReport

2. Strategy Scoring (unchanged)  
   └── Strategy.a_score_market_conditions(report) → (score, explanation)

3. Parameter Selection (NEW - the separation point)
   ├── Auto Mode: ParameterBuilder.from_market_report() → StrategyParameters
   └── Manual Mode: ParameterBuilder.manual() → StrategyParameters

4. Strategy Generation (refactored - no market dependency)
   └── Strategy.a_generate_from_parameters(parameters, mode) → context

5. Streaming/Pricing (unchanged)
   └── StreamManager.a_process_suggestion_request() → TradingSuggestion
```

### Key Design Decisions

#### 1. Introduce `StrategyParameters` Dataclass

Pure parameter object containing all inputs needed for generation:

```python
@dataclass
class StrategyParameters:
    dte_min: int
    dte_max: int
    spread_width: int
    otm_percentage: float
    quality_threshold: float = 0.05
    short_strike: Decimal | None = None  # Manual override
    long_strike: Decimal | None = None   # Manual override
    support_level: Decimal | None = None  # From technical analysis
    resistance_level: Decimal | None = None
```

**Rationale**: Separating parameters from `MarketConditionReport` allows:
- Manual specification independent of market data
- Easy testing with simple parameter objects
- Future UI controls map directly to parameters
- Clear contract between scoring and generation

#### 2. Replace Boolean `force_generation` with `GenerationMode` Enum

```python
class GenerationMode(Enum):
    STRICT = "strict"    # 5% quality gate, return None if fail
    RELAXED = "relaxed"  # 15% quality gate, warn if fail
    FORCE = "force"      # Always pick best, log all deviations
```

**Rationale**: Three-state enum is clearer than overloading boolean:
- `STRICT` = current auto mode behavior
- `RELAXED` = current force mode with quality gates
- `FORCE` = true forcing with fallback to best available

#### 3. Add Fallback Strike Selection

New method `_find_best_available_strikes()` for `FORCE` mode:
- Gets longest expiration in DTE range
- Finds closest strikes to target (no quality gate)
- Logs deviation percentage
- Always returns something unless no strikes exist at all

**Rationale**: Guarantees force mode produces output, solving the core problem.

#### 4. Keep Backward Compatibility

Existing `a_prepare_suggestion_context()` signature stays but becomes a wrapper:

```python
async def a_prepare_suggestion_context(
    self, symbol, report, force_generation=False
):
    # Build parameters from report (old behavior)
    parameters = ParameterBuilder.from_market_report(report, config, strategy_name)
    
    # Convert boolean to mode
    mode = GenerationMode.FORCE if force_generation else GenerationMode.STRICT
    
    # Call new method
    return await self.a_generate_from_parameters(symbol, parameters, mode)
```

**Rationale**: No breaking changes to existing callers. Migration can be gradual.

---

## Consequences

### Positive

1. **Force mode works reliably** - Always generates strategies, shows quality warnings
2. **Manual parameters enabled** - Foundation for UI controls (Phase 5)
3. **Better testability** - Test generation with simple parameter objects
4. **Clearer separation** - Scoring vs generation have distinct responsibilities
5. **Future-ready** - Easy to add DTE sliders, width selectors, strike overrides

### Negative

1. **Migration effort** - Must refactor all 14 strategy classes
2. **Code duplication short-term** - Old and new methods coexist during migration
3. **Learning curve** - Developers must understand new parameter flow
4. **Potential for misuse** - Users might over-rely on force mode with bad conditions

### Mitigation Strategies

1. **Migration effort** → Phase 1 creates reusable base, Phases 2-4 copy pattern
2. **Code duplication** → Keep old methods as thin wrappers, deprecate after 2 releases
3. **Learning curve** → Update `CLAUDE.md`, `AI.md`, provide migration guide
4. **Force mode misuse** → Prominent red warnings in UI, log all forced generations

---

## Alternatives Considered

### Alternative 1: Add More Booleans

Add `force_really_hard=True`, `ignore_quality=True`, etc.

**Rejected**: Boolean explosion, unclear semantics, hard to extend.

### Alternative 2: Config-Only Approach

Store all parameters in `TradingConfig`, no manual override.

**Rejected**: Can't do per-request customization, blocks UI controls.

### Alternative 3: Complete Rewrite

Throw away existing code, redesign from scratch.

**Rejected**: Too risky, breaks working functionality, loses domain knowledge.

### Alternative 4: Keep Current Architecture

Do minimal changes to make force mode work.

**Rejected**: Doesn't solve root coupling problem, blocks future features.

---

## Implementation Strategy

### Phase 1: Foundation (2-3 days)
- Create `parameters.py` with dataclasses
- Update `expiration_utils.py` with `GenerationMode`
- Write unit tests for parameter system
- **Deliverable**: New system, 100% backward compatible

### Phase 2: Credit Spreads (3-5 days)
- Add `a_generate_from_parameters()` to base class
- Add `_find_best_available_strikes()` fallback
- Update bull put and bear call spreads
- Update tests
- **Deliverable**: Credit spreads use new architecture

### Phase 3: Strategy Selector (2-3 days)
- Update `_generate_forced()` to use new flow
- Add quality warning builders
- Update UI to show warnings
- **Deliverable**: Force mode always generates

### Phase 4: Remaining Strategies (5-7 days)
- Migrate debit spreads, iron condors, volatility strategies
- Migrate advanced strategies
- Full test suite
- **Deliverable**: All strategies migrated

### Phase 5: Manual UI (Future Epic)
- DTE range sliders
- Spread width selector
- OTM percentage slider
- Advanced controls
- **Deliverable**: User-controllable parameters

**Total Estimated Effort**: 12-18 days (Phases 1-4)

---

## Validation

### Success Metrics

1. **Force mode success rate**: 100% (never returns "Cannot Generate")
2. **Quality warnings shown**: 100% when deviation >5%
3. **Test coverage**: >90% for new parameter code
4. **Performance**: Generation time ±5% of baseline
5. **Backward compatibility**: 0 breaking changes in Phases 1-4

### Testing Approach

1. **Unit tests**: Parameter validation, mode behavior, fallback logic
2. **Integration tests**: End-to-end forced generation with poor conditions
3. **Regression tests**: Auto mode behavior unchanged
4. **Manual tests**: Force generation in extreme market conditions

### Rollback Plan

If critical issues found:
1. Feature flag to disable new parameter system
2. Old `a_prepare_suggestion_context()` code still intact
3. Revert wrapper, use original implementation
4. No data migration needed (parameters not stored yet)

---

## Related Documents

- **Epic**: `senextrader_docs/planning/EPIC_STRATEGY_GENERATION_SEPARATION.md`
- **Analysis**: `/tmp/architecture_analysis.md` (detailed coupling research)
- **Current Code**: 
  - `services/strategy_selector.py:285` - `_generate_forced()`
  - `services/strategies/credit_spread_base.py:306` - `a_prepare_suggestion_context()`
  - `services/utils/expiration_utils.py:178` - `find_expiration_with_optimal_strikes()`

---

## Notes

### Algorithm vs Strategy Distinction

**Senex Trident** = Algorithm
- Lives at `/trading/senex-trident/`
- Fixed approach to position management
- Market analysis determines HOW to manage positions
- Automated trading service

**Credit Spreads, Iron Condors, etc.** = Strategies
- Live at `/trading/`
- Market analysis determines IF viable (scoring)
- User/automation decides WHEN to deploy
- Can have manual parameter overrides

This ADR focuses on **strategies**. Senex Trident may benefit from similar separation in future, but that's a separate decision.

### Quality Gate Philosophy

Current quality gates (5% deviation) are based on TastyTrade methodology - they prevent executing strategies with strikes too far from optimal. However, forcing users to never see imperfect suggestions is a product decision, not a technical limitation.

New approach:
- **Automated trading**: Use STRICT mode, respect quality gates
- **User-requested suggestions**: Use RELAXED/FORCE, show warnings
- **Manual trading**: User decides if warnings are acceptable

---

## Decision Record

**Date**: 2025-11-02  
**Decision**: Approved for implementation pending review  
**Revisit Date**: After Phase 2 completion  
**Supersedes**: None  
**Superseded By**: TBD

---

*ADR Last Updated: 2025-11-02*
