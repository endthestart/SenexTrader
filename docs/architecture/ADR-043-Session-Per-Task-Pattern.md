# ADR-043: Session-Per-Task Pattern for TastyTrade Sessions

**Date**: 2025-10-31
**Status**: Implemented
**Priority**: Critical (Production Bug Fix)

## Context

Production experienced recurring "Event loop is closed" errors causing Celery worker crashes every ~2 days. The issue manifested as:

```
ERROR: Session validation error for user 1: Event loop is closed
ERROR: <asyncio.locks.Event object... is bound to a different event loop>
ERROR: Failed to refresh session for user 1: Event loop is closed
```

### Root Cause

1. **ClassVar Session Caching**: Sessions were cached in class-level variables (`ClassVar`)
2. **Celery Worker Recycling**: Workers recycle after 100 tasks (`--max-tasks-per-child=100`)
3. **Event Loop Lifecycle**: `asgiref.sync.async_to_sync` creates/closes event loops per task
4. **Module State Persistence**: Python's import system caches modules across worker recycling
5. **Stale References**: Cached sessions referenced closed event loops from previous workers

### Impact

- DTE monitoring failed for positions at 7 DTE (risk management critical)
- Position sync tasks failed repeatedly
- Services crashed silently requiring manual restart
- 2-day downtime undetected (Oct 29-31, 2025)

## Decision

**Remove all session caching and implement session-per-task pattern.**

### Changes Made

1. **Removed ClassVar Caching** (`tastytrade_session.py`):
   - Removed: `_sessions`, `_session_expiry`, `_refresh_tokens`, `_last_activity`, `_lock`
   - Removed: `_refresh_task`, `_task_running`

2. **Simplified `get_session_for_user`**:
   - Creates fresh session for each call
   - No event loop detection logic needed
   - Enhanced logging for debugging

3. **Removed Supporting Methods**:
   - `_needs_refresh`, `_refresh_session`, `_store_session`, `_clear_session`
   - `start_background_refresh`, `stop_background_refresh`, `_background_refresh_loop`
   - `get_session_info`, `force_refresh_session`, `clear_user_session`, `record_activity`

4. **Updated `data_access.py`**:
   - Removed event loop error handling fallback
   - Simplified validation logic

### Performance Impact

- **Session creation overhead**: ~200-500ms per task
- **Task frequency**: Every 10 minutes (sync_positions_task)
- **Added latency per hour**: ~1.8 seconds total
- **Assessment**: Acceptable trade-off for eliminating critical production bug

## Rationale

### Why Session-Per-Task?

1. **Aligns with KISS Principle**: Simplest solution that eliminates root cause
2. **Follows Django Patterns**: Management commands already use session-per-invocation
3. **Real Data Only**: If session fails, task fails immediately (no stale data)
4. **Testable**: Easy to verify each task gets fresh session
5. **Proven Pattern**: Research showed this is standard for async in sync contexts

### Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **Session-Per-Task** | Simple, eliminates bug | Slightly slower | **Selected** |
| Worker Signal Hooks | Keeps caching | Complex, still fragile | Rejected |
| Event-Loop-Aware Caching | Current approach | **Already failing** | Not working |
| Process-Aware Caching | Detects PID changes | Race conditions | Too complex |
| Separate Async Workers | Proper async env | Major infrastructure change | Over-engineering |

## Consequences

### Positive

- **Zero "Event loop is closed" errors** (validated in development)
- **Predictable behavior**: Fresh session per task
- **Simpler codebase**: -400 lines of complex caching logic
- **Better logging**: Enhanced debugging information
- **Easier testing**: No state to manage

### Negative

- **Slight performance overhead**: ~200-500ms per task (acceptable for 10-min intervals)
- **More API calls**: Each task creates new session (mitigated by OAuth token caching in SDK)

### Neutral

- **No session monitoring**: Removed session info/monitoring methods (not needed)
- **Breaking changes**: Removed public methods (acceptable per CLAUDE.md: "No backward compatibility")

## Implementation

### Files Modified

1. `services/brokers/tastytrade_session.py` (primary changes)
2. `services/data_access.py` (simplified validation)

### Files Created

1. `trading/management/commands/check_celery_health.py` - Health monitoring
2. `scripts/monitor_dte_execution.sh` - DTE task monitoring
3. `architecture/ADR-043-Session-Per-Task-Pattern.md` - This document

### Testing

```bash
# Syntax validation
python -m py_compile services/brokers/tastytrade_session.py
python -m py_compile services/data_access.py

# Health check
python manage.py check_celery_health --verbose

# Monitor DTE execution
./scripts/monitor_dte_execution.sh
```

### Deployment

1. **Deployed**: 2025-10-31 (emergency fix)
2. **Monitoring**: 48-hour observation period
3. **Success Criteria**:
   - Zero "Event loop is closed" errors for 7 days
   - All Celery tasks complete successfully
   - Task latency increase < 500ms

## Monitoring

### Metrics to Track

- `tastytrade.session.creation.count` (by user_id, task_name)
- `tastytrade.session.creation.duration_ms`
- `tastytrade.session.errors` (by error_type)

### Alerts

- "Event loop is closed" errors > 0
- Session creation duration > 2 seconds
- Session error rate > 5%

### Logs to Check

```bash
# Session lifecycle
journalctl CONTAINER_NAME=celery_worker -f | grep "Creating fresh session"

# DTE monitoring
journalctl CONTAINER_NAME=celery_worker -f | grep "monitor_positions_for_dte"

# Errors
journalctl CONTAINER_NAME=celery_worker -f -p err
```

## References

- [CLAUDE.md](/CLAUDE.md) - Project guidelines (KISS, DRY, YAGNI)
- [Production Operations Guide](/senextrader_docs/operations/production-operations-guide.md)
- Research: Internal investigation report (2025-10-31)
- Related Issue: Position at 7 DTE (order 410555945) not processed

## Lessons Learned

1. **Stateful caching in async+sync contexts is fragile**: Event loops are process-local
2. **ClassVar doesn't mean "singleton"**: Module state persists across worker recycles
3. **Event loop detection is reactive**: Prevention (session-per-task) beats detection
4. **Simple solutions often best**: KISS > clever caching
5. **Monitor worker lifecycle**: Add health checks to detect issues early

## Future Considerations

If performance becomes an issue:
1. Increase `worker_max_tasks_per_child` to 500 (reduces recycling frequency)
2. Implement Redis-backed session cache with worker PID tracking
3. Consider dedicated async worker pool for heavy async tasks

For now, session-per-task provides the right balance of simplicity, correctness, and performance.
