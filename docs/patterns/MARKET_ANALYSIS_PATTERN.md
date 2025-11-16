# Market Analysis Pattern (Epic 32)

**Pattern:** Context-Aware Market Analysis
**Component:** `services/market_analysis.py`
**Status:** Production (Epic 32 complete)

---

## Overview

The Market Analysis pattern provides unified market regime, extreme, and momentum detection for strategy scoring. It consolidates fragmented analysis logic into a single `MarketAnalyzer` service that produces standardized `MarketConditionReport` objects with context-aware fields.

**Key Principle:** The analyzer returns **data**, not decisions. Strategies score this data to determine appropriateness.

---

## Architecture

### Components

```
MarketAnalyzer
    ↓ analyzes market
MarketConditionReport (data container)
    ↓ consumed by
Strategy._score_market_conditions_impl()
    ↓ produces
(score, reasons)
```

### Data Flow

1. **MarketAnalyzer** collects raw data (prices, indicators, IV metrics)
2. **MarketConditionReport.__post_init__()** runs detection logic
   - `_detect_regime()` → regime classification
   - `_detect_extremes()` → overbought/oversold warnings
   - `_detect_momentum()` → continuation vs exhaustion
3. **Strategies** consume report and score conditions
4. **StrategySelector** picks highest-scoring strategy

---

## Context-Aware Fields (Epic 32)

### 1. Regime Detection

**Fields:**
- `regime_primary: RegimeType | None` — Primary market regime
- `regime_confidence: float` — Confidence score (0-100)

**Regime Types:**
```python
class RegimeType(str, Enum):
    BULL = "bull"           # Strong uptrend (MACD bullish + strong ADX)
    BEAR = "bear"           # Strong downtrend (MACD bearish + strong ADX)
    RANGE = "range"         # Range-bound (low ADX, price oscillating)
    HIGH_VOL = "high_vol"   # High IV rank (>75) without crisis
    CRISIS = "crisis"       # Market stress level >= 80
```

**Detection Logic:**
1. Crisis: `market_stress_level >= 80` → `CRISIS`
2. High IV: `iv_rank >= 75` → `HIGH_VOL`
3. Range: `is_range_bound == True` → `RANGE`
4. Trend: `trend_strength == "strong"` + MACD → `BULL` or `BEAR`

**Example Usage:**
```python
if report.regime_primary == RegimeType.CRISIS:
    # Crisis: avoid all trades
    score_adjustment -= 50
    reasons.append("Market crisis - avoid trading")
elif report.regime_primary == RegimeType.BULL:
    # Bullish regime: favor bullish strategies
    score_adjustment += 30
    reasons.append(f"Bull regime (confidence {report.regime_confidence:.0f}%)")
```

**Benefits:**
- Replaces verbose MACD trend checks (20+ lines → 5 lines)
- Self-documenting (`RegimeType.CRISIS` vs `market_stress_level >= 80`)
- Crisis detection prevents dangerous trades

---

### 2. Extreme Detection

**Fields:**
- `is_overbought: bool` — 3+ overbought warnings
- `overbought_warnings: int` — Count of overbought indicators
- `is_oversold: bool` — 3+ oversold warnings
- `oversold_warnings: int` — Count of oversold indicators

**Warning Sources:**
- RSI > 70 (+1 warning), RSI > 80 (+2 warnings)
- Bollinger position above/below bands (+1 warning)
- Price extension > 5% from SMA (+1 warning)

**Detection Logic:**
```python
def _detect_extremes(self) -> None:
    overbought_count = 0

    # RSI signals
    if self.rsi > 70:
        overbought_count += 1
    if self.rsi > 80:
        overbought_count += 1  # Extra warning

    # Bollinger position
    if self.bollinger_position == "above_upper":
        overbought_count += 1

    # SMA extension
    if ((self.current_price - self.sma_20) / self.sma_20) > 0.05:
        overbought_count += 1

    self.overbought_warnings = overbought_count
    self.is_overbought = overbought_count >= 3
```

