# Docker Compose Strategy

## Overview

This document defines the Docker Compose orchestration strategy for Senex Trader, including development and production configurations, service definitions, health checks, dependency management, and volume strategies.

---

## Compose File Structure

### File Organization

```
project_root/
├── docker-compose.yml              # Base configuration (shared)
├── docker-compose.dev.yml          # Development overrides
├── docker-compose.prod.yml         # Production overrides
├── .env                            # Development environment variables
├── .env.production                 # Production environment variables (not in git)
└── docker/
    ├── Dockerfile                  # Production Dockerfile
    ├── Dockerfile.dev              # Development Dockerfile
    └── entrypoint.sh               # Shared entrypoint script
```

### Usage Pattern

**Development**:
```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Production**:
```bash
podman-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Base Configuration (docker-compose.yml)

### Complete Base Compose File

```yaml
version: '3.8'

services:
  # ==========================================================================
  # PostgreSQL Database
  # ==========================================================================
  postgres:
    image: postgres:16-alpine
    container_name: senex_postgres
    restart: unless-stopped
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
      start_period: 10s

  # ==========================================================================
  # Redis Cache/Broker
  # ==========================================================================
  redis:
    image: redis:7-alpine
    container_name: senex_redis
    restart: unless-stopped
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
      start_period: 10s

  # ==========================================================================
  # Django Web Application
  # ==========================================================================
  web:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: senex_web
    restart: unless-stopped
    command: web
    environment:
      # Django Core
      ENVIRONMENT: ${ENVIRONMENT:-production}
      DJANGO_SETTINGS_MODULE: ${DJANGO_SETTINGS_MODULE:-}
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
      ALLOWED_HOSTS: ${ALLOWED_HOSTS}
      WS_ALLOWED_ORIGINS: ${WS_ALLOWED_ORIGINS}
      APP_BASE_URL: ${APP_BASE_URL}

      # Database
      DB_NAME: ${DB_NAME:-senextrader}
      DB_USER: ${DB_USER:-senex_user}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_HOST: postgres
      DB_PORT: 5432

      # Redis
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade API
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET}
      TASTYTRADE_BASE_URL: ${TASTYTRADE_BASE_URL:-}

      # Security
      SECURE_SSL_REDIRECT: ${SECURE_SSL_REDIRECT:-False}
      SECURE_HSTS_SECONDS: ${SECURE_HSTS_SECONDS:-0}

      # Email (optional)
      EMAIL_HOST: ${EMAIL_HOST:-}
      EMAIL_PORT: ${EMAIL_PORT:-587}
      EMAIL_USE_TLS: ${EMAIL_USE_TLS:-True}
      EMAIL_HOST_USER: ${EMAIL_HOST_USER:-}
      EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD:-}
      DEFAULT_FROM_EMAIL: ${DEFAULT_FROM_EMAIL:-[email protected]}

      # Monitoring (optional)
      SENTRY_DSN: ${SENTRY_DSN:-}
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

  # ==========================================================================
  # Celery Worker
  # ==========================================================================
  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: senex_celery_worker
    restart: unless-stopped
    command: celery-worker
    environment:
      # Django Core
      ENVIRONMENT: ${ENVIRONMENT:-production}
      DJANGO_SETTINGS_MODULE: ${DJANGO_SETTINGS_MODULE:-}
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}

      # Database
      DB_NAME: ${DB_NAME:-senextrader}
      DB_USER: ${DB_USER:-senex_user}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_HOST: postgres
      DB_PORT: 5432

      # Redis
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade API
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET}
      TASTYTRADE_BASE_URL: ${TASTYTRADE_BASE_URL:-}
    volumes:
      - logs:/var/log/senextrader
    networks:
      - senex_network
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # ==========================================================================
  # Celery Beat Scheduler
  # ==========================================================================
  celery_beat:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: senex_celery_beat
    restart: unless-stopped
    command: celery-beat
    environment:
      # Django Core
      ENVIRONMENT: ${ENVIRONMENT:-production}
      DJANGO_SETTINGS_MODULE: ${DJANGO_SETTINGS_MODULE:-}
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}

      # Database
      DB_NAME: ${DB_NAME:-senextrader}
      DB_USER: ${DB_USER:-senex_user}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_HOST: postgres
      DB_PORT: 5432

      # Redis
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade API
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET}
      TASTYTRADE_BASE_URL: ${TASTYTRADE_BASE_URL:-}
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

# ============================================================================
# Volumes
# ============================================================================
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  logs:
    driver: local
  staticfiles:
    driver: local
  celerybeat_schedule:
    driver: local

# ============================================================================
# Networks
# ============================================================================
networks:
  senex_network:
    driver: bridge
```

---

## Development Override (docker-compose.dev.yml)

