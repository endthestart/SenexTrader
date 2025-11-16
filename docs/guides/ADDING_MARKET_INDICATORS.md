# Guide: Adding Market Indicators to Context Detection

**Audience:** Developers extending Epic 32 market analysis
**Prerequisite:** Understanding of `MarketAnalyzer` and `MarketConditionReport`
**Related:** patterns/MARKET_ANALYSIS_PATTERN.md, architecture/ADR-032-Market-Analysis-Consolidation.md

---

## Overview

This guide shows how to extend Epic 32's context-aware market analysis with new indicators, regimes, or extreme detection logic. The pattern maintains the core principle: **analyzers return data, strategies make decisions.**

---

## Extension Points

### 1. Adding a New Regime Type
### 2. Adding Extreme Detection Indicators
### 3. Adding Momentum Signals
### 4. Adding Custom Market Metrics

---

## 1. Adding a New Regime Type

**Use Case:** You want to detect a "consolidation" regime (range-bound + low volatility).

### Step 1: Define the Enum

**File:** `services/market_analysis.py`

```python
class RegimeType(str, Enum):
    """Market regime classification."""
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    CRISIS = "crisis"
    CONSOLIDATION = "consolidation"  # NEW
```

### Step 2: Update Detection Logic

**File:** `services/market_analysis.py` → `MarketConditionReport._detect_regime()`

```python
def _detect_regime(self) -> None:
    """Detect market regime."""
    confidence = 0.0

    # Crisis detection (highest priority - keep first)
    if self.market_stress_level >= 80:
        self.regime_primary = RegimeType.CRISIS
        self.regime_confidence = min(self.market_stress_level, 100.0)
        return

    # High volatility regime
    if self.iv_rank >= 75:
        self.regime_primary = RegimeType.HIGH_VOL
        self.regime_confidence = min(self.iv_rank, 100.0)
        return

    # NEW: Consolidation detection (range + low vol)
    if self.is_range_bound and self.historical_volatility < 15.0:
        self.regime_primary = RegimeType.CONSOLIDATION
        confidence = 50.0
        # Boost confidence if very tight range
        if self.range_bound_days >= 5:
            confidence += 20.0
        # Boost confidence if very low volatility
        if self.historical_volatility < 10.0:
            confidence += 15.0
        self.regime_confidence = min(confidence, 100.0)
        return

    # Range-bound detection (broader than consolidation)
    if self.is_range_bound:
        self.regime_primary = RegimeType.RANGE
        self.regime_confidence = min(50.0 + (self.range_bound_days * 10), 100.0)
        return

    # ... rest of existing detection logic
```

**Key Principles:**
- Order matters: crisis → high vol → consolidation → range
- Calculate confidence scores (0-100)
- Return early when regime detected
- Document thresholds (15.0 HV, 5 days, etc.)

### Step 3: Update Strategy Scoring

**File:** `services/my_strategy.py`

```python
async def _score_market_conditions_impl(
    self, report: MarketConditionReport
) -> tuple[float, list[str]]:
    score_adjustment = 0.0
    reasons = []

    # Handle new CONSOLIDATION regime
    if report.regime_primary == RegimeType.CONSOLIDATION:
        # Example: Iron Condor loves consolidation
        score_adjustment += 40
        reasons.append(
            f"Consolidation regime (confidence {report.regime_confidence:.0f}%) - "
            "ideal for range strategies"
        )

    # ... rest of scoring logic
```

### Step 4: Add Tests

**File:** `tests/test_market_analysis.py`

```python
@pytest.mark.asyncio
async def test_consolidation_regime_detection():
    """Test consolidation regime detection."""
    report = MarketConditionReport(
        symbol="SPY",
        current_price=500.0,
        sma_20=500.0,
        is_range_bound=True,
        range_bound_days=5,
        historical_volatility=12.0,  # Low vol
        iv_rank=30.0,
        market_stress_level=15.0,
        # ... other required fields
    )

    # Verify detection
    assert report.regime_primary == RegimeType.CONSOLIDATION, \
        f"Expected CONSOLIDATION, got {report.regime_primary}"
    assert report.regime_confidence >= 70, \
        f"Expected high confidence, got {report.regime_confidence}"
```

**File:** `tests/test_epic32_validation.py`

