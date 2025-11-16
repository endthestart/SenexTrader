# Dockerfile Design for Senex Trader

## Overview

This document specifies the multi-stage Dockerfile design for Senex Trader, optimized for security, size, and build performance. The design follows 2025 best practices with Podman compatibility as a primary requirement.

---

## Design Principles

### 1. Multi-Stage Build
- **Stage 1 (base)**: System dependencies and user setup
- **Stage 2 (dependencies)**: Python package installation
- **Stage 3 (runtime)**: Minimal runtime image with application code

**Benefits**:
- 60-80% size reduction (from ~1GB to ~300-400MB)
- Build cache optimization (dependencies layer separate from code)
- Security (no build tools in final image)

### 2. Security First
- Non-root user (UID/GID 1000)
- Minimal attack surface (slim base image, no dev tools)
- No secrets in image layers
- Read-only root filesystem compatible

### 3. Podman Compatibility
- Rootless by default (non-root user from start)
- No docker-specific commands
- Compatible with podman-compose
- No host volume permission issues

### 4. Layer Optimization
- Strategic layer ordering (least to most frequently changed)
- BuildKit cache mounts for pip
- Combined RUN commands to reduce layers
- Effective .dockerignore patterns

---

## Base Image Selection

### Recommended: `python:3.12-slim-bookworm`

**Rationale**:
- ✅ Debian-based (excellent compatibility)
- ✅ Small footprint (~120MB base)
- ✅ Security updates from Debian
- ✅ All packages available (no musl libc issues)
- ✅ Well-tested for production

**Alternatives Considered**:

| Base Image | Size | Pros | Cons | Recommendation |
|------------|------|------|------|----------------|
| `python:3.12-alpine` | ~60MB | Smallest | Musl libc compatibility issues, slower builds | ❌ Avoid |
| `python:3.12-slim-bookworm` | ~120MB | Best balance | Slightly larger than Alpine | ✅ Use this |
| `python:3.12-bookworm` | ~900MB | Full Debian | Unnecessary packages | ❌ Too large |
| Distroless | ~80MB | Maximum security | Complex, no shell | ⚠️ Advanced use only |

**Alpine Issues for Senex Trader**:
- `psycopg2` requires compilation (no wheels available)
- `pandas` requires compilation (slow builds)
- `cryptography` requires Rust toolchain
- Build time increases from 5 minutes to 15+ minutes

---

## Multi-Stage Dockerfile Structure

### Complete Dockerfile Template

```dockerfile
# syntax=docker/dockerfile:1.4

# ============================================================================
# Stage 1: Base - System dependencies and user setup
# ============================================================================
FROM python:3.12-slim-bookworm AS base

# Set Python environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client libraries
    libpq-dev \
    libpq5 \
    # Cryptography dependencies
    libssl3 \
    libffi8 \
    # Utilities
    curl \
    ca-certificates \
    # gosu for privilege dropping (if running as root initially)
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex

# Create application directories
RUN mkdir -p /app /app/logs /app/staticfiles /app/media /var/log/senex_trader && \
    chown -R senex:senex /app /var/log/senex_trader

# Set working directory
WORKDIR /app

# ============================================================================
# Stage 2: Dependencies - Python package installation
# ============================================================================
FROM base AS dependencies

# Install build dependencies (needed for compiling Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip setuptools wheel

# Copy requirements files
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies with BuildKit cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ============================================================================
# Stage 3: Runtime - Final application image
# ============================================================================
FROM base AS runtime

# Copy Python packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=senex:senex . /app/

# Create entrypoint script
COPY --chown=senex:senex docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set ownership
RUN chown -R senex:senex /app

# Switch to non-root user
USER senex

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# Labels (OCI standard)
LABEL org.opencontainers.image.title="Senex Trader" \
      org.opencontainers.image.description="Automated options trading platform" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.vendor="Senex Trading"

# Entry point
ENTRYPOINT ["/entrypoint.sh"]

# Default command (can be overridden)
CMD ["web"]
```

---

## Layer Optimization Strategy

### Layer Ordering (Least to Most Frequently Changed)

1. **Base system dependencies** (rarely changes)
   - `apt-get install` commands
   - User creation
   - Directory creation

2. **Python dependencies** (changes monthly)
   - `requirements.txt` copy
   - `pip install` commands

