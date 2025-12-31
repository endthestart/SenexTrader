# P&L Calculation Architecture

> Single source of truth for all P&L calculation logic.

## Overview

All P&L calculations flow through `PnLCalculator` in `services/positions/lifecycle/pnl_calculator.py`. This ensures consistent results regardless of closure pathway.

## Position Closure Pathways

| Pathway | Trigger | P&L Method |
|---------|---------|------------|
| Profit Target | Order fills via AlertStreamer | `calculate_profit_target_pnl()` |
| DTE Automation | 7 DTE threshold reached | `calculate_profit_target_pnl()` |
| Manual Close | User closes at broker | `calculate_from_transactions()` |
| Assignment | Option assigned | `calculate_from_transactions()` |
| Expiration | Option expires worthless | `calculate_from_transactions()` |

## P&L Formulas

### Credit Spreads (Short Put/Call Vertical)
```
P&L = (entry_credit - close_debit) × quantity × 100
```
- **Profit**: When you close for less than you received
- **Loss**: When you close for more than you received

### Debit Spreads (Long Put/Call Vertical)
```
P&L = (close_credit - entry_debit) × quantity × 100
```
- **Profit**: When you close for more than you paid
- **Loss**: When you close for less than you paid

### Transaction-Based (Ground Truth)
```python
opening_value = sum(
    +tx.net_value if tx.action == "Sell to Open" else -tx.net_value
    for tx in opening_txns
)
closing_value = sum(
    -tx.net_value if tx.action == "Buy to Close" else +tx.net_value
    for tx in closing_txns
)
pnl = opening_value + closing_value
```

## Code Architecture

```
PnLCalculator (Single Source of Truth)
├── calculate_profit_target_pnl()   # Real-time profit target fills
├── calculate_from_transactions()    # Batch reconciliation
├── calculate_realized_pnl()         # Simple price-based
├── calculate_unrealized_pnl()       # Open position mark-to-market
├── calculate_leg_pnl()              # Individual option leg
└── calculate_portfolio_pnl()        # Aggregate across positions

ProfitCalculator (Wrapper)
├── calculate_trade_pnl()            # Trade-level P&L
├── calculate_position_realized()    # Position aggregate
└── calculate_profit_target_pnl()    # Delegates to PnLCalculator

PositionClosureService
└── _calculate_pnl()                 # Delegates to PnLCalculator
```

## Transaction Linking

Transactions are linked to positions by:
1. `opening_order_id` - Opening trade order
2. `profit_target_details[*].order_id` - Profit target fills
3. `metadata.dte_automation.order_id` - DTE automation closes
4. Symbol-based matching (fallback for external closes)

See `TransactionImporter.link_transactions_to_positions()`.

## Key Files

| File | Purpose |
|------|---------|
| `services/positions/lifecycle/pnl_calculator.py` | **Single source of truth** |
| `services/positions/lifecycle/profit_calculator.py` | Trade-based wrapper |
| `services/positions/closure_service.py` | Batch closure processing |
| `services/orders/transactions.py` | Transaction import/linking |
| `streaming/services/order_event_processor.py` | Real-time profit targets |

## Edge Cases

### Partial Fills
Each profit target fill updates:
- `position.quantity` decremented
- `position.total_realized_pnl` incremented
- `position.profit_target_details[key].status = "filled"`

### Senex Trident (3 Independent Targets)
- Target 1 fills → P&L recorded, targets 2 & 3 remain active
- Target 2 fills → P&L recorded, target 3 remains active
- Target 3 fills → Position fully closed

### Assignments
```
P&L = opening_credit + assignment_net_value
```
Creates equity position for acquired shares.

### Expired Worthless
```
P&L = opening_credit  (full credit kept)
```
No closing transactions needed.

## Debugging P&L Discrepancies

1. **Check transaction linking**: Are all transactions linked to the position?
   ```python
   TastyTradeTransaction.objects.filter(related_position=position)
   ```

2. **Verify opening_price_effect**: Is position marked as Credit or Debit?

3. **Compare transaction-based P&L**:
   ```python
   from services.positions.lifecycle.pnl_calculator import PnLCalculator
   from services.positions.closure_service import PositionClosureService

   service = PositionClosureService()
   opening_txns = await service._get_opening_transactions(position)
   closing_txns = await service._get_closing_transactions(position)
   pnl = PnLCalculator.calculate_from_transactions(opening_txns, closing_txns)
   ```

4. **Recalculate from position**:
   ```python
   service = PositionClosureService()
   pnl = await service.recalculate_pnl(position)
   ```
