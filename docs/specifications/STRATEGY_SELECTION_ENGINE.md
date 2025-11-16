# Strategy Selection Engine

**Last updated**: 2025-10-21
**Status**: Production (verify before deploying changes)
**Owner**: Strategy Working Group

## Quick Summary

- Scores every available strategy in auto mode and respects manual overrides.
- Depends on real TastyTrade data; hard stops enforce data freshness and risk rules.
- Outputs human-readable explanations for each scoring adjustment.

## Known Issues (2025-10-21)

- Suggestion generation is inconsistent; audit manual-mode paths end-to-end.
- Market data freshness is unclear; instrument currentness must be surfaced.
- Logic updates require duplicated changes across strategies; consolidation task open.
- From epic 22-strategy-expansion: added complexity led to related and unrelated bugs, logic changes, forced suggestions, daily/multi-equity commands, and separated Trident implementation.

---


**Version:** 1.0  
**Last Updated:** 2025-01-20  
**Status:** Production

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Phase 1: Data Collection](#phase-1-data-collection)
4. [Phase 2: Metric Calculation](#phase-2-metric-calculation)
5. [Phase 3: Market Condition Validation](#phase-3-market-condition-validation)
6. [Phase 4: Strategy Scoring](#phase-4-strategy-scoring)
7. [Phase 5: Selection & Ranking](#phase-5-selection--ranking)
8. [Phase 6: Decision Output](#phase-6-decision-output)
9. [Strategy-Specific Configurations](#strategy-specific-configurations)
10. [Development Notes](#development-notes)

---

## Overview

The Senex Trader strategy selection engine analyzes market conditions and ranks all available options strategies to recommend the most appropriate trade for current conditions. The system operates in two modes:

- **Auto Mode**: Scores all strategies, selects the highest-scoring strategy above minimum threshold
- **Manual Mode**: Generates requested strategy with confidence warnings if conditions are suboptimal

### Key Design Principles

1. **Real Data Only**: Never uses mock data; fails gracefully if data unavailable
2. **Hard Stops First**: Protects against unacceptable risk before scoring
3. **Graduated Scoring**: Uses 0-100 scale with penalties/bonuses, not binary pass/fail
4. **Strategy Agnostic**: All strategies evaluated against same base metrics
5. **Transparent Decisions**: Every score adjustment includes human-readable explanation

### System Flow

```
Market Data → Technical Indicators → Market Validation → Strategy Scoring → Ranking → Decision
    ↓              ↓                      ↓                    ↓              ↓         ↓
 TT API      RSI/MACD/ADX/etc        Hard Stops          All Strategies   Sort by   Winner
 60 days     Bollinger/HV/IV         Earnings/Div        Scored 0-100    Score    or None
```

---

## References & External Resources

- **TastyAgent Example**: https://github.com/ferdousbhai/tasty-agent/blob/main/tasty_agent/server.py
- **TastyTrade SDK**: Core dependency for market data and options chains
- **TastyTrade Methodology**: Scoring thresholds based on TastyTrade's proven approach (16-delta shorts, 45 DTE, 50% profit targets)

--- 

## Phase 1: Data Collection

The strategy selection process begins by collecting market data from multiple sources. All data flows through the `MarketConditionValidator` which orchestrates the collection pipeline.

### Data Sources & Timeframes

**Historical Price Data:**
- **Fetch Period**: 60 calendar days (~42 trading days accounting for weekends/holidays)
- **Minimum Acceptable**: 20 trading days (95% tolerance)
- **Data Points**: OHLC (Open, High, Low, Close) + Volume
- **Source**: TastyTrade API via `MarketDataService`
- **Cache**: Database-backed with intelligent refresh

**Real-Time Quote Data:**
- **Update Frequency**: Streaming (real-time via WebSocket)
- **Fallback**: REST API poll with 5-minute cache TTL
- **Fields**: Bid, Ask, Last, Previous Close, Volume
- **Source**: TastyTrade streaming service
- **Staleness Threshold**: 5 minutes (triggers hard stop)

**Market Metrics (IV, Volume, Greeks):**
- **Update Frequency**: 1-minute cache TTL
- **Fields**: 
  - IV Rank (52-week percentile)
  - IV Percentile (alternative calculation)
  - Current IV (30-day implied volatility)
  - Beta (for portfolio correlation)
- **Source**: TastyTrade `MarketMetricInfo` API
- **Storage**: Memory cache + database persistence

**Risk Event Data:**
- **Earnings Calendar**: Next expected report date, days until earnings
- **Dividend Schedule**: Ex-dividend date, next payment date
- **Source**: TastyTrade market metrics
- **Update**: Checked on every strategy evaluation

### Data Quality Checks

Before proceeding to calculations, the system validates data quality:

1. **Freshness Check**: Data timestamp < 5 minutes old
2. **Completeness Check**: Minimum 20 trading days of history
3. **Quote Validity**: Bid/Ask spread reasonable (not crossed)
4. **API Availability**: TastyTrade session active and authenticated

**If any check fails**: System returns `data_available = False` and triggers universal hard stop.

---

## Phase 2: Metric Calculation

Once raw data is collected, the `TechnicalIndicatorCalculator` computes technical indicators using pure Python (with pandas optimization when available).

### Technical Indicators (All Daily Timeframe)

#### Moving Averages

**SMA 20 (Simple Moving Average)**
- **Period**: 20 trading days
- **Purpose**: Trend direction (price above = uptrend, below = downtrend)
- **Calculation**: Average of last 20 closing prices
- **Used By**: Credit spreads (directional confirmation), Covered Call

**MACD (Moving Average Convergence Divergence)**
- **Fast EMA**: 12 days
- **Slow EMA**: 26 days  
- **Signal Line**: 9-day EMA of MACD line
- **Output**: Bullish/Bearish/Neutral signal based on histogram
- **Purpose**: Momentum and trend direction
- **Used By**: All strategies for directional bias scoring

#### Momentum Oscillators

**RSI (Relative Strength Index)**
- **Period**: 14 days
- **Scale**: 0-100
- **Calculation**: 14-period rolling average of gains vs losses
- **Interpretation**:
  - > 70: Overbought (mean reversion risk)
  - 45-55: Neutral (ideal for range-bound strategies)
  - < 30: Oversold (mean reversion risk)
- **Used By**: All strategies (extremes = risk, neutral = opportunity)

**ADX (Average Directional Index)**
- **Period**: 14 days
- **Scale**: 0-100
- **Calculation**: 14-period Wilder's smoothing on True Range and Directional Movement
- **Interpretation**:
  - > 30: Strong trend (good for directional plays, bad for range-bound)
  - 20-30: Moderate trend
  - < 20: Weak trend (good for credit spreads, Iron Condor)
- **Used By**: Key differentiator between directional and range-bound strategies

#### Price Channels & Support/Resistance

**Bollinger Bands**
- **Period**: 20 days (20-period SMA for middle band)
- **Standard Deviation**: ±2.0 from middle band
- **Calculation**: 20-day SMA ± (2 × 20-day standard deviation)
- **Real-Time Mode**: 19 historical closes + 1 current intraday price
- **Positions**: `above_upper`, `middle`, `below_lower`
- **Purpose**: Identify price extremes and potential reversals
- **Used By**: All strategies (extremes = caution, middle = stability)

**Support & Resistance Levels**
- **Period**: 20 days
- **Support**: 20-day rolling minimum of lows
- **Resistance**: 20-day rolling maximum of highs
- **Purpose**: Key price levels for strike selection
- **Used By**: Bull Put (support buffer), Bear Call (resistance cap)

**Recent Price Move**
- **Period**: 5 days (last 5 trading days)
- **Calculation**: (max high - min low) / current price × 100
- **Purpose**: Short-term volatility measurement for stress calculation
- **Threshold**: > 5% = elevated stress

#### Volatility Metrics

**Historical Volatility (HV)**
- **Period**: 30 days
- **Calculation**: Standard deviation of daily returns × √252 × 100
- **Annualization Factor**: 252 trading days per year
- **Output**: Annualized percentage (e.g., 25.5 = 25.5% annual volatility)
- **Purpose**: Realized price movement for comparison to implied volatility

**Implied Volatility Rank (IV Rank)**
- **Period**: 52 weeks (1 year)
- **Source**: TastyTrade API `tos_implied_volatility_index_rank`
- **Calculation**: (Current IV - 52-week low) / (52-week high - 52-week low) × 100
- **Scale**: 0-100 percentile
- **Purpose**: Determine if options are expensive (high IV) or cheap (low IV)
- **Interpretation**:
  - **> 70%**: Very expensive (great for selling, bad for buying)
  - **50-70%**: Elevated (good for credit strategies)
  - **25-50%**: Moderate (acceptable for most strategies)
  - **< 25%**: Low (bad for credit strategies, good for debit strategies)

**Current IV (IV30)**
- **Period**: 30-day forward-looking
- **Source**: TastyTrade API current implied volatility
- **Purpose**: Expected volatility for the next 30 days
- **Used In**: HV/IV ratio calculation

**HV/IV Ratio**
- **Calculation**: Historical Volatility (30-day) / Current IV (30-day)
- **Purpose**: Determine if options are overpriced or underpriced relative to realized movement
- **Interpretation**:
  - **< 0.8**: IV HIGH relative to HV → Options overpriced → **Good for SELLING**
  - **1.0**: Equal → Fair value
  - **> 1.2**: IV LOW relative to HV → Options underpriced → **Good for BUYING**
- **Critical For**: Distinguishing credit strategies (want < 0.8) from debit strategies (want > 1.2)

#### Market Stress Calculation

**Market Stress Level (0-100 composite)**
- **Components**:
  1. **IV Rank (40% weight)**:
     - IV > 70%: +40 points × (IV/100)
     - IV 50-70%: +20 points × (IV/100)
  2. **Recent Price Volatility (30% weight)**:
     - Move > 5%: up to +30 points (10% move = max)
     - Move 3-5%: +15 points
  3. **Technical Breaks (30% weight)**:
     - Price < Support × 0.98: +15 points
     - Price > Resistance × 1.02: +15 points
- **Threshold**: > 80 = extreme stress (triggers -15 to -20 penalties for all strategies)
- **Purpose**: Composite risk indicator for unpredictable market conditions

#### Range-Bound Detection

**Range-Bound Market**
- **Period**: 3 consecutive days
- **Threshold**: Price range ≤ 2.0 points
- **Calculation**: max(close) - min(close) over 3 days
- **Purpose**: Detect sideways consolidation
- **Impact**: 
  - **Senex Trident**: HARD STOP (prevents position stacking)
  - **Iron Condor/Butterfly**: FAVORABLE (range-bound preferred)

### Caching Strategy

To prevent redundant calculations and reduce CPU load:

- **Memory Cache (Redis)**: 5-minute TTL for hot data
- **Database Cache**: Persistent storage for historical reference
- **Cache Keys**: `{indicator}_{symbol}_1D_{period}_{params}`
- **Performance Impact**: 80% CPU reduction on cache hits

---

## Phase 3: Market Condition Validation

After metrics are calculated, the `MarketConditionValidator` assembles a comprehensive `MarketConditionReport` and checks for hard stops that prevent trading.

### MarketConditionReport Structure

The report contains all calculated metrics in a single data class:


```python
@dataclass
class MarketConditionReport:
    # Symbol & Price
    symbol: str
    current_price: float
    open_price: float
    
    # Technical Indicators
    data_available: bool  # FALSE = insufficient data
    rsi: float  # 0-100
    macd_signal: str  # 'bullish', 'bearish', 'neutral'
    bollinger_position: str  # 'above_upper', 'middle', 'below_lower'
    sma_20: float
    support_level: float | None
    resistance_level: float | None
    
    # Trend Strength
    adx: float | None  # 0-100, None if unavailable
    trend_strength: str  # "weak", "moderate", "strong"
    
    # Volatility
    historical_volatility: float  # Annualized % (e.g., 25.5 = 25.5%)
    hv_iv_ratio: float  # HV/IV ratio
    current_iv: float  # e.g., 0.285 = 28.5%
    iv_rank: float  # 0-100 percentile
    iv_percentile: float  # Alternative calculation
    
    # Market Conditions
    is_range_bound: bool
    range_bound_days: int
    market_stress_level: float  # 0-100
    recent_move_pct: float
    
    # Data Quality
    is_data_stale: bool
    last_update: datetime | None
    
    # Hard Stop Flags
    no_trade_reasons: list[str]
    
    # Risk Events
    has_upcoming_earnings: bool
    earnings_date: datetime | None
    days_until_earnings: int | None
    earnings_within_danger_window: bool
    has_upcoming_dividend: bool
    dividend_ex_date: datetime | None
    dividend_next_date: datetime | None
    days_until_dividend: int | None
    dividend_within_risk_window: bool
    
    # Portfolio
    beta: float | None  # For beta-weighted calculations
```

### Hard Stop Validation

Before any strategy can score conditions, the validator checks for universal hard stops. These are conditions that prevent **ALL** strategies from trading:

#### Universal Hard Stops (Apply to ALL Strategies)

**1. Stale Data**
- **Trigger**: Market data older than 5 minutes
- **Check**: `DATA_STALENESS_MINUTES = 5`
- **Reason**: Outdated pricing creates unacceptable execution risk
- **Detection**: `timestamp < (now - 5 minutes)`
- **Message**: `"data_stale"`
- **Impact**: `can_trade() = False`, all strategies return score 0

**Example**:
```python
# Last quote: 10:15:00 AM
# Current time: 10:21:00 AM  
# Age: 6 minutes > 5 minute threshold
# Result: HARD STOP - "Cannot trade with stale data"
```

**2. Insufficient Historical Data**
- **Trigger**: Less than 20 trading days of price history
- **Check**: `data_available = False`
- **Reason**: Cannot calculate technical indicators (RSI needs 14, MACD needs 26)
- **Detection**: Technical calculator returns insufficient data
- **Message**: `"Insufficient historical data for technical analysis"`
- **Impact**: All strategies return score 0

**3. Earnings Within Danger Window**
- **Trigger**: Earnings announcement within 7 days (configurable per strategy)
- **Check**: `DANGER_WINDOW_DAYS = 7`
- **Reason**: Extreme volatility risk around earnings
- **Detection**: TastyTrade `expected_report_date` parsed from market metrics
- **Message**: `"earnings_in_X_days"`
- **Impact**: Most strategies blocked; volatility strategies may TARGET earnings

**Earnings Window Classifications**:
- **0-3 days**: "TARGET" for Long Straddle, Long Strangle, Call Backspread
- **4-7 days**: "AVOID" for all credit/spread strategies
- **8+ days**: "NEUTRAL" (safe for all)

**Strategies That AVOID Earnings** (within 7 days):
- Senex Trident, Bull Put, Bear Call, Bull Call, Bear Put
- Short Iron Condor, Long Iron Condor, Iron Butterfly
- Calendar Spread, Covered Call, Cash-Secured Put

**Strategies That TARGET Earnings** (within 1-3 days):
- Long Straddle, Long Strangle, Call Backspread

**4. Dividend Within Risk Window**
- **Trigger**: Ex-dividend date within 5 days
- **Check**: `RISK_WINDOW_DAYS = 5`
- **Reason**: High early assignment risk for short options
- **Detection**: TastyTrade `dividend_ex_date` from market metrics
- **Message**: `"dividend_in_X_days"`
- **Impact**: Strategies with short positions blocked/warned

**Assignment Risk Levels**:
- **High Risk (0-2 days)**: `HIGH_RISK_DAYS = 2`
  - Covered Call: Short call will be assigned (holders want dividend)
  - Bear Call Spread: Short call leg at extreme risk
  - Cash-Secured Put: Higher assignment probability
- **Moderate Risk (3-5 days)**: 
  - Bull Put Spread, Covered Call: Monitor closely
- **Low Risk (6+ days)**: Safe for all strategies

#### Strategy-Specific Hard Stops

These only block specific strategies while allowing others:

**5. Range-Bound Market (Senex Trident ONLY)**
- **Trigger**: Price stays within 2-point range for 3+ consecutive days
- **Check**: `RANGE_BOUND_DAYS_THRESHOLD = 3`, range ≤ 2.0 points
- **Reason**: Prevents position stacking at same strikes (Trident-specific rule)
- **Strategy**: Senex Trident ONLY
- **Message**: `"Range-bound market (X days) - prevents position stacking"`
- **Why Trident-Specific**: 6-leg structure would create overlapping positions; Iron Condor/Butterfly PREFER range-bound markets

**6. Insufficient Premium (Cash-Secured Put ONLY)**
- **Trigger**: IV Rank < 50%
- **Check**: `MIN_IV_RANK = 50` (HARD STOP)
- **Reason**: Capital commitment (100% of strike) requires higher premium than credit spreads
- **Strategy**: Cash-Secured Put ONLY
- **Message**: `"IV Rank below 50 - insufficient premium"`
- **Comparison**: CSP (50%) > Iron Condor (45%) > Credit Spreads (25%)

**7. No Stock Position (Covered Call ONLY)**
- **Trigger**: User doesn't own 100+ shares
- **Check**: `has_sufficient_shares(symbol, 100)`
- **Reason**: Must own stock to cover short call
- **Strategy**: Covered Call ONLY
- **Score**: 15 (not 0 - allows UI to suggest buying stock)
- **Message**: `"Requires 100+ shares"`

**8. Extreme High IV (Debit Spreads ONLY)**
- **Trigger**: IV Rank > 70%
- **Check**: `MAX_IV_RANK = 70`
- **Reason**: Options too expensive to buy
- **Strategy**: Bull Call, Bear Put, Long Straddle, Calendar Spread
- **Score**: -25 to -30 penalty (not hard stop)
- **Message**: `"Options too expensive - wait for IV to settle"`

---

## Phase 4: Strategy Scoring

If all hard stops pass, each strategy evaluates the market conditions and returns a score (0-100) with detailed explanation.

### Scoring System Design

**Base Architecture:**
- **Starting Score**: 50 (neutral baseline)
- **Adjustments**: Penalties (-) and bonuses (+) based on metric alignment
- **Final Range**: Clamped to 0-100 using `clamp_score()`
- **Minimum Viable**: 30-35 (varies by strategy complexity)
- **Output**: (score: float, explanation: str) with pipe-separated reasons

**Confidence Levels:**
- **80-100**: HIGH confidence (excellent conditions)
- **60-79**: MEDIUM confidence (acceptable conditions)
- **40-59**: LOW confidence (suboptimal but possible)
- **0-39**: VERY LOW confidence (not recommended)

### Scoring Weights by Metric Category

Different strategies prioritize different metrics:


**Premium Selling Strategies** (want HIGH IV > 50%):
- IV Rank: **Primary** (30-40% weight)
- ADX: **Secondary** (20-30% weight) - prefer < 20 (range-bound)
- HV/IV Ratio: **Tertiary** (15-20% weight) - want < 0.8 (overpriced options)
- Direction: **Quaternary** (10-15% weight)
- Examples: Credit Spreads, Senex Trident, Iron Condor, Cash-Secured Put

**Premium Buying Strategies** (want LOW IV < 40%):
- IV Rank: **Primary INVERSE** (30-35% weight) - want low
- HV/IV Ratio: **Secondary** (20-25% weight) - want > 1.2 (underpriced options)
- ADX: **Tertiary** (15-20% weight) - prefer > 25 (trending for big move)
- Direction: **Quaternary** (10-15% weight)
- Examples: Debit Spreads, Long Straddle, Calendar Spread

### Strategy-Specific Scoring Logic

Below are the detailed scoring algorithms for each strategy family:

---

#### Credit Spreads (Bull Put, Bear Call)

**Base Score**: 50  
**Minimum Viable**: 35  
**Use Case**: Premium collection in directional markets with high IV

**Scoring Factors**:
- **Direction Alignment**: +25 (favorable MACD), -20 (unfavorable)
- **ADX Trend Confirmation**: +15 (strong trend aligned), -5 (weak trend)
- **IV Rank**: +20 (> 25%), -5 to -15 (graduated penalty below)
- **HV/IV Ratio**: +15 (< 0.8, IV overpriced), -8 (> 1.2, IV underpriced)
- **RSI**: +5 (neutral 45-55), -5 to -15 (extremes)
- **Price vs SMA**: +15 (favorable trend), -15 (counter-trend)
- **Market Stress**: +10 (< 50), -15 (> 70)
- **Bollinger Position**: +5 (near support/resistance), -10 (extreme)

**Example Calculation**:
```python
# Bull Put Spread Example
base_score = 50
+ 25  # Bullish MACD (favorable)
+ 15  # ADX 28 with bullish confirmation
+ 18  # IV Rank 55% (above 25%, bonus = min(20, (55-25)*0.3))
+ 15  # HV/IV 0.75 (IV overpriced for selling)
+ 5   # RSI 52 (neutral)
+ 15  # Price above SMA (uptrend confirmed)
+ 10  # Market stress 42 (low)
+ 5   # Near support (good entry point)
= 158 raw → clamped to 100 → "HIGH confidence"
```

---

#### Debit Spreads (Bull Call, Bear Put)

**Base Score**: 50  
**Minimum Viable**: 35  
**Use Case**: Directional plays when options are cheap (low IV)

**Scoring Factors**:
- **IV Environment** (INVERSE of credit spreads):
  - 30-50% range: +25 (optimal)
  - \> 70%: -25 (too expensive)
  - < 10%: -15 (minimal premium)
- **HV/IV Ratio** (want underpriced options):
  - \> 1.3: +20 (significantly underpriced)
  - \> 1.15: +15
  - < 0.8: -15 (overpriced, bad for buying)
- **ADX Trend Strength** (need momentum):
  - \> 30: +20 (optimal strong trend)
  - 20-30: +12 (moderate)
  - < 20: -20 (insufficient momentum)
- **Direction Alignment**: Same as credit spreads
- **Market Stress**: +10 (< 40), +3 (40-60), -15 (> 70)

**Key Difference from Credit Spreads**: Debit spreads PAY to enter (buy options), so they want LOW IV and strong directional momentum. Credit spreads COLLECT premium (sell options), so they want HIGH IV.

---

#### Senex Trident

**Base Score**: 50  
**Minimum Viable**: 30  
**HARD STOP**: Range-bound market = 0  
**Use Case**: Premium collection in neutral-to-bullish, non-trending markets

**Scoring Factors**:
- **IV Rank**: +30 bonus (> 25%), -0.8 × deficit (higher bonus than credit spreads)
- **ADX**: +10 (< 20, weak trend), -20 (> 30, strong trend)
- **HV/IV Ratio**: +15 (< 0.8), -8 (> 1.2)
- **MACD**: +15 (neutral preferred), -10 (strong directional)
- **Market Stress**: +10 (< 30), -15 (> 70)
- **Bollinger**: +5 (middle), -5 (extremes)
- **RSI**: +10 (neutral 45-55), -5 (bias), -15 (extremes)

**Special Rules**: 
- Range-bound = HARD STOP (prevents stacking 6-leg positions)
- Prefers sideways-to-slightly-bullish over strong trends
- Higher IV requirement than simple credit spreads (collects more premium)

---

#### Short Iron Condor

**Base Score**: 50  
**Minimum Viable**: 35  
**Use Case**: Range-bound, high IV environment

**Scoring Factors**:
- **IV Rank** (PRIMARY - 30% weight):
  - \> 70%: +30 (exceptional)
  - 60-70%: +24 (excellent)
  - 45-60%: +15 (adequate)
  - < 35: -20 (insufficient)
- **ADX** (SECONDARY - 25% weight):
  - < 20: +25 (IDEAL, range-bound)
  - 20-25: +18 (favorable)
  - 25-30: +10 (manageable)
  - \> 35: -25 (AVOID, trending)
- **HV/IV Ratio**: +20 (< 0.8), -15 (> 1.2)
- **MACD**: +15 (neutral), -10 (strong directional)
- **RSI**: +10 (neutral 45-55), -10 (extremes)

**Strategy Profile**: 4-leg structure (1 put spread + 1 call spread) profits from sideways price action. Requires decent IV (> 45%) and calm markets.

---

#### Iron Butterfly

**Base Score**: 40 (LOWER than Iron Condor)  
**Minimum Viable**: 35  
**Use Case**: EXTREMELY range-bound, VERY high IV (stricter than Condor)

**Scoring Factors**:
- **IV Rank** (STRICTER - 35% weight):
  - \> 75%: +35 (EXCELLENT)
  - 70-75%: +25
  - 60-70%: +10
  - < 50: -35 (use Condor instead)
- **ADX** (MUCH STRICTER - 30% weight):
  - < 12: +30 (EXTREMELY range-bound, PERFECT)
  - 12-15: +20 (very range-bound)
  - 15-18: +10
  - \> 22: -30 (AVOID)
- **Range Persistence**: +20 (5+ days consolidation)
- **HV/IV Ratio**: +15 (< 0.7, very expensive IV)

**Strategy Profile**: ATM short strikes (same strike for call and put) = tighter profit zone than Condor. Requires EXTREME range-bound conditions and VERY high IV.

---

#### Long Straddle

**Base Score**: 50  
**Minimum Viable**: 30  
**Use Case**: Big move expected, direction unknown, LOW IV environment

**Scoring Factors** (OPPOSITE of credit strategies):
- **IV Rank** (INVERSE - 30% weight):
  - < 20%: +30 (EXCELLENT, options cheap)
  - 20-30%: +20 (optimal)
  - 30-40%: +10 (acceptable)
  - 50-60%: -15 (expensive)
  - \> 60%: -30 (VERY EXPENSIVE, avoid)
- **HV/IV Ratio** (want underpriced - 25% weight):
  - \> 1.4: +25 (severely underpriced)
  - \> 1.2: +15
  - < 0.9: -20 (overpriced)
- **ADX** (want strong trend - 20% weight):
  - \> 35: +20 (very strong, big move likely)
  - \> 25: +15
  - < 20: -15 (insufficient movement)
- **Catalysts**: Bonus for upcoming earnings (1-3 days ideal)

**Strategy Profile**: Buy ATM call + ATM put. Profits from large moves in EITHER direction. Wants cheap options (low IV) before volatility expansion.

---

#### Cash-Secured Put

**Base Score**: 50  
**Minimum Viable**: 35  
**HARD STOP**: IV Rank < 50% = 0  
**Use Case**: Premium collection with willingness to own stock

**Scoring Factors**:
- **IV Rank** (HARD STOP at 50%):
  - \> 70%: +30 (exceptional)
  - 60-70%: +24 (excellent)
  - 50-60%: +15 (adequate)
  - < 50%: 0 (HARD STOP)
- **ADX** (prefer range-bound):
  - < 20: +20 (IDEAL)
  - < 25 with bullish/neutral: +16
  - \> 40 with bearish: -40 (AVOID, high assignment risk)
- **HV/IV Ratio**: +20 (> 1.3), +16 (> 1.15)
- **Premium Yield**: +15 (> 2.5% of strike price)
- **Market Direction**: -20 (bearish), +15 (neutral), +10 (bullish)

**Strategy Profile**: Requires 100% cash backing (vs 20-30% margin for spreads), so needs higher premium threshold (50% vs 25%).

---

#### Covered Call

**Base Score**: 50  
**Minimum Viable**: 35  
**PREREQUISITE**: Must own 100+ shares (score = 15 if not)  
**Use Case**: Income generation on existing stock holdings

**Scoring Factors**:
- **IV Rank** (optimal 40-70%):
  - In range: +25
  - \> 50%: +20
  - < 25: -15
- **MACD**:
  - Neutral: +15 (ideal - no strong move expected)
  - Bullish with high ADX: -20 (caps upside gains)
  - Bearish: -10 (limited downside protection)
- **ADX** (prefer range-bound):
  - < 20: +10 (favorable)
  - \> 30: -10 (risky, may move through strike)
- **Stock Position Value**: +10 (if profitable)

**Strategy Profile**: Requires stock ownership. Returns low score (15) if no shares owned, allowing UI to suggest "Buy 100 shares?"

---

#### Calendar Spread

**Base Score**: 50  
**Minimum Viable**: 35  
**Use Case**: Profit from time decay differential, LOW IV preferred

**Scoring Factors**:
- **IV Environment** (INVERSE - want LOW):
  - < 25%: +35 (EXCELLENT, cheap)
  - 25-40%: +20
  - \> 60%: -30 (too expensive)
- **ADX** (want neutral):
  - < 20: +25 (range-bound, ideal)
  - 20-30: +15
  - \> 35: -15
- **HV/IV Ratio** (want > 1.1):
  - \> 1.2: +20
  - \> 1.1: +12
  - < 0.9: -15
- **Price Proximity to ATM**: +10 (within 2% of strike)

**Strategy Profile**: Sell near-term, buy longer-term at same strike. Profits from faster time decay of short leg.

---

## Phase 5: Selection & Ranking

After all strategies are scored, the `StrategySelector` ranks them and selects the winner (Auto Mode) or validates the requested strategy (Manual Mode).

### Auto Mode: Best Strategy Selection

**Process**:
1. **Check Universal Hard Stops**: If `report.can_trade() = False`, return None immediately
2. **Score All Strategies**: Call `a_score_market_conditions()` for every registered strategy
3. **Filter by Minimum Threshold**: Eliminate strategies below minimum viable score (30-35)
4. **Sort by Score**: Highest score first
5. **Tie-Breaking**: If scores equal, use deterministic priority order
6. **Generate Suggestion**: Prepare context for top strategy
7. **Build Explanation**: Detailed breakdown with all strategy scores

**Deterministic Tie-Breaking Priority** (highest to lowest):
1. Credit Spreads: `bull_put_spread`, `bear_call_spread`, `cash_secured_put`
2. Debit Spreads: `bull_call_spread`, `bear_put_spread`
3. Iron Condors: `short_iron_condor`, `long_iron_condor`
4. Volatility Strategies: `long_straddle`, `long_strangle`, `iron_butterfly`
5. Advanced Multi-Leg: `call_backspread`, `calendar_spread`, `covered_call`

**Example Auto Mode Result**:
```python
{
    "type": "auto",
    "title": "Selected: Bull Put Spread",
    "confidence": {"level": "HIGH", "score": 78.5},
    "scores": [
        {"strategy": "Bull Put Spread", "score": 78.5, "selected": True,
         "reasons": ["Bullish MACD - favorable", "IV rank 55% - good premium", ...]},
        {"strategy": "Bear Call Spread", "score": 42.0, "selected": False,
         "reasons": ["Bullish market - unsuitable for bear call", ...]},
        {"strategy": "Senex Trident", "score": 35.2, "selected": False,
         "reasons": ["IV rank acceptable", "Weak trend favorable", ...]}
    ],
    "market": {
        "direction": "bullish",
        "iv_rank": 55.0,
        "volatility": 28.5,
        "range_bound": False,
        "stress": 42.0
    }
}
```

### Manual Mode: Forced Strategy Generation

**Process**:
1. **Validate Strategy Exists**: Check if requested strategy is registered
2. **Score Requested Strategy**: Calculate score even if below threshold
3. **Generate Regardless** (with `force_generation=True`): Bypass minimum threshold
4. **Add Confidence Warning**: If score < minimum, warn user
5. **Build Explanation**: Show why conditions are suboptimal

**Example Manual Mode Result** (low score):
```python
{
    "type": "forced",
    "title": "Requested: Bear Call Spread",
    "confidence": {"level": "LOW", "score": 32.0},
    "conditions": [
        "Bullish market - bear call spread not suitable",
        "Price above SMA - lacks downward momentum",
        "IV rank 28% below minimum (35%)"
    ],
    "warnings": [
        "Market conditions not ideal for this strategy",
        "Consider Bull Put Spread instead (score: 78.5)"
    ],
    "market": { /* same as auto */ }
}
```

---

## Phase 6: Decision Output

The final step is converting the selected strategy into actionable data for the UI and order placement.

### Output Structures

**Success (Strategy Selected)**:


```python
(
    strategy_name: str,        # e.g., "bull_put_spread"
    suggestion: TradingSuggestion,  # Database object with strikes, pricing, Greeks
    explanation: dict          # Detailed scoring breakdown (see above)
)
```

**No Strategy Viable**:
```python
(
    None,  # No strategy selected
    None,  # No suggestion created
    {
        "type": "low_scores",  # or "no_trade" if hard stops
        "title": "No Suitable Strategy",
        "scores": [/* all strategies with scores */],
        "market": {/* current conditions */},
        "reasons": ["IV rank too low across all strategies", ...]
    }
)
```

**Hard Stop Triggered**:
```python
(
    None,
    None,
    {
        "type": "no_trade",
        "title": "Cannot Trade - Stale Data",
        "hard_stops": ["Data Stale", "Last Update: 10:15 AM"],
        "market_status": {
            "last_update": "2024-01-20 10:15:00",
            "data_stale": True
        }
    }
)
```

### UI Display Logic

The frontend receives the explanation dict and renders:

1. **High Confidence (80-100)**:
   - Green badge: "HIGH CONFIDENCE"
   - Primary action button: "Generate Trade"
   - No warnings shown

2. **Medium Confidence (60-79)**:
   - Yellow badge: "MEDIUM CONFIDENCE"
   - Primary action button: "Generate Trade"
   - Optional info: "Acceptable conditions"

3. **Low Confidence (40-59)**:
   - Orange badge: "LOW CONFIDENCE"
   - Secondary action button: "Generate Anyway" (Manual Mode)
   - Warning icon with reasons

4. **Very Low / No Trade (0-39)**:
   - Red badge: "NOT RECOMMENDED"
   - Action disabled (or Manual Mode option)
   - Red alert with hard stop reasons

### Strategy Suggestions List

All strategies are always shown with their scores for transparency:

```
Auto Mode - Selected Strategy: Bull Put Spread (Score: 78.5)

 Ranked Strategies:
 1. ✓ Bull Put Spread          78.5  HIGH    [Selected]
    └─ Bullish MACD - favorable for bull put spread
    └─ IV rank 55% - good premium collection
    └─ Price above SMA - uptrend confirmed
    
 2.   Short Iron Condor         52.0  MEDIUM
    └─ IV rank adequate but prefer higher for condor
    └─ ADX 28 - moderate trend, prefer range-bound
    
 3.   Senex Trident             35.2  LOW
    └─ IV rank acceptable
    └─ Weak trend favorable but score below threshold
    
 4.   Bear Call Spread          28.0  VERY LOW
    └─ Bullish market - bear call spread not suitable
```

---

## Strategy-Specific Configurations

### Summary Comparison Table

| Strategy | Base | Min | IV Want | ADX Want | Direction | Capital | Assignment Risk |
|----------|------|-----|---------|----------|-----------|---------|----------------|
| **Bull Put Spread** | 50 | 35 | HIGH (>25%) | <20 range | Bullish | Margin | Moderate (short put) |
| **Bear Call Spread** | 50 | 35 | HIGH (>25%) | <20 range | Bearish | Margin | HIGH (short call) |
| **Bull Call Spread** | 50 | 35 | LOW (<40%) | >25 trend | Bullish | Debit | None (long) |
| **Bear Put Spread** | 50 | 35 | LOW (<40%) | >25 trend | Bearish | Debit | None (long) |
| **Senex Trident** | 50 | 30 | HIGH (>25%) | <20 range | Neutral/Bull | Margin | Moderate (2 short puts) |
| **Short Iron Condor** | 50 | 35 | HIGH (>45%) | <20 range | Neutral | Margin | HIGH (short put/call) |
| **Iron Butterfly** | 40 | 35 | VERY HIGH (>70%) | <12 tight | Neutral | Margin | VERY HIGH (ATM shorts) |
| **Long Straddle** | 50 | 30 | LOW (<30%) | >25 trend | Neutral | Debit | None (long) |
| **Long Strangle** | 50 | 30 | LOW (<30%) | >25 trend | Neutral | Debit | None (long) |
| **Cash-Secured Put** | 50 | 35 | HIGH (>50%) | <20 range | Bullish | 100% Cash | HIGH (short put) |
| **Covered Call** | 50 | 35 | MED-HIGH (40-70%) | <20 range | Neutral | Stock + Margin | HIGH (short call) |
| **Calendar Spread** | 50 | 35 | LOW (<40%) | <20 range | Neutral | Debit | LOW (spread) |

### Key Strategy Distinctions

**Premium Sellers (want HIGH IV > 45%)**:
- Credit Spreads, Senex Trident, Iron Condor, Iron Butterfly, Cash-Secured Put, Covered Call
- Logic: Collecting premium → want expensive options

**Premium Buyers (want LOW IV < 40%)**:
- Debit Spreads, Long Straddle, Long Strangle, Calendar Spread
- Logic: Paying premium → want cheap options

**Range-Bound Preferred (ADX < 20)**:
- Credit Spreads, Senex Trident, Iron Condor, Iron Butterfly, Cash-Secured Put, Covered Call
- Logic: Profit from time decay and stability

**Trending Market Preferred (ADX > 25)**:
- Debit Spreads, Long Straddle, Long Strangle
- Logic: Need directional momentum for profit

**Special Requirements**:
- **Covered Call**: Must own 100+ shares
- **Cash-Secured Put**: Must have 100% cash of strike price
- **Senex Trident**: Cannot trade if range-bound (position stacking)

---

## Development Notes

### System Design Decisions

**1. Underlying Symbol Selection**
- **Default**: QQQ (high liquidity, active options market)
- **User Override**: Search box allows equity selection (same as watchlist)
- **Validation**: Checks for sufficient option chain liquidity

**2. Risk Budget Enforcement**
- **Timing**: Risk budget checked ONLY at order submission, not during suggestion
- **Rationale**: Allow users to see suggestions even if over budget
- **UI**: Pop-up error prevents order submission if budget exceeded
- **Future**: Consider pre-emptive warning during suggestion phase

**3. Error Handling Improvements Needed**
- [ ] Better messaging for missing expiration dates
- [ ] Clear errors for missing strikes in option chain
- [ ] Graceful degradation when TastyTrade API is slow/unavailable
- [ ] Retry logic for transient API failures

**4. Manual Mode Philosophy**
- **Current**: Generate requested strategy even if score < threshold
- **Rationale**: Users may have information we don't (upcoming news, hedge needs)
- **Safety**: Display confidence warnings and suggest alternatives
- **Risk**: User can override warnings and proceed

**5. Auto Mode vs Manual Mode**
- **Auto Mode**: System picks best strategy (highest score above threshold)
- **Manual Mode**: User picks strategy (force generation with warnings)
- **Hybrid Idea**: "Suggest 3 best" mode for email notifications

### UI Enhancement Requests

**Trading Page Improvements**:
1. **Direction Indicator**: Expand beyond "bullish/bearish" to show:
   - MACD histogram value and trend
   - ADX strength with interpretation (weak/moderate/strong)
   - Combined assessment (e.g., "Strong Bullish Trend" vs "Weak Bullish Bias")

2. **Market Conditions Box Styling**:
   - Increase indicator width (use more of container width)
   - Make values bolder/more prominent
   - Add visual gauges for IV Rank, Market Stress
   - Color-code indicators (green = favorable, red = caution)

### Calculation Details Reference

**MACD Signal Calculation**:
```python
fast_ema = close.ewm(span=12).mean()
slow_ema = close.ewm(span=26).mean()
macd_line = fast_ema - slow_ema
signal_line = macd_line.ewm(span=9).mean()
histogram = macd_line - signal_line

if histogram > 0:
    return "bullish"
elif histogram < 0:
    return "bearish"
else:
    return "neutral"
```

**IV Rank Calculation** (from TastyTrade):
```python
iv_rank = ((current_iv - iv_52week_low) / 
           (iv_52week_high - iv_52week_low)) * 100
```

**Market Stress Calculation**:
```python
stress = 0
# IV Rank component (40% weight)
if iv_rank > 70:
    stress += 40 * (iv_rank / 100)
elif iv_rank > 50:
    stress += 20 * (iv_rank / 100)

# Volatility component (30% weight)
if recent_move > 5%:
    stress += min(recent_move / 10%, 1.0) * 30
elif recent_move > 3%:
    stress += 15

# Technical breaks (30% weight)
if price < support * 0.98:
    stress += 15
if price > resistance * 1.02:
    stress += 15

return min(stress, 100)
```

---

## Development Roadmap

### Current Status: ✅ Production

**Completed**:
- ✅ All technical indicators implemented and cached
- ✅ All strategy scoring algorithms complete
- ✅ Hard stop validation working
- ✅ Auto and Manual modes functional
- ✅ Real-time streaming data integration
- ✅ Earnings and dividend detection
- ✅ WebSocket-based suggestion generation

**Next Priorities**:



---

## Quick Reference: Commands

**Navigate to Epic 27**:
```bash
cd /path/to/senextrader_project/senextrader
cat ../senextrader_docs/planning/27-code-quality-improvements/README.md
cat ../senextrader_docs/planning/27-code-quality-improvements/task-001-fix-n1-queries.md
```

**Start First Task** (Fix N+1 Queries - 2-3 hours):
```bash
# Impact: Production-safe database queries, 80-95% query reduction
# Priority: ⚠️ CRITICAL - Performance blocker
```

**Run Strategy Validation Tests**:
```bash
python manage.py test_strategy_validation QQQ
```

**Check Current Market Metrics**:
```bash
python manage.py preload_market_metrics SPY QQQ
```

---

## Appendix: Metric Summary Tables

### Time Frame Reference

| Metric | Period | Time Frame | Data Source |
|--------|--------|------------|-------------|
| SMA 20 | 20 days | Daily bars | Historical OHLC |
| MACD | 12/26/9 days | Fast/Slow/Signal EMAs | Historical closes |
| RSI | 14 days | Daily bars | Historical closes |
| Bollinger Bands | 20 days ± 2σ | Daily bars | Historical closes |
| ADX | 14 days | Daily bars | Historical OHLC |
| Support/Resistance | 20 days | Min/Max levels | Historical highs/lows |
| Recent Move | 5 days | Short-term range | Historical highs/lows |
| Historical Volatility | 30 days | Annualized | Historical daily returns |
| IV Rank | 52 weeks | Percentile rank | TastyTrade API |
| IV Percentile | 52 weeks | Percentage | TastyTrade API |
| Current IV (IV30) | 30 days | Forward-looking | TastyTrade API |
| HV/IV Ratio | 30 days / 30 days | Realized vs Implied | Calculated |
| Range-Bound | 3 days | Consecutive | Historical closes |

### Hard Stops Reference

| Hard Stop | Threshold | Applies To | Score | Reason |
|-----------|-----------|------------|-------|--------|
| Stale Data | > 5 minutes | ALL | 0 | Execution risk |
| Earnings | Within 7 days | Most strategies | 0 | Volatility spike |
| Dividend | Within 5 days | Short options | 0 | Assignment risk |
| Insufficient Data | < 20 days | ALL | 0 | Cannot calculate |
| Range-Bound | 3+ days, 2pt | Senex Trident only | 0 | Position stacking |
| Low Premium | IV < 50% | CSP only | 0 | Poor ROI |
| No Stock | < 100 shares | Covered Call only | 15 | Cannot cover |
| Extreme IV | IV > 70% | Debit spreads | -25 | Too expensive |
| Market Stress | > 80 | ALL | -15 to -20 | Extreme volatility |

---

*End of Documentation*

# What I want to do
From /path/to/senextrader_project/senextrader_docs/planning/epics-done/22-strategy-expansion/ it seems we added a lot of complexity. We ran into quite a few related and unrelated bugs. We changed some of the logic, allowed for suggestions to be forced. We created a management command that does daily suggestions. Created a multi-equity-suggestions command. We separated Trident. 
Problems
- Generation of suggestions is inconsistent. 
- Market data recency and consistency is unknown. I have no idea if the data is stale or up to date going into a generation. 
- Whenever we want to make a change to the logic, it seems like it is a large effort to make the change across all strategies. 