```python
@pytest.fixture
def consolidation_market():
    """Consolidation scenario for validation."""
    return MarketConditionReport(
        symbol="SPY",
        current_price=500.0,
        is_range_bound=True,
        range_bound_days=7,
        historical_volatility=10.0,  # Very low
        # ... other fields
    )

@pytest.mark.asyncio
async def test_consolidation_iron_condor_preference(consolidation_market):
    """Iron Condor should score well in consolidation."""
    report = consolidation_market
    strategy = IronCondorStrategy(mock_user)

    adjustment, reasons = await strategy._score_market_conditions_impl(report)
    score = 50.0 + adjustment

    assert score >= 80, f"Consolidation should favor Iron Condor (got {score})"
    assert report.regime_primary == RegimeType.CONSOLIDATION
```

---

## 2. Adding Extreme Detection Indicators

**Use Case:** You want to add volume spike detection to extreme warnings.

### Step 1: Add Field to Report

**File:** `services/market_analysis.py` → `MarketConditionReport`

```python
@dataclass
class MarketConditionReport:
    # ... existing fields

    # Volume metrics (NEW)
    volume_spike: bool = False  # Volume > 2x average
    avg_volume_20d: float = 0.0  # 20-day average volume
```

### Step 2: Update Detection Logic

**File:** `services/market_analysis.py` → `MarketConditionReport._detect_extremes()`

```python
def _detect_extremes(self) -> None:
    """Detect overbought/oversold extremes with warning counts."""
    overbought_count = 0
    oversold_count = 0

    # RSI signals (existing)
    if self.rsi > 70:
        overbought_count += 1
    if self.rsi > 80:
        overbought_count += 1

    # Bollinger Band position (existing)
    if self.bollinger_position == "above_upper":
        overbought_count += 1
    if self.bollinger_position == "below_lower":
        oversold_count += 1

    # Price extension from SMA (existing)
    if self.sma_20 > 0:
        extension_pct = ((self.current_price - self.sma_20) / self.sma_20) * 100
        if extension_pct > 5.0:
            overbought_count += 1
        if extension_pct < -5.0:
            oversold_count += 1

    # NEW: Volume spike warning
    if self.volume_spike:
        # Volume spike amplifies extreme conditions
        # If price spiking up with volume, add to overbought
        if self.current_price > self.sma_20:
            overbought_count += 1
        # If price spiking down with volume, add to oversold
        elif self.current_price < self.sma_20:
            oversold_count += 1

    # Update fields
    self.overbought_warnings = overbought_count
    self.oversold_warnings = oversold_count
    self.is_overbought = overbought_count >= 3
    self.is_oversold = oversold_count >= 3
```

### Step 3: Populate Field in Analyzer

**File:** `services/market_analysis.py` → `MarketAnalyzer.a_analyze_market_conditions()`

```python
async def a_analyze_market_conditions(
    self, user: AbstractBaseUser, symbol: str, market_snapshot: dict[str, Any] | None = None
) -> MarketConditionReport:
    # ... existing data collection

    # NEW: Calculate volume spike
    volume_spike = False
    avg_volume_20d = 0.0
    if market_snapshot and 'volume' in market_snapshot and 'avg_volume_20d' in market_snapshot:
        current_volume = market_snapshot['volume']
        avg_volume_20d = market_snapshot['avg_volume_20d']
        if current_volume > avg_volume_20d * 2.0:
            volume_spike = True

    return MarketConditionReport(
        # ... existing fields
        # NEW volume fields
        volume_spike=volume_spike,
        avg_volume_20d=avg_volume_20d,
    )
```

### Step 4: Add Tests

```python
@pytest.mark.asyncio
async def test_volume_spike_overbought_warning():
    """Volume spike should add to overbought warnings."""
    report = MarketConditionReport(
        symbol="SPY",
        current_price=510.0,  # Above SMA
        sma_20=500.0,
        rsi=72.0,  # Overbought (1 warning)
        bollinger_position="above_upper",  # (2 warnings)
        volume_spike=True,  # (3 warnings) - NEW
        # ... other fields
    )

    assert report.overbought_warnings >= 3
    assert report.is_overbought is True
```

---

## 3. Adding Momentum Signals

**Use Case:** You want to add a "REVERSAL_CONFIRMED" momentum signal (stronger than EXHAUSTION).

### Step 1: Define the Enum

