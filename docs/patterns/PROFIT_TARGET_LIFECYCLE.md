# Profit Target Lifecycle Architecture

**Version**: 1.0
**Date**: 2025-10-06
**Status**: IMPLEMENTED
**Related**: Phase 3-6 Implementation (commit e84cec2, cf02b46)

---

## Executive Summary

This document describes the profit target lifecycle architecture implemented in Phases 3-6 of the position lifecycle management system. The key architectural decision is that **multiple profit targets can fill independently** without canceling each other, maximizing realized P&L opportunities.

**Core Principle**: Profit targets operate independently until DTE threshold triggers full position closure.

---

## Architecture Overview

### Independent Profit Target Model

Unlike traditional "one profit target per position" systems, Senex Trader supports **multiple simultaneous profit targets** where each can fill independently:

```
Position Entry (3 contracts)
    ↓
3 Profit Targets Created:
    - Target 1: 40% profit (1 contract)
    - Target 2: 50% profit (1 contract)
    - Target 3: 60% profit (1 contract)
    ↓
Target 1 Fills → Record P&L, Targets 2 & 3 stay active
    ↓
Target 2 Fills → Record P&L, Target 3 stays active
    ↓
Target 3 Fills → Position fully closed
```

**Alternative Flow** (DTE closure):
```
Position Entry (3 contracts)
    ↓
3 Profit Targets Created
    ↓
Target 1 Fills → Record P&L
    ↓
7 DTE Threshold Reached
    ↓
DTEManager cancels Targets 2 & 3
    ↓
DTEManager closes remaining 2 contracts via market order
    ↓
Position fully closed
```

### Why Independent Targets?

**Traditional Model** (single profit target):
- Position has 1 profit target order
- When it fills, position closes entirely
- Misses opportunities if market continues favorable

**Independent Model** (multiple profit targets):
- Position has N profit targets at different price levels
- Each fills independently as market moves
- Maximizes P&L by capturing incremental profits
- DTE threshold provides safety exit for unfilled targets

---

## Data Model

### Position.profit_target_details Structure

```python
{
    "put_spread_1_40": {
        "order_id": "abc123",           # TastyTrade order ID
        "percent": 40.0,                 # Profit target percentage
        "original_credit": 1.50,         # Entry credit for this spread
        "target_price": 0.90,            # Limit price for target order
        "status": "filled",              # Optional: filled/cancelled/rejected
        "filled_at": "2025-10-06T...",   # Optional: ISO timestamp
        "fill_price": 0.85,              # Optional: actual fill price
        "realized_pnl": 65.00            # Optional: P&L for this fill
    },
    "put_spread_2_60": {
        "order_id": "def456",
        "percent": 60.0,
        "original_credit": 1.50,
        "target_price": 0.60
        # No status = still active
    }
}
```

**Field Semantics**:
- **order_id**: Links to TastyTrade order for fill monitoring
- **percent**: Profit target percentage (40% = exit at 60% of entry credit)
- **original_credit**: Entry credit used for P&L calculation
- **target_price**: Limit price submitted to broker
- **status**: Added after fill/cancel (absence means "active")
- **filled_at**: ISO 8601 timestamp of fill event
- **fill_price**: Actual execution price (may differ from target_price)
- **realized_pnl**: Calculated P&L for this specific fill

### Position.lifecycle_state Transitions

```
pending_entry
    ↓ [Entry order fills]
open_full (all contracts active, all profit targets placed)
    ↓ [One or more profit targets fill]
open_partial (some contracts closed, some profit targets still active)
    ↓ [All profit targets fill OR DTE threshold]
closed
```

**Key States**:
- **open_full**: Original position quantity intact, all profit targets active
- **open_partial**: Some profit targets filled, quantity reduced, remaining targets active
- **closed**: All contracts closed (either via profit targets or DTE closure)

---

## Event Flow

### Profit Target Fill (Phase 3)

**Trigger**: AlertStreamer detects order fill event

