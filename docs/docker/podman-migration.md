# Podman Migration Guide

## Overview

This document provides comprehensive guidance for using Podman instead of Docker for Senex Trader containerization. It covers Podman fundamentals, compatibility with Docker, migration steps, and production deployment with podman-compose.

---

## Podman vs Docker: Key Differences

### Architecture

**Docker**:
- Client-server architecture
- Docker daemon runs as root
- Daemon manages all containers
- Privileged daemon required

**Podman**:
- Daemonless architecture
- No root daemon (rootless by default)
- Direct container management
- Fork-exec model (like traditional Unix processes)

### Security Model

**Docker**:
- Daemon runs as root
- All users with Docker access have root-equivalent privileges
- Attack surface: compromised daemon = root access

**Podman**:
- Rootless by default
- User namespaces for isolation
- No daemon attack surface
- Principle of least privilege

### Compatibility

**Podman CLI**: 99% compatible with Docker CLI

```bash
# These commands work identically
docker run -it ubuntu bash
podman run -it ubuntu bash

docker ps
podman ps

docker build -t myapp .
podman build -t myapp .
```

**Podman Compose**: ~95% compatible with docker-compose.yml

---

## Podman Installation

### Linux (Recommended Platform)

**Fedora/RHEL/CentOS**:
```bash
sudo dnf install podman podman-compose
```

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install podman podman-compose
```

**Arch Linux**:
```bash
sudo pacman -S podman podman-compose
```

### Verify Installation

```bash
podman --version
# Podman 4.9.0

podman-compose --version
# podman-compose version 1.0.6
```

---

## Docker to Podman Command Translation

### Basic Commands

| Task | Docker | Podman |
|------|--------|--------|
| Run container | `docker run` | `podman run` |
| List containers | `docker ps` | `podman ps` |
| Stop container | `docker stop` | `podman stop` |
| Remove container | `docker rm` | `podman rm` |
| List images | `docker images` | `podman images` |
| Build image | `docker build` | `podman build` |
| Pull image | `docker pull` | `podman pull` |
| Push image | `docker push` | `podman push` |
| Execute command | `docker exec` | `podman exec` |
| View logs | `docker logs` | `podman logs` |

### Compose Commands

| Task | docker-compose | podman-compose |
|------|----------------|----------------|
| Start services | `docker-compose up` | `podman-compose up` |
| Stop services | `docker-compose down` | `podman-compose down` |
| Build services | `docker-compose build` | `podman-compose build` |
| View logs | `docker-compose logs` | `podman-compose logs` |
| Scale services | `docker-compose up --scale` | `podman-compose up --scale` |

### Alias for Easy Migration

**Add to ~/.bashrc or ~/.zshrc**:
```bash
alias docker=podman
alias docker-compose=podman-compose
```

**Effect**: All Docker commands automatically use Podman

---

## Rootless Containers

### What is Rootless?

**Traditional (Docker)**:
- Daemon runs as root
- Containers run as root by default
- User must be in `docker` group (root-equivalent)

**Rootless (Podman)**:
- No daemon
- Containers run as user processes
- User namespaces remap container UID 0 to user UID
- No special privileges required

### User Namespace Mapping

**Example**:
- Host user: `alice` (UID 1000)
- Container user: `root` (UID 0)
- Mapping: Container UID 0 → Host UID 1000

**Benefit**: Container "root" has no privileges outside container

### Enabling Rootless

**Automatic**: Podman runs rootless by default when not run with `sudo`

**Manual Configuration** (if needed):
```bash
# Enable user namespaces
sudo sysctl kernel.unprivileged_userns_clone=1

# Make persistent
echo 'kernel.unprivileged_userns_clone=1' | sudo tee /etc/sysctl.d/99-rootless.conf

# Set up user namespaces
podman system migrate
```

### UID/GID Mapping in Rootless Mode

**Automatic Mapping**:
- Container UID 0 (root) → Host UID 1000 (user)
- Container UID 1000 (senex) → Host UID 101000 (subuid)

**File Ownership**:
```bash
# Inside container
whoami  # senex
id -u   # 1000

# On host (viewing container files)
ls -la /home/user/.local/share/containers/storage/volumes/
# Files appear as UID 101000 (subuid mapping)
```

**Volume Mounts**:
```bash
# Host directory owned by user (UID 1000)
ls -la /data
# drwxr-xr-x user user /data