```python
class MomentumSignal(str, Enum):
    CONTINUATION = "continuation"
    EXHAUSTION = "exhaustion"
    REVERSAL_CONFIRMED = "reversal_confirmed"  # NEW
    UNCLEAR = "unclear"
```

### Step 2: Update Detection Logic

```python
def _detect_momentum(self) -> None:
    """Assess momentum (continuation vs exhaustion vs reversal)."""
    confidence = 0.0

    # NEW: Reversal confirmed (extreme + MACD divergence)
    if self.is_overbought and self.macd_signal == "bearish":
        # Overbought BUT MACD already turned bearish = confirmed reversal
        self.momentum_signal = MomentumSignal.REVERSAL_CONFIRMED
        confidence = 70.0 + (self.overbought_warnings * 10)
        self.momentum_confidence = min(confidence, 100.0)
        return

    if self.is_oversold and self.macd_signal == "bullish":
        # Oversold BUT MACD already turned bullish = confirmed reversal
        self.momentum_signal = MomentumSignal.REVERSAL_CONFIRMED
        confidence = 70.0 + (self.oversold_warnings * 10)
        self.momentum_confidence = min(confidence, 100.0)
        return

    # Exhaustion signals (existing logic)
    if (self.is_overbought or self.is_oversold) and self.trend_strength == "strong":
        self.momentum_signal = MomentumSignal.EXHAUSTION
        # ... existing logic

    # ... rest of detection
```

### Step 3: Update Strategy Scoring

```python
if report.momentum_signal == MomentumSignal.REVERSAL_CONFIRMED:
    # Higher confidence than just EXHAUSTION
    if self.is_bearish_strategy:
        score_adjustment += 35  # vs 20 for EXHAUSTION
        reasons.append(
            f"Reversal confirmed (confidence {report.momentum_confidence:.0f}%) - "
            "high probability reversal"
        )
```

---

## 4. Adding Custom Market Metrics

**Use Case:** You want to add put/call ratio to detect sentiment extremes.

### Step 1: Add Field

```python
@dataclass
class MarketConditionReport:
    # ... existing fields

    # Sentiment metrics (NEW)
    put_call_ratio: float = 1.0  # Put/Call ratio (e.g., 1.2 = bearish, 0.8 = bullish)
    put_call_extreme: str = "neutral"  # "bearish_extreme", "bullish_extreme", "neutral"
```

### Step 2: Create Helper Method

```python
def _detect_put_call_extreme(self) -> None:
    """Detect sentiment extremes from put/call ratio."""
    if self.put_call_ratio > 1.5:
        self.put_call_extreme = "bearish_extreme"
    elif self.put_call_ratio < 0.6:
        self.put_call_extreme = "bullish_extreme"
    else:
        self.put_call_extreme = "neutral"
```

### Step 3: Call in `__post_init__`

```python
def __post_init__(self):
    # ... existing detection

    # NEW: Put/call ratio analysis
    self._detect_put_call_extreme()
```

### Step 4: Integrate into Extreme Detection (Optional)

```python
def _detect_extremes(self) -> None:
    # ... existing warnings

    # NEW: Put/call ratio as additional signal
    if self.put_call_extreme == "bearish_extreme":
        oversold_count += 1  # Market fear = oversold
    elif self.put_call_extreme == "bullish_extreme":
        overbought_count += 1  # Market greed = overbought

    # ... rest of logic
```

### Step 5: Use in Strategy

```python
if report.put_call_extreme == "bearish_extreme":
    # Extreme fear = contrarian buy opportunity
    if self.is_bullish_strategy:
        score_adjustment += 25
        reasons.append(
            f"Put/call ratio {report.put_call_ratio:.2f} - extreme fear, "
            "contrarian buy opportunity"
        )
```

---

## Best Practices

### 1. Maintain Detection Hierarchy

**Priority Order (highest to lowest):**
1. Crisis detection (`market_stress_level >= 80`)
2. High volatility (`iv_rank >= 75`)
3. Custom regimes (consolidation, etc.)
4. Range-bound
5. Trend-based (bull/bear)

**Why:** Crisis must always be detected first to avoid dangerous trades.

### 2. Calculate Confidence Scores

Every detection should have a confidence score (0-100):

```python
# Good: Transparent confidence calculation
confidence = 50.0  # Base
if self.range_bound_days >= 5:
    confidence += 20.0  # More days = higher confidence
if self.historical_volatility < 10.0:
    confidence += 15.0  # Lower vol = higher confidence
self.regime_confidence = min(confidence, 100.0)  # Cap at 100
```

