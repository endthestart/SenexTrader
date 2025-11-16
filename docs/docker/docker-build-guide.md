# Docker/Podman Container Setup

This directory contains the containerization files for Senex Trader.

## 📋 Separation of Concerns

This setup is **only for building and pushing containers**. Deployment is handled separately.

### Phase 1: Build & Push (This Directory)
- **Purpose**: Create production-ready container images
- **Tool**: `build.sh` script
- **Output**: Container image pushed to Gitea registry
- **Scope**: CI/CD and image management

### Phase 2: Deployment (Separate)
- **Purpose**: Deploy containers to production servers
- **Location**: `senextrader_docs/deployment/`
- **Tools**: Ansible, docker-compose, systemd
- **Scope**: Infrastructure and orchestration

## 🚀 Quick Start

### Build Locally
```bash
# From project root (auto-generates tag from Git)
python build.py --no-push
```

### Build and Push to Gitea
```bash
# Build and push with auto-generated tag (branch-commit-timestamp)
python build.py

# Build and push with specific tag
python build.py --tag v1.0.0

# Build only, don't push
python build.py --no-push

# Verbose mode
python build.py --tag v1.0.0 -v
```

### Test Locally
```bash
# Run all services (development mode)
cd docker
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Run all services (production mode)
cd docker
podman-compose -f docker-compose.yml -f docker-compose.prod.yml up
```

## 📁 Files

### Container Images
- `Dockerfile` - Multi-stage production image (Python 3.12, PostgreSQL 15, Redis 7)
- `Dockerfile.dev` - Simple development image with live reload
- `entrypoint.sh` - Service routing (web/celery-worker/celery-beat)

### Orchestration
- `docker-compose.yml` - Base service configuration
- `docker-compose.dev.yml` - Development overrides
- `docker-compose.prod.yml` - Production overrides (scaling, resources)

### Configuration
- `../.dockerignore` - Build context exclusions
- `../.env.example` - Development environment template
- `../.env.production.example` - Production environment template

## 🏗️ Architecture

### Services (5 total)
1. **PostgreSQL 15** - Primary database (matches production deployment)
2. **Redis 7** - Cache, Celery broker, Channels backend (matches production deployment)
3. **Django Web** - Daphne ASGI server (WebSocket support)
4. **Celery Worker** - Background tasks (multi-replica capable)
5. **Celery Beat** - Task scheduler (single instance only)

### Network & Storage
- **Network**: Internal bridge network (`senex_network`)
- **Volumes**: postgres_data, redis_data, logs, staticfiles
- **Bind Mounts**: Uses `${APP_DIR:-.}` for path resolution (local dev: `.`, production: `/opt/senex-trader`)

## 🔧 Development Workflow

1. **Make changes** to code
2. **Build locally** to test: `python build.py --no-push`
3. **Test with compose**: `cd docker && podman-compose -f docker-compose.yml -f docker-compose.dev.yml up`
4. **Push to registry**: `python build.py --tag v1.x.x`
5. **Deploy** (handled by deployment scripts in senextrader_docs)

## 🎯 Image Registry

- **Registry**: gitea.andermic.net
- **Image Name**: endthestart/senex-trader
- **Tags**:
  - `latest` - Most recent build
  - `v1.x.x` - Semantic versioning
  - Custom tags via `--tag` flag

## 📊 Image Details

- **Base**: Python 3.12-slim-bookworm
- **Size Target**: <500 MB
- **User**: Non-root (UID 1000, Podman rootless compatible)
- **Platform**: linux/amd64
- **Server**: Daphne ASGI (required for WebSocket support)

## 🔍 Health Checks

All services have health checks:
- **Web**: `curl http://localhost:8000/health/`
- **PostgreSQL**: `pg_isready -U senex_user`
- **Redis**: `redis-cli ping`

## 🚨 Important Notes

1. **Never commit** `.env.production` (contains secrets)
2. **Build script** only builds and pushes - no deployment
3. **Deployment** is handled separately (see senextrader_docs/deployment)
4. **Daphne ASGI** is required (not optional) - WebSockets needed for real-time market data
5. **PostgreSQL 15 & Redis 7** match production versions (Debian 12 compatibility)
6. **Celery Beat** must run as single instance (not scalable)
7. **APP_DIR** environment variable controls bind mount paths (dev: `.`, prod: `/opt/senex-trader`)

## 🔗 See Also

- **Deployment**: `senextrader_docs/deployment/` - Production deployment guides
- **Planning**: `senextrader_docs/docker/` - Containerization research and planning
- **Reference**: `~/Development/options_strategy_trader/` - Reference implementation