```python
# streaming/services/stream_manager.py:_handle_order_event
async def _handle_order_event(self, order):
    # Check if this order is a profit target
    if position.profit_target_details:
        for pt_key, pt_details in position.profit_target_details.items():
            if pt_details.get("order_id") == order.id:
                await self._handle_profit_target_fill(trade, order)
                return
```

**Processing** (`_handle_profit_target_fill`):

1. **Extract fill data** (uses `abs()` for quantity - critical bug fix cf02b46):
```python
fill_data = self._extract_fill_data(order)
filled_quantity = abs(int(order.size))  # TastyTrade returns negative for buy-to-close
fill_price = Decimal(str(order.price))
```

2. **Update position quantity**:
```python
position.quantity -= filled_quantity  # Decrease by contracts closed
```

3. **Update lifecycle state**:
```python
if position.quantity == 0:
    position.lifecycle_state = "closed"
else:
    position.lifecycle_state = "open_partial"
```

4. **Calculate realized P&L** (uses ProfitCalculator):
```python
from services.position_lifecycle.profit_calculator import ProfitCalculator
calculator = ProfitCalculator()
realized_pnl = calculator.calculate_profit_target_pnl(
    position, fill_price, filled_quantity
)
position.total_realized_pnl += realized_pnl
```

5. **Update profit_target_details** (critical bug fix cf02b46):
```python
for pt_key, pt_details in position.profit_target_details.items():
    if pt_details.get("order_id") == order.id:
        pt_details["status"] = "filled"
        pt_details["filled_at"] = filled_at.isoformat()
        pt_details["fill_price"] = float(fill_price)
        pt_details["realized_pnl"] = float(realized_pnl)
        break
```

6. **Create Trade record**:
```python
new_trade = await Trade.objects.acreate(
    user=trade.user,
    position=position,
    lifecycle_event="profit_target_fill",
    realized_pnl=realized_pnl,
    fill_price=fill_price,
    # ... lifecycle_snapshot for audit trail
)
```

7. **Send notification**:
```python
await notification_service.send_notification(
    message=f"Profit target hit for {position.symbol}. {remaining_targets_count} targets remain active.",
    notification_type="success"
)
```

8. **Broadcast WebSocket update**:
```python
await self._broadcast("position_update", {
    "position_id": position.id,
    "lifecycle_state": position.lifecycle_state,
    "quantity": position.quantity,
    "total_realized_pnl": float(position.total_realized_pnl)
})
```

### DTE Threshold Closure (Phase 2)

**Trigger**: Celery beat task runs daily at 9:30 AM ET

```python
# services/position_lifecycle/dte_manager.py
async def close_position_at_dte(self, position):
    # Cancel all remaining profit targets
    remaining_order_ids = [
        pt["order_id"] for pt in position.profit_target_details.values()
        if pt.get("order_id") and not pt.get("status")
    ]

    for order_id in remaining_order_ids:
        await cancellation_service.cancel_order(order_id)

    # Close entire position via market order
    await order_service.close_position(position, reason="dte_threshold")
```

**Result**:
- All unfilled profit targets canceled
- Remaining contracts closed via market order
- Position lifecycle_state → "closed"
- Trade record created with lifecycle_event="dte_closure"

---

## Strategy-Specific Implementations

### Senex Trident (3 independent profit targets)

```python
# services/senex_trident_strategy.py
async def get_profit_target_specifications(self, position, **kwargs):
    return [
        ProfitTargetSpec(
            spread_type="put_spread_1_40",
            profit_percentage=40.0,
            quantity=1,
            # ... order details
        ),
        ProfitTargetSpec(
            spread_type="put_spread_2_60",
            profit_percentage=60.0,
            quantity=1,
            # ... order details
        ),
        ProfitTargetSpec(
            spread_type="call_spread_60",
            profit_percentage=60.0,
            quantity=1,
            # ... order details
        ),
    ]
```

**Lifecycle Example**:
```
Entry: 3 contracts @ $2.50 credit
    ↓
Target 1 (40%): Fills @ $1.50 → Realizes $100 profit (1 contract)
    Position: 2 contracts remaining, 2 targets active
    ↓
Target 2 (60%): Fills @ $1.00 → Realizes $150 profit (1 contract)
    Position: 1 contract remaining, 1 target active
    ↓
Target 3 (60%): Fills @ $1.00 → Realizes $175 profit (1 contract - call spread)
    Position: 0 contracts → lifecycle_state="closed"
    Total P&L: $425
```

