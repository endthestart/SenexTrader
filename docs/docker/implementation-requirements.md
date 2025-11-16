# Implementation Requirements

## Overview

This document specifies all code changes, files to create, and configurations required to implement Docker/Podman containerization for Senex Trader. Each requirement includes file paths, code snippets, and rationale.

---

## File Creation Requirements

### 1. Docker Directory Structure

**Create**: `docker/` directory in project root

```bash
mkdir -p docker/gunicorn
```

**Files to create**:
- `docker/Dockerfile`
- `docker/Dockerfile.dev`
- `docker/entrypoint.sh`
- `docker/gunicorn/gunicorn.conf.py`

---

### 2. Dockerfile (Production)

**File**: `docker/Dockerfile`

**Purpose**: Multi-stage production image build

**Size Target**: <500 MB

**Required Content** (see `dockerfile-design.md` for complete version):

```dockerfile
# syntax=docker/dockerfile:1.4

FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libpq5 \
    libssl3 \
    libffi8 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex

RUN mkdir -p /app /app/logs /app/staticfiles /app/media /var/log/senextrader && \
    chown -R senex:senex /app /var/log/senextrader

WORKDIR /app

FROM base AS dependencies

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

COPY requirements.txt /tmp/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt

FROM base AS runtime

COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

COPY --chown=senex:senex . /app/

COPY --chown=senex:senex docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN chown -R senex:senex /app

USER senex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

LABEL org.opencontainers.image.title="Senex Trader" \
      org.opencontainers.image.description="Automated options trading platform" \
      org.opencontainers.image.version="1.0.0"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["web"]
```

---

### 3. Dockerfile.dev (Development)

**File**: `docker/Dockerfile.dev`

**Purpose**: Simplified development image with hot-reload

**Required Content**:

```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=senextrader.settings.development

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex

WORKDIR /app

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

USER senex

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

---

### 4. Entrypoint Script

**File**: `docker/entrypoint.sh`

**Purpose**: Service routing, initialization, dependency waiting

**Required Content** (see `dockerfile-design.md` for complete version):

```bash
#!/bin/bash
set -e

echo "Starting Senex Trader container..."
echo "Command: $1"

SERVICE_TYPE="${1:-web}"

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
python << END
import sys, time, os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.${ENVIRONMENT:-production}')
django.setup()
from django.db import connection
from django.db.utils import OperationalError
for i in range(30):
    try:
        connection.ensure_connection()
        print("PostgreSQL is ready!")
        sys.exit(0)
    except OperationalError as e:
        print(f"PostgreSQL not ready (attempt {i+1}/30): {e}")
        time.sleep(2)
print("Failed to connect to PostgreSQL")
sys.exit(1)
END

# Wait for Redis
echo "Waiting for Redis..."
python << END
import sys, time, redis, os
redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
for i in range(30):
    try:
        r = redis.from_url(redis_url)
        r.ping()
        print("Redis is ready!")
        sys.exit(0)
    except Exception as e:
        print(f"Redis not ready (attempt {i+1}/30): {e}")
        time.sleep(2)
print("Failed to connect to Redis")
sys.exit(1)
END

# Run initialization for web service
if [ "$SERVICE_TYPE" = "web" ] || [ "$SERVICE_TYPE" = "daphne" ]; then
    echo "Running database migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear

    echo "Initialization complete!"
fi

# Route to service
case "$SERVICE_TYPE" in
    web|daphne)
        echo "Starting Daphne ASGI server..."
        exec daphne -b 0.0.0.0 -p 8000 senextrader.asgi:application
        ;;

    gunicorn)
        echo "Starting Gunicorn WSGI server..."
        exec gunicorn senextrader.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 4 \
            --timeout 120 \
            --access-logfile - \
            --error-logfile -
        ;;

    celery-worker|worker)
        echo "Starting Celery worker..."
        exec celery -A senextrader worker \
            --loglevel=info \
            --queues=celery,accounts,trading \
            --concurrency=4 \
            --max-tasks-per-child=100
        ;;

    celery-beat|beat)
        echo "Starting Celery beat..."
        rm -f /app/celerybeat-schedule*
        exec celery -A senextrader beat \
            --loglevel=info \
            --pidfile=/tmp/celerybeat.pid \
            --schedule=/app/celerybeat-schedule
        ;;

    *)
        echo "Running custom command: $@"
        exec "$@"
        ;;
