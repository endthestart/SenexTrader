# Async/Sync Documentation Consolidation

**Date**: 2025-11-06
**Status**: Complete

## What Was Consolidated

All async/sync documentation has been consolidated into a single authoritative guide:

**Primary Document**: `docs/guides/ASYNC_SYNC_PATTERNS.md`

This guide now includes:
1. **6 Core Patterns** - Management commands, Celery tasks, scripts, services
2. **Common Mistakes & Fixes** - Real examples from production
3. **Decision Tree** - Quick reference for which pattern to use
4. **Historical Lessons** - Years of production issues and their resolutions
5. **Quick Reference Card** - At-a-glance guidance

## Previously Scattered Documentation

### Archived Files (Historical Reference Only)
- `docs/archive/ASYNC_FIX_COMPLETE.md` - ForeignKey async fix (Oct 2025)
- `docs/archive/EVENT_LOOP_CLOSURE_FIX.md` - Event loop management (Oct 2025)

### Planning Repository
- Various async mentions in task files (kept for historical context)
- No centralized async guide existed

### Lessons Integrated
1. **Event Loop Closure** - Don't add validation after `run_async()` closes loop
2. **ForeignKey Access** - Use `select_related()` in async queries
3. **Data Corruption** - Wrong async patterns caused Positions 33/34 corruption
4. **Redundant Validation** - Trust service layers
5. **Pattern Selection** - When to use `run_async` vs event loop pattern

## Updated References

### CLAUDE.md
- Added `docs/guides/ASYNC_SYNC_PATTERNS.md` as **first** required reading
- Marked as CRITICAL with warning about data corruption

### Why This Matters

Between Oct-Nov 2025, we encountered:
- Multiple `SynchronousOnlyOperation` errors in production
- Data corruption in Positions 33 & 34 from async/sync mix
- 15+ iterations to fix a simple script due to async confusion

This consolidation ensures:
- ✅ Single source of truth for async patterns
- ✅ Prevents future async-related data corruption
- ✅ Reduces development time (no more trial-and-error)
- ✅ Preserves hard-won lessons for the team

## For Future Developers

Before writing **any** code that touches Django ORM AND TastyTrade SDK:
1. Read `docs/guides/ASYNC_SYNC_PATTERNS.md`
2. Use the Decision Tree to pick your pattern
3. Follow the examples exactly
4. When in doubt, use Pattern 1 (Pure Sync + Event Loop) for management commands

**Remember**: Async/sync errors cause data corruption, not just runtime errors.
