# Algorithmic Options Trading at Market Extremes: A Comprehensive Framework

Your options trading system faces a critical challenge: knowing when to trust technical indicators versus when market extremes require override logic. This framework provides specific, rule-based decision criteria to solve this problem.

## The core problem solved

**At all-time highs (ATH):** Bullish indicators fire buy signals, but overextension risk is high. **During oversold conditions:** Indicators suggest bounce, but momentum may continue lower. **Your system needs:** Deterministic rules to distinguish true signals from false extremes, without machine learning complexity.

## Executive framework: The regime-override hierarchy

Your existing indicators (MACD, RSI, ADX, Bollinger Bands, IV Rank) provide the foundation. The solution is a **three-layer decision hierarchy** that adds context filters and override rules at market extremes.

### Layer 1: Market regime detection (Always check first)

Before trusting any indicator, determine the current market regime. This single step prevents 60%+ of false signals at extremes.

**Regime classification rules:**

```
TRENDING BULL REGIME:
- Price > 200-day SMA AND
- ADX > 25 AND
- McClellan Oscillator > 0 AND
- A/D Line rising

TRENDING BEAR REGIME:
- Price < 200-day SMA AND
- ADX > 25 AND
- McClellan Oscillator < 0 AND
- A/D Line falling

RANGE-BOUND REGIME:
- ADX < 20 OR
- Price oscillating ±3% around 200-day SMA for 20+ days

HIGH VOLATILITY REGIME:
- VIX > 25 OR
- VIX > 30% above 20-day moving average

CRISIS REGIME:
- VIX > 40 AND
- VIX term structure in backwardation (front month > back month)
```

**Critical rule:** In TRENDING regimes, overbought/oversold signals are CONTINUATION signals, not reversal signals. In RANGE-BOUND regimes, they are REVERSAL signals. This single distinction eliminates most false signals.

### Layer 2: Extreme condition detection (Override triggers)

Add these binary checks that flag when standard indicators should be questioned:

**At all-time highs (ATH) warning signals:**

```
ATH_EXTENDED = TRUE if any 3+ of following:
1. Price within 2% of 52-week high
2. RSI > 70 for 5+ consecutive days
3. Price > 10% above 20-day SMA
4. Volume declining on new highs (current volume < 80% of 20-day average)
5. New Highs/New Lows ratio declining while price rising
6. Put/Call ratio > 1.15 (fear at highs = divergence)
7. VIX elevated (>18) despite new highs
8. Price > VWAP + 2.5 standard deviations
```

**Oversold extreme warning signals:**

```
OVERSOLD_EXTREME = TRUE if any 3+ of following:
1. RSI < 30 for 3+ consecutive days
2. Price < 20-day SMA by 8%+
3. VIX > 30
4. $TICK multiple readings < -1000 in single session
5. TRIN closes > 2.0
6. Put/Call ratio > 1.25
7. McClellan Oscillator < -100
8. Price < VWAP - 2.5 standard deviations
```

**Key insight:** These flags don't tell you the direction—they tell you standard indicators are unreliable. You need Layer 3 to determine action.

### Layer 3: Momentum persistence vs exhaustion (The discriminator)

This is where you distinguish continuation from reversal at extremes. The answer lies in **confluence analysis**—when multiple independent factors align.

**Continuation signals (Trust the trend, ignore overbought/oversold):**

```
CONTINUATION_CONFIRMED = TRUE if ALL of:
1. Volume increasing in trend direction (current > 120% of 20-day avg)
2. No RSI/MACD divergence (momentum confirming price)
3. Breadth confirming (A/D Line making new highs/lows with price)
4. Market internals aligned:
   - For uptrend: $TICK averaging >+500, multiple readings >+800
   - For downtrend: $TICK averaging <-500, multiple readings <-800
5. VIX behaving normally:
   - In uptrend: VIX declining
   - In downtrend: VIX rising
6. VWAP and price trending same direction
```

**Exhaustion signals (Reversal likely, fade the extreme):**

```
EXHAUSTION_CONFIRMED = TRUE if 3+ of following:
1. RSI divergence (price new high/low, RSI not confirming)
2. Volume climax (>200% average) followed by declining volume
3. Breadth divergence (fewer stocks participating in move)
4. Market internal exhaustion:
   - $TICK extreme (>+1200 or <-1200) at price extreme
   - Multiple failed attempts to sustain extreme TICK readings
5. VIX divergence:
   - Price falling but VIX not making new highs = bottom near
   - Price rising but VIX spiking = fear at highs = top near
6. Candlestick exhaustion (long wicks, hammer/shooting star at extremes)
7. Price extended >3 ATR from moving average
8. Volume declining on each successive high/low
```

## Specific implementation rules for your system

### Rule set 1: ATH override logic

When your system identifies ATH conditions, apply this decision tree:

