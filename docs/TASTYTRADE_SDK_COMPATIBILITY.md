# TastyTrade SDK Compatibility Guide

## Problem

The tastytrade Python SDK has different session class names across versions:
- **v10.3.0 and earlier**: Uses `OAuthSession`  
- **Later versions**: Uses `Session`

When deploying code that works locally to production with a different SDK version, imports fail causing:
- **502 Bad Gateway** - Web containers crash on startup
- **Streamers fail** - Portfolio Greeks and real-time data unavailable  
- **Silent failures** - Services appear to run but don't function

## Current Implementation

The codebase uses `Session` directly from the tastytrade SDK.

**File**: `services/brokers/tastytrade/session.py`
```python
from tastytrade import Session
```

## Pre-Deployment Check

Ensure SDK version compatibility by reviewing:
- `docs/deployment/checklists/pre-deployment-checklist.md`
- Local and production `requirements.txt` for tastytrade version

## Troubleshooting

### 502 Bad Gateway
```bash
podman logs web 2>&1 | grep ImportError
```

### Streamers Not Working
```bash
podman logs web 2>&1 | grep -i stream
```
