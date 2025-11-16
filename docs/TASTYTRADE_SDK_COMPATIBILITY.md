# TastyTrade SDK Compatibility Guide

## Problem

The tastytrade Python SDK has different session class names across versions:
- **v10.3.0 and earlier**: Uses `OAuthSession`  
- **Later versions**: May use `Session` or different naming

When deploying code that works locally to production with a different SDK version, imports fail causing:
- **502 Bad Gateway** - Web containers crash on startup
- **Streamers fail** - Portfolio Greeks and real-time data unavailable  
- **Silent failures** - Services appear to run but don't function

## Solution: Compatibility Layer

Always use `SDKSession` which automatically works across SDK versions.

### Implementation

**File**: `services/brokers/tastytrade_session.py`
```python
# SDK version compatibility layer
try:
    from tastytrade import OAuthSession as SDKSession
except ImportError:
    from tastytrade import Session as SDKSession
```

### Usage

```python
# ✅ CORRECT
from services.brokers.tastytrade_session import SDKSession
session = SDKSession(...)

# ❌ WRONG - breaks with SDK version changes  
from tastytrade import OAuthSession
session = OAuthSession(...)
```

## Pre-Deployment Check

**ALWAYS run before deploying:**

```bash
./scripts/pre_deploy_check.sh
```

This catches SDK compatibility issues before deployment.

## Troubleshooting

### 502 Bad Gateway
```bash
podman logs web 2>&1 | grep ImportError
```

### Streamers Not Working
```bash
podman logs web 2>&1 | grep -i stream
```

## See Full Documentation

For complete details, see `docs/TASTYTRADE_SDK_COMPATIBILITY.md`