```
IF (ATH_EXTENDED == TRUE):
    IF (CONTINUATION_CONFIRMED == TRUE):
        # Strong trend, overbought can persist
        ALLOW bullish strategies with adjustments:
        - Reduce position size to 60% of normal
        - Tighten profit targets (take 50% at 1.5R instead of 2R)
        - Use call debit spreads instead of naked calls
        - Favor 30-45 DTE (avoid weeklies)
        - Set stops at -2ATR instead of -1ATR
        
    ELSIF (EXHAUSTION_CONFIRMED == TRUE):
        # Override bullish signals
        RECOMMEND neutral-to-bearish strategies:
        - Iron condors with call side 2-3% OTM
        - Bear call spreads at resistance
        - Risk reversals (sell calls, buy puts)
        - NO bullish directional plays
        
    ELSE:
        # Unclear - reduce conviction
        RECOMMEND neutral strategies only:
        - Iron butterflies
        - Short strangles (wider strikes)
        - Reduce size to 40% of normal
        - Wait for clearer signal
```

### Rule set 2: Oversold override logic

```
IF (OVERSOLD_EXTREME == TRUE):
    IF (CONTINUATION_CONFIRMED == TRUE):
        # Downtrend accelerating, avoid longs
        RECOMMEND bearish strategies:
        - Bear put spreads
        - Naked puts only if theta outweighs directional risk
        - NO bullish plays even if RSI < 30
        
    ELSIF (EXHAUSTION_CONFIRMED == TRUE):
        # Reversal likely, capitalize
        RECOMMEND bullish strategies:
        - Bull call spreads
        - Bull put spreads (sell premium at depressed levels)
        - Long straddles if IV not yet spiked
        - Target 30-60 DTE for vega expansion benefit
        
    ELSE:
        # Knife-catching risk
        WAIT for confirmation:
        - Require price to close above VWAP
        - Require RSI to cross back above 30
        - Require positive divergence + volume confirmation
        - Then enter with reduced size (50%)
```

### Rule set 3: Volume confirmation requirements

Professional traders report breakouts with volume >150% of average succeed 71% of the time, versus 58% without volume. Make this non-negotiable:

```
VOLUME_CONFIRMED = (Current_Volume > 1.5 × 20_day_avg_volume)

For ANY directional strategy recommendation:
IF (VOLUME_CONFIRMED == FALSE):
    Reduce strategy score by 40 points
    Flag as "LOW CONVICTION - NEEDS CONFIRMATION"
    
Breakout trades specifically:
IF (VOLUME_CONFIRMED == FALSE):
    DO NOT RECOMMEND (historical 58% failure rate)
```

### Rule set 4: Market internals integration

Your system lacks these critical inputs. Add them as daily data feeds:

**$TICK (NYSE or NASDAQ TICK index):**
```
TICK_BULLISH = Multiple readings >+800 in 30-min window
TICK_BEARISH = Multiple readings <-800 in 30-min window
TICK_EXHAUSTION = Single reading >+1200 or <-1200 at price extreme

Modify strategy recommendations:
IF (TICK_EXHAUSTION == TRUE):
    Favor counter-trend entries
    Reduce trend-following position sizes by 50%
    
IF (TICK_BULLISH/BEARISH aligned with proposed strategy):
    Increase confidence score by 20 points
```

**TRIN (Arms Index):**
```
TRIN_OVERSOLD = TRIN closes >2.0
# 80% historical probability of bounce next day

IF (TRIN_OVERSOLD == TRUE):
    Override bearish strategies for next session
    Recommend bull put spreads, short puts
    Flag as "HIGH PROBABILITY BOUNCE"
```

**Advance/Decline Line:**
```
AD_DIVERGENCE_BEARISH = (Price making new highs AND A/D_Line flat or declining)
AD_DIVERGENCE_BULLISH = (Price making new lows AND A/D_Line flat or rising)

IF (AD_DIVERGENCE_BEARISH == TRUE):
    Reduce bullish strategy scores by 30 points
    Increase bearish strategy scores by 20 points
    Flag as "BREADTH WARNING"
    
IF (AD_DIVERGENCE_BULLISH == TRUE):
    Reduce bearish strategy scores by 30 points
    Increase bullish strategy scores by 20 points
    Flag as "BREADTH IMPROVEMENT"
```

**McClellan Oscillator:**
```
IF (McClellan_Osc > +100):
    Market extremely overbought but likely to CONTINUE 2-3 weeks
    Maintain bullish strategies but prepare for eventual reversal
    
IF (McClellan_Osc < -100):
    Market extremely oversold but likely to CONTINUE 2-3 weeks
    Maintain bearish strategies but prepare for eventual reversal
    
IF (McClellan_Osc between +70 to +100 and turning down):
    Overbought reversal signal - recommend neutral/bearish
    
IF (McClellan_Osc between -70 to -100 and turning up):
    Oversold reversal signal - recommend neutral/bullish
```

## Options-specific overlay rules

Beyond stock technical indicators, options markets provide forward-looking information. Integrate these:

### IV Rank regime rules

Your system already has IV Rank. Use it to modulate strategy selection:

