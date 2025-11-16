# Reference Application Comparison

## Overview

This document compares the Docker implementation between the reference application (options_strategy_trader) and Senex Trader, identifying reusable patterns, key differences, and adaptation strategies.

---

## Side-by-Side Architecture Comparison

| Aspect | Options Strategy Trader (Reference) | Senex Trader | Adaptation Notes |
|--------|-------------------------------------|--------------|------------------|
| **Django Version** | 5.2.6 | 5.2.6 | ✅ Same |
| **Python Version** | 3.11 | 3.12 | ⚠️ Update Dockerfile base image |
| **Base Image** | `python:3.11-slim` | `python:3.12-slim-bookworm` | ✅ Direct replacement |
| **ASGI Server** | Not used (WSGI only) | Daphne (for WebSockets) | ⚠️ Add Daphne to requirements |
| **WSGI Server** | Gunicorn | Gunicorn or Daphne | ✅ Can reuse Gunicorn config |
| **Celery** | Yes (5.5.3) | Yes (5.5.3) | ✅ Same version |
| **PostgreSQL** | postgres:15-alpine | postgres:16-alpine | ✅ Upgrade version |
| **Redis** | redis:7-alpine | redis:7-alpine | ✅ Same |
| **Static Files** | WhiteNoise | WhiteNoise | ✅ Same pattern |
| **User Management** | Dynamic UID/GID via gosu | Static UID 1000 | ⚠️ Simplify (remove dynamic) |
| **Nginx** | Included (production) | Optional | ⚠️ WhiteNoise makes it optional |
| **SSL/TLS** | Let's Encrypt + Certbot | External (reverse proxy) | ⚠️ Delegate to infrastructure |
| **Logging** | Stdout/stderr | File-based + stdout | ⚠️ Align with container best practices |

---

## Detailed Feature Comparison

### 1. Dockerfile Structure

#### Reference Application (options_strategy_trader)

**File**: `/path/to/options_strategy_trader/docker/Dockerfile`

**Structure**: 3-stage multi-stage build
- **Stage 1 (base)**: System dependencies, user creation
- **Stage 2 (dependencies)**: Python package installation
- **Stage 3 (runtime)**: Application code, entrypoint

**Key Features**:
- Uses `gosu` for privilege dropping
- Dynamic UID/GID modification via PUID/PGID
- Health check with `curl`
- OCI-compliant labels
- Multi-service routing via entrypoint

**Senex Trader Adaptation**:
- ✅ Keep 3-stage build pattern
- ✅ Keep health check
- ⚠️ Simplify user management (remove gosu, use static UID 1000)
- ✅ Add Daphne for ASGI support
- ✅ Keep OCI labels

#### Code to Reuse

**Base Stage** (from reference):
```dockerfile
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app
```

**Adapt for Senex**:
```dockerfile
FROM python:3.12-slim-bookworm AS base  # Update Python version

# Same ENV and apt-get commands
# Change user name from 'app' to 'senex'
RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex
```

---

### 2. Entrypoint Script

#### Reference Application

**File**: `/path/to/options_strategy_trader/docker/entrypoint.sh`

**Features**:
- User permission modification (PUID/PGID)
- Database wait logic
- Static file collection
- Multi-service routing (web/worker/beat/flower)
- Privilege dropping with gosu

**Lines 22-52**: Dynamic UID/GID modification
**Lines 63-74**: Database wait
**Lines 76-82**: Initialization (migrate, collectstatic)
**Lines 84-121**: Service routing

**Senex Trader Adaptation**:
- ❌ Remove PUID/PGID modification (unnecessary complexity)
- ✅ Keep database wait logic
- ✅ Keep initialization logic
- ✅ Adapt service routing for Daphne
- ❌ Remove Flower (not used in Senex)

#### Code to Reuse