# Mount in container
podman run -v /data:/app/data myapp
# Inside container, /app/data is accessible by UID 1000 (senex user)
```

**Key Point**: UID 1000 in container maps to host user UID, avoiding permission issues

---

## Podman Compose Implementation

### Installation

**Method 1: Package Manager** (Recommended):
```bash
sudo apt-get install podman-compose  # Debian/Ubuntu
sudo dnf install podman-compose      # Fedora/RHEL
```

**Method 2: pip**:
```bash
pip3 install podman-compose
```

**Verify**:
```bash
podman-compose --version
```

### Compatibility with docker-compose.yml

**Podman Compose** supports:
- ✅ version 2.x and 3.x compose files
- ✅ services, volumes, networks
- ✅ depends_on with conditions
- ✅ environment variables
- ✅ health checks
- ✅ build context
- ✅ restart policies
- ✅ resource limits (via systemd)
- ✅ profiles

**Known Limitations**:
- ❌ Swarm mode features (deploy, replicas via Swarm)
- ❌ Some Docker-specific extensions

**Workaround for Replicas**:
```bash
# Instead of deploy.replicas in compose file
podman-compose up -d --scale web=3
```

### Using Compose Files

**Single File**:
```bash
podman-compose -f docker-compose.yml up -d
```

**Multiple Files** (dev override):
```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Environment File**:
```bash
podman-compose --env-file .env.production up -d
```

---

## Image Building with Podman

### Dockerfile Compatibility

**Podman Build**: 100% compatible with Dockerfile syntax

**BuildKit Support**: Podman 4.0+ uses BuildKit-compatible backend

### Build Command

**Basic Build**:
```bash
podman build -t senextrader:latest .
```

**Multi-Architecture Build**:
```bash
podman build --platform linux/amd64,linux/arm64 -t senextrader:latest .
```

**Build with Secrets** (BuildKit syntax):
```bash
podman build \
  --secret id=tastytrade_secret,src=.secrets/tastytrade.key \
  -t senextrader:latest .
```

### Build Cache

**Local Cache**:
```bash
# Enable layer caching
podman build --layers -t senextrader:latest .
```

**Cache Export/Import**:

**Note**: `--cache-to` and `--cache-from` are BuildKit features. Support varies by Podman version (requires 4.4+ with Buildah backend). Use `--layers` for reliable built-in caching.

```bash
# Recommended: Use --layers for built-in caching
podman build --layers -t senextrader:latest .

# Advanced: Export/import cache (Podman 4.4+ only)
podman build --cache-to type=local,dest=/tmp/buildcache .
podman build --cache-from type=local,src=/tmp/buildcache .
```

---

## Registry Operations

### Pulling Images

**Docker Hub**:
```bash
podman pull docker.io/python:3.12-slim-bookworm
```

**Quay.io**:
```bash
podman pull quay.io/podman/stable
```

**Private Registry**:
```bash
podman pull myregistry.com/senextrader:latest
```

### Pushing Images

**Login to Registry**:
```bash
podman login myregistry.com
# Username: user
# Password: ****
```

**Push Image**:
```bash
podman push myregistry.com/senextrader:latest
```

**Push Multiple Tags**:
```bash
podman tag senextrader:latest myregistry.com/senextrader:1.0.0
podman tag senextrader:latest myregistry.com/senextrader:latest

podman push myregistry.com/senextrader:1.0.0
podman push myregistry.com/senextrader:latest
```

---

## Podman Systemd Integration

### Why Systemd?

**Benefits**:
- Auto-start containers on boot
- Restart containers on failure
- Resource limits (CPU, memory)
- Logging via journald
- Production-ready service management

### Generate Systemd Unit Files

**Single Container**:
```bash
# Start container
podman run -d --name senex_web senextrader:latest

# Generate systemd unit file
podman generate systemd --name senex_web --files --new
# Creates: container-senex_web.service
```

**Compose Project**:
```bash
# Start services
podman-compose up -d

# Generate systemd unit file for entire project
podman-compose systemd --name senex-trader
```

### Install Systemd Units

**User Services** (rootless):
```bash
# Copy unit files
mkdir -p ~/.config/systemd/user/
cp container-*.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable services
systemctl --user enable container-senex_web.service
systemctl --user start container-senex_web.service

# Enable linger (start services without login)
loginctl enable-linger $USER
```

**System Services** (rootful):
```bash
# Copy unit files
sudo cp container-*.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable container-senex_web.service
sudo systemctl start container-senex_web.service
```