### Bull Put Spread (single profit target)

```python
# services/bull_put_spread_strategy.py
async def get_profit_target_specifications(self, position, **kwargs):
    return [
        ProfitTargetSpec(
            spread_type="put_spread_50",
            profit_percentage=50.0,
            quantity=position.quantity,
            # ... order details
        ),
    ]
```

**Lifecycle Example**:
```
Entry: 1 contract @ $1.00 credit
    ↓
Target (50%): Fills @ $0.50 → Realizes $50 profit
    Position: 0 contracts → lifecycle_state="closed"
```

---

## Security & Validation

### Input Validation (CODE_REVIEW.md Issue #7)

All profit_target_details mutations pass through validation:

```python
from services.validation.profit_target_validator import validate_profit_target_details

# Before saving to database
position.profit_target_details = validate_profit_target_details(new_details)
```

**Validation Rules**:
- Maximum 10 profit targets per position
- Required fields: order_id, percent, target_price
- Percent range: 0 < percent <= 100
- Order ID length: <= 200 characters
- No unexpected fields allowed
- Numeric ranges enforced

### Notification Sanitization (CODE_REVIEW.md Issue #11)

Before sending profit_target_details via WebSocket/email:

```python
from services.validation.profit_target_validator import sanitize_for_notification

safe_details = sanitize_for_notification(position.profit_target_details)
await notification_service.send_notification(
    details={"target_details": safe_details}  # Sanitized
)
```

**Sanitization**:
- Truncates order_id to last 8 characters
- Removes internal fields (original_credit, target_price)
- Rounds P&L to 2 decimal places
- Validates structure before sending

---

## Monitoring & Observability

### Position State Tracking

```python
# Query positions by lifecycle state
open_full_positions = Position.objects.filter(lifecycle_state="open_full")
open_partial_positions = Position.objects.filter(lifecycle_state="open_partial")

# Track profit target fill rate
filled_targets = sum(
    1 for details in position.profit_target_details.values()
    if details.get("status") == "filled"
)
total_targets = len(position.profit_target_details)
fill_rate = filled_targets / total_targets if total_targets > 0 else 0
```

### Lifecycle Events Audit Trail

```python
# Retrieve all lifecycle events for a position
lifecycle_trades = Trade.objects.filter(
    position=position,
    lifecycle_event__isnull=False
).order_by("created_at")

for trade in lifecycle_trades:
    print(f"{trade.lifecycle_event}: {trade.realized_pnl} @ {trade.created_at}")
```

**Output Example**:
```
entry: None @ 2025-10-01 10:30:00
profit_target_fill: 65.00 @ 2025-10-02 14:15:00
profit_target_fill: 150.00 @ 2025-10-03 11:45:00
dte_closure: 50.00 @ 2025-10-15 09:35:00
```

---

## Performance Characteristics

### Real-Time Detection

- **AlertStreamer latency**: ~1 second from broker fill to detection
- **Processing time**: ~100ms for _handle_profit_target_fill
- **Database writes**: 2 queries (Position.asave + Trade.create)
- **WebSocket broadcast**: ~50ms to connected clients

### Scalability

**Current Design** (per-user isolation):
- Each user has dedicated UserStreamManager
- Profit target fills process independently
- No cross-user locking or contention

**Limits**:
- Max 10 profit targets per position (validated)
- Max positions per user: Database-limited (no hard cap)
- Concurrent fill handling: Sequential per position (no race condition protection yet)

---

## Known Limitations & Future Work

### Missing Features (CODE_REVIEW.md)

**Issue #5: Race Condition Testing**
- No integration tests for concurrent profit target fills
- Theoretical race condition if 2+ targets fill simultaneously
- Mitigation: Database transactions provide some protection
- **Priority**: P1 (tests needed)