3. **Application code** (changes frequently)
   - Source code copy
   - Static files

**Cache Efficiency**:
- Changing code does NOT invalidate dependency layers
- Most builds reuse cached dependency layer (5-second builds vs 5-minute full builds)

### Combined RUN Commands

**❌ Bad (Multiple Layers)**:
```dockerfile
RUN apt-get update
RUN apt-get install -y libpq-dev
RUN apt-get install -y libssl3
RUN rm -rf /var/lib/apt/lists/*
```
- Creates 4 layers
- Each layer persists (even after cleanup)
- Final image includes all intermediate state

**✅ Good (Single Layer)**:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*
```
- Creates 1 layer
- Cleanup in same layer reduces final image size
- Minimizes intermediate state

### BuildKit Cache Mounts

**Purpose**: Speed up repeated builds without invalidating layers

**Pip Cache Mount**:
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt
```

**Benefits**:
- Pip downloads cached across builds
- Dependencies not re-downloaded unless version changes
- Build time reduced from 5 minutes to 30 seconds for incremental changes

**Podman Compatibility**: Cache mounts work with `--layers` flag. Advanced cache export/import (`--cache-to`/`--cache-from`) requires Podman 4.4+ with Buildah backend.

---

## .dockerignore Design

### Purpose
Exclude files from build context to:
- Reduce build context size (faster uploads to builder)
- Prevent secrets from entering image layers
- Exclude development files from production images

### Recommended .dockerignore

```
# Python cache
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Virtual environments
venv/
env/
ENV/
.venv

# Django
*.log
db.sqlite3
db.sqlite3-journal
/staticfiles/
/media/

# Celery
celerybeat-schedule*

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# Git
.git/
.gitignore
.gitattributes

# Docker
.dockerignore
Dockerfile*
docker-compose*.yml
.env*

# Documentation
*.md
docs/

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/
.mypy_cache/
.ruff_cache/

# CI/CD
.github/
.gitlab-ci.yml

# Secrets (explicit exclusion)
*.key
*.pem
*.cert
*.crt
secrets/

# OS
.DS_Store
Thumbs.db

# Temporary files
*.tmp
*.temp
*.bak
```

**Size Impact**: Typical reduction from 500MB build context to 50MB

---

## User Management & Permissions

### Non-Root User Strategy

**Creation**:
```dockerfile
RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex
```

**Why UID/GID 1000**:
- Matches common host user UID/GID
- Reduces volume mount permission issues
- Podman rootless default mapping

**Ownership**:
```dockerfile
RUN chown -R senex:senex /app /var/log/senex_trader
```

**Switching**:
```dockerfile
USER senex
```

### Runtime UID/GID Modification (Optional)

**Use Case**: Match host permissions dynamically

**Approach**: Use entrypoint script to modify user at runtime

**entrypoint.sh**:
```bash
#!/bin/bash
set -e

# Modify user UID/GID if running as root and PUID/PGID set
if [ "$(id -u)" = "0" ] && [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "Modifying senex user to PUID=$PUID, PGID=$PGID"
    groupmod -o -g "$PGID" senex
    usermod -o -u "$PUID" senex
    chown -R senex:senex /app /var/log/senex_trader

    # Drop privileges and execute command as senex
    exec gosu senex "$@"
else
    # Already running as senex or no modification needed
    exec "$@"
fi
```

**Note**: This pattern is from reference application but adds complexity. Simpler to use fixed UID/GID 1000.

---

## Entrypoint Script Design

### Purpose
- Route commands to appropriate services (web, celery_worker, celery_beat)
- Perform initialization tasks (migrations, collectstatic)
- Wait for dependencies (PostgreSQL, Redis)

### Entrypoint Script Template