**Example Usage:**
```python
if report.is_overbought and report.momentum_signal == MomentumSignal.EXHAUSTION:
    # Overbought + exhaustion = potential reversal down
    score_adjustment -= 25
    reasons.append(
        f"Overbought exhausted ({report.overbought_warnings} warnings) - reversal risk"
    )
elif report.is_oversold and report.momentum_signal == MomentumSignal.EXHAUSTION:
    # Oversold + exhaustion = potential bounce up
    score_adjustment += 20
    reasons.append(
        f"Oversold exhausted ({report.oversold_warnings} warnings) - bounce opportunity"
    )
```

**Benefits:**
- Multi-indicator aggregation (reduces false positives)
- Transparent warning counts (debuggable)
- Prevents counter-trend entries at extremes

---

### 3. Momentum Assessment

**Fields:**
- `momentum_signal: MomentumSignal` — Momentum classification
- `momentum_confidence: float` — Confidence score (0-100)

**Momentum Types:**
```python
class MomentumSignal(str, Enum):
    CONTINUATION = "continuation"  # Strong trend, room to run
    EXHAUSTION = "exhaustion"      # Extreme conditions, reversal likely
    UNCLEAR = "unclear"            # Mixed signals or weak trend
```

**Detection Logic:**
```python
def _detect_momentum(self) -> None:
    # Exhaustion: strong trend + extreme conditions
    if (self.is_overbought or self.is_oversold) and self.trend_strength == "strong":
        self.momentum_signal = MomentumSignal.EXHAUSTION
        confidence = 50.0 + (min(warnings, 5) * 10)
        self.momentum_confidence = min(confidence, 100.0)
        return

    # Continuation: strong trend, NOT extreme
    if self.trend_strength == "strong" and not self.is_overbought and not self.is_oversold:
        self.momentum_signal = MomentumSignal.CONTINUATION
        self.momentum_confidence = 60.0 + (20.0 if self.adx > 40 else 0)
        return

    # Unclear
    self.momentum_signal = MomentumSignal.UNCLEAR
    self.momentum_confidence = 0.0
```

**Example Usage:**
```python
if report.momentum_signal == MomentumSignal.CONTINUATION:
    if report.regime_primary == RegimeType.BULL:
        # Bullish continuation: favorable for bull strategies
        score_adjustment += 15
        reasons.append("Bullish momentum continuing")
    elif report.regime_primary == RegimeType.BEAR:
        # Bearish continuation: avoid bull strategies
        score_adjustment -= 15
        reasons.append("Bearish momentum continuing - avoid")
```

**Benefits:**
- Combines trend + extreme detection
- Identifies late-cycle exhaustion
- Prevents chasing extended trends

---

## Strategy Scoring Pattern

### Template

```python
class MyStrategy(BaseStrategy):
    async def _score_market_conditions_impl(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score market conditions using Epic 32 context fields.

        Returns:
            (score_adjustment, reasons)
        """
        score_adjustment = 0.0
        reasons = []

        # 1. Regime-aware scoring
        if report.regime_primary == RegimeType.BULL:
            # Favorable for bullish strategies
            score_adjustment += 30
            reasons.append(f"Bull regime (confidence {report.regime_confidence:.0f}%)")
        elif report.regime_primary == RegimeType.CRISIS:
            # Avoid all strategies in crisis
            score_adjustment -= 50
            reasons.append("Market crisis - avoid trading")

        # 2. Extreme detection
        if report.is_overbought and report.momentum_signal == MomentumSignal.EXHAUSTION:
            # Overbought exhaustion: potential reversal
            score_adjustment -= 25
            reasons.append(f"Overbought exhausted - reversal risk")

        # 3. Momentum confirmation
        if report.momentum_signal == MomentumSignal.CONTINUATION:
            if report.regime_primary == RegimeType.BULL:
                score_adjustment += 15
                reasons.append("Bullish momentum continuing")

        # 4. Traditional indicators (still useful)
        if report.hv_iv_ratio < 0.8:
            score_adjustment += 15
            reasons.append("High IV - good premium conditions")

        return (score_adjustment, reasons)
```

### Reference Implementations

