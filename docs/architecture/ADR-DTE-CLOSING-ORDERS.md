# ADR: DTE Closing Orders Must Replace, Not Create Positions

**Date**: 2025-10-31
**Status**: Accepted
**Author**: System Architecture Team

## Context

During DTE (Days To Expiration) risk management, the system was creating NEW positions instead of closing existing ones. This critical bug occurred when order #417895808 was submitted as a new opening order with $0.10 bid price, rather than replacing the existing profit target order #410555945 with a higher closing price.

### The Problem

1. **Order Submission Without Context**: When `execute_order_spec()` submits an order to TastyTrade, it has no knowledge that this is meant to close an existing position.

2. **TastyTrade Interpretation**: Without explicit linkage, TastyTrade interprets:
   - Debit order on credit spread → Opening a new debit position
   - Credit order on debit spread → Opening a new credit position

3. **Result**: Duplicate positions accumulate instead of risk being eliminated.

## Decision

Create a Trade record with `trade_type="close"` BEFORE submitting the closing order, ensuring our system knows this is a closing trade even if the broker API doesn't support explicit position linkage.

### Implementation

```python
# BEFORE (Bug: Creates new position)
order_id = await execute_order_spec(order_spec)
await _record_closing_trade(position, legs, order_id)  # Too late!

# AFTER (Fixed: Closes existing position)
trade = await Trade.objects.acreate(
    position=position,
    trade_type="close",  # CRITICAL
    broker_order_id=temp_id,
    lifecycle_event="dte_close",
    # ... other fields
)
order_id = await execute_order_spec(order_spec)
trade.broker_order_id = order_id
await trade.asave()
```

## Consequences

### Positive

1. **Prevents Duplicate Positions**: System correctly identifies closing orders
2. **Audit Trail**: Trade record exists even if order submission fails
3. **State Consistency**: Position lifecycle properly tracked
4. **Error Handling**: Can update Trade with rejection reasons

### Negative

1. **Orphaned Records**: If order submission fails, Trade exists with temp ID
2. **Two-Phase Update**: Must update Trade after getting real order ID
3. **Not True Solution**: Still relies on application-level tracking

### Trade-offs Accepted

We accept the risk of orphaned Trade records (with proper error status) over the critical risk of creating duplicate positions.

## Alternatives Considered

### 1. Enhance TastyTrade SDK

**Approach**: Add "reduce_only" or position linkage to SDK
**Rejected Because**: Requires SDK changes outside our control

### 2. Use Different Order Submission Method

**Approach**: Create custom broker API calls with position context
**Rejected Because**: Breaks abstraction, increases complexity

### 3. Post-Submission Linking

**Approach**: Link order to position after submission
**Rejected Because**: Too late - broker already processed as new position

## Future Improvements

### Short Term
- Add `position_id` parameter to `execute_order_spec()`
- Implement order validation before submission

### Long Term
- Work with TastyTrade to add "reduce_only" flag
- Implement broker-agnostic position linkage
- Add real-time position reconciliation

## Validation

### Test Cases Required

1. **No New Position Test**: Verify Position.objects.create() not called
2. **Trade Linkage Test**: Verify Trade.position points to existing position
3. **Lifecycle Test**: Verify position.lifecycle_state → "closing"
4. **Error Handling Test**: Verify Trade updated on order rejection

### Monitoring

- Alert if Position created with `lifecycle_event` containing "dte"
- Track ratio of Trade records with temp vs real order IDs
- Monitor positions with lifecycle_state="closing" but no fills

## Decision Metrics

### Success Criteria
- Zero new positions created during DTE automation
- 100% of DTE closes have Trade.trade_type="close"
- No duplicate positions in production

### Failure Indicators
- Any position with duplicate symbols at same strikes
- Trade records with trade_type=None during DTE
- Positions at 0 DTE without closing attempts

## Related Documents

- [DTE_MANAGEMENT_PATTERN.md](../patterns/DTE_MANAGEMENT_PATTERN.md)
- [PROFIT_TARGET_LIFECYCLE.md](../patterns/PROFIT_TARGET_LIFECYCLE.md)
- Issue #417895808 - New position created instead of close

## Approval

This ADR is approved for immediate implementation due to the critical nature of the bug. The fix prevents financial risk from duplicate positions and ensures proper risk management at expiration.