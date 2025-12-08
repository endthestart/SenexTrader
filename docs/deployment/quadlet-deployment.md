# Podman Quadlet Deployment

## Overview

This directory contains Quadlet configuration files for deploying Senex Trader using Podman and systemd integration. Quadlet provides production-grade container management with systemd's battle-tested reliability.

**Requirements:**
- **Podman 4.4 or newer** (Quadlet was introduced in Podman 4.4)
- systemd (any modern version)
- Linux kernel with cgroup v2 support

**Note:** Debian 12 ships with Podman 4.3.1 which does NOT support Quadlet. The Ansible playbook automatically upgrades Podman from the Kubic repository.

## Why Quadlet?

**Previous Issues with podman-compose:**
- Restart policies didn't work reliably
- No centralized service management
- Containers stayed down after failures
- No auto-update capabilities

**Benefits of Quadlet:**
- **Rock-solid auto-restart**: systemd's proven service management
- **Production-ready**: Designed for production workloads
- **Auto-updates**: Optional automatic container updates with rollback
- **Better logging**: Native journalctl integration
- **Proper dependencies**: systemd manages service startup order
- **No daemon overhead**: Maintains Podman's rootless benefits
- **Modern approach**: Podman 4.4+ deprecated `podman generate systemd` in favor of Quadlet

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   systemd                       │
│  (manages services, auto-restart, logging)      │
└─────────────────┬───────────────────────────────┘
                  │
      ┌───────────┴───────────┐
      │                       │
   Quadlet              Podman Runtime
   (.container)         (rootless containers)
      │                       │
      └───────────┬───────────┘
                  │
    ┌─────────────┴─────────────┐
    │  Senex Trader Containers  │
    │  - postgres               │
    │  - redis                  │
    │  - web                    │
    │  - celery-worker          │
    │  - celery-beat            │
    └───────────────────────────┘
```

## Files

### Network Configuration
- **`senex-network.network`**: Shared bridge network for all containers

### Container Configurations
- **`postgres.container`**: PostgreSQL 15 database with `:U` volume flag (fixes permission issues)
- **`redis.container`**: Redis 7 cache/broker with `:U` volume flag
- **`web.container`**: Django ASGI application (Daphne server)
- **`celery-worker.container`**: Background task processor
- **`celery-beat.container`**: Periodic task scheduler

## Key Features

### 1. Volume Permission Fix
All volume mounts use the `:U` flag to enable auto-chown for rootless Podman:
```
Volume=${APP_DIR}/data/postgres:/var/lib/postgresql/data:U
```
This fixes the "Permission denied" errors we saw in production.

### 2. Environment Variables
Environment variables are loaded from `.env` file using systemd's `EnvironmentFile`:
```
EnvironmentFile=%d/.env
Environment=POSTGRES_DB=${DB_NAME}
```

### 3. Service Dependencies
Containers have proper startup dependencies:
```
Requires=postgres.service redis.service
After=postgres.service redis.service
```

### 4. Health Checks
Built-in health monitoring:
```
HealthCmd=pg_isready -U ${DB_USER} -d ${DB_NAME}
HealthInterval=10s
```

### 5. Auto-Restart
systemd handles restarts reliably:
```
[Service]
Restart=always
RestartSec=10s
```

## Deployment

### Automated Deployment (Recommended)

Use the Ansible playbook:

```bash
# Deploy to staging
ansible-playbook deployment/ansible/deploy.yml --limit staging --ask-vault-pass

# Deploy to production
ansible-playbook deployment/ansible/deploy.yml --limit production --ask-vault-pass
```

The playbook will:
1. Copy Quadlet files to appropriate location (`/etc/containers/systemd/` or `~/.config/containers/systemd/`)
2. Copy `.env` file with configuration
3. Reload systemd daemon
4. Enable and start all services
5. Verify services are running

### Manual Deployment

1. **Copy files** to Quadlet directory:
   ```bash
   # For rootless (recommended)
   mkdir -p ~/.config/containers/systemd/
   cp *.container *.network ~/.config/containers/systemd/
   cp .env ~/.config/containers/systemd/

   # For rootful
   mkdir -p /etc/containers/systemd/
   cp *.container *.network /etc/containers/systemd/
   cp .env /etc/containers/systemd/
   ```

2. **Reload systemd** to load Quadlet files:
   ```bash
   # Rootless
   systemctl --user daemon-reload

   # Rootful
   sudo systemctl daemon-reload
   ```

3. **Enable and start services**:
   ```bash
   # Rootless
   systemctl --user enable --now senex-network.service
   systemctl --user enable --now postgres.service
   systemctl --user enable --now redis.service
   systemctl --user enable --now web.service
   systemctl --user enable --now celery-worker.service
   systemctl --user enable --now celery-beat.service

   # Rootful
   sudo systemctl enable --now senex-network.service
   sudo systemctl enable --now postgres.service
   sudo systemctl enable --now redis.service
   sudo systemctl enable --now web.service
   sudo systemctl enable --now celery-worker.service
   sudo systemctl enable --now celery-beat.service
   ```

## Service Management

### Check Service Status
```bash
# All services
systemctl --user status postgres.service redis.service web.service

# Individual service
systemctl --user status web.service
```

### View Logs
```bash
# Follow web service logs
journalctl --user -u web.service -f

# Last 100 lines
journalctl --user -u web.service -n 100

# All services
journalctl --user -u postgres.service -u redis.service -u web.service -u celery-worker.service -u celery-beat.service
```

### Restart Service
```bash
systemctl --user restart web.service
```

### Stop/Start Service
```bash
systemctl --user stop web.service
systemctl --user start web.service
```

### Disable Service
```bash
systemctl --user disable --now web.service
```

## Auto-Updates (Optional)

To enable automatic container updates:

1. Uncomment `AutoUpdate=registry` in `.container` files
2. Enable auto-update timer:
   ```bash
   systemctl --user enable --now podman-auto-update.timer
   ```

This will automatically pull new images and restart containers daily.

## Troubleshooting

### Services Won't Start

Check systemd status:
```bash
systemctl --user status web.service
journalctl --user -u web.service -n 50
```

### Permission Errors

Verify `:U` flag is present in volume mounts in `.container` files.

Check file ownership:
```bash
ls -la ${APP_DIR}/data/
```

### Environment Variables Not Loading

Verify `.env` file exists in Quadlet directory:
```bash
# Rootless
ls -la ~/.config/containers/systemd/.env

# Rootful
ls -la /etc/containers/systemd/.env
```

Check `EnvironmentFile` directive in `.container` files.

### Container Not Found

Verify containers exist:
```bash
podman ps -a
```

Reload systemd daemon:
```bash
systemctl --user daemon-reload
```

## Migration from podman-compose

If you have existing containers running via podman-compose:

1. Stop old containers:
   ```bash
   podman-compose down
   ```

2. Deploy Quadlet files (see Deployment section above)

3. Verify new services are running:
   ```bash
   systemctl --user status web.service
   podman ps
   ```

## Benefits Summary

| Feature | podman-compose | Quadlet + systemd |
|---------|----------------|-------------------|
| Auto-restart | Unreliable | Rock-solid |
| Service management | Manual | systemd |
| Logging | podman logs | journalctl |
| Auto-updates | No | Built-in |
| Dependencies | Limited | Full systemd |
| Production-ready | No | Yes |
| Rootless support | Yes | Yes |

## References

- [Podman Quadlet Documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
- [Red Hat: Make systemd better for Podman with Quadlet](https://www.redhat.com/en/blog/quadlet-podman)
- [Quadlet: Running Podman containers under systemd](https://mo8it.com/blog/quadlet/)