### Purpose
- Use SQLite instead of PostgreSQL (simpler setup)
- Mount source code as volume (live reload)
- Expose all service ports for debugging
- Use development Dockerfile

### Complete Development Override

```yaml
version: '3.8'

services:
  # Development doesn't need PostgreSQL (uses SQLite)
  postgres:
    profiles:
      - full  # Only start if 'full' profile specified

  # Development Redis (still needed for Celery and Channels)
  redis:
    container_name: senex_redis_dev
    ports:
      - "6379:6379"  # Expose for redis-cli debugging

  # Development Web Server
  web:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
    container_name: senex_web_dev
    command: python manage.py runserver 0.0.0.0:8000
    environment:
      ENVIRONMENT: development
      DJANGO_SETTINGS_MODULE: senextrader.settings.development
      SECRET_KEY: django-insecure-dev-key-for-local-only
      FIELD_ENCRYPTION_KEY: dev-encryption-key-local-only
      ALLOWED_HOSTS: localhost,127.0.0.1
      WS_ALLOWED_ORIGINS: http://localhost:8000,http://127.0.0.1:8000
      APP_BASE_URL: http://localhost:8000

      # No PostgreSQL config (uses SQLite)

      # Redis (local)
      REDIS_URL: redis://redis:6379/1
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade (sandbox)
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID:-}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET:-}
      TASTYTRADE_BASE_URL: https://api.cert.tastyworks.com

      # Security (disabled for dev)
      SECURE_SSL_REDIRECT: False
    ports:
      - "8000:8000"  # Expose for direct access
    volumes:
      - .:/app  # Mount source code for live reload
      - ./logs:/var/log/senextrader
    depends_on:
      - redis
    healthcheck:
      disable: true  # Disable health check for faster startup

  # Development Celery Worker
  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
    container_name: senex_celery_worker_dev
    command: celery -A senextrader worker --loglevel=debug --queues=celery,accounts,trading
    environment:
      ENVIRONMENT: development
      DJANGO_SETTINGS_MODULE: senextrader.settings.development
      SECRET_KEY: django-insecure-dev-key-for-local-only
      FIELD_ENCRYPTION_KEY: dev-encryption-key-local-only

      # Redis (local)
      REDIS_URL: redis://redis:6379/1
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade (sandbox)
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID:-}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET:-}
      TASTYTRADE_BASE_URL: https://api.cert.tastyworks.com
    volumes:
      - .:/app  # Mount source code for live reload
      - ./logs:/var/log/senextrader
    depends_on:
      - redis

  # Development Celery Beat
  celery_beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.dev
    container_name: senex_celery_beat_dev
    command: celery -A senextrader beat --loglevel=debug
    environment:
      ENVIRONMENT: development
      DJANGO_SETTINGS_MODULE: senextrader.settings.development
      SECRET_KEY: django-insecure-dev-key-for-local-only
      FIELD_ENCRYPTION_KEY: dev-encryption-key-local-only

      # Redis (local)
      REDIS_URL: redis://redis:6379/1
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade (sandbox)
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID:-}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET:-}
      TASTYTRADE_BASE_URL: https://api.cert.tastyworks.com
    volumes:
      - .:/app  # Mount source code for live reload
      - ./logs:/var/log/senextrader
    depends_on:
      - redis
```

---

## Production Override (docker-compose.prod.yml)

### Purpose
- Enable all production features
- Add Nginx reverse proxy
- Enforce security settings
- Use production secrets

### Complete Production Override

```yaml
version: '3.8'

services:
  # Production PostgreSQL (full features)
  postgres:
    container_name: senex_postgres_prod
    # Don't expose port (internal only)

  # Production Redis
  redis:
    container_name: senex_redis_prod
    # Don't expose port (internal only)

  # Production Web Server
  web:
    container_name: senex_web_prod
    deploy:
      replicas: 2  # Multiple replicas for high availability
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
    environment:
      ENVIRONMENT: production
      SECURE_SSL_REDIRECT: True
      SECURE_HSTS_SECONDS: 31536000
      SECURE_HSTS_INCLUDE_SUBDOMAINS: True
      SECURE_HSTS_PRELOAD: True
    # Don't expose port directly (use nginx)

  # Production Celery Worker (scaled)
  celery_worker:
    container_name: senex_celery_worker_prod
    deploy:
      replicas: 2  # Multiple workers for throughput
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G

  # Production Celery Beat (single instance)
  celery_beat:
    container_name: senex_celery_beat_prod
    deploy:
      replicas: 1  # MUST be 1 (scheduler conflict)
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M

  # ==========================================================================
  # Nginx Reverse Proxy (Production Only)
  # ==========================================================================
  nginx:
    image: nginx:alpine
    container_name: senex_nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - staticfiles:/app/staticfiles:ro
      - ssl_certs:/etc/nginx/ssl:ro
    networks:
      - senex_network
    depends_on:
      - web
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  ssl_certs:
    driver: local
```