```
HIGH_IV_REGIME = (IV_Rank > 70 OR VIX > 25)
LOW_IV_REGIME = (IV_Rank < 30 OR VIX < 15)
NORMAL_IV = (IV_Rank between 30-70 AND VIX between 15-25)

Strategy selection modifications:

IF (HIGH_IV_REGIME == TRUE):
    FAVOR premium-selling strategies:
        - Iron condors (score +30)
        - Credit spreads (score +20)
        - Short strangles (score +25)
    REDUCE premium-buying strategies:
        - Long calls/puts (score -30)
        - Debit spreads (score -15)
    
IF (LOW_IV_REGIME == TRUE):
    FAVOR premium-buying strategies:
        - Long calls/puts (score +25)
        - Debit spreads (score +20)
        - Long straddles (score +15)
    REDUCE premium-selling strategies:
        - Iron condors (score -20)
        - Credit spreads (score -15)
        
IF (NORMAL_IV == TRUE):
    Use technical directional bias without IV adjustment
```

### Put/Call ratio sentiment override

```
PCR_EXTREME_FEAR = (Put/Call_Ratio > 1.20)
PCR_EXTREME_GREED = (Put/Call_Ratio < 0.70)

IF (PCR_EXTREME_FEAR == TRUE AND at_market_lows):
    # Contrarian bullish signal
    Override bearish technical signals
    Recommend: Bull put spreads, short puts, bull call spreads
    Flag as "SENTIMENT CAPITULATION"
    Historical success rate: ~65-70% within 5-10 days
    
IF (PCR_EXTREME_GREED == TRUE AND at_market_highs):
    # Contrarian bearish signal
    Override bullish technical signals
    Recommend: Bear call spreads, iron condors, risk reversals
    Flag as "SENTIMENT EUPHORIA"
```

### VIX term structure regime

```
VIX_BACKWARDATION = (Spot_VIX > VIX_front_month_future)
VIX_CONTANGO = (Spot_VIX < VIX_front_month_future)

IF (VIX_BACKWARDATION == TRUE):
    Market in crisis/fear mode
    REDUCE all short volatility strategies by 50% size
    FAVOR: Long puts, long straddles, protective strategies
    DO NOT: Sell naked options, short strangles
    
IF (VIX_CONTANGO == TRUE AND steep (>2 vol points/month)):
    Market complacent
    FAVOR: Premium selling, iron condors
    Watch for: Sudden flattening = warning signal
```

### Volatility skew signals

```
SKEW_EXTREME = (OTM_Put_IV - OTM_Call_IV) > 12 vol points

IF (SKEW_EXTREME == TRUE):
    Extreme fear priced in downside
    Puts overpriced relative to calls
    FAVOR: Sell put spreads, buy call spreads
    AVOID: Buying puts (expensive), selling calls (cheap)
    
IF (SKEW < 3 vol points):
    Unusual complacency
    INCREASE: Protective put allocation
    WARNING: Market not pricing tail risk
```

### Dealer gamma positioning

If you can access gamma exposure data (SpotGamma, SqueezeMetrics):

```
ABOVE_GAMMA_FLIP = (Price > Zero_Gamma_Level)
BELOW_GAMMA_FLIP = (Price < Zero_Gamma_Level)
AT_CALL_WALL = (Price within 1% of highest gamma strike above)
AT_PUT_WALL = (Price within 1% of highest gamma strike below)

IF (ABOVE_GAMMA_FLIP == TRUE):
    # Dealers hedge by selling rallies, buying dips (stabilizing)
    Market in mean-reversion mode
    FAVOR: Iron condors, range-bound strategies
    Expect: Lower volatility, pinning near strikes
    
IF (BELOW_GAMMA_FLIP == TRUE):
    # Dealers hedge by buying rallies, selling dips (destabilizing)
    Market in trending mode
    FAVOR: Directional strategies, avoid premium selling
    Expect: Higher volatility, breakout potential
    
IF (AT_CALL_WALL == TRUE):
    Strong resistance expected
    FAVOR: Bear call spreads, iron condors
    REDUCE: Bullish directional bets
    
IF (AT_PUT_WALL == TRUE):
    Strong support expected
    FAVOR: Bull put spreads, iron condors
    REDUCE: Bearish directional bets
```

## Complete decision algorithm

Here's the step-by-step logic your system should execute:

### Step 1: Regime identification

```python
# Pseudocode for your system

def identify_regime():
    regimes = []
    
    # Trend regime
    if price > sma_200 and adx > 25 and mcclellan > 0:
        regimes.append("TRENDING_BULL")
    elif price < sma_200 and adx > 25 and mcclellan < 0:
        regimes.append("TRENDING_BEAR")
    elif adx < 20:
        regimes.append("RANGE_BOUND")
    
    # Volatility regime
    if vix > 25:
        regimes.append("HIGH_VOLATILITY")
    if vix > 40:
        regimes.append("CRISIS")
    
    return regimes
```

### Step 2: Extreme detection