esac
```

**Make executable**:
```bash
chmod +x docker/entrypoint.sh
```

---

### 5. Docker Compose Files

**File**: `docker-compose.yml` (base configuration)

**Purpose**: Shared service definitions

**Required Content** (see `docker-compose-strategy.md` for complete version):

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME:-senextrader}
      POSTGRES_USER: ${DB_USER:-senex_user}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - senex_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-senex_user} -d ${DB_NAME:-senextrader}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks:
      - senex_network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    build:
      context: .
      dockerfile: docker/Dockerfile
    command: web
    environment:
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
      DB_HOST: postgres
      REDIS_URL: redis://redis:6379/0
      # ... (see docker-compose-strategy.md for complete list)
    volumes:
      - logs:/var/log/senextrader
      - staticfiles:/app/staticfiles
    networks:
      - senex_network
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile
    command: celery-worker
    environment:
      # Same as web
    volumes:
      - logs:/var/log/senextrader
    networks:
      - senex_network
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery_beat:
    build:
      context: .
      dockerfile: docker/Dockerfile
    command: celery-beat
    environment:
      # Same as web
    volumes:
      - logs:/var/log/senextrader
      - celerybeat_schedule:/app
    networks:
      - senex_network
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

volumes:
  postgres_data:
  redis_data:
  logs:
  staticfiles:
  celerybeat_schedule:

networks:
  senex_network:
    driver: bridge
```

**File**: `docker-compose.dev.yml` (development overrides)

**File**: `docker-compose.prod.yml` (production overrides)

See `docker-compose-strategy.md` for complete versions.

---

### 6. .dockerignore

**File**: `.dockerignore`

**Purpose**: Exclude unnecessary files from build context

**Required Content** (copy from reference application):

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

# Git
.git/
.gitignore

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

# Secrets
*.key
*.pem
*.cert
secrets/

# OS
.DS_Store
Thumbs.db
```

---

### 7. Environment File Templates

**File**: `.env.example`

**Purpose**: Template for development environment

**Required Content** (see `environment-variables.md` for complete version):

```bash
# Django Core
ENVIRONMENT=development
SECRET_KEY=django-insecure-dev-key-CHANGE-THIS
FIELD_ENCRYPTION_KEY=dev-key-CHANGE-THIS
ALLOWED_HOSTS=localhost,127.0.0.1
WS_ALLOWED_ORIGINS=http://localhost:8000
APP_BASE_URL=http://localhost:8000

# Database (SQLite for dev)
# No DB_* variables needed

# Redis
REDIS_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/2
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/3

# TastyTrade (sandbox)
TASTYTRADE_CLIENT_ID=your-dev-client-id
TASTYTRADE_CLIENT_SECRET=your-dev-client-secret
TASTYTRADE_BASE_URL=https://api.cert.tastyworks.com
```

**File**: `.env.production.example`

**Purpose**: Template for production environment (never commit actual .env.production)

See `environment-variables.md` for complete version.

---

## Code Changes Required

### 1. Add Missing Dependencies

**File**: `requirements.txt`

**Add**:
```
psycopg2-binary>=2.9.9    # PostgreSQL driver (production)
daphne>=4.2.1              # ASGI server for WebSockets
whitenoise>=6.6.0          # Static file serving
gunicorn>=21.2.0           # WSGI server (optional)
```

**Recommendation**: Migrate to split requirements (see `reference-comparison.md`)

---

### 2. Create Health Check Endpoint

**File**: `accounts/views.py` (or create `health/views.py`)

**Add**:
```python
from django.http import JsonResponse
from django.db import connection
import redis
import os


def health_check(request):
    """
    Simple health check endpoint for container health checks.
    Tests database and Redis connectivity.
    """
    try:
        # Test database
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        # Test Redis
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis.from_url(redis_url)
        r.ping()

        return JsonResponse({"status": "healthy"}, status=200)
    except Exception as e:
        return JsonResponse(
            {"status": "unhealthy", "error": str(e)},
            status=500
        )


def health_check_simple(request):
    """
    Ultra-simple health check (no dependencies).
    Use for liveness probes.
    """
    return JsonResponse({"status": "ok"}, status=200)
```

**File**: `senextrader/urls.py`

**Add**:
```python
from accounts.views import health_check, health_check_simple

urlpatterns = [
    # ... existing patterns
    path('health/', health_check, name='health'),
    path('health/simple/', health_check_simple, name='health-simple'),
]
```

---

### 3. Update Production Settings for Containers

**File**: `senextrader/settings/production.py`

**Add/Modify**:

```python
import os

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Allowed hosts from environment
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

# Database (PostgreSQL)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'senextrader'),
        'USER': os.environ.get('DB_USER', 'senex_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,  # Connection pooling
        'OPTIONS': {
            'sslmode': os.environ.get('DB_SSL_MODE', 'prefer'),
        },
    }
}

# Redis
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Cache
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Celery
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/2')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/3')

# Channels
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
            'capacity': 1500,
            'expiry': 60,
            'group_expiry': 300,
        },
    },
}

# Static files (WhiteNoise)
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Container-mode logging (stdout/stderr)
if os.environ.get('CONTAINER_MODE', 'false').lower() == 'true':
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'format': '{levelname} {name} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
            'trading': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
        },
    }
```

---

### 4. Ensure Celery App Configuration

**File**: `senextrader/celery.py`

**Verify/Update**:

```python
import os
from celery import Celery

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.production')