**Bear Call Spread** (bearish/neutral strategy)
- Favors: `BEAR` regime, overbought exhaustion, elevated stress
- Avoids: `BULL` regime, oversold exhaustion
- See: `services/bear_call_spread_strategy.py:52-177`

**Bull Put Spread** (bullish/neutral strategy)
- Favors: `BULL` regime, oversold exhaustion, low stress
- Avoids: `BEAR` regime, overbought exhaustion, crisis
- See: `services/bull_put_spread_strategy.py:52-171`

---

## Common Patterns

### 1. Crisis Avoidance
```python
# ALL strategies should heavily penalize CRISIS
if report.regime_primary == RegimeType.CRISIS:
    score_adjustment -= 50
    reasons.append("Market crisis - avoid trading")
```

### 2. Directional Confirmation
```python
# Confirm regime matches strategy bias
if report.regime_primary == RegimeType.BULL:
    if self.is_bullish_strategy:
        score_adjustment += 30
    else:
        score_adjustment -= 30
```

### 3. Reversal Opportunities
```python
# Exhaustion signals reversal opportunities
if report.is_overbought and report.momentum_signal == MomentumSignal.EXHAUSTION:
    if self.is_bearish_strategy:
        score_adjustment += 20  # Reversal down opportunity
```

### 4. Trend Continuation
```python
# Continuation signals confirm trend following
if report.momentum_signal == MomentumSignal.CONTINUATION:
    if report.regime_primary matches self.bias:
        score_adjustment += 15  # Trend following opportunity
```

---

## Testing Pattern

### Unit Tests
```python
@pytest.mark.asyncio
async def test_crisis_detection():
    """Verify CRISIS regime detection."""
    report = MarketConditionReport(
        symbol="SPY",
        current_price=220.0,
        market_stress_level=95.0,  # Crisis level
        iv_rank=98.0,
        # ... other fields
    )

    assert report.regime_primary == RegimeType.CRISIS
    assert report.regime_confidence >= 80
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_strategy_crisis_avoidance():
    """Verify strategy avoids trading in crisis."""
    report = create_crisis_report()
    strategy = BullPutSpreadStrategy(user)

    adjustment, reasons = await strategy._score_market_conditions_impl(report)
    final_score = 50.0 + adjustment

    assert final_score < 40  # Should score very low
    assert any("crisis" in r.lower() for r in reasons)
```

---

## Migration Guide

### Before Epic 32 (Verbose Scoring)
```python
# Old: 20+ lines of repetitive MACD checks
if report.macd_signal == "bullish":
    if report.trend_strength == "strong":
        score += 25
        reasons.append("Strong bullish trend")
    elif report.trend_strength == "moderate":
        score += 15
        reasons.append("Moderate bullish trend")
    else:
        score += 5
        reasons.append("Weak bullish trend")
elif report.macd_signal == "bearish":
    if report.trend_strength == "strong":
        score -= 25
        reasons.append("Strong bearish trend")
    # ... more conditions
```

### After Epic 32 (Context-Aware)
```python
# New: 5 lines with regime detection
if report.regime_primary == RegimeType.BULL:
    score += 30
    reasons.append(f"Bull regime (confidence {report.regime_confidence:.0f}%)")
elif report.regime_primary == RegimeType.BEAR:
    score -= 30
    reasons.append(f"Bear regime (confidence {report.regime_confidence:.0f}%)")
```

**Benefits:**
- 75% less code
- Self-documenting (enum types)
- Confidence transparency
- Easier to test

---

## Best Practices

### 1. Always Check Crisis
Every strategy must heavily penalize `CRISIS` regime:
```python
if report.regime_primary == RegimeType.CRISIS:
    score_adjustment -= 50  # Minimum penalty
    reasons.append("Market crisis - avoid trading")
```

### 2. Combine Extreme + Momentum
Use both signals for reversal detection:
```python
# Good: checks both extreme AND momentum
if report.is_overbought and report.momentum_signal == MomentumSignal.EXHAUSTION:
    # High confidence reversal signal

# Bad: checks only extreme (false positives)
if report.is_overbought:
    # Could be early in uptrend (still has momentum)
```

### 3. Use Confidence Scores
Display confidence for transparency:
```python
reasons.append(
    f"Bull regime (confidence {report.regime_confidence:.0f}%) - favorable"
)
```