```python
# Bad: Magic number confidence
self.regime_confidence = 75.0  # Why 75? Unclear.
```

### 3. Document Thresholds

```python
# Good: Documented thresholds
if self.historical_volatility < 15.0:  # 15% HV = low volatility threshold
    ...

# Bad: Magic numbers
if self.historical_volatility < 15:  # Why 15?
    ...
```

### 4. Test Edge Cases

```python
# Test boundary conditions
@pytest.mark.asyncio
async def test_regime_priority_crisis_over_bull():
    """Crisis should take priority over bull trend."""
    report = MarketConditionReport(
        symbol="SPY",
        market_stress_level=85.0,  # CRISIS
        macd_signal="bullish",  # Also bullish
        trend_strength="strong",  # Strong trend
        # ... other fields
    )

    # Crisis should win despite bullish signals
    assert report.regime_primary == RegimeType.CRISIS
```

### 5. Maintain Backward Compatibility

If adding new fields, provide defaults:

```python
# Good: Default values for new fields
@dataclass
class MarketConditionReport:
    volume_spike: bool = False  # Safe default
    put_call_ratio: float = 1.0  # Neutral default
```

---

## Common Patterns

### Pattern 1: Multi-Factor Detection

Combine multiple indicators for higher confidence:

```python
def _detect_strong_trend(self) -> bool:
    """Detect strong trend (multi-factor confirmation)."""
    factors = 0

    # Factor 1: ADX
    if self.adx and self.adx > 30:
        factors += 1

    # Factor 2: MACD
    if self.macd_signal in ["bullish", "bearish"]:
        factors += 1

    # Factor 3: Price vs SMA
    if abs(self.current_price - self.sma_20) / self.sma_20 > 0.05:
        factors += 1

    # Require 2+ factors
    return factors >= 2
```

### Pattern 2: Graduated Scoring

Use graduated thresholds instead of binary:

```python
# Good: Graduated
if self.iv_rank > 80:
    confidence = 90
elif self.iv_rank > 70:
    confidence = 75
elif self.iv_rank > 60:
    confidence = 60
else:
    confidence = 50

# Bad: Binary
if self.iv_rank > 70:
    confidence = 100
else:
    confidence = 0
```

### Pattern 3: Defensive Checks

Always validate data before calculations:

```python
# Good: Defensive
if self.sma_20 > 0 and self.current_price > 0:
    extension_pct = ((self.current_price - self.sma_20) / self.sma_20) * 100
else:
    extension_pct = 0.0  # Safe fallback

# Bad: Assumes valid data
extension_pct = ((self.current_price - self.sma_20) / self.sma_20) * 100  # ZeroDivisionError risk
```

---

## Validation Checklist

Before deploying new indicators:

- [ ] Enum defined (if new regime/momentum type)
- [ ] Detection logic implemented in `__post_init__`
- [ ] Confidence score calculated (0-100)
- [ ] Thresholds documented
- [ ] Unit tests added
- [ ] Integration tests added
- [ ] Historical validation (if regime change)
- [ ] Strategy scoring updated
- [ ] Documentation updated (this guide + pattern guide)
- [ ] Backward compatibility verified

---

## Testing Template

```python
# File: tests/test_market_analysis.py

@pytest.mark.asyncio
async def test_new_indicator_detection():
    """Test [indicator name] detection."""
    # Arrange: Create report with conditions
    report = MarketConditionReport(
        symbol="SPY",
        # ... fields that trigger detection
    )

    # Act: Detection runs in __post_init__
    # (no explicit call needed)

    # Assert: Verify detection
    assert report.new_field == expected_value, \
        f"Expected {expected_value}, got {report.new_field}"
    assert report.new_field_confidence >= threshold, \
        f"Expected confidence >= {threshold}, got {report.new_field_confidence}"


@pytest.mark.asyncio
async def test_new_indicator_strategy_scoring(mock_user):
    """Test strategy scoring with new indicator."""
    # Arrange
    report = create_report_with_new_indicator()
    strategy = MyStrategy(mock_user)

    # Act
    adjustment, reasons = await strategy._score_market_conditions_impl(report)
    score = 50.0 + adjustment

    # Assert
    assert score >= expected_minimum, \
        f"Expected score >= {expected_minimum}, got {score}"
    assert any("keyword" in r.lower() for r in reasons), \
        "Expected reason containing 'keyword'"


# File: tests/test_epic32_validation.py

@pytest.fixture
def scenario_with_new_indicator():
    """Historical scenario for validation."""
    return MarketConditionReport(
        symbol="SPY",
        # ... historical data
        new_field=historical_value,
    )

@pytest.mark.asyncio
async def test_new_indicator_historical_accuracy(scenario_with_new_indicator):
    """Validate new indicator against historical data."""
    report = scenario_with_new_indicator

    # Verify detection matches expected outcome
    assert report.new_field == expected_historical_detection
```