---

## Health Check Strategy

### Service Health Checks

#### PostgreSQL
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-senex_user} -d ${DB_NAME:-senextrader}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

**Purpose**: Verify database accepts connections

#### Redis
```yaml
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

**Purpose**: Verify Redis responds to ping

#### Django Web
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

**Purpose**: Verify HTTP server and application health

**Required**: Django health endpoint at `/health/` (see `implementation-requirements.md`)

---

## Dependency Management

### Service Dependencies

```yaml
depends_on:
  postgres:
    condition: service_healthy
  redis:
    condition: service_healthy
```

**Behavior**:
- Container waits for `postgres` to be healthy before starting
- Container waits for `redis` to be healthy before starting
- Ensures data layer is ready before application starts

### Startup Order

1. **PostgreSQL** starts → Health check passes
2. **Redis** starts → Health check passes
3. **Web, Worker, Beat** start in parallel (all depend on postgres + redis)

---

## Volume Strategy

### Named Volumes

```yaml
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  logs:
    driver: local
  staticfiles:
    driver: local
  celerybeat_schedule:
    driver: local
```

**Benefits**:
- Docker/Podman manages volume lifecycle
- Data persists across container restarts
- Easy backup/restore (`podman volume export`)

### Volume Mounts

#### PostgreSQL Data
```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```
**Purpose**: Database persistence

#### Redis Data
```yaml
volumes:
  - redis_data:/data
```
**Purpose**: Optional cache persistence (AOF/RDB)

#### Application Logs
```yaml
volumes:
  - logs:/var/log/senextrader
```
**Purpose**: Centralized logging across all services

#### Static Files
```yaml
volumes:
  - staticfiles:/app/staticfiles
```
**Purpose**: Collected static files (if using Nginx)

#### Celery Beat Schedule
```yaml
volumes:
  - celerybeat_schedule:/app
```
**Purpose**: Scheduler state persistence

---

## Network Configuration

### Bridge Network

```yaml
networks:
  senex_network:
    driver: bridge
```

**Features**:
- Internal DNS resolution (service names resolve to IPs)
- Isolated from host network
- Inter-container communication only

### Service Communication

**DNS Names**:
- `postgres` → PostgreSQL container
- `redis` → Redis container
- `web` → Django web container(s)
- `celery_worker` → Celery worker container(s)
- `celery_beat` → Celery beat container

**Example Connection String**:
```
postgresql://senex_user:password@postgres:5432/senextrader
```

---

## Scaling Strategy

### Horizontal Scaling

**Scale Web Service**:
```bash
podman-compose up -d --scale web=3
```
**Result**: 3 web replicas behind load balancer

**Scale Celery Worker**:
```bash
podman-compose up -d --scale celery_worker=4
```
**Result**: 4 worker replicas processing tasks

**Celery Beat**: DO NOT SCALE (must be 1 instance)

### Load Balancing

**Nginx Upstream** (add to nginx config):
```nginx
upstream web_backend {
    least_conn;
    server senex_web_1:8000;
    server senex_web_2:8000;
    server senex_web_3:8000;
}

server {
    listen 80;
    location / {
        proxy_pass http://web_backend;
    }
}
```

---

## Resource Limits

### Production Resource Limits

```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'      # Maximum CPU cores
      memory: 1G       # Maximum memory
    reservations:
      cpus: '0.5'      # Guaranteed CPU cores
      memory: 512M     # Guaranteed memory
```

**Recommended Limits**:

| Service | CPU Limit | Memory Limit | CPU Reserve | Memory Reserve |
|---------|-----------|--------------|-------------|----------------|
| postgres | 2.0 | 4G | 1.0 | 2G |
| redis | 1.0 | 1G | 0.5 | 512M |
| web | 1.0 | 1G | 0.5 | 512M |
| celery_worker | 2.0 | 2G | 1.0 | 1G |
| celery_beat | 0.5 | 512M | 0.25 | 256M |
| nginx | 0.5 | 256M | 0.25 | 128M |

---

## Environment Variable Loading

### .env File Loading

**Automatic Loading**: Docker Compose loads `.env` from project root

```bash
# .env
DB_PASSWORD=secret123
TASTYTRADE_CLIENT_ID=abc123
```

**Usage in Compose**:
```yaml
environment:
  DB_PASSWORD: ${DB_PASSWORD}
  TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