**Database Wait** (from reference, lines 63-74):
```bash
python << END
import sys
import time
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.wsgi')
django.setup()

from django.db import connection
from django.db.utils import OperationalError

for i in range(30):
    try:
        connection.ensure_connection()
        sys.exit(0)
    except OperationalError:
        time.sleep(2)
sys.exit(1)
END
```

**Adapt for Senex**:
```bash
# Change 'config.wsgi' to 'senextrader.settings.production'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.production')
```

---

### 3. Docker Compose Configuration

#### Reference Application

**File**: `/path/to/options_strategy_trader/docker/docker-compose.yml`

**Services**:
1. options_trader_db (PostgreSQL)
2. options_trader_redis (Redis)
3. options_trader_web (Django)
4. options_trader_celery_worker (Celery Worker)
5. options_trader_celery_beat (Celery Beat)
6. options_trader_nginx (Nginx - production profile)
7. certbot (SSL certificates - production profile)
8. flower (Celery monitoring - monitoring profile)

**Key Patterns**:
- Service profiles (production, monitoring)
- Health checks with conditions
- Volume sharing (staticfiles between Django and Nginx)
- Network isolation (app_network)
- Environment variable defaulting (`${VAR:-default}`)

**Senex Trader Adaptation**:
- ✅ Keep all core services (db, redis, web, worker, beat)
- ❌ Remove Nginx (WhiteNoise sufficient, SSL via external proxy)
- ❌ Remove Certbot (SSL managed externally)
- ❌ Remove Flower (can add later if needed)
- ✅ Keep service profiles pattern
- ✅ Keep health check pattern
- ✅ Keep network isolation

#### Code to Reuse

**Health Check Pattern** (from reference):
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

**Dependency Pattern** (from reference):
```yaml
depends_on:
  options_trader_db:
    condition: service_healthy
  options_trader_redis:
    condition: service_healthy
```

**Environment Variable Defaults** (from reference):
```yaml
environment:
  POSTGRES_DB: ${POSTGRES_DB:-options_trader}
  POSTGRES_USER: ${POSTGRES_USER:-postgres}
```

---

### 4. Requirements Management

#### Reference Application

**Structure**: Split requirements
- `requirements/base.txt` - Core dependencies
- `requirements/production.txt` - Production-only
- `requirements/development.txt` - Development-only

**Senex Trader Current**: Single `requirements.txt`

**Recommendation**: Adopt split requirements pattern

**Migration Path**:
```bash
# Create requirements/ directory
mkdir requirements

# Split into base/production/development
# base.txt: Django, DRF, Celery, TastyTrade SDK, Channels
# production.txt: -r base.txt + psycopg2, gunicorn, whitenoise
# development.txt: -r base.txt + pytest, black, ruff
```

**Benefits**:
- Smaller production images (no dev tools)
- Clearer dependency management
- Faster builds (fewer dependencies to install)

---

### 5. Gunicorn Configuration

#### Reference Application

**File**: `/path/to/options_strategy_trader/docker/gunicorn/gunicorn.conf.py`

**Features** (64 lines):
- Workers: `(CPU cores * 2) + 1`
- Timeout: 120s
- Max requests: 1000 (with jitter for memory leak prevention)
- Preload: True (better memory efficiency)
- Logging: stdout/stderr
- Process naming
- Request size limits
- Lifecycle hooks

**Senex Trader**: No gunicorn config (using Django runserver or Daphne)

**Recommendation**: Create gunicorn config for WSGI option

**Code to Reuse** (entire file, adapt paths):
```python
# gunicorn.conf.py
import multiprocessing

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"  # For WSGI only (use uvicorn.workers.UvicornWorker for ASGI)
worker_connections = 1000
timeout = 120

# Request handling
max_requests = 1000
max_requests_jitter = 50

# Application loading
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "senextrader_gunicorn"

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# User/Group
user = "senex"
group = "senex"
```

---

### 6. Nginx Configuration

#### Reference Application