---

## Performance Considerations

### Lazy Evaluation (If Expensive)

For expensive calculations, use `@cached_property`:

```python
from functools import cached_property

@dataclass
class MarketConditionReport:
    # ... existing fields

    @cached_property
    def expensive_metric(self) -> float:
        """Calculate expensive metric (cached)."""
        # Only computed once, then cached
        return self._calculate_expensive_metric()

    def _calculate_expensive_metric(self) -> float:
        # Complex calculation here
        pass
```

### Avoid External Calls in Detection

Detection logic should use only fields already in the report:

```python
# Good: Uses existing fields
def _detect_regime(self) -> None:
    if self.market_stress_level >= 80:  # Field already set
        self.regime_primary = RegimeType.CRISIS

# Bad: Makes external API call
def _detect_regime(self) -> None:
    vix = await self.api.get_vix()  # Slow! Don't do this in __post_init__
    if vix >= 80:
        self.regime_primary = RegimeType.CRISIS
```

**Reason:** `__post_init__` is synchronous; external calls belong in `MarketAnalyzer.a_analyze_market_conditions()`.

---

## Examples from Production

### Example 1: Crisis Regime Detection

```python
# services/market_analysis.py:207-210
if self.market_stress_level >= 80:
    self.regime_primary = RegimeType.CRISIS
    self.regime_confidence = min(self.market_stress_level, 100.0)
    return
```

**Lessons:**
- Simple threshold (80)
- Confidence = stress level (transparent)
- Early return (priority detection)

### Example 2: Extreme Detection

```python
# services/market_analysis.py:260-291
def _detect_extremes(self) -> None:
    overbought_count = 0
    oversold_count = 0

    # RSI signals
    if self.rsi > 70:
        overbought_count += 1
    if self.rsi > 80:
        overbought_count += 1  # Extra warning for extreme RSI

    # ... more warnings

    self.overbought_warnings = overbought_count
    self.is_overbought = overbought_count >= 3
```

**Lessons:**
- Incremental warnings (not binary)
- Transparent count (debuggable)
- 3+ threshold (reduces false positives)

### Example 3: Strategy Usage

```python
# services/bear_call_spread_strategy.py:74-89
if report.regime_primary == RegimeType.BEAR:
    score_adjustment += 30
    reasons.append(
        f"Bear regime (confidence {report.regime_confidence:.0f}%) - "
        "very favorable for bear call spread"
    )
elif report.regime_primary == RegimeType.BULL:
    score_adjustment -= 30
    reasons.append(
        f"Bull regime (confidence {report.regime_confidence:.0f}%) - "
        "very unfavorable for bear call spread"
    )
```

**Lessons:**
- Enum comparison (readable)
- Confidence displayed (transparency)
- Clear scoring reasons

---

## References

- **Main Implementation:** services/market_analysis.py:36-332
- **Reference Strategies:**
  - services/bear_call_spread_strategy.py:52-177
  - services/bull_put_spread_strategy.py:52-171
- **Pattern Guide:** patterns/MARKET_ANALYSIS_PATTERN.md
- **ADR:** architecture/ADR-032-Market-Analysis-Consolidation.md
- **Tests:** tests/test_market_analysis.py, tests/test_epic32_validation.py

---

## Getting Help

If you're unsure about:
- **Threshold values:** Review validation results, adjust based on backtesting
- **Detection order:** Crisis → High Vol → Custom → Range → Trend (standard hierarchy)
- **Confidence calculation:** Start with 50.0 base, add factors, cap at 100.0
- **Testing approach:** Follow templates in this guide

For complex extensions, create an ADR documenting your approach before implementing.
