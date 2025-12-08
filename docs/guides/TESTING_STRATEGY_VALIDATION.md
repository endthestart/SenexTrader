# Strategy Validation Testing Guide

## Overview

The `test_strategy_validation` management command comprehensively tests all trading strategies against multiple equities. This is the primary tool for validating strategy functionality as new strategies are added in future development phases.

## Purpose

This command serves as:
- **Validation Tool**: Verify each strategy works correctly with real market data
- **Debugging Aid**: Identify specific failure reasons (missing price, no expirations, etc.)
- **Regression Testing**: Ensure changes don't break existing strategies
- **Documentation**: Generate detailed reports showing how strategies perform across different equities

## Usage

### Basic Usage

```bash
# Test with default top 20 equities (requires superuser)
python manage.py test_strategy_validation

# Test with specific user
python manage.py test_strategy_validation --user your@email.com

# Test specific symbols
python manage.py test_strategy_validation --user your@email.com --symbols SPY QQQ AAPL
```

### Default Test Equities

The command tests 20 high-volume equities by default:

**Major ETFs:**
- SPY, QQQ, IWM

**Mega Caps:**
- AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA

**Large Caps:**
- JPM, V, WMT, JNJ, UNH

**Other High-Volume:**
- AMD, NFLX, DIS, BA, GS

## Output Sections

### 1. Header

```
================================================================================
STRATEGY VALIDATION REPORT
Generated: 2025-10-18 09:08:43
Testing 20 equities with 3 strategies each (60 total tests)
================================================================================
```

### 2. Per-Equity Analysis

For each equity, the report shows:

#### Market Indicators
- **Price Data**: Current price, open price
- **Technical Indicators**: RSI, MACD signal, Bollinger position, SMA 20
- **Trend Metrics**: ADX, trend strength
- **Volatility**: Historical volatility, IV rank, current IV, HV/IV ratio
- **Market State**: Range-bound status, market stress level
- **Support/Resistance**: Key price levels

Example:
```
MARKET INDICATORS
────────────────────────────────────────────────────────────────────────────
 WARNING: No current price data available

Price:              $0.00
RSI:                49.8
MACD Signal:        bearish
Bollinger:          middle
SMA 20:             $664.70
ADX:                36.8 (strong)
Historical Vol:     11.3%
IV Rank:            27.0
Current IV:         2142.0%
HV/IV Ratio:        0.01 (IV elevated)
Range Bound:        No (0 days)
Market Stress:      0/100
```

#### Strategy Rankings

Shows ALL 3 strategies with scores, regardless of viability:

```
STRATEGY RANKINGS
────────────────────────────────────────────────────────────────────────────
1. Bear Call Spread     100.0  [OK] VIABLE
   Bearish MACD - favorable | Strong downtrend confirmed | IV high

2. Senex Trident         71.0  [OK] VIABLE
   IV rank favorable | Strong trend unsuitable for Trident | IV high

3. Bull Put Spread       35.0  [OK] VIABLE
   Bearish market - bull put not suitable | Acceptable trend | IV high
```

#### Generated Suggestions

For viable strategies (score >= 30), attempts generation with detailed results:

**Success:**
```
[OK] Senex Trident (Score: 78.0)
  Expiration:    2025-11-21 (34 DTE)
  Put Spread 1:  Short $530 / Long $525 (×2)
  Put Spread 2:  Short $525 / Long $520 (×2)
  Call Spread:   Short $555 / Long $560 (×1)
  Credit:        $850.00
  Max Risk:      $1,150.00
  R/R:           1.35:1
```

**Failure with Details:**
```
[FAIL] Bear Call Spread - No current price available
  Market data shows $0.00

[FAIL] Bull Put Spread - No valid strikes found in any DTE range
  Attempted DTE ranges:
    - 30-45 (standard)
    - 21-60 (wider)
    - 14-90 (very wide)
```

### 3. Summary Statistics

```
================================================================================
SUMMARY
================================================================================
Total Strategy Tests:     60
Viable (score >= 30):     45
Below Threshold:          15
Suggestions Generated:    42
Generation Failures:      3
Hard Stops (no trade):    0

Processing Time:          45.2s
```

### 4. Failure Patterns

Aggregates failures by type to identify systematic issues:

```
================================================================================
FAILURE PATTERNS
================================================================================
No Current Price               5 equities, 15 strategies
  Examples: SPY:bear_call_spread, SPY:senex_trident, SPY:bull_put_spread

Missing Strikes                2 equities, 6 strategies
  Examples: TSLA:senex_trident, NVDA:bear_call_spread

Option Chain Unavailable       1 equities, 3 strategies
  Examples: DIS:senex_trident
```

## Intelligent Features

### Fallback DTE Ranges

The command automatically tries progressively wider DTE ranges when looking for valid option expirations:

1. **Standard Range (30-45 DTE)**: Primary target range matching production behavior
2. **Wider Range (21-60 DTE)**: Fallback for equities with limited option availability
3. **Very Wide Range (14-90 DTE)**: Last resort for illiquid equities

This ensures maximum test coverage without manual intervention.

### Graceful Error Handling

The command continues processing even when individual equities fail:
- Price data unavailable → Skip generation, show warning, continue to next equity
- Option chain missing → Try fallback ranges, document failure, continue
- Hard stops detected → Report reason, skip all strategies for that equity, continue

### Detailed Error Messages

Each failure includes specific diagnostic information:
- **No Price**: Shows current price value ($0.00)
- **Missing Strikes**: Lists attempted DTE ranges and required strikes
- **Option Chain Issues**: Explains which expirations were checked