```

### Multiple .env Files

**Pattern**: Use different .env files per environment

**Development**:
```bash
cp .env.example .env
# Edit .env with development values
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Production**:
```bash
cp .env.production.example .env.production
# Edit .env.production with production values (NEVER commit)
podman-compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Service Profiles

### Purpose
Control which services start with profiles

### Profile Definitions

```yaml
services:
  postgres:
    profiles:
      - full  # Only start with 'full' profile

  nginx:
    profiles:
      - production  # Only start with 'production' profile
```

### Usage

**Start minimal services** (development):
```bash
podman-compose up  # Only redis, web, celery_worker, celery_beat
```

**Start with PostgreSQL** (testing):
```bash
podman-compose --profile full up  # Includes postgres
```

**Start production stack**:
```bash
podman-compose --profile production up  # Includes nginx
```

---

## Restart Policies

### Policy Options

```yaml
restart: unless-stopped
```

**Options**:
- `no` - Never restart
- `always` - Always restart
- `on-failure` - Restart only on non-zero exit
- `unless-stopped` - Restart unless manually stopped

**Recommendation**: Use `unless-stopped` for production (survives system reboot but respects manual stops)

---

## Container Naming

### Consistent Naming

```yaml
container_name: senex_web_prod
```

**Benefits**:
- Predictable container names for scripts
- Easier debugging (`podman logs senex_web_prod`)
- Consistent across deployments

**Pattern**: `{project}_{service}_{environment}`

---

## Common Operations

### Start Services

**Development**:
```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Production**:
```bash
podman-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Stop Services

```bash
podman-compose down
```

### Restart Single Service

```bash
podman-compose restart web
```

### View Logs

**All services**:
```bash
podman-compose logs -f
```

**Single service**:
```bash
podman-compose logs -f web
```

### Execute Command in Container

```bash
podman-compose exec web python manage.py shell
```

### Scale Services

```bash
podman-compose up -d --scale web=3 --scale celery_worker=4
```

### Rebuild Services

```bash
podman-compose build --no-cache
podman-compose up -d --force-recreate
```

---

## Troubleshooting

### Check Service Status

```bash
podman-compose ps
```

### Check Service Health

```bash
podman inspect --format='{{.State.Health.Status}}' senex_web
```

### View Service Logs

```bash
podman-compose logs --tail=100 -f web
```

### Enter Container Shell

```bash
podman-compose exec web /bin/bash
```

### Check Network Connectivity

```bash
# From web container, test postgres connection
podman-compose exec web nc -zv postgres 5432

# From web container, test redis connection
podman-compose exec web nc -zv redis 6379
```

### Recreate Volumes

```bash
podman-compose down -v  # WARNING: Deletes all data
podman-compose up -d
```

---

## Backup & Restore

### Backup PostgreSQL

```bash
# Backup to file
podman-compose exec -T postgres pg_dump -U senex_user senextrader > backup.sql

# Backup with compression
podman-compose exec -T postgres pg_dump -U senex_user senextrader | gzip > backup.sql.gz
```

### Restore PostgreSQL

```bash
# Restore from file
cat backup.sql | podman-compose exec -T postgres psql -U senex_user senextrader

# Restore from compressed
gunzip -c backup.sql.gz | podman-compose exec -T postgres psql -U senex_user senextrader
```

### Backup Volumes

```bash
# Export volume to tarball
podman volume export postgres_data -o postgres_data_backup.tar
```

### Restore Volumes

```bash
# Import volume from tarball
podman volume import postgres_data postgres_data_backup.tar
```

---

## Security Best Practices

### 1. Never Commit .env Files

```
# .gitignore
.env
.env.production
.env.local
.env.*.local
```

### 2. Use Docker Secrets (Swarm Mode)

```yaml
secrets:
  db_password:
    external: true
  tastytrade_secret:
    external: true

services:
  web:
    secrets:
      - db_password
      - tastytrade_secret
```

### 3. Scan Images for Vulnerabilities

```bash
podman scout cves senextrader:latest
```

### 4. Use Read-Only Root Filesystem

```yaml
services:
  web:
    read_only: true
    tmpfs:
      - /tmp
      - /var/log/senextrader
```

### 5. Drop Capabilities

```yaml
services:
  web:
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Only if binding privileged ports
```

---

## Summary

The Docker Compose strategy provides:

- ✅ **Multi-Environment Support**: Development and production configurations
- ✅ **Health Checks**: All services monitored for availability
- ✅ **Dependency Management**: Proper startup order with health conditions
- ✅ **Volume Strategy**: Data persistence and shared volumes
- ✅ **Network Isolation**: Internal bridge network for security
- ✅ **Scaling Support**: Horizontal scaling for web and workers
- ✅ **Resource Limits**: CPU and memory constraints for stability
- ✅ **Restart Policies**: Automatic recovery from failures

**Next Steps**:
- See `static-files-strategy.md` for static file serving options
- See `build-workflow.md` for image building and pushing
- See `initialization-checklist.md` for first-time setup