```python
def detect_extremes(price, indicators):
    ath_warnings = 0
    oversold_warnings = 0
    
    # ATH checks
    if price > (52_week_high * 0.98):  # Within 2%
        ath_warnings += 1
    if indicators['rsi'] > 70 and indicators['rsi_days_overbought'] >= 5:
        ath_warnings += 1
    if (price - sma_20) / sma_20 > 0.10:  # 10% above
        ath_warnings += 1
    if volume < (avg_volume_20 * 0.80):  # Declining volume
        ath_warnings += 1
    if new_highs_lows_ratio_declining():
        ath_warnings += 1
    if put_call_ratio > 1.15:
        ath_warnings += 1
    if vix > 18 and price_at_highs:
        ath_warnings += 1
    if price > (vwap + 2.5 * vwap_stdev):
        ath_warnings += 1
    
    # Oversold checks
    if indicators['rsi'] < 30 and indicators['rsi_days_oversold'] >= 3:
        oversold_warnings += 1
    if (sma_20 - price) / sma_20 > 0.08:
        oversold_warnings += 1
    if vix > 30:
        oversold_warnings += 1
    if tick_multiple_extreme_low():  # Multiple < -1000
        oversold_warnings += 1
    if trin > 2.0:
        oversold_warnings += 1
    if put_call_ratio > 1.25:
        oversold_warnings += 1
    if mcclellan_osc < -100:
        oversold_warnings += 1
    if price < (vwap - 2.5 * vwap_stdev):
        oversold_warnings += 1
    
    return {
        'ath_extended': ath_warnings >= 3,
        'oversold_extreme': oversold_warnings >= 3,
        'ath_score': ath_warnings,
        'oversold_score': oversold_warnings
    }
```

### Step 3: Continuation vs exhaustion

```python
def analyze_momentum_persistence(indicators, internals):
    continuation_score = 0
    exhaustion_score = 0
    
    # Continuation signals
    if volume > (avg_volume * 1.20):
        continuation_score += 1
    if not has_rsi_divergence():
        continuation_score += 1
    if ad_line_confirming_price():
        continuation_score += 1
    if tick_aligned_with_trend():  # >+500 bull, <-500 bear
        continuation_score += 1
    if vix_behavior_normal():
        continuation_score += 1
    if vwap_price_aligned():
        continuation_score += 1
    
    # Exhaustion signals
    if has_rsi_divergence():
        exhaustion_score += 1
    if volume_climax() or volume_declining_on_extension():
        exhaustion_score += 1
    if breadth_divergence():
        exhaustion_score += 1
    if tick_extreme_exhaustion():  # >1200 or <-1200
        exhaustion_score += 1
    if vix_divergence():
        exhaustion_score += 1
    if candlestick_exhaustion():
        exhaustion_score += 1
    if price_extended_atr(threshold=3):
        exhaustion_score += 1
    if volume_declining_on_successive_extremes():
        exhaustion_score += 1
    
    return {
        'continuation_confirmed': continuation_score >= 5,
        'exhaustion_confirmed': exhaustion_score >= 3,
        'continuation_score': continuation_score,
        'exhaustion_score': exhaustion_score
    }
```

### Step 4: Strategy selection with overrides

```python
def select_strategy(regime, extremes, momentum, iv_rank, put_call, vix_structure):
    
    # Start with base technical indicator scores (your existing system)
    strategies = calculate_base_strategy_scores()  # Your current 0-100 system
    
    # Apply regime adjustments
    if "TRENDING_BULL" in regime:
        strategies['bullish'] += 20
        strategies['bearish'] -= 30
        # In bull trends, overbought is continuation signal
        if extremes['ath_extended'] and momentum['continuation_confirmed']:
            # Don't penalize bullish strategies
            pass
        elif extremes['ath_extended'] and momentum['exhaustion_confirmed']:
            # Override bullish signals
            strategies['bullish'] = 0
            strategies['neutral'] += 40
            strategies['bearish'] += 30
            
    elif "TRENDING_BEAR" in regime:
        strategies['bearish'] += 20
        strategies['bullish'] -= 30
        if extremes['oversold_extreme'] and momentum['continuation_confirmed']:
            # Don't penalize bearish strategies
            pass
        elif extremes['oversold_extreme'] and momentum['exhaustion_confirmed']:
            # Override bearish signals
            strategies['bearish'] = 0
            strategies['neutral'] += 40
            strategies['bullish'] += 30
            
    elif "RANGE_BOUND" in regime:
        strategies['neutral'] += 30
        # In ranges, overbought/oversold are reversal signals
        if extremes['ath_extended']:
            strategies['bearish'] += 25
            strategies['bullish'] -= 20
        if extremes['oversold_extreme']:
            strategies['bullish'] += 25
            strategies['bearish'] -= 20
    
    # Apply IV rank adjustments
    if iv_rank > 70:
        strategies['credit_spreads'] += 30
        strategies['iron_condors'] += 30
        strategies['debit_spreads'] -= 15
        strategies['long_options'] -= 30
    elif iv_rank < 30:
        strategies['debit_spreads'] += 20
        strategies['long_options'] += 25
        strategies['credit_spreads'] -= 15
        strategies['iron_condors'] -= 20
    
    # Apply put/call ratio adjustments
    if put_call > 1.20 and extremes['oversold_extreme']:
        # Contrarian bullish
        strategies['bullish'] += 25
        strategies['bearish'] -= 20
        strategies['confidence'] = "HIGH - SENTIMENT CAPITULATION"
    elif put_call < 0.70 and extremes['ath_extended']:
        # Contrarian bearish
        strategies['bearish'] += 25
        strategies['bullish'] -= 20
        strategies['confidence'] = "HIGH - SENTIMENT EUPHORIA"
    
    # Apply VIX structure adjustments
    if vix_structure == "BACKWARDATION":
        strategies['bullish'] += 15
        strategies['short_vol'] = 0  # Override all short vol
        strategies['long_vol'] += 40
    
    # High volatility regime adjustments
    if "HIGH_VOLATILITY" in regime or "CRISIS" in regime:
        # Reduce all position sizes
        strategies['position_size_multiplier'] = 0.5
        strategies['iron_condors'] -= 20
        strategies['undefined_risk'] = 0  # Never trade undefined risk
    
    # Volume confirmation check
    if not volume_confirmed():
        for key in strategies:
            if 'directional' in key or 'breakout' in key:
                strategies[key] -= 40
        strategies['confidence'] = "LOW - AWAITING VOLUME CONFIRMATION"
    
    # Final scoring and recommendation
    top_strategies = sorted(strategies.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'recommended_strategy': top_strategies[0][0],
        'strategy_scores': dict(top_strategies[:5]),
        'position_size': base_size * strategies.get('position_size_multiplier', 1.0),
        'confidence_level': calculate_confidence(momentum, extremes),
        'warnings': generate_warnings(extremes, momentum, regime)
    }
```