### Systemd Unit Example

**Generated Unit File** (container-senex_web.service):
```ini
[Unit]
Description=Podman container-senex_web.service
Wants=network-online.target
After=network-online.target
RequiresMountsFor=%t/containers

[Service]
Environment=PODMAN_SYSTEMD_UNIT=%n
Restart=always
TimeoutStartSec=900
TimeoutStopSec=70
ExecStartPre=/bin/rm -f %t/%n.ctr-id
ExecStart=/usr/bin/podman run \
    --cidfile=%t/%n.ctr-id \
    --cgroups=no-conmon \
    --rm \
    --sdnotify=conmon \
    --replace \
    --name senex_web \
    -d \
    --env-file /etc/senex-trader/.env \
    senextrader:latest
ExecStop=/usr/bin/podman stop --ignore --cidfile=%t/%n.ctr-id
ExecStopPost=/usr/bin/podman rm -f --ignore --cidfile=%t/%n.ctr-id
Type=notify
NotifyAccess=all

[Install]
WantedBy=multi-user.target
```

---

## Podman Pods (Alternative to Compose)

### What are Pods?

**Concept**: Kubernetes-style pods (multiple containers sharing namespace)

**Benefits**:
- Containers share network namespace (localhost communication)
- Shared storage volumes
- Atomic start/stop
- Kubernetes-compatible

### Creating a Pod

**Create Pod**:
```bash
podman pod create --name senex-trader -p 8000:8000
```

**Add Containers to Pod**:
```bash
# PostgreSQL
podman run -d --pod senex-trader \
  --name postgres \
  -e POSTGRES_PASSWORD=secret \
  postgres:16-alpine

# Redis
podman run -d --pod senex-trader \
  --name redis \
  redis:7-alpine

# Django Web
podman run -d --pod senex-trader \
  --name web \
  -e DB_HOST=localhost \
  -e REDIS_URL=redis://localhost:6379/0 \
  senextrader:latest
```

**Benefits in Pod**:
- All containers communicate via `localhost` (shared network namespace)
- Single IP address for entire pod
- Port mapping at pod level only

### Generate Kubernetes YAML

**Export Pod to Kubernetes**:
```bash
podman generate kube senex-trader > senex-trader-pod.yaml
```

**Deploy to Kubernetes**:
```bash
kubectl apply -f senex-trader-pod.yaml
```

**Recommendation**: Use Compose for development, Pods for Kubernetes migration path

---

## Volume Management

### Podman Volume Commands

```bash
# Create volume
podman volume create postgres_data

# List volumes
podman volume ls

# Inspect volume
podman volume inspect postgres_data

# Remove volume
podman volume rm postgres_data

# Export volume to tarball
podman volume export postgres_data -o postgres_data.tar

# Import volume from tarball
podman volume import postgres_data postgres_data.tar
```

### Volume Location

**Rootless**:
```
~/.local/share/containers/storage/volumes/
```

**Rootful**:
```
/var/lib/containers/storage/volumes/
```

### Volume Permissions

**Rootless**: Volumes automatically mapped to user UID (no permission issues)

**Rootful**: Same as Docker (must match container UID)

---

## Networking

### Network Types

**Podman Networks**:
- `bridge` - Default, isolated network
- `host` - Use host network namespace
- `none` - No networking
- `slirp4netns` - Rootless networking (default for rootless)

### Network Commands

```bash
# Create network
podman network create senex_network

# List networks
podman network ls

# Inspect network
podman network inspect senex_network

# Remove network
podman network rm senex_network
```

### Rootless Networking

**Default**: slirp4netns (user-mode networking)

**Performance**: Slightly slower than bridge (~5-10% overhead)

**Alternative**: pasta (faster, Podman 4.4+)
```bash
podman run --network pasta ...
```

---

## Production Deployment with Podman

### Deployment Architecture

**Recommended**:
- Rootless Podman for security
- Systemd for service management
- podman-compose for orchestration
- Reverse proxy (Nginx/Traefik) for SSL

### Deployment Steps

#### 1. Install Podman on Server

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install podman podman-compose

# Enable user namespaces
sudo sysctl kernel.unprivileged_userns_clone=1
echo 'kernel.unprivileged_userns_clone=1' | sudo tee /etc/sysctl.d/99-rootless.conf
```

#### 2. Configure User

```bash
# Create service user
sudo useradd -m -s /bin/bash senex-app

# Switch to service user
sudo su - senex-app