# Determine settings module based on ENVIRONMENT
environment = os.environ.get('ENVIRONMENT', 'production')
if environment == 'production':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.production')
else:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senextrader.settings.development')

app = Celery('senextrader')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

---

### 5. Update .gitignore

**File**: `.gitignore`

**Add**:
```
# Docker
.env
.env.production
.env.local
.env.*.local

# Container volumes
postgres_data/
redis_data/

# Static files
staticfiles/
```

---

## Optional Enhancements

### 1. Gunicorn Configuration (Optional)

**File**: `docker/gunicorn/gunicorn.conf.py`

**Purpose**: Production WSGI server config (if using Gunicorn instead of Daphne)

See `reference-comparison.md` for complete version.

---

### 2. Makefile for Build Automation

**File**: `Makefile`

**Purpose**: Simplify build/test/push commands

See `build-workflow.md` for complete version.

---

### 3. CI/CD Integration

**File**: `.github/workflows/build-and-push.yml`

**Purpose**: Automated builds on push/PR

See `build-workflow.md` for complete version.

---

## Implementation Checklist

### Phase 1: File Creation
- [ ] Create `docker/` directory
- [ ] Create `docker/Dockerfile`
- [ ] Create `docker/Dockerfile.dev`
- [ ] Create `docker/entrypoint.sh` (make executable)
- [ ] Create `docker-compose.yml`
- [ ] Create `docker-compose.dev.yml`
- [ ] Create `docker-compose.prod.yml`
- [ ] Create `.dockerignore`
- [ ] Create `.env.example`
- [ ] Create `.env.production.example`

### Phase 2: Dependency Updates
- [ ] Add `psycopg2-binary` to requirements
- [ ] Add `daphne` to requirements
- [ ] Add `whitenoise` to requirements
- [ ] Add `gunicorn` to requirements (optional)
- [ ] Consider migrating to split requirements

### Phase 3: Code Changes
- [ ] Create health check endpoints
- [ ] Update `urls.py` to include health endpoints
- [ ] Update `production.py` settings for containers
- [ ] Verify Celery app configuration
- [ ] Update `.gitignore`

### Phase 4: Testing
- [ ] Test local build: `podman build -t senextrader:test .`
- [ ] Test Django check: `podman run --rm -e SECRET_KEY=test -e FIELD_ENCRYPTION_KEY=test senextrader:test python manage.py check`
- [ ] Test development compose: `podman-compose -f docker-compose.yml -f docker-compose.dev.yml up`
- [ ] Verify all services healthy
- [ ] Test application functionality
- [ ] Create superuser and test admin

### Phase 5: Documentation
- [ ] Document build process
- [ ] Document deployment process
- [ ] Update README with Docker instructions
- [ ] Create runbook for operations team

### Phase 6: Production Deployment
- [ ] Generate production secrets
- [ ] Create `.env.production` with real values
- [ ] Build production images
- [ ] Test in staging environment
- [ ] Deploy to production
- [ ] Configure systemd for auto-start
- [ ] Set up monitoring
- [ ] Configure backups

---

## Validation Tests

### Build Validation

**Test 1**: Dockerfile builds successfully
```bash
podman build -f docker/Dockerfile -t senextrader:test .
```
**Expected**: Build completes, image <500 MB

**Test 2**: Django check passes
```bash
podman run --rm \
  -e SECRET_KEY=test-key \
  -e FIELD_ENCRYPTION_KEY=test-key \
  senextrader:test \
  python manage.py check
```
**Expected**: "System check identified no issues"

**Test 3**: Entry point routing works
```bash
podman run --rm senextrader:test web --help
```
**Expected**: Daphne help output

### Compose Validation

**Test 4**: Services start
```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
**Expected**: All services healthy

**Test 5**: Health endpoint responds
```bash
curl http://localhost:8000/health/
```
**Expected**: `{"status": "healthy"}`

**Test 6**: Admin accessible
```bash
curl -I http://localhost:8000/admin/
```
**Expected**: HTTP 302 (redirect to login)

---

## Summary

**Implementation requires**:

- ✅ **10 New Files**: Dockerfile, compose files, entrypoint, .dockerignore, env templates
- ✅ **4 Dependencies**: psycopg2-binary, daphne, whitenoise, gunicorn (optional)
- ✅ **3 Code Changes**: Health endpoints, production settings, gitignore
- ✅ **6 Validation Tests**: Build, check, entry point, compose, health, admin
- ✅ **6 Implementation Phases**: File creation, dependencies, code, testing, docs, deployment

**Estimated Effort**: 4-8 hours for complete implementation

**Next Steps**:
1. Create all required files (Phase 1)
2. Update dependencies (Phase 2)
3. Make code changes (Phase 3)
4. Test locally (Phase 4)
5. Document (Phase 5)
6. Deploy to production (Phase 6)

**Reference**: All other documentation files in `/path/to/senextrader_docs/docker/` provide detailed guidance for each component.