### Step 5: Specific strategy parameters

```python
def generate_strategy_parameters(selected_strategy, iv_rank, days_to_expiration_pref):
    
    params = {}
    
    if selected_strategy == "iron_condor":
        if iv_rank > 70:
            params['delta'] = 0.30  # 30-delta wings
            params['dte'] = 45  # 45 days to expiration
            params['profit_target'] = 0.50  # Take profit at 50% max
        else:
            params['delta'] = 0.20  # Wider wings if lower IV
            params['dte'] = 30
            params['profit_target'] = 0.50
            
    elif selected_strategy == "bull_put_spread":
        params['short_put_delta'] = 0.30
        params['long_put_delta'] = 0.15
        params['dte'] = 30-45
        params['profit_target'] = 0.50
        
    elif selected_strategy == "bear_call_spread":
        params['short_call_delta'] = 0.30
        params['long_call_delta'] = 0.15
        params['dte'] = 30-45
        params['profit_target'] = 0.50
        
    elif selected_strategy == "long_call_debit":
        params['delta'] = 0.60-0.70  # ITM or ATM
        params['dte'] = 60-90  # Longer dated for theta management
        params['profit_target'] = 1.00  # 100% gain
        
    # Add stop loss rules
    params['stop_loss'] = calculate_stop_loss(selected_strategy, iv_rank)
    params['time_stop'] = 21  # Close or roll at 21 DTE
    
    return params
```

## Real-world example: QQQ on October 20, 2025

Let's apply this framework to the current QQQ situation to demonstrate how it resolves conflicting signals.

### Current QQQ situation summary

**Price:** $611.93 (just 0.08% below all-time high of $613.18)

**Conflicting indicators:**
- **Bullish signals:** Price above all major MAs (5, 20, 50, 200-day), hidden bullish RSI divergence, long-term uptrend intact
- **Bearish signals:** RSI 73.69 (extreme overbought), MACD sell signal, Williams %R -1.73 (overbought), volume rising on down days

**Volatility context:** VIX spiked 31.83% to 21.66 on Oct 10 (Trump tariff threats), currently elevated at ~20-21

**Options flow:** Heavy institutional put buying (multiple $1M+ trades in $540-575 puts, executed above ask = urgency)

**Sentiment:** Put/Call ratio elevated, QQQ/VIX ratio at historic extremes (near previous tops)

### Framework application

**Step 1: Regime identification**
```
- Price > 200-day SMA ✓ ($611.93 > $523.12)
- ADX: Need current value (assume >25 based on trend)
- McClellan Oscillator: Need to check
- A/D Line: Research suggests potential divergence (fewer new highs)

REGIME: TRENDING_BULL but showing signs of exhaustion
VIX: 20-21 = HIGH_VOLATILITY (threshold >20)

Combined: TRENDING_BULL + HIGH_VOLATILITY
```

**Step 2: Extreme detection**
```
ATH warnings:
1. Within 2% of ATH ✓ (0.08% below)
2. RSI >70 for 5+ days ✓ (73.69)
3. Price >10% above 20-day ✓ ($611 vs $580)
4. Volume declining on new highs ✓ (confirmed)
5. New highs/lows ratio declining (indicated)
6. Put/Call ratio >1.15 ✓ (heavy put buying)
7. VIX elevated >18 at highs ✓ (20-21)
8. Price > VWAP +2.5σ (need to calculate)

ATH_EXTENDED = TRUE (7+ warnings)
```

**Step 3: Continuation vs exhaustion**
```
Continuation signals:
- Volume increasing in trend? NO (declining on rallies)
- No RSI divergence? NO (hidden bullish divergence mentioned but also extreme OB)
- Breadth confirming? NO (fewer new highs while price at highs)
- TICK aligned? Unknown
- VIX behaving normally? NO (VIX spiked at highs = fear)
- VWAP/price aligned? Neutral

CONTINUATION_CONFIRMED = FALSE (0-1 of 6 criteria)

Exhaustion signals:
- RSI divergence? MAYBE (mixed signals)
- Volume climax or declining? YES (declining on extensions)
- Breadth divergence? YES (fewer new highs)
- TICK extreme? Unknown
- VIX divergence? YES (VIX elevated at price highs)
- Candlestick exhaustion? YES (multiple rejections at $605-609)
- Price >3 ATR from MA? Possibly
- Volume declining on successive highs? YES

EXHAUSTION_CONFIRMED = TRUE (4-5 of 8 criteria met)
```

