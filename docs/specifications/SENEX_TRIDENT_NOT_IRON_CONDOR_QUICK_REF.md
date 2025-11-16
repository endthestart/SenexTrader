# ⚠️ IMPORTANT: Senex Trident Strategy Clarification

## READ THIS FIRST

**Senex Trident is NOT an iron condor.**

This is the most common source of confusion for AI assistants working on this codebase.

## Quick Facts

| Characteristic | Iron Condor | Senex Trident |
|----------------|-------------|---------------|
| **Structure** | 1 put spread + 1 call spread | **2 put spreads + 1 call spread** |
| **Total Legs** | 4 legs | **6 legs** |
| **Symmetry** | Symmetric (1:1 ratio) | **Asymmetric (2:1 ratio)** |
| **Exit Strategy** | Single profit target, exits as one | **3 independent profit targets** |
| **Profit Targets** | One target (e.g., 50%) | **40%, 60%, 50% (separate)** |
| **Directional Bias** | Neutral | **Neutral to slightly bullish** |
| **Strategy Type** | Standard | **Proprietary** |

## Why It Matters

1. **Position Sizing**: Senex Trident has 6 legs, not 4
2. **Risk Calculation**: 2 put spreads (quantity 2) vs 1 put spread (quantity 1)
3. **Order Execution**: Requires correct quantities (put_spread_quantity=2, call_spread_quantity=1)
4. **Profit Management**: Three separate closing orders, not one
5. **Greeks**: Must aggregate 6 legs, not 4

## What to Say

✅ **CORRECT**:
- "Senex Trident (2 put spreads + 1 call spread)"
- "6-leg Senex Trident strategy"
- "Senex Trident with three independent profit targets"
- "Asymmetric credit spread strategy"

❌ **WRONG**:
- "Senex Trident (iron condor)"
- "4-leg iron condor"
- "Iron condor variant called Senex Trident"
- "Standard iron condor structure"

## Full Documentation

For complete technical details, see:
- **[senextrader_docs/specifications/SENEX_TRIDENT_STRATEGY_DEFINITION.md](../senextrader_docs/specifications/SENEX_TRIDENT_STRATEGY_DEFINITION.md)**

## Code References

The codebase has been updated to avoid "iron condor" terminology when referring to Senex Trident:
- `Position.is_complete_trident` - checks if all 3 spreads present
- `Position.is_full_iron_condor` - DEPRECATED alias for backwards compatibility
- All docstrings clarified to specify "2 put spreads + 1 call spread"
- Comments updated to avoid iron condor confusion

---

**Remember**: If you see "iron condor" in reference to Senex Trident in the code, it's likely incorrect and should be flagged for correction.
