# Quadlet Deployment Guide

Systemd-native container orchestration for Senex Trader using Podman Quadlet.

---

## What is Quadlet?

**Quadlet** is built into Podman 4.4+ and provides systemd-native container management.

### Why Quadlet Instead of Docker Compose?

| Feature | Quadlet | Docker Compose |
|---------|---------|----------------|
| **Integration** | Native systemd (journald logs, systemctl) | Separate daemon |
| **Restart Policies** | Full systemd restart logic | Limited options |
| **Dependencies** | Systemd `Requires=`, `After=` | `depends_on` (basic) |
| **Security** | SELinux, rootless, systemd sandboxing | Rootful by default |
| **Logging** | journalctl (unified logs) | docker logs only |
| **Auto-start** | systemd targets | Requires docker-compose service |

**Result**: Better reliability, security, and integration with modern Linux systems.

---

## 🏗️ Architecture

### Service Topology

```
senex-network.network (Podman network)
├── postgres.container     (PostgreSQL 15-alpine)
│   └── Volume: /var/lib/postgresql/data
├── redis.container        (Redis 7-alpine)
│   └── Volume: /data
├── web.container          (Senex Trader ASGI)
│   ├── Depends: postgres, redis
│   ├── Port: 8000
│   └── Volume: staticfiles
├── celery-worker.container (Background tasks)
│   └── Depends: postgres, redis
└── celery-beat.container   (Scheduler)
    └── Depends: postgres, redis
```

### Files Structure

**Default templates** (tracked in git, generic):
```
deployment/ansible/templates/quadlet/
├── postgres.container.j2    # Database service
├── redis.container.j2       # Cache/broker service
├── web.container.j2         # Django ASGI
├── celery-worker.container.j2
└── celery-beat.container.j2
```

**Custom overrides** (gitignored, deployment-specific):
```
config/ansible/templates/quadlet/
├── postgres.container.j2    # Optional: Custom database config
├── redis.container.j2       # Optional: Custom cache config
├── web.container.j2         # Optional: Custom web config
├── celery-worker.container.j2
└── celery-beat.container.j2
```

**Network configuration** (tracked in git):
- `deployment/quadlet/senex-network.network` - Podman network definition

**How it works:**
- The deployment playbook automatically uses templates from `config/` if they exist
- Otherwise, it falls back to default templates in `deployment/ansible/templates/quadlet/`
- This means default templates work out-of-the-box (no copying required)
- You only need to copy templates to `config/` if you need deployment-specific customizations
- All templates use variables (`{{ app_directory }}`, `{{ quadlet_dir }}`) - no hardcoded paths

---

## Quadlet File Format

Quadlet uses `.container` files with systemd-style ini format.

### Example: web.container.j2 (Template)

```ini
[Container]
Image=${GITEA_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
ContainerName=web
EnvironmentFile={{ quadlet_dir }}/.env
Exec=web
Volume={{ app_directory }}/data/staticfiles:/app/staticfiles:U
PublishPort=0.0.0.0:8000:8000
Network=senex-network.network

[Service]
Restart=always
RestartSec=10s
TimeoutStartSec=120
```

**Note:** Templates use Jinja2 variables (`{{ quadlet_dir }}`, `{{ app_directory }}`) which are replaced during deployment. This ensures templates are generic and work for any deployment without hardcoded paths.

### Key Directives

**[Container] Section:**
- `Image=` - Container image to use (supports env var substitution)
- `ContainerName=` - Name for the container
- `EnvironmentFile=` - Load environment variables
- `Exec=` - Command to run (overrides image CMD)
- `Volume=` - Mount volumes (`:U` = change ownership to container user)
- `PublishPort=` - Port mapping (host:container)
- `Network=` - Attach to Podman network
- `HealthCmd=` - Health check command

**[Service] Section:**
- `Restart=` - Restart policy (always, on-failure, etc.)
- `RestartSec=` - Delay between restarts
- `TimeoutStartSec=` - Max time to wait for startup

---

## Deployment Locations

### Rootful Podman (Staging)
```
/etc/containers/systemd/
├── .env                    # Environment variables
├── senex-network.network
├── postgres.container
├── redis.container
├── web.container
├── celery-worker.container
└── celery-beat.container

/etc/systemd/system/
├── postgres.service.d/
│   └── override.conf       # systemd drop-ins
├── web.service.d/
│   └── override.conf
└── ...
```

**Managed by**: System systemd
**Commands**: `systemctl status web.service`

### Rootless Podman (Production)
```
/opt/senex-trader/.config/containers/systemd/
├── .env
├── senex-network.network
└── *.container files

/opt/senex-trader/.config/systemd/user/
├── postgres.service.d/
│   └── override.conf
└── ...
```

**Managed by**: User systemd (senex user)
**Commands**: `systemctl --user status web.service`

---

## How Quadlet Works

### 1. Quadlet Generator (Automatic)

When you run `systemctl daemon-reload`, Quadlet:

1. Scans `containers/systemd/` for `.container` and `.network` files
2. Converts them to systemd `.service` units
3. Places generated units in systemd service directory
4. Systemd can now manage containers like native services