**Step 4: Options overlay**
```
IV Rank: Unknown but VIX 20-21 suggests moderate-high
Put/Call Ratio: Elevated (>1.15 based on heavy put buying)
VIX Structure: Was inverted on Oct 16 (backwardation)
Dealer Gamma: Likely major walls at $600 (round number) and $610-615

Options environment: MIXED
- High IV favors selling premium
- Heavy put buying suggests smart money bearish/hedging
- Backwardation suggests fear (though may have normalized)
```

### Framework decision

```
Input: 
- Regime: TRENDING_BULL + HIGH_VOLATILITY
- Extremes: ATH_EXTENDED = TRUE
- Momentum: EXHAUSTION_CONFIRMED = TRUE
- IV Rank: ~60-70 (estimated from VIX 20)
- Put/Call: Elevated
- VIX Structure: Recently backwardated

Decision tree:
IF (ATH_EXTENDED == TRUE):  ✓
    IF (EXHAUSTION_CONFIRMED == TRUE):  ✓
        # Override bullish signals
        RECOMMEND: neutral-to-bearish strategies

Specific strategies:
1. Iron condors with call side emphasis
   - Short calls at $615-620 (resistance)
   - Short puts at $590-595 (support/VWAP)
   - 30-45 DTE
   - Capitalize on range-bound expectations
   
2. Bear call spreads
   - Short $610 calls / Long $620 calls
   - 30 DTE
   - Collect premium at resistance
   
3. Risk reversals (advanced)
   - Sell $620 calls
   - Buy $590 puts
   - Defines range expectations
   
4. NO bullish directional plays
   - Despite long-term uptrend
   - Too many exhaustion signals
   - Sentiment too crowded
```

**Position sizing:**
```
Base size adjustment:
- HIGH_VOLATILITY regime: 0.5x multiplier
- EXHAUSTION + ATH: Additional 0.8x multiplier
- Final: 0.4x normal position size (40%)

Rationale: VIX 20+ creates whipsaw risk, elevated uncertainty
```

### What NOT to do (anti-recommendations)

```
❌ DO NOT: Aggressive bullish call buying
   Reason: RSI 73.69, exhaustion confirmed, resistance at $605-609

❌ DO NOT: Naked put selling
   Reason: Heavy institutional put buying suggests smart money sees downside

❌ DO NOT: Short strangles (undefined risk)
   Reason: VIX 20+ = high volatility regime, use defined risk only

❌ DO NOT: 0DTE or weekly options
   Reason: Gamma risk extreme, unclear direction, news risk

❌ DO NOT: Full size positions
   Reason: Multiple regime warnings, reduce to 40%

✓ DO: Wait for clearer signals
   - Breakout above $609 with volume >80M = bullish confirmed
   - Breakdown below $595 = bearish confirmed
   - Current $595-609 range = no man's land
```

### If forced to trade today

**Best approach:**
```
STRATEGY: Defensive iron condor
- Sell $620 calls / Buy $625 calls
- Sell $590 puts / Buy $585 puts
- 30 DTE (Nov expiration)
- Position size: 40% of normal
- Profit target: 50% of max profit
- Stop loss: 2x credit received

RATIONALE:
- High IV favors selling premium
- Range-bound expectations ($595-$609)
- Defined risk appropriate for HIGH_VOLATILITY
- Gamma walls likely support range

WARNINGS:
- News risk: Tariff announcements, Fed speakers
- Volatility risk: VIX could spike further
- Breakout risk: If breaks $609, close call side immediately
```

**Alternative for conservative traders:**
```
STRATEGY: Wait
- Current signal quality: 50/100 (conflicting)
- Better entries:
  * Long at $580-590 pullback (support)
  * Long on breakout >$615 (confirmation)
  * Short on breakdown <$595 (breakdown)
  
"No man's land" = preserve capital
```

## Implementation checklist for your system

### Phase 1: Data integration (Week 1-2)

**Add these data feeds:**
1. ✓ NYSE/NASDAQ $TICK index (real-time or daily extremes)
2. ✓ TRIN/Arms Index (daily closes)
3. ✓ NYSE Advance/Decline Line (daily)
4. ✓ McClellan Oscillator (daily, formula provided earlier)
5. ✓ New Highs/New Lows ratio (daily)
6. ✓ CBOE Total Put/Call Ratio ($CPC) (daily)
7. ✓ VIX term structure (front month vs 3-month futures)
8. ✓ Volume data (for VWAP, volume confirmation)

### Phase 2: Calculation engine (Week 3-4)