**Issue #1: Position Quantity Race Condition**
- No optimistic locking on position.quantity updates
- Rare scenario: 2 fills processed in parallel could corrupt quantity
- **Priority**: P2 (low probability, high impact)

### Performance Optimizations (P2)

**Issue #9: Database Query Optimization**
- profit_target_details scanned linearly (O(n))
- Could use database index on order_id for faster lookups
- **Impact**: Minimal (max 10 targets per position)

**Issue #10: Notification Rate Limiting**
- No rate limiting for notification_service calls
- Rapid consecutive fills could spam user
- **Priority**: P2 (low probability)

---

## Integration Points

### Phase 2: DTE Management
- DTEManager cancels remaining profit targets at 7 DTE
- `services/position_lifecycle/dte_manager.py:close_position_at_dte`

### Phase 4: Trade Reconciliation
- Reconciliation service backfills missed profit target fills
- `trading/tasks.py:monitor_open_orders`

### Phase 5: Notifications
- NotificationService alerts user on profit target fills
- `services/notification_service.py:send_notification`

### Phase 6: Strategy Interface
- Strategies implement `get_profit_target_specifications()`
- Returns list of ProfitTargetSpec for position
- `services/strategies/base.py:BaseStrategy`

---

## Testing Strategy

### Unit Tests (Implemented)

```python
# tests/test_profit_targets.py
def test_calculate_profit_target_price_basic():
    """Test 40%/50%/60% profit target calculations."""

def test_senex_trident_profit_targets_specification():
    """Test Senex Trident 3-target structure."""
```

### Integration Tests (Missing - CODE_REVIEW.md Issue #5)

**Needed**:
```python
async def test_concurrent_profit_target_fills():
    """Verify position state correct when 2 targets fill simultaneously."""

async def test_profit_target_fill_then_dte_closure():
    """Verify DTE closure cancels remaining targets after partial fills."""

async def test_profit_target_details_updated_correctly():
    """Verify all fields populated in profit_target_details after fill."""
```

---

## Migration Guide

### From Single Profit Target Systems

**Old Model**:
```python
position.profit_target_order_id = "abc123"  # Single order
position.profit_target_percent = 50.0
```

**New Model**:
```python
position.profit_target_details = {
    "spread_50": {
        "order_id": "abc123",
        "percent": 50.0,
        "target_price": 0.50
    }
}
```

**Migration Steps**:
1. Read old `profit_target_order_id` and `profit_target_percent`
2. Create profit_target_details entry with spread_type key
3. Set profit_targets_created = True
4. Remove old fields

---

## References

### Implementation Files

- `streaming/services/stream_manager.py` - Profit target fill detection (lines 1058-1066, 1228-1379)
- `services/position_lifecycle/profit_calculator.py` - P&L calculations
- `services/position_lifecycle/dte_manager.py` - DTE-based closure and cancellation
- `services/validation/profit_target_validator.py` - Input validation and sanitization
- `trading/models.py` - Position.profit_target_details field definition (line 171)

### Planning Documents

- `/path/to/senextrader_docs/planning/profit-management/PHASE_3_PROFIT_TARGET_MONITORING.md`
- `/path/to/senextrader_docs/planning/profit-management/CODE_REVIEW.md`
- `/path/to/senextrader_docs/planning/profit-management/IMPLEMENTATION_CHECKLIST.md`

### Related Commits

- `e84cec2` - Phase 3-6 implementation
- `cf02b46` - Critical bug fixes (sign handling, profit_target_details update)

---

## Summary

The profit target lifecycle architecture enables **multiple independent profit targets per position**, allowing strategies to capture incremental profits as the market moves. Key design principles:

1. **Independence**: Each profit target fills independently without affecting others
2. **Safety**: DTE threshold cancels all remaining targets and closes position
3. **Transparency**: Complete audit trail via Trade.lifecycle_event records
4. **Security**: Validated inputs prevent malicious data injection
5. **Observability**: Real-time WebSocket updates and lifecycle state tracking

This architecture maximizes realized P&L opportunities while maintaining safety through DTE-based exit rules.

---

*For implementation details, see Phase 3-6 planning documents in `/path/to/senextrader_docs/planning/profit-management/`*