```bash
#!/bin/bash
set -e

# ============================================================================
# Senex Trader Container Entrypoint
# ============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Function: Wait for PostgreSQL
# ============================================================================
wait_for_postgres() {
    echo -e "${YELLOW}Waiting for PostgreSQL...${NC}"

    python << END
import sys
import time
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senex_trader.settings.${ENVIRONMENT:-production}')
django.setup()

from django.db import connection
from django.db.utils import OperationalError

max_retries = 30
retry_interval = 2

for i in range(max_retries):
    try:
        connection.ensure_connection()
        print("PostgreSQL is ready!")
        sys.exit(0)
    except OperationalError as e:
        print(f"PostgreSQL not ready (attempt {i+1}/{max_retries}): {e}")
        time.sleep(retry_interval)

print("Failed to connect to PostgreSQL after {max_retries} attempts")
sys.exit(1)
END
}

# ============================================================================
# Function: Wait for Redis
# ============================================================================
wait_for_redis() {
    echo -e "${YELLOW}Waiting for Redis...${NC}"

    python << END
import sys
import time
import redis
import os

redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
max_retries = 30
retry_interval = 2

for i in range(max_retries):
    try:
        r = redis.from_url(redis_url)
        r.ping()
        print("Redis is ready!")
        sys.exit(0)
    except Exception as e:
        print(f"Redis not ready (attempt {i+1}/{max_retries}): {e}")
        time.sleep(retry_interval)

print(f"Failed to connect to Redis after {max_retries} attempts")
sys.exit(1)
END
}

# ============================================================================
# Main Entrypoint Logic
# ============================================================================

echo -e "${GREEN}Starting Senex Trader container...${NC}"
echo "Command: $1"

# Determine service type from first argument
SERVICE_TYPE="${1:-web}"

# Wait for dependencies (all services need database and Redis)
wait_for_postgres
wait_for_redis

# Run initialization tasks (only for web service to avoid race conditions)
if [ "$SERVICE_TYPE" = "web" ] || [ "$SERVICE_TYPE" = "gunicorn" ] || [ "$SERVICE_TYPE" = "daphne" ]; then
    echo -e "${YELLOW}Running database migrations...${NC}"
    python manage.py migrate --noinput

    echo -e "${YELLOW}Collecting static files...${NC}"
    python manage.py collectstatic --noinput --clear

    echo -e "${GREEN}Initialization complete!${NC}"
fi

# Route to appropriate service
case "$SERVICE_TYPE" in
    web|daphne)
        echo -e "${GREEN}Starting Daphne ASGI server...${NC}"
        exec daphne -b 0.0.0.0 -p 8000 senex_trader.asgi:application
        ;;

    gunicorn)
        echo -e "${GREEN}Starting Gunicorn WSGI server (WebSockets not supported)...${NC}"
        exec gunicorn senex_trader.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 4 \
            --timeout 120 \
            --max-requests 1000 \
            --max-requests-jitter 50 \
            --access-logfile - \
            --error-logfile -
        ;;

    celery-worker|celery_worker|worker)
        echo -e "${GREEN}Starting Celery worker...${NC}"
        exec celery -A senex_trader worker \
            --loglevel=info \
            --queues=celery,accounts,trading \
            --concurrency=4 \
            --max-tasks-per-child=100
        ;;

    celery-beat|celery_beat|beat)
        echo -e "${GREEN}Starting Celery beat scheduler...${NC}"
        # Clean up old schedule files (they can become corrupted)
        rm -f /app/celerybeat-schedule*
        exec celery -A senex_trader beat \
            --loglevel=info \
            --pidfile=/tmp/celerybeat.pid \
            --schedule=/app/celerybeat-schedule
        ;;

    *)
        # Unknown command - pass through to shell
        echo -e "${YELLOW}Running custom command: $@${NC}"
        exec "$@"
        ;;
esac
```

### Entrypoint Features

1. **Dependency Waiting**: Ensures PostgreSQL and Redis are ready
2. **Initialization**: Runs migrations and collectstatic for web service
3. **Service Routing**: Routes to web/worker/beat based on command
4. **Error Handling**: Exits with non-zero code on failures
5. **Custom Commands**: Supports arbitrary commands (e.g., `python manage.py shell`)

---

## Build Arguments vs Environment Variables

### Build Arguments (ARG)

**Purpose**: Values used during image build

**Use Cases**:
- Python version selection
- Build-time feature flags
- Non-sensitive configuration

**Example**:
```dockerfile
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm
```

**Scope**: Only available during build (not in running container)

### Environment Variables (ENV)

**Purpose**: Values used at runtime

**Use Cases**:
- Database connection strings
- API keys
- Django settings module
- Debug flags

**Example**:
```dockerfile
ENV DJANGO_SETTINGS_MODULE=senex_trader.settings.production
ENV PYTHONUNBUFFERED=1
```

**Scope**: Available in running container (can be overridden)

### Combining ARG and ENV

**Pattern**: Use ARG for build-time defaults, ENV for runtime configuration

