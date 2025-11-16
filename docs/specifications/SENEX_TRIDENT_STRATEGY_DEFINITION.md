# Senex Trident Strategy Definition

## CRITICAL: What Senex Trident IS and IS NOT

### ⚠️ Senex Trident IS NOT AN IRON CONDOR

**This is a critical distinction that must be understood:**

- **Iron Condor**: A neutral options strategy consisting of 1 bull put spread + 1 bear call spread (4 legs total, equal quantities)
- **Senex Trident**: A custom proprietary strategy consisting of 2 bull put spreads + 1 bear call spread (6 legs total, asymmetric quantities)

### Senex Trident Structure

The Senex Trident is a **unique asymmetric multi-leg strategy** with a very specific configuration:

#### Leg Configuration
- **2 Bull Put Spreads** (quantity: 2 each = 4 legs total)
  - Sell 2 put contracts at the short strike (higher)
  - Buy 2 put contracts at the long strike (lower)
- **1 Bear Call Spread** (quantity: 1 = 2 legs total)
  - Sell 1 call contract at the short strike (lower)
  - Buy 1 call contract at the long strike (higher)

**Total: 6 option legs, not 4**

#### Key Structural Differences from Iron Condor

| Feature | Iron Condor | Senex Trident |
|---------|-------------|---------------|
| Put spreads | 1 spread | 2 spreads |
| Call spreads | 1 spread | 1 spread |
| Total legs | 4 legs | 6 legs |
| Symmetry | Symmetric (1:1) | Asymmetric (2:1) |
| Put/Call ratio | 1:1 | 2:1 |
| Strategy type | Standard | Proprietary |

### Exit Strategy: The Defining Characteristic

What truly distinguishes Senex Trident from an iron condor is its **three independent profit target exit strategy**:

#### Profit Targets (Independent Orders)
1. **Put Spread #1**: 40% profit target
2. **Put Spread #2**: 60% profit target  
3. **Call Spread**: 50% profit target

Each spread exits independently when its individual profit target is reached. This is fundamentally different from an iron condor which typically:
- Exits as a single unit
- Has one profit target for the entire position
- Does not have split, independent exits for different legs

#### Additional Exit Rules
- **DTE Exit**: Close all remaining spreads at 7 DTE (Days To Expiration)
- **Independent Execution**: Each spread can fill at different times
- **Sequential Profit Taking**: Spreads may reach targets on different days

### Why the Distinction Matters

1. **Position Sizing**: 
   - Iron condor: 1 contract = 4 legs
   - Senex Trident: 1 position = 6 legs (2 put spreads + 1 call spread)

2. **Risk Calculation**:
   - Iron condor: (spread_width × 100) - credit_received per side
   - Senex Trident: (spread_width × 200) for puts + (spread_width × 100) for call - total_credit

3. **Profit Management**:
   - Iron condor: Single profit target, exits as one
   - Senex Trident: Three independent profit targets, partial exits

4. **Order Execution**:
   - Iron condor: 1 opening order, 1 closing order
   - Senex Trident: 1 opening order, 3 separate closing orders (profit targets)

### Market Conditions

Senex Trident shares some market preference with iron condors:
- **Neutral to slightly bullish bias** (selling premium on both sides)
- **High implied volatility** (for premium collection)
- **Range-bound expectations** (profits from sideways movement)
- **NOT trending markets** (ADX < 25 preferred)

The asymmetric structure (2 put spreads vs 1 call spread) affects position sizing and profit management, but does NOT create a bearish bias. All spreads are SHORT (selling premium), making this a neutral to slightly bullish strategy that profits from time decay and IV contraction.

### Code References

When referencing this strategy in code:
- ✅ CORRECT: "Senex Trident", "2 put spreads + 1 call spread", "asymmetric condor variant"
- ❌ WRONG: "iron condor", "4-leg iron condor", "standard iron condor"

### Summary

**Senex Trident is a proprietary 6-leg asymmetric credit spread strategy with independent profit targets for each spread. It is structurally and operationally different from a standard 4-leg iron condor, despite superficial similarities in being a multi-leg credit strategy with both put and call spreads.**

The name "Trident" refers to the three independent profit targets (the three prongs of the trident), not just the multi-leg structure.