**Files**:
- `/path/to/options_strategy_trader/nginx/nginx.conf` - Global config
- `/path/to/options_strategy_trader/nginx/conf.d/senextrader.conf` - Site config

**Features**:
- SSL/TLS configuration
- Static file serving (separate location blocks)
- Rate limiting
- WebSocket support
- Security headers
- Gzip compression

**Senex Trader Adaptation**:
- ❌ Not needed (WhiteNoise + external reverse proxy)
- ✅ Document Nginx reverse proxy config (minimal, SSL + proxy_pass only)
- ❌ Skip static file serving in Nginx (WhiteNoise handles it)

**Minimal Nginx Config for Senex** (external reverse proxy):
```nginx
upstream senex_backend {
    server localhost:8000;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/ssl/certs/your-domain.com.crt;
    ssl_certificate_key /etc/ssl/private/your-domain.com.key;

    # All requests to Django (WhiteNoise serves static files)
    location / {
        proxy_pass http://senex_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support
    location /ws/ {
        proxy_pass http://senex_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

### 7. .dockerignore

#### Reference Application

**File**: `/path/to/options_strategy_trader/.dockerignore` (117 lines)

**Categories**:
- Python cache files
- Virtual environments
- Django-specific (db.sqlite3, logs, media)
- IDEs
- Git
- Docker files
- Documentation
- Testing
- CI/CD
- Secrets
- OS files

**Senex Trader**: No .dockerignore

**Recommendation**: Adopt reference .dockerignore verbatim (generic patterns)

**Code to Reuse**: Entire file (no changes needed)

---

### 8. Logging Configuration

#### Reference Application

**Pattern**: Switched from file-based to stdout/stderr

**Reason**: Avoid volume permission issues, cloud-native pattern

**Implementation** (production.py):
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

**Senex Trader Current**: File-based logging at `/var/log/senextrader/`

**Recommendation**:
- Keep file-based for development (local debugging)
- Switch to stdout/stderr for production (container best practice)
- Add environment-based switching

**Code to Adapt**:
```python
# senextrader/settings/production.py
if os.environ.get('CONTAINER_MODE', 'false').lower() == 'true':
    # Container mode: log to stdout/stderr
    LOGGING = {
        'version': 1,
        'handlers': {
            'console': {'class': 'logging.StreamHandler'},
        },
        'root': {'handlers': ['console'], 'level': 'INFO'},
    }
else:
    # Traditional mode: log to files
    LOGGING = {
        # ... existing file-based config
    }
```

---

## Key Differences and Rationale

### 1. User Management

**Reference**: Dynamic UID/GID modification via PUID/PGID environment variables

**Senex**: Static UID/GID (1000)

**Rationale**:
- Podman rootless mode handles UID mapping automatically
- Dynamic modification adds complexity without benefit
- Static UID 1000 matches most host users

---

### 2. Nginx Inclusion

**Reference**: Nginx included as service (production profile)

**Senex**: Nginx external (separate reverse proxy)

**Rationale**:
- WhiteNoise serves static files efficiently
- Simpler container orchestration (fewer services)
- SSL/reverse proxy delegated to infrastructure layer
- More flexible deployment (any reverse proxy: Nginx, Traefik, Caddy, ALB)

---

### 3. ASGI vs WSGI

**Reference**: WSGI only (Gunicorn)

**Senex**: ASGI (Daphne) for WebSocket support

**Rationale**:
- Senex uses Django Channels for real-time streaming
- WebSocket support requires ASGI server
- Can still use Gunicorn with Uvicorn workers if needed

---

### 4. Celery Flower

**Reference**: Includes Flower (monitoring profile)

**Senex**: Omit initially

**Rationale**:
- Optional monitoring tool
- Can add later if needed
- Reduce initial complexity

---

### 5. PostgreSQL Version

**Reference**: postgres:15-alpine

**Senex**: postgres:16-alpine (upgrade)

**Rationale**:
- Newer version with performance improvements
- Better JSON/JSONB support
- Security patches

---

## Reusable Patterns

### Pattern 1: Multi-Stage Build

**Why**: Minimize image size by excluding build tools

**Reference Implementation**: 3-stage (base, dependencies, runtime)

**Senex Adoption**: ✅ Use same pattern

---

### Pattern 2: Health Checks with Conditions

**Why**: Ensure dependencies ready before starting dependents

**Reference Implementation**:
```yaml
depends_on:
  postgres:
    condition: service_healthy