## Failure Types

### 1. No Current Price
**Cause**: Market data unavailable (market closed, API issues, data staleness)
**Effect**: Cannot calculate strikes, all strategies skip generation
**Indicator**: Warning shown in Market Indicators section

### 2. Missing Strikes
**Cause**: Required strikes not available in option chain
**Effect**: Strategy cannot find valid expiration with needed strikes
**Shows**: Attempted DTE ranges and specific missing strikes

### 3. Option Chain Unavailable
**Cause**: Option chain fetch failed for all expirations
**Effect**: Cannot validate strikes or build OCC bundle
**Shows**: Which expirations were attempted

### 4. Hard Stops
**Cause**: Market conditions prevent ALL strategies from trading
**Effect**: Entire equity skipped
**Reasons**: Data stale, exchange closed, system errors

## Interpreting Results

### Successful Generation

When a suggestion is generated, you'll see:
- Full position details (strikes, quantities, expiration)
- Financial metrics (credit, max risk, R/R ratio)
- DTE information

This confirms:
- Market data is available
- Strategy scoring logic works
- Option chains are accessible
- Strike selection is valid
- OCC bundle creation succeeds
- Stream manager integration works

### Failed Generation

When generation fails, examine:
1. **Error Type**: Identifies root cause (price, strikes, chain)
2. **Details**: Shows specific values (price, DTE ranges, strikes)
3. **Failure Patterns**: Reveals if issue affects multiple equities

Common patterns:
- **All equities fail with "No Price"** → Market closed or API issue
- **Specific equities fail with "Missing Strikes"** → Illiquid options market
- **Random failures** → Intermittent API issues

## Use Cases

### 1. Adding New Strategies

When implementing a new strategy:

```bash
# Test the new strategy across all default equities
python manage.py test_strategy_validation --user your@email.com
```

Look for:
- Strategy appears in rankings
- Score calculation works correctly
- Generation succeeds for viable conditions
- Errors are strategy-specific (not systemic)

### 2. Debugging Strategy Issues

When a strategy isn't generating suggestions:

```bash
# Test specific equity where issue occurs
python manage.py test_strategy_validation --user your@email.com --symbols SPY
```

Check:
- Market indicators section for data issues
- Strategy ranking section for score and explanation
- Generated suggestions section for specific error
- Failure patterns for systemic issues

### 3. Regression Testing

After making changes to strategy logic:

```bash
# Run full test suite
python manage.py test_strategy_validation --user your@email.com
```

Compare results before/after:
- Generation success rate should not decrease
- Scores should remain consistent for same market conditions
- New failure patterns indicate potential regressions

### 4. Production Readiness

Before deploying strategy changes:

```bash
# Test with production user account
python manage.py test_strategy_validation --user production@email.com
```

Verify:
- At least 70% generation success rate
- No unexpected failure patterns
- All strategies score consistently
- Error messages are actionable

## Expected Behavior

### During Market Hours

With valid market data:
- **Price**: Non-zero values for all equities
- **Indicators**: Complete technical indicator data
- **Suggestions**: 60-80% generation success rate
- **Failures**: Primarily due to low scores or missing strikes

### During Off-Hours

When market is closed:
- **Price**: May show $0.00 (stale data detected)
- **Indicators**: Historical data still available
- **Suggestions**: Generation fails with "No current price"
- **Patterns**: "No Current Price" affects all equities

## Troubleshooting

### All Generations Fail with "No Current Price"

**Likely Causes:**
- Market is closed (weekend, after-hours)
- TastyTrade API credentials invalid
- Data staleness threshold exceeded

**Solutions:**
- Run during market hours (9:30 AM - 4:00 PM ET, weekdays)
- Verify TastyTrade account credentials
- Check Redis cache connectivity

### Specific Equities Consistently Fail

**Likely Causes:**
- Illiquid options market (limited expirations)
- Wide bid-ask spreads
- Insufficient option chain data

**Solutions:**
- Review option chain availability on TastyTrade
- Consider excluding illiquid symbols from test
- Check if issue is temporary (data provider issue)

### Slow Processing Time

**Normal**: ~2-3 seconds per equity (40-60s for 20 equities)
**Slow**: >5 seconds per equity

**Likely Causes:**
- API rate limiting
- Network latency
- Cache misses

**Solutions:**
- Run during off-peak hours
- Reduce number of test symbols
- Warm up cache with separate queries first

## Integration with Daily Email

The daily suggestions email uses the same underlying logic:
- `StrategySelector.a_select_top_suggestions()`
- `MarketConditionValidator.a_analyze_market_conditions()`
- `strategy.a_prepare_suggestion_context()`

Differences:
- **Email**: Filters to top 3 suggestions, sends via email
- **Test Command**: Shows all strategies, outputs to console with detailed diagnostics

Success in test command = success in daily email flow.

## Future Enhancements

As new strategies are added:
1. Update `DEFAULT_SYMBOLS` if different equities are more relevant
2. Adjust `DTE_RANGES` if strategies need different DTE preferences
3. Add strategy-specific validation checks to failure pattern tracking
4. Enhance output format for new strategy types (e.g., spreads vs naked options)

## Related Commands

- `python manage.py run_automated_trade`: Execute actual trades
- `python manage.py preload_market_metrics`: Warm up cache before testing
- `python manage.py test_real_data`: Test market data fetching infrastructure

## Support

For issues with this command:
1. Check market hours (must be open for price data)
2. Verify TastyTrade credentials are valid
3. Review failure patterns to identify root cause
4. Test with single equity first to isolate issue
5. Consult error messages for specific diagnostic information