### 4. Traditional Indicators Still Useful
Context fields don't replace all indicators:
```python
# Regime provides direction, HV/IV provides premium quality
if report.regime_primary == RegimeType.BULL:
    score += 30  # Directional bias

if report.hv_iv_ratio < 0.8:
    score += 15  # Good premium (separate concern)
```

---

## Common Pitfalls

### ❌ Ignoring Crisis Detection
```python
# BAD: No crisis check
if report.regime_primary == RegimeType.BEAR:
    score += 30
# Crisis regime also bearish but should avoid trading!
```

**Fix:**
```python
# GOOD: Crisis check first
if report.regime_primary == RegimeType.CRISIS:
    score -= 50
elif report.regime_primary == RegimeType.BEAR:
    score += 30
```

### ❌ Overweighting Single Signal
```python
# BAD: Relying only on RSI
if report.rsi > 70:
    score -= 30  # Could be false positive
```

**Fix:**
```python
# GOOD: Use aggregated extreme detection
if report.is_overbought:  # 3+ signals required
    score -= 30
```

### ❌ Treating Overbought as Immediate Reversal
```python
# BAD: Assumes overbought = instant reversal
if report.is_overbought:
    score += 30  # for bearish strategy
```

**Fix:**
```python
# GOOD: Check for exhaustion
if report.is_overbought and report.momentum_signal == MomentumSignal.EXHAUSTION:
    score += 30  # High confidence reversal
```

---

## Extension Points

### Adding New Regimes
```python
# In services/market_analysis.py
class RegimeType(str, Enum):
    # ... existing
    CONSOLIDATION = "consolidation"  # New regime

# In _detect_regime()
if self.is_range_bound and self.historical_volatility < 15.0:
    self.regime_primary = RegimeType.CONSOLIDATION
    self.regime_confidence = 70.0
    return
```

### Adding New Extreme Indicators
```python
# In _detect_extremes()
def _detect_extremes(self) -> None:
    overbought_count = 0

    # ... existing warnings

    # New: Volume spike
    if hasattr(self, 'volume_spike') and self.volume_spike:
        overbought_count += 1

    self.overbought_warnings = overbought_count
    self.is_overbought = overbought_count >= 3
```

**See:** `guides/ADDING_MARKET_INDICATORS.md` for complete examples

---

## Performance Considerations

### Detection Cost
- Context detection runs in `MarketConditionReport.__post_init__()`
- Executes once per market analysis (not per strategy)
- Negligible overhead (~0.1ms per detection)

### Optimization
If performance becomes an issue:
```python
# Cache regime detection results
@cached_property
def regime_info(self):
    self._detect_regime()
    return (self.regime_primary, self.regime_confidence)
```

---

## Monitoring

### Log Context Fields
```python
logger.info(
    f"{symbol}: Regime={report.regime_primary} "
    f"(confidence {report.regime_confidence:.0f}%), "
    f"Overbought={report.is_overbought} ({report.overbought_warnings}), "
    f"Momentum={report.momentum_signal}"
)
```

### Track Accuracy
```python
# Log regime vs actual market outcome
logger.info(
    f"Regime={report.regime_primary}, ActualMove={actual_move_pct:.1%}"
)
# Review monthly for regime detection accuracy
```

---

## References

- **Implementation:** services/market_analysis.py:36-332
- **Reference Strategies:**
  - services/bear_call_spread_strategy.py:52-177
  - services/bull_put_spread_strategy.py:52-171
- **Validation:** planning/32-market-analysis-enhancement/VALIDATION_RESULTS.md
- **ADR:** architecture/ADR-032-Market-Analysis-Consolidation.md
- **Extension Guide:** guides/ADDING_MARKET_INDICATORS.md

---

## Validation Results

Epic 32 context-aware analysis achieved **75% accuracy** vs 25% baseline:
- Crisis detection: 100% accuracy (avoided COVID crash)
- Reversal detection: 67% accuracy (flash crash bounce identified)
- Overall improvement: +50 percentage points

**Production Status:** ✅ Validated and deployed