```

**Senex Adoption**: ✅ Use same pattern

---

### Pattern 3: Service Profiles

**Why**: Conditional service inclusion (dev vs prod)

**Reference Implementation**:
```yaml
nginx:
  profiles:
    - production
```

**Senex Adoption**: ✅ Use for optional services

---

### Pattern 4: Environment Variable Defaults

**Why**: Sensible defaults with override capability

**Reference Implementation**:
```yaml
environment:
  POSTGRES_DB: ${POSTGRES_DB:-senextrader}
```

**Senex Adoption**: ✅ Use throughout compose files

---

### Pattern 5: Split Requirements

**Why**: Smaller production images

**Reference Implementation**: requirements/base.txt, requirements/production.txt, requirements/development.txt

**Senex Adoption**: ✅ Migrate to split pattern

---

## Migration Checklist

### Files to Create (from reference patterns)

- [ ] `docker/Dockerfile` (adapted from reference)
- [ ] `docker/Dockerfile.dev` (simplified single-stage)
- [ ] `docker/entrypoint.sh` (simplified, no gosu)
- [ ] `docker-compose.yml` (base configuration)
- [ ] `docker-compose.dev.yml` (development overrides)
- [ ] `docker-compose.prod.yml` (production overrides)
- [ ] `.dockerignore` (copy from reference)
- [ ] `.env.example` (environment variable template)
- [ ] `gunicorn/gunicorn.conf.py` (optional, for WSGI)

### Files to Update

- [ ] `requirements.txt` → Split into `requirements/base.txt`, `requirements/production.txt`, `requirements/development.txt`
- [ ] `senextrader/settings/production.py` → Add container-mode logging
- [ ] Add `psycopg2-binary` to production requirements
- [ ] Add `daphne` to requirements (ASGI server)
- [ ] Add `whitenoise` to requirements (if not present)

### Code Changes

- [ ] Create health check endpoint (`/health/`)
- [ ] Update settings for container environment variables
- [ ] Test database connection in entrypoint
- [ ] Ensure all services use environment variables (no hardcoded values)

---

## Summary

### Patterns to Adopt from Reference

1. ✅ **Multi-stage Dockerfile** - Minimize image size
2. ✅ **Health checks with conditions** - Proper startup order
3. ✅ **Service profiles** - Conditional service inclusion
4. ✅ **Split requirements** - Smaller production images
5. ✅ **Environment variable defaults** - Sensible defaults
6. ✅ **.dockerignore patterns** - Faster builds
7. ✅ **Database wait logic** - Robust initialization
8. ✅ **OCI labels** - Image metadata

### Patterns to Simplify for Senex

1. ❌ **Remove dynamic UID/GID** - Podman handles it
2. ❌ **Remove Nginx service** - WhiteNoise sufficient
3. ❌ **Remove Certbot** - SSL via external proxy
4. ❌ **Omit Flower initially** - Add later if needed
5. ⚠️ **Switch to ASGI** - Add Daphne for WebSockets

### Key Adaptations

- **Python 3.11 → 3.12** - Update base image
- **User 'app' → 'senex'** - Align with project name
- **WSGI → ASGI** - WebSocket support
- **File logs → stdout** - Container best practices
- **postgres:15 → postgres:16** - Newer version

**Next Steps**: See `implementation-requirements.md` for detailed code changes needed to implement containerization.