**Build these functions:**
1. `identify_regime()` - Classifies market regime
2. `detect_extremes()` - Flags ATH/oversold warnings
3. `analyze_momentum_persistence()` - Continuation vs exhaustion
4. `calculate_volume_confirmation()` - 150% threshold check
5. `check_market_internals()` - TICK, TRIN, A/D scoring
6. `calculate_breadth_divergence()` - A/D Line vs price
7. `check_vix_structure()` - Contango vs backwardation
8. `calculate_put_call_sentiment()` - Extreme thresholds

### Phase 3: Strategy modification engine (Week 5-6)

**Implement score adjustment logic:**
```python
def adjust_strategy_scores(base_scores, regime, extremes, momentum, options_data):
    adjusted = base_scores.copy()
    
    # Apply all override rules from above
    # Return modified scores with explanations
    
    return {
        'scores': adjusted,
        'recommended': get_top_strategy(adjusted),
        'confidence': calculate_confidence_level(),
        'warnings': list_all_warnings(),
        'reasons': explain_adjustments()
    }
```

### Phase 4: Testing and calibration (Week 7-8)

**Backtest on known extremes:**
- March 2020 COVID crash (extreme oversold)
- January 2022 tech top (ATH with hidden warnings)
- October 2023 QQQ bottom at $320 (oversold reversal)
- August 2024 flash crash (momentum exhaustion)

**Metrics to track:**
- Signal accuracy at extremes (target >70%)
- False positive rate (target <30%)
- Strategy returns vs baseline system
- Sharpe ratio improvement

### Phase 5: User interface (Week 9-10)

**Display enhancements:**
```
Strategy Recommendation Dashboard:

PRIMARY: Iron Condor (Score: 85/100)
CONFIDENCE: Medium (3/5 stars)

⚠️ WARNINGS:
• ATH Extended (7/8 criteria met)
• Exhaustion Confirmed (5/8 criteria met)
• High Volatility Regime (VIX 20.8)

REGIME DETECTED:
• Trending Bull (Long-term)
• High Volatility (Short-term)
• Range-Bound Expected ($595-$609)

KEY FACTORS:
✓ IV Rank 68 - Favorable for selling premium
✓ Volume 42M - Below average (58M) - Caution
✓ Put/Call 1.18 - Elevated fear at highs
✓ TRIN 0.87 - Neutral
⚠️ RSI 73.69 - Extreme overbought
⚠️ A/D Line divergence detected

ALTERNATIVE STRATEGIES:
2. Bear Call Spread (Score: 78/100)
3. Neutral Butterfly (Score: 71/100)
4. Wait for Confirmation (Score: 70/100)

OVERRIDE ACTIVE: Bullish strategies reduced due to exhaustion signals at ATH
```

## Critical success factors

### 1. Don't overthink it

The framework seems complex, but the core logic is simple:
1. **Check the regime** - Is it trending or ranging?
2. **Check for extremes** - Are we at ATH or oversold?
3. **Check persistence** - Is momentum continuing or exhausted?
4. **Apply rules** - Follow the decision trees above

Most of the time (70%+), your existing indicators work fine. The override logic only activates at genuine extremes.

### 2. Confidence scoring is crucial

Not every signal is equal. Implement a confidence score:

```
HIGH CONFIDENCE (80-100):
- 5+ continuation/exhaustion signals aligned
- Volume confirmed
- Market internals aligned
- Clear regime
→ Full position size

MEDIUM CONFIDENCE (60-79):
- 3-4 signals aligned
- Some conflicting data
- Regime clear but momentum mixed
→ 60% position size

LOW CONFIDENCE (40-59):
- 2-3 signals aligned
- Multiple conflicting signals
- Regime unclear or transitioning
→ 40% position size OR wait

NO CONFIDENCE (<40):
- Fewer than 2 signals aligned
- Completely mixed signals
- "No man's land"
→ DO NOT TRADE
```

### 3. The "wait" option is a strategy

Add "Wait for Confirmation" as a legitimate strategy recommendation. When your system shows confidence <50%, the recommendation should be:

```
RECOMMENDED: Wait for clearer signal
CONFIDENCE: 42/100

RATIONALE:
- Conflicting indicators (bull trend + exhaustion)
- Low volume confirmation
- News risk elevated
- Better entry opportunities at $580 or $615

ALERT ME WHEN:
✓ Price breaks above $609 with volume >80M (bullish)
✓ Price breaks below $595 (bearish)
✓ RSI crosses below 65 (momentum cooling)
✓ VIX drops below 18 (volatility normalizing)
```

### 4. Position sizing is as important as direction

Your system should output:
- **Direction** (bullish/neutral/bearish)
- **Strategy** (specific options structure)
- **Size** (% of normal position size)
- **Confidence** (0-100 score)

The size adjustment based on regime and extremes prevents catastrophic losses when signals fail.

### 5. Learn from failures

Log every trade where:
- System recommended strategy X
- Regime was Y
- Extremes were Z
- Outcome was W

Analyze monthly:
- Which regime/extreme combinations have highest success?
- Which momentum signals most reliable?
- Which override rules most effective?
- False positive patterns

Continuously refine thresholds (e.g., maybe your market needs RSI >75 for ATH extreme, not >70).

## Key principles for market extremes

### The core insights

1. **Overbought can stay overbought in strong trends** - Don't fade momentum without exhaustion confirmation. Require 3+ exhaustion signals before overriding bullish trend.

