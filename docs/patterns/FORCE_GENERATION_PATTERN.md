# Force Generation Pattern

## Overview

Force generation allows manual/user-requested strategy generation to bypass score threshold checks while preserving all warnings and explanations. This pattern enables educational use and strategy exploration in any market condition while maintaining safety through prominent warnings.

## When to Use

- Manual strategy selection by user (UI forced mode)
- Educational/learning scenarios
- Strategy comparison tools
- Debugging and validation

## When NOT to Use

- Automated suggestion generation (daily emails, etc.)
- Default/auto mode strategy selection
- Production trading algorithms
- Risk-limited accounts without explicit user acknowledgment

## Implementation Pattern

### Strategy Level

Add `force_generation` parameter to `a_prepare_suggestion_context()`:

```python
async def a_prepare_suggestion_context(
    self,
    symbol: str,
    report: MarketConditionReport | None = None,
    suggestion_mode: bool = False,
    force_generation: bool = False  # Bypass threshold if True
) -> dict | None:
    # ... existing scoring logic ...

    # Check threshold (allow bypass in force mode)
    if score < self.MIN_SCORE_THRESHOLD and not force_generation:
        logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
        return None

    # Log force generation (important for debugging)
    if force_generation and score < self.MIN_SCORE_THRESHOLD:
        logger.warning(
            f"⚠️ Force generating {self.strategy_name} despite low score "
            f"({score:.1f}) - user explicitly requested"
        )

    # Continue with generation...
```

### StrategySelector Level

Pass `force_generation=True` only in `_generate_forced()`:

```python
# In _generate_forced method
context = await strategy.a_prepare_suggestion_context(
    symbol, report,
    suggestion_mode=suggestion_mode,
    force_generation=True  # Bypass thresholds
)
```

### API Level

Forced endpoint uses `forced_strategy` parameter:

```python
# POST /trading/api/suggestions/forced/
# Body: {"symbol": "SPY", "strategy": "call_backspread"}

selected_strategy, suggestion, explanation = await selector.a_select_and_generate(
    symbol, forced_strategy=strategy_name  # Triggers _generate_forced()
)
```

## UI Pattern

Show warnings prominently when strategy generated with low score:

```html
<!-- Yellow warning if generated with low score -->
<div class="alert alert-warning">
  <h6>⚠️ Unfavorable Market Conditions</h6>
  <p>This strategy scored low (35/100) in current conditions.</p>
  <ul>
    <li>Reason 1...</li>
    <li>Reason 2...</li>
  </ul>
  <p><strong>Recommendation:</strong> Wait for better conditions or use alternative strategy.</p>
</div>

<!-- Strategy details shown below warning -->
<div class="strategy-details">
  ...
</div>
```

## Comparison with suggestion_mode

| Feature | suggestion_mode | force_generation |
|---------|----------------|------------------|
| Purpose | Skip risk validation | Bypass score thresholds |
| Use Case | Email suggestions | Manual user requests |
| Warnings | Preserved | Preserved |
| Auto Mode | Can be True | Always False |
| Forced Mode | Can be True | Always True |

## Testing Pattern

```python
@pytest.mark.asyncio
async def test_strategy_force_generation(user):
    strategy = CallBackspreadStrategy(user)

    # Unfavorable market (will score < 35)
    report = create_bearish_market_report()

    # Normal mode: blocked
    context = await strategy.a_prepare_suggestion_context("SPY", report)
    assert context is None

    # Forced mode: generates
    context = await strategy.a_prepare_suggestion_context(
        "SPY", report, force_generation=True
    )
    assert context is not None
    assert context["market_data"]["score"] < 35
```

## Logging Best Practices

```python
# When threshold blocks generation
logger.info(f"Score too low ({score:.1f}) - not generating {strategy_name}")

# When force generation bypasses threshold
logger.warning(
    f"⚠️ Force generating {strategy_name} despite low score ({score:.1f}) - "
    f"user explicitly requested"
)

# In StrategySelector
logger.info(
    f"✅ Force generated {strategy_name}: score={score:.1f} "
    f"(below threshold but user requested)"
)
```

## Architecture

### Threshold Values

- **Default**: 35 (defined in `BaseStrategy.MIN_SCORE_THRESHOLD`)
- **Iron Butterfly**: 40 (more selective due to complexity)
- **Credit Spreads**: 35 (inherited from base class)
- **Debit Spreads**: 35 (inherited from base class)
- **Advanced Volatility**: 35 (hardcoded in individual strategies)

### Strategies Updated (Epic 30)

All 14 strategies now support force generation:

**Credit Spreads (2)**:
- Bull Put Spread
- Bear Call Spread

**Debit Spreads (3)**:
- Bull Call Spread
- Bear Put Spread
- Cash Secured Put

**Advanced Volatility (5)**:
- Call Backspread
- Long Iron Condor
- Long Straddle
- Long Strangle
- Short Iron Condor

**Complex Spreads (3)**:
- Iron Butterfly
- Calendar Spread
- Covered Call

**Special Strategy (1)**:
- Senex Trident (separate system, not affected)

## See Also

- Epic 30: Manual Strategy Generation & UI Improvements
- [SCORING_SYSTEM_ANALYSIS.md](../planning/epics-done/22-strategy-expansion/SCORING_SYSTEM_ANALYSIS.md) (threshold architecture)
- [TASTYTRADE_SDK_BEST_PRACTICES.md](../guides/TASTYTRADE_SDK_BEST_PRACTICES.md) (suggestion_mode pattern)