# Enable linger (services start without login)
loginctl enable-linger senex-app
```

#### 3. Deploy Application

```bash
# Clone repository
git clone https://github.com/yourusername/senextrader.git
cd senextrader

# Create .env file
cp .env.production.example .env.production
# Edit .env.production with secrets

# Build images
podman-compose -f docker-compose.yml -f docker-compose.prod.yml build

# Start services
podman-compose --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d
```

#### 4. Generate Systemd Units

```bash
# Generate systemd units for all services
podman-compose systemd --name senex-trader

# Install units
mkdir -p ~/.config/systemd/user/
cp *.service ~/.config/systemd/user/

# Reload and enable
systemctl --user daemon-reload
systemctl --user enable --now podman-compose@senex-trader.service
```

#### 5. Configure Reverse Proxy

**Nginx** (running on host):
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Troubleshooting

### Issue: Port Already in Use

**Error**: `Error: address already in use`

**Solution**:
```bash
# Find process using port
sudo lsof -i :8000

# Or use podman to check
podman ps -a

# Stop conflicting container
podman stop <container-id>
```

### Issue: Permission Denied (Rootless)

**Error**: `EACCES: permission denied`

**Solution**:
```bash
# Ensure user namespaces enabled
sudo sysctl kernel.unprivileged_userns_clone=1

# Check subuid/subgid mappings
cat /etc/subuid
cat /etc/subgid

# If missing, add mappings
sudo usermod --add-subuids 100000-165535 $USER
sudo usermod --add-subgids 100000-165535 $USER

# Reset Podman
podman system reset
```

### Issue: Compose Not Found

**Error**: `podman-compose: command not found`

**Solution**:
```bash
# Install via pip
pip3 install --user podman-compose

# Add to PATH
echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc
source ~/.bashrc
```

### Issue: Health Check Failing

**Error**: Container marked unhealthy

**Solution**:
```bash
# Check health check logs
podman inspect --format='{{json .State.Health}}' senex_web | jq

# Test health check manually
podman exec senex_web curl -f http://localhost:8000/health/

# Disable health check temporarily (debugging)
# In docker-compose.yml:
# healthcheck:
#   disable: true
```

---

## Podman vs Docker: Feature Comparison

| Feature | Docker | Podman | Notes |
|---------|--------|--------|-------|
| Daemon | Yes (root) | No | Podman is daemonless |
| Rootless | No (experimental) | Yes (default) | Podman more secure |
| Compose | docker-compose | podman-compose | ~95% compatible |
| Swarm | Yes | No | Use Kubernetes instead |
| BuildKit | Yes | Yes | Podman 4.0+ |
| Kubernetes YAML | No | Yes | `podman generate kube` |
| Systemd | Via external tool | Native | `podman generate systemd` |
| Pods | No | Yes | Kubernetes-style pods |
| OCI Compliant | Yes | Yes | Both use same standards |

---

## Migration Checklist

### Pre-Migration

- [ ] Install Podman and podman-compose on development machine
- [ ] Test Dockerfile build with Podman
- [ ] Test compose file with podman-compose
- [ ] Verify all features work (health checks, volumes, networking)

### Migration

- [ ] Update CI/CD pipelines to use Podman commands
- [ ] Update documentation references (Docker → Podman)
- [ ] Train team on Podman-specific features (pods, systemd)
- [ ] Set up aliases for Docker commands (optional)

### Post-Migration

- [ ] Monitor performance (compare with Docker baseline)
- [ ] Verify security improvements (rootless operation)
- [ ] Document any Podman-specific configurations
- [ ] Update runbooks and incident response procedures

---

## Summary

**Podman for Senex Trader provides**:

- ✅ **Enhanced Security**: Rootless by default, no root daemon
- ✅ **Docker Compatibility**: 99% CLI compatible, 95% Compose compatible
- ✅ **Production Ready**: Systemd integration for service management
- ✅ **Simpler Architecture**: Daemonless, direct process management
- ✅ **Kubernetes Compatible**: Generate Kubernetes YAML from Pods
- ✅ **Resource Isolation**: User namespaces, cgroups v2 support

**Recommended Approach**:
1. Use podman-compose for orchestration (familiar Docker Compose syntax)
2. Deploy rootless for security
3. Use systemd for production service management
4. Leverage Podman-specific features (pods, kube export) as needed

**Next Steps**: See `build-workflow.md` for Podman build commands and `initialization-checklist.md` for deployment procedures.
