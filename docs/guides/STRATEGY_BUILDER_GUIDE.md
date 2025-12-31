# Strategy Builder Guide

> Unified strategy architecture for composable option strategies.

## Overview

Epic 50 introduced a unified strategy architecture using the **builder pattern**. All strategies are now instantiated through a simple factory and share common interfaces.

## Factory Usage

### Get a Single Strategy

```python
from services.strategies.factory import get_strategy

# Get a bull put spread strategy
strategy = get_strategy("short_put_vertical", user)

# Score market conditions
score, explanation = await strategy.a_score_market_conditions(report)
```

### List Available Strategies

```python
from services.strategies.factory import list_strategies

# Get all available strategy names
strategies = list_strategies()
# ['call_calendar', 'cash_secured_put', 'covered_call', 'iron_butterfly', ...]
```

### Instantiate All Strategies

```python
from services.strategies.factory import get_all_strategies

# Get all strategies for a user
strategies = get_all_strategies(user)
for name, strategy in strategies.items():
    score, _ = await strategy.a_score_market_conditions(report)
```

## Available Strategies

### Vertical Spreads (Credit & Debit)

| Strategy Name | Type | Direction | Description |
|---------------|------|-----------|-------------|
| `short_put_vertical` | Credit | Bullish | Bull Put Spread |
| `short_call_vertical` | Credit | Bearish | Bear Call Spread |
| `long_call_vertical` | Debit | Bullish | Bull Call Spread |
| `long_put_vertical` | Debit | Bearish | Bear Put Spread |

### Multi-Leg Strategies

| Strategy Name | Type | Description |
|---------------|------|-------------|
| `short_iron_condor` | Credit | Sell puts + calls, defined risk |
| `long_iron_condor` | Debit | Buy puts + calls, defined risk |
| `iron_butterfly` | Credit | ATM short, wings for protection |
| `call_calendar` | Time | Same strike, different expirations |
| `put_calendar` | Time | Same strike, different expirations |

### Volatility Strategies

| Strategy Name | Type | Market View |
|---------------|------|-------------|
| `long_straddle` | Debit | High volatility expected |
| `short_straddle` | Credit | Low volatility expected |
| `long_strangle` | Debit | High volatility, cheaper than straddle |
| `short_strangle` | Credit | Range-bound, undefined risk |

### Backspreads

| Strategy Name | Type | Direction | Risk |
|---------------|------|-----------|------|
| `long_call_ratio_backspread` | 2:1 | Bullish | Danger zone at long strikes |
| `long_put_ratio_backspread` | 2:1 | Bearish | Danger zone at long strikes |

### Covered Positions

| Strategy Name | Type | Description |
|---------------|------|-------------|
| `covered_call` | Income | Own stock, sell calls |
| `cash_secured_put` | Income | Cash reserved for potential assignment |

### Proprietary

| Strategy Name | Description |
|---------------|-------------|
| `senex_trident` | 2 bull puts + 1 bear call (6 legs) |

## Strategy Interface

All strategies implement these common methods:

```python
class BaseStrategy:
    @property
    def strategy_name(self) -> str:
        """Unique identifier for the strategy."""
        
    def automation_enabled_by_default(self) -> bool:
        """Whether strategy can be automated."""
        
    def should_place_profit_targets(self, position) -> bool:
        """Whether to place profit target orders."""
        
    def get_dte_exit_threshold(self, position) -> int:
        """Days to expiration exit threshold."""
        
    async def a_score_market_conditions(self, report) -> tuple[float, str]:
        """Score market conditions (0-100+) with explanation."""
```

## VerticalSpreadBuilder

For programmatic spread construction:

```python
from services.strategies.builders import VerticalSpreadBuilder
from services.strategies.core import VerticalSpreadParams, Direction, OptionType

# Create builder
builder = VerticalSpreadBuilder(user)

# Define parameters
params = VerticalSpreadParams(
    direction=Direction.BULLISH,
    option_type=OptionType.PUT,
    width_min=5,
    width_max=5,
    dte_min=30,
    dte_max=45,
)

# Build the spread
result = await builder.build("QQQ", params)

if result.success:
    composition = result.composition
    expiration = result.expiration
    strikes = result.strikes
    quality = result.quality
```

## Risk Classifications

Strategies are classified by risk profile:

- **DEFINED**: Maximum loss known upfront (spreads, long options)
- **UNDEFINED**: Potential for unlimited loss (naked shorts, short straddles)

```python
from services.strategies.core.risk import RiskClassifier

classifier = RiskClassifier()
profile = classifier.classify("short_put_vertical")  # DEFINED
profile = classifier.classify("short_straddle")       # UNDEFINED
```

## Best Practices

1. **Always check score before trading**: Use `a_score_market_conditions` to verify conditions
2. **Respect automation flags**: Don't automate strategies that return `False` for `automation_enabled_by_default()`
3. **Check risk profile**: UNDEFINED risk strategies require explicit user confirmation
4. **Use DTE thresholds**: Exit positions when `get_dte_exit_threshold()` is reached

## See Also

- `docs/specifications/SENEX_TRIDENT_STRATEGY_DEFINITION.md` - Trident details
- `docs/guides/ASYNC_SYNC_PATTERNS.md` - Async patterns used in strategies
- `docs/guides/TASTYTRADE_PRICE_CONVENTIONS.md` - Price handling