**Example conversion:**
```
web.container → web.service
├── ExecStart=/usr/bin/podman run ...
├── ExecStop=/usr/bin/podman stop ...
└── Type=notify
```

### 2. Environment Variable Substitution

Quadlet supports `${VAR}` substitution from `EnvironmentFile`:

**.env file:**
```bash
GITEA_REGISTRY=your-registry.example.com
IMAGE_NAME=your-org/senex-trader
IMAGE_TAG=v0.2.25
```

**In .container file:**
```ini
Image=${GITEA_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
```

**Result:**
```
Image=your-registry.example.com/your-org/senex-trader:v0.2.25
```

---

## Managing Services

### Staging (Rootful)

```bash
# Check status
systemctl status web.service

# Restart service
systemctl restart web.service

# View logs
journalctl -u web.service -f

# Enable auto-start
systemctl enable web.service

# View all senex services
systemctl list-units '*postgres*' '*redis*' '*web*' '*celery*'
```

### Production (Rootless)

```bash
# From root (managing senex user services)
systemctl --user -M senex@ status web.service
systemctl --user -M senex@ restart web.service
journalctl --user -M senex@ -u web.service -f

# As senex user
systemctl --user status web.service
systemctl --user restart web.service
journalctl --user -u web.service -f
```

---

## Deployment Workflow

### 1. Update Configuration

```bash
# Edit inventory to use new image tag
vim config/ansible/inventory/hosts.yml
# Change: image_tag: v0.2.26
```

### 2. Run Ansible Deployment

```bash
make deploy-production
```

**Ansible performs**:
1. Pulls new image from registry
2. Updates `.env` file with new image tag
3. Runs `systemctl daemon-reload` (regenerates units)
4. Restarts services in order

### 3. Verify Deployment

```bash
# Check services are running
systemctl --user -M senex@ status web.service

# Check container status
sudo -u senex podman ps

# Verify health endpoint
curl https://your-domain.com/health/
```

---

## 🛠️ Manual Operations

### Reload Quadlet Configuration

After modifying `.container` files:

```bash
# Rootful
systemctl daemon-reload
systemctl restart web.service

# Rootless
systemctl --user daemon-reload
systemctl --user restart web.service
```

### Update Environment Variables

```bash
# Edit .env file
vim /opt/senex-trader/.config/containers/systemd/.env

# Restart affected services
systemctl --user restart web.service celery-worker.service
```

### Pull New Image

```bash
# As senex user
podman pull your-registry.example.com/your-org/senex-trader:v0.2.26

# Restart service to use new image
systemctl --user restart web.service
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status
systemctl --user status web.service

# View full logs
journalctl --user -u web.service -n 100

# Check Podman status
podman ps -a
podman logs web
```

### Quadlet Not Generating Units

```bash
# Verify Podman version (needs 4.4+)
podman --version

# Check Quadlet directory exists
ls -la /opt/senex-trader/.config/containers/systemd/

# Force regeneration
systemctl --user daemon-reload

# View generated units
systemctl --user cat web.service
```

### Environment Variables Not Working

```bash
# Check .env file exists
ls -la /opt/senex-trader/.config/containers/systemd/.env

# Verify permissions
chmod 600 .env

# Check drop-in files
systemctl --user cat web.service | grep -A 5 'EnvironmentFile'
```

### Container Can't Connect to Database

```bash
# Check network exists
podman network ls | grep senex

# Verify all containers on same network
podman inspect postgres | grep NetworkMode
podman inspect web | grep NetworkMode

# Test connectivity from web container
podman exec web ping postgres
```

---

## Security Features

### Rootless Podman Benefits
- Containers run as non-root user (UID 987 = senex)
- User namespaces isolate processes
- No privileged operations possible
- Reduced attack surface

### SELinux Integration
- Quadlet respects SELinux contexts
- Volumes automatically labeled (`:Z` for private, `:z` for shared)
- Container processes confined by policy

### Systemd Sandboxing
Production web service has additional restrictions:
```ini
[Service]
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
```

---

## 📚 Advanced Topics

### Custom Health Checks

```ini
[Container]
HealthCmd=/usr/bin/curl -f http://localhost:8000/health/ || exit 1
HealthInterval=30s
HealthTimeout=10s
HealthRetries=3
```

### Resource Limits

```ini
[Container]
PidsLimit=100
ShmSize=256m
Ulimit=nofile=65536:65536

[Service]
MemoryMax=2G
CPUQuota=200%
```

### Automatic Updates

```ini
[Container]
AutoUpdate=registry

[Service]
# Restart on update
X-RestartPolicy=always
```

Then enable auto-update timer:
```bash
systemctl --user enable --now podman-auto-update.timer
```

---

## 📖 Related Documentation

- **Build Process:** See `docker/README.md`
- **Deployment Guide:** See `deployment/README.md`
- **Ansible Playbook:** See `deployment/ansible/deploy.yml`
- **Podman Quadlet Docs:** https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html

---

**Last Updated:** 2025-11-04
**Podman Version:** 5.x+
**Quadlet Support:** Built-in (Podman ≥ 4.4)