```dockerfile
ARG ENVIRONMENT=production
ENV ENVIRONMENT=${ENVIRONMENT}
```

**Result**: Build-time default can be overridden at build (`--build-arg ENVIRONMENT=dev`) or runtime (`-e ENVIRONMENT=dev`)

---

## Health Checks

### Dockerfile HEALTHCHECK

**Purpose**: Container orchestrator can detect unhealthy containers

**Syntax**:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1
```

**Parameters**:
- `--interval`: How often to run check (30 seconds)
- `--timeout`: Max time for check to complete (10 seconds)
- `--start-period`: Grace period for application startup (40 seconds)
- `--retries`: Consecutive failures before marking unhealthy (3)

**Command**:
- `curl -f`: Fail on HTTP errors (4xx, 5xx)
- `|| exit 1`: Return non-zero exit code on failure

### Application Health Endpoint

**Required**: `/health/` endpoint in Django

**Simple Implementation**:
```python
# accounts/views.py or dedicated health app
from django.http import JsonResponse
from django.db import connection

def health_check(request):
    """Simple health check endpoint."""
    try:
        # Test database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return JsonResponse({"status": "healthy"}, status=200)
    except Exception as e:
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)
```

**URL Configuration**:
```python
# senex_trader/urls.py
urlpatterns = [
    path('health/', health_check, name='health'),
    # ... other patterns
]
```

**Advanced Health Check**: See `implementation-requirements.md` for detailed health check with Redis/Celery checks

---

## Image Labels

### OCI Standard Labels

**Purpose**: Metadata for image identification and management

**Recommended Labels**:
```dockerfile
LABEL org.opencontainers.image.title="Senex Trader" \
      org.opencontainers.image.description="Automated options trading platform" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="Senex Trading <[email protected]>" \
      org.opencontainers.image.url="https://your-domain.com" \
      org.opencontainers.image.source="https://github.com/yourusername/senex_trader" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="2025-01-15T00:00:00Z"
```

**Dynamic Labels** (set at build time):
```bash
podman build \
  --label org.opencontainers.image.version="$(git describe --tags)" \
  --label org.opencontainers.image.revision="$(git rev-parse HEAD)" \
  --label org.opencontainers.image.created="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t senex_trader:latest .