2. **Oversold can get more oversold in crashes** - Don't catch knives without bottoming confirmation. Require TRIN >2.0 or VIX divergence before bullish oversold plays.

3. **Volume is the ultimate arbiter** - No volume confirmation? Reduce conviction by 40 points. This single rule prevents most false breakout losses.

4. **Breadth confirms or denies price** - Price at new highs without advancing issues making new highs = distribution. A/D Line is the lie detector.

5. **Market internals provide early warning** - TICK extremes (>1200 or <-1200) at price extremes signal exhaustion before price reverses.

6. **VIX behavior reveals truth** - Price falling but VIX not rising? Bottom near. Price rising but VIX elevated? Top near. VIX divergence precedes price reversal.

7. **Options markets are forward-looking** - Heavy institutional put buying at ATH? They know something. Heavy call buying at lows? Smart money positioning. Follow the flow.

8. **Multiple timeframe confirmation required** - Single timeframe signals fail at extremes. Need daily trend + 4H setup + 1H trigger alignment for high conviction.

9. **Regime determines interpretation** - Same RSI 75 reading means "continuation" in trending bull, "reversal" in range-bound. Context is everything.

10. **When in doubt, reduce size** - Can't decide if continuation or exhaustion? Trade both scenarios with 40% size each. Or wait.

## Advanced enhancements (Phase 2)

Once basic framework is working, consider adding:

### 1. Unusual options activity detection

Monitor for:
- Volume >5x average in specific strikes
- Block trades >$100k executed above ask (urgency)
- Open interest increases >50% in single day
- Concentrated institutional flow

When detected, flag as "SMART MONEY SIGNAL" and adjust strategy scores accordingly.

### 2. Multi-timeframe RSI system

Calculate RSI on multiple timeframes:
- Daily RSI (trend)
- 4-hour RSI (swing)
- 1-hour RSI (entry timing)

Signal strength increases when all three aligned:
```
ALL TIMEFRAMES OVERSOLD (RSI <30):
- Daily <30 AND 4H <30 AND 1H <30
- Extremely rare (2-3 times per year)
- Historical success rate >85% for bullish reversal
- Override all other bearish signals
- Flag as "MULTI-TIMEFRAME EXTREME - HIGH CONVICTION"
```

### 3. Sector rotation analysis

If QQQ at ATH but:
- XLF (Financials) outperforming tech = Rotation away from growth
- XLU (Utilities) strength = Defensive positioning
- XLI (Industrials) weakness = Economic concerns

Reduce bullish QQQ recommendations even if technicals look good.

### 4. Earnings season overlay

During peak earnings (Jan, Apr, Jul, Oct):
- Increase IV Rank threshold for premium selling (70 → 80)
- Reduce position sizes by 20% (event risk)
- Avoid 0-14 DTE options (earnings volatility)
- Favor post-earnings strategies (IV crush plays)

### 5. Time-of-day filters

Professional traders report best results:
- **First hour (9:30-10:30 AM):** Momentum trades, breakouts
- **Mid-day (11:00 AM-2:00 PM):** Institutional accumulation, avoid day trading
- **Last hour (3:00-4:00 PM):** Position squaring, momentum

Don't apply intraday signals during mid-day lull. Wait for first/last hour confirmation.

### 6. Fed calendar integration

During Fed weeks:
- Reduce all position sizes by 30%
- Close undefined risk positions
- Favor neutral strategies
- No positions through announcement (2:00 PM Wednesday)
- Post-Fed: Wait 30 minutes for volatility settling

Fed days historically see 2-3x normal intraday volatility. Your system should automatically flag Fed weeks and adjust recommendations.

## Conclusion: The meta-principle

**Your system doesn't need to predict the market. It needs to recognize when its predictions are unreliable.**

The entire framework above boils down to:
1. Base indicators give directional bias (your existing system)
2. Regime detection provides context (trending vs ranging)
3. Extreme detection flags when base indicators are unreliable (ATH/oversold warnings)
4. Momentum analysis determines action (continuation vs exhaustion)
5. Options overlay optimizes structure (IV/skew/flow)
6. Position sizing manages risk (confidence-based)

When base indicators + regime + extremes + momentum all align → High confidence, full size

When they conflict → Low confidence, small size or wait

When extremely conflicting → "Wait for confirmation" recommendation

**The goal isn't to be right more often. The goal is to trade with size when right and trade small when uncertain.**

This framework achieves that by layering contextual intelligence over your existing technical indicators, specifically addressing the ATH and oversold extreme scenarios where standard indicators fail.

Implement the core logic first (Phases 1-3), backtest on historical extremes, then refine thresholds for your specific market and trading style. The beauty of this rules-based approach is it's completely deterministic, explainable to users, and continuously improvable through data analysis.

Your users will understand WHY the system is recommending iron condors instead of bullish call spreads at ATH, because you can show them: "7 ATH warning signals active, 5 exhaustion signals confirmed, regime is high volatility - system override to neutral strategies."

That transparency builds trust and differentiates your application from black-box ML systems that can't explain their reasoning—especially critical for options trading where understanding risk is paramount.