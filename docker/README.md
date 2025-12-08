# Docker Build Guide

Container build system for Senex Trader using Podman with multi-stage optimization.

---

## 🏗️ Build System Overview

### Technology Stack
- **Container Engine:** Podman 5.x (rootless-compatible)
- **Base Image:** python:3.12-slim-bookworm
- **Build Strategy:** Multi-stage (base → dependencies → runtime)
- **Registry:** Private container registry (configure in .senextrader.json)

### Multi-Stage Build Benefits
1. **Base Stage** - System dependencies and user setup
2. **Dependencies Stage** - Python package compilation with build tools
3. **Runtime Stage** - Final optimized image (no build tools)

**Result**: Smaller images, faster builds with layer caching, enhanced security.

---

## Quick Start

### Using build.py (Recommended)

```bash
# Build with auto-generated tag (git-based)
./build.py

# Build with specific tag
./build.py --tag v1.0.0

# Build without pushing (local testing)
./build.py --tag test-build --no-push

# Cross-platform build
./build.py --tag v1.0.0 --platform linux/amd64,linux/arm64
```

### Using Makefile

```bash
# Build and push
make build TAG=v1.0.0

# The Makefile wraps build.py for convenience
```

---

## Configuration

### Build Configuration (.senextrader.json)

**Location**: Project root (gitignored)

```json
{
  "registry": "gitea.andermic.net",
  "owner": "endthestart",
  "image_name": "senex-trader",
  "project_dir": null,
  "default_no_push": false
}
```

**Setup:**
```bash
cp .senextrader.json.example .senextrader.json
# Edit with your registry details
```

---

## 📁 Container Files

### Dockerfile (Multi-Stage)

**Location**: `docker/Dockerfile`

**Stage 1: Base**
- Python 3.12 on Debian Bookworm
- System dependencies (PostgreSQL client, SSL libs)
- Non-root user (`senex`, UID 1000)
- Timezone: America/New_York

**Stage 2: Dependencies**
- Build tools (gcc, g++, build-essential)
- Python package compilation
- User-local pip installation (rootless compatible)
- Layer caching for faster rebuilds

**Stage 3: Runtime** (Final Image)
- Copies compiled packages only (no build tools)
- Application code and entrypoint
- Health check enabled (`/health/` endpoint)
- Runs as non-root user

### entrypoint.sh

**Location**: `docker/entrypoint.sh`

**Services**:
- `web` - Daphne ASGI server (port 8000)
- `celery-worker` - Background task processing
- `celery-beat` - Periodic task scheduler

**Features**:
- Wait-for-dependencies (PostgreSQL, Redis)
- Automatic migrations
- Static file collection
- Environment validation

---

## 🔖 Image Tagging Strategy

### Auto-Generated Tags
Format: `{branch}-{commit}-{timestamp}`

Example: `production-bugfixes-6bde376-20251104-143522`

**When to use**: Development builds, feature branches

### Semantic Version Tags
Format: `vX.Y.Z`

Example: `v0.2.25`

**When to use**: Production releases, staging deployments

### Latest Tag
Always points to most recent build.

**When to use**: Development environments only (not production)

---

## 🐳 Development Workflows

### Local Development (Docker Compose)

```bash
# Start all services
docker-compose -f docker/docker-compose.dev.yml up

# Rebuild after code changes
docker-compose -f docker/docker-compose.dev.yml up --build

# Stop services
docker-compose -f docker/docker-compose.dev.yml down
```

**Note**: Production uses Quadlet (systemd-native), not docker-compose.

### Testing Container Builds

```bash
# Build without pushing
./build.py --tag test --no-push

# Run locally
podman run -p 8000:8000 \
  -e SECRET_KEY=test \
  -e DB_HOST=localhost \
  gitea.andermic.net/endthestart/senex-trader:test

# Check health
curl http://localhost:8000/health/
```

---

## Registry Authentication

### Login to Gitea Registry

```bash
# Using build.py (automatic)
./build.py --tag v1.0.0
# Prompts for credentials if not authenticated

# Manual login
podman login gitea.andermic.net
# Enter username and token
```

### Creating Access Token

1. Navigate to https://gitea.andermic.net/user/settings/applications
2. Generate new token with `write:packages` permission
3. Save token securely (needed for registry push)

---

## Image Structure

### Exposed Ports
- **8000** - HTTP/WebSocket (Daphne ASGI)

### Volumes
- `/app/staticfiles` - Static assets
- `/app/media` - Uploaded media files
- `/app/logs` - Application logs

### Environment Variables
See `.env.production.example` for complete list.

**Required**:
- `SECRET_KEY` - Django secret
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `REDIS_URL`
- `TASTYTRADE_CLIENT_ID`, `TASTYTRADE_CLIENT_SECRET`

### Health Check
- **Endpoint**: `/health/`
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Retries**: 3

---

## Build Options

### Platform Targeting

```bash
# Build for specific platform
./build.py --tag v1.0.0 --platform linux/amd64

# Multi-arch build
./build.py --tag v1.0.0 --platform linux/amd64,linux/arm64
```

### Cache Management

```bash
# Force rebuild without cache
./build.py --tag v1.0.0 --no-cache

# View build cache
podman system df

# Clear build cache
podman system prune
```

---

## Troubleshooting

### Build Fails with "Registry auth required"

```bash
# Check authentication
podman login gitea.andermic.net

# Verify credentials
cat ~/.docker/auth.json
```

### Build Fails with "No space left"

```bash
# Clean up old images
podman image prune -a

# Check disk usage
podman system df

# Remove unused volumes
podman volume prune
```

### Container Won't Start

```bash
# Check container logs
podman logs <container-id>

# Inspect container
podman inspect <container-id>

# Verify environment variables
podman exec <container-id> env
```

---

## 📚 Related Documentation

- **Deployment:** See `deployment/README.md`
- **Quadlet:** See `deployment/quadlet/README.md` (production orchestration)
- **Development:** See main `README.md`
- **Dockerfile:** See `docker/Dockerfile` (inline comments)

---

**Last Updated:** 2025-11-04
**Container Engine:** Podman 5.x
**Base Image:** python:3.12-slim-bookworm