```

---

## Size Optimization Techniques

### Target: <500MB Final Image

**Breakdown**:
- Base image (python:3.12-slim): ~120MB
- System dependencies: ~50MB
- Python packages: ~200-300MB
- Application code: ~10-20MB
- **Total**: ~380-490MB

### Optimization Checklist

1. ✅ **Use slim base image** (not full Debian)
2. ✅ **Multi-stage build** (exclude build tools)
3. ✅ **Clean apt cache** (`rm -rf /var/lib/apt/lists/*`)
4. ✅ **No pip cache in image** (`PIP_NO_CACHE_DIR=1`)
5. ✅ **Combined RUN commands** (reduce layers)
6. ✅ **Effective .dockerignore** (reduce build context)
7. ✅ **No unnecessary files** (exclude tests, docs)
8. ✅ **Optimize Python packages** (only production requirements)

### Advanced: Layer Squashing (Optional)

**Purpose**: Combine all layers into single layer (further size reduction)

**Podman Command**:
```bash
podman build --squash -t senex_trader:latest .
```

**Tradeoff**: Lose layer caching (slower subsequent builds)

**Recommendation**: Only use for final production images

---

## Podman-Specific Considerations

### Rootless by Default

**Key Difference**: Podman runs containers as non-root user by default

**Implications**:
- Non-root user (senex) is the default
- No need for `gosu` or privilege dropping
- Volume mounts automatically map to host user

**Benefit**: Better security out of the box

### UID/GID Mapping

**Podman Behavior**:
- Container UID 1000 maps to host UID (current user)
- No permission issues with volume mounts
- Seamless integration with host filesystem

**Docker Behavior**:
- Container UID 1000 is distinct from host
- May require `chown` on host volumes
- Can use `--user` flag to match host UID

### BuildKit Compatibility

**Podman Build**: Uses BuildKit-compatible backend in Podman 4.0+

**Cache Mounts**: Dockerfile `RUN --mount=type=cache` is fully supported with `--layers` flag

**Cache Export/Import**: `--cache-to`/`--cache-from` requires Podman 4.4+ (check your version)
```bash
# Recommended: Use --layers for automatic caching
podman build --layers -t senex_trader:latest .

# Advanced (Podman 4.4+): External cache
podman build --layers --cache-to type=local,dest=/tmp/buildcache .
```

### Docker Compose vs Podman Compose

**podman-compose**: Python-based Docker Compose alternative

**Compatibility**: ~95% compatible with docker-compose.yml syntax

**Installation**:
```bash
pip install podman-compose
```

**Usage**:
```bash
podman-compose up -d
```

**Differences**: See `podman-migration.md` for detailed comparison

---

## Development vs Production Images

### Development Image

**Purpose**: Fast iteration, debugging tools

**Dockerfile.dev**:
```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=senex_trader.settings.development

# Install all dependencies (including dev tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create user
RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex

WORKDIR /app

# Install Python packages (dev requirements)
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Switch to non-root user
USER senex

# No code copy (use volume mount for live reload)
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

**Key Differences**:
- Single-stage (simplicity over size)
- Includes dev tools (pytest, black, ruff)
- No code copy (mount as volume for live reload)
- Django runserver (auto-reload)

### Production Image

**Purpose**: Minimal, secure, optimized

**Key Differences**:
- Multi-stage build (size optimization)
- Only production dependencies
- Code baked into image (immutable)
- Daphne/Gunicorn (production ASGI/WSGI)
- Health checks
- OCI labels

---

## Build Performance Optimization

### Parallel Builds

**BuildKit Parallel Stages**: Automatically parallelizes independent stages

**Example**:
```dockerfile
# These two stages can build in parallel if independent
FROM base AS dependencies
RUN pip install -r requirements.txt

FROM base AS staticfiles
RUN python manage.py collectstatic --noinput
```

### Build Cache Strategy

**Recommended: Built-in Layer Caching**:
```bash
# Podman caches layers automatically with --layers
podman build --layers -t senex_trader:latest .

# Subsequent builds reuse cached layers
podman build --layers -t senex_trader:latest .
```

**Advanced: External Cache** (Podman 4.4+ only):
```bash
# Local cache export
podman build --layers --cache-to type=local,dest=/tmp/buildcache .

# Local cache import
podman build --layers --cache-from type=local,src=/tmp/buildcache .
```

### Remote Cache (CI/CD)

**Note**: Registry-based cache requires Podman 4.4+ with Buildah backend. Verify support before using in CI/CD.

**Registry-based Cache** (if supported):
```bash
# Push cache to registry
podman build --cache-to type=registry,ref=myregistry.com/senex_trader:buildcache .

# Pull cache from registry
podman build --cache-from type=registry,ref=myregistry.com/senex_trader:buildcache .
```

**Alternative**: Use `--layers` and let Podman's built-in caching handle it (more reliable).

---

## Testing the Image

### Build Test

```bash
podman build -t senex_trader:test .
```

### Size Test

```bash
podman images senex_trader:test
# Verify size < 500MB
```

### Run Test

```bash
podman run --rm \
  -e SECRET_KEY=test-secret-key \
  -e FIELD_ENCRYPTION_KEY=test-encryption-key \
  senex_trader:test python manage.py check
```

### Health Check Test

```bash
podman run -d --name senex_test \
  -e SECRET_KEY=test-secret-key \
  -e FIELD_ENCRYPTION_KEY=test-encryption-key \
  -e DB_NAME=test \
  -p 8000:8000 \
  senex_trader:test

# Wait for startup
sleep 10

# Test health endpoint
curl -f http://localhost:8000/health/

# Cleanup
podman stop senex_test
podman rm senex_test
```

---

## Summary

The Dockerfile design for Senex Trader provides:

- ✅ **Multi-Stage Build**: 60-80% size reduction
- ✅ **Security**: Non-root user, minimal attack surface
- ✅ **Podman Compatibility**: Rootless by default
- ✅ **Layer Optimization**: Effective caching for fast builds
- ✅ **Flexible Entry Point**: Routes to web/worker/beat services
- ✅ **Health Checks**: Container orchestrator integration
- ✅ **Size Target**: <500MB final image
- ✅ **Development Support**: Separate Dockerfile.dev for iteration

**Next Steps**:
- See `environment-variables.md` for complete variable reference
- See `build-workflow.md` for build and push commands
- See `docker-compose-strategy.md` for orchestration
