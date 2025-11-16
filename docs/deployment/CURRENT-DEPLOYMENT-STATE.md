# Current Deployment State - Senex Trader Production

**Last Updated**: 2025-10-30
**Server**: your-domain.com
**Status**: ✅ Production Active

This document reflects the **actual current deployment** as of October 30, 2025, and supersedes earlier planning documents for day-to-day operations.

## Table of Contents

1. [Deployment Overview](#deployment-overview)
2. [Server Architecture](#server-architecture)
3. [Directory Structure](#directory-structure)
4. [Services Running](#services-running)
5. [Container Configuration](#container-configuration)
6. [Networking](#networking)
7. [Backup System](#backup-system)
8. [Monitoring](#monitoring)
9. [Deployment Workflow](#deployment-workflow)
10. [Service Management](#service-management)
11. [Debugging Services](#debugging-services)

## Deployment Overview

### Infrastructure
- **Provider**: Cloud VPS
- **OS**: Ubuntu 24.04 LTS
- **User**: `senex` (UID 987)
- **Deployment Path**: `/opt/senex-trader/`
- **Container Runtime**: Podman (rootless)
- **Service Manager**: systemd (user services via Quadlet)
- **Reverse Proxy**: Nginx (root systemd service)
- **SSL/TLS**: Let's Encrypt (managed by certbot)

### Deployment Method
- **Primary**: Quadlet container definitions + manual deployment
- **Automation**: Partial (Ansible structure exists but deployment is primarily manual/scripted)
- **Container Registry**: `gitea.andermic.net/endthestart/senex-trader`

### Current Phase
**Phase 1: Single Server MVP**
- All services on one VPS
- Separated containers for each service
- Manual scaling not yet implemented
- Basic monitoring via watchdog service

## Server Architecture

```
Internet
    │
    └─> Nginx (port 443, SSL) [Root systemd service]
            │
            └─> http://localhost:8000
                    │
            [Podman Network: senex-trader_senex_network]
                    │
        ┌───────────┼───────────┬───────────┬──────────┐
        │           │           │           │          │
    ┌───▼───┐  ┌───▼───┐  ┌────▼────┐  ┌───▼───┐  ┌───▼────┐
    │  Web  │  │Celery │  │ Celery  │  │Postgre│  │ Redis  │
    │(Daphne│  │Worker │  │  Beat   │  │SQL 15 │  │   7    │
    │ :8000)│  │       │  │         │  │ :5432 │  │ :6379  │
    └───────┘  └───────┘  └─────────┘  └───────┘  └────────┘
    [User: senex, Rootless Podman containers]
```

## Directory Structure

```
/opt/senex-trader/
├── .config/
│   ├── containers/
│   │   └── systemd/                    # Quadlet container definitions
│   │       ├── web.container
│   │       ├── celery-worker.container
│   │       ├── celery-beat.container
│   │       ├── postgres.container
│   │       ├── redis.container
│   │       ├── senex-network.network
│   │       └── .env                     # Environment variables (SECRETS)
│   └── systemd/
│       └── user/
│           ├── postgres-backup.service
│           └── postgres-backup.timer
├── data/
│   ├── postgres/                        # PostgreSQL data volume
│   ├── redis/                           # Redis persistence
│   ├── staticfiles/                     # Django static files
│   └── media/                           # User uploads
├── backups/                             # Database backups
├── bin/
│   └── postgres-backup.sh               # Backup script
├── scripts/
│   └── senex-watchdog.py                # Health monitoring script
└── logs/                                # Application logs

/etc/nginx/
└── sites-enabled/
    └── your-domain.com                  # Nginx configuration

/etc/letsencrypt/
└── live/your-domain.com/                # SSL certificates
    ├── fullchain.pem
    └── privkey.pem
```

## Services Running

All container services run as systemd user units under the `senex` user:

| Service | Type | Status | Description |
|---------|------|--------|-------------|
| **web.service** | Container | ✅ Running | Daphne ASGI server (Django + WebSocket) |
| **celery-worker.service** | Container | ✅ Running | Celery background task worker |
| **celery-beat.service** | Container | ✅ Running | Celery periodic task scheduler |
| **postgres.service** | Container | ✅ Running | PostgreSQL 15 database |
| **redis.service** | Container | ✅ Running | Redis 7 (cache, broker, channels) |
| **postgres-backup.service** | Oneshot | ⚠️ Failed | Database backup (timer-triggered) |
| **postgres-backup.timer** | Timer | ✅ Active | Daily backup at 02:00 UTC |
| **nginx.service** | System | ✅ Running | Reverse proxy (root service) |

### Service Dependencies

```
postgres.service  ────┐
redis.service     ────┼──> web.service
senex-network     ────┘

postgres.service  ────┐
redis.service     ────┼──> celery-worker.service
senex-network     ────┘

postgres.service  ────┐
redis.service     ────┼──> celery-beat.service
senex-network     ────┘
```

## Container Configuration

### Web Container (Daphne)

**Image**: `${GITEA_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}`
**Port**: 8000 → 8000
**Command**: `web` (runs Daphne ASGI server)
**Volumes**:
- `/opt/senex-trader/data/staticfiles:/app/staticfiles:U`

**Environment**: Loaded from `/opt/senex-trader/.config/containers/systemd/.env`

**Health Check**: None (nginx handles this via reverse proxy checks)

### Celery Worker Container

**Image**: Same as web
**Command**: `celery-worker`
**Volumes**: None
**Network**: senex-network

### Celery Beat Container

**Image**: Same as web
**Command**: `celery-beat` (periodic task scheduler)
**Volumes**: None
**Network**: senex-network

### PostgreSQL Container

**Image**: `docker.io/library/postgres:15-alpine`
**Database**: `senex`
**User**: `senex`
**Password**: From `.env` → `$DB_PASSWORD`
**Volumes**:
- `/opt/senex-trader/data/postgres:/var/lib/postgresql/data:U`

**Health Check**: `pg_isready` every 10s

**Note**: Documentation mentioned PostgreSQL 16, but production runs 15-alpine.

### Redis Container

**Image**: `docker.io/library/redis:7-alpine`
**Command**: `redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru --stop-writes-on-bgsave-error no`
**Volumes**:
- `/opt/senex-trader/data/redis:/data:U`

**Health Check**: `redis-cli ping` every 10s

**Redis Databases**:
- **DB 0**: Django cache
- **DB 1**: Django Channels (WebSocket)
- **DB 2**: Celery broker
- **DB 3**: Celery results

## Networking

### Podman Network

**Name**: `senex-trader_senex_network`
**Driver**: bridge
**Quadlet Definition**: `/opt/senex-trader/.config/containers/systemd/senex-network.network`

**DNS Resolution**: Containers can reach each other by container name:
- `postgres` → PostgreSQL
- `redis` → Redis
- `web` → Web application

### External Access

**HTTP (80)** → Redirects to HTTPS
**HTTPS (443)** → Nginx → http://localhost:8000 (web container)
**SSH (22)** → Server access

All other ports are **not exposed** externally.

### Firewall

Managed by `ufw` (Ubuntu's uncomplicated firewall):
- Allow: 22/tcp (SSH)
- Allow: 80/tcp (HTTP)
- Allow: 443/tcp (HTTPS)
- Deny: All others

## Backup System

### Automated Backups

**Service**: `postgres-backup.timer`
**Schedule**: Daily at 02:00 UTC
**Retention**: 7 days
**Location**: `/opt/senex-trader/backups/`
**Naming**: `pre-deploy-YYYY-MM-DD-HHMMSS.sql.gz`

**Note**: Backup service currently **failing** - needs debugging (see Debugging section)

### Backup Script

**Location**: `/opt/senex-trader/bin/postgres-backup.sh`
**Method**: `podman exec postgres pg_dump` piped to gzip
**Compression**: gzip
**Rotation**: `find` with `-mtime +7` to delete old backups

### Manual Backup

```bash
# SSH to server
ssh root@your-domain.com

# Create manual backup
sudo -u senex podman exec postgres pg_dump -U senex senex | gzip > /opt/senex-trader/backups/manual-$(date +%Y-%m-%d-%H%M%S).sql.gz
```

## Monitoring

### Watchdog Service

**Script**: `/opt/senex-trader/scripts/senex-watchdog.py`
**Function**: Monitors `/health/simple/` endpoint
**Action**: Restarts web service after 3 consecutive failures
**Notifications**: Email on restart
**Log**: `/var/log/senextrader/watchdog.log`

**Managed By**: Likely systemd timer or cron (requires verification)

### Log Locations

| Service | Log Location |
|---------|-------------|
| **Web** | `journalctl --user -M senex@ -u web.service` |
| **Celery Worker** | `journalctl --user -M senex@ -u celery-worker.service` |
| **Celery Beat** | `journalctl --user -M senex@ -u celery-beat.service` |
| **PostgreSQL** | `journalctl --user -M senex@ -u postgres.service` |
| **Redis** | `journalctl --user -M senex@ -u redis.service` |
| **Nginx** | `/var/log/nginx/access.log`, `/var/log/nginx/error.log` |
| **Watchdog** | `/var/log/senextrader/watchdog.log` |

## Deployment Workflow

### Current Deployment Process

The actual deployment process (as of Oct 30, 2025) is:

1. **Build Container Image**
   ```bash
   # From local development machine
   cd ~/Development/senextrader_project/senextrader/
   ./build.py --tag pre-deploy-$(date +%Y-%m-%d-%H%M%S)
   ```

2. **Update .env on Server**
   ```bash
   # SSH to server
   ssh root@your-domain.com
   sudo -u senex vim /opt/senex-trader/.config/containers/systemd/.env
   # Update IMAGE_TAG to new tag
   ```

3. **Create Pre-Deployment Backup**
   ```bash
   # Backups are named "pre-deploy-*" suggesting this is part of workflow
   sudo -u senex /opt/senex-trader/bin/postgres-backup.sh
   ```

4. **Reload Services**
   ```bash
   # Reload systemd to pick up any config changes
   sudo systemctl --user -M senex@ daemon-reload

   # Restart services to pull new image
   sudo systemctl --user -M senex@ restart web.service
   sudo systemctl --user -M senex@ restart celery-worker.service
   sudo systemctl --user -M senex@ restart celery-beat.service
   ```

5. **Verify Deployment**
   ```bash
   # Check service status
   sudo systemctl --user -M senex@ status web.service

   # Check logs
   sudo journalctl --user -M senex@ -u web.service -n 50

   # Test health endpoint
   curl -I https://your-domain.com/health/
   ```

### Configuration Management

**Quadlet Files**: Managed in `senextrader_config` repository
**Deployment**: Manual copy to `/opt/senex-trader/.config/containers/systemd/`
**Secrets**: Stored in `.env` file (not in version control)

## Service Management

### Starting/Stopping Services

```bash
# As root on server
ssh root@your-domain.com

# Check service status
systemctl --user -M senex@ status web.service

# Stop a service
systemctl --user -M senex@ stop web.service

# Start a service
systemctl --user -M senex@ start web.service

# Restart a service
systemctl --user -M senex@ restart web.service

# Enable service to start on boot
systemctl --user -M senex@ enable web.service

# View service logs
journalctl --user -M senex@ -u web.service -f
```

### Container Management

```bash
# As senex user
sudo -u senex podman ps                    # List running containers
sudo -u senex podman logs web              # View container logs
sudo -u senex podman exec -it web bash     # Shell into container
sudo -u senex podman network ls            # List networks
sudo -u senex podman inspect web           # Inspect container
```

### Nginx Management

```bash
# Nginx runs as root systemd service
systemctl status nginx
systemctl reload nginx        # Reload config without dropping connections
systemctl restart nginx       # Full restart

# Test config before reload
nginx -t

# View logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## Debugging Services

See [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md) for comprehensive debugging procedures for each service.

### Quick Debug Commands

**Check all service status:**
```bash
ssh root@your-domain.com 'systemctl --user -M senex@ list-units --type=service | grep -E "(web|celery|postgres|redis)"'
```

**Check container status:**
```bash
ssh root@your-domain.com 'sudo -u senex podman ps -a'
```

**View recent web logs:**
```bash
ssh root@your-domain.com 'sudo -u senex journalctl --user -u web.service -n 100 --no-pager'
```

**Test database connection:**
```bash
ssh root@your-domain.com 'sudo -u senex podman exec postgres psql -U senex -d senex -c "SELECT version();"'
```

**Test Redis:**
```bash
ssh root@your-domain.com 'sudo -u senex podman exec redis redis-cli ping'
```

**Check disk space:**
```bash
ssh root@your-domain.com 'df -h /opt/senex-trader/'
```

## Known Issues

1. **postgres-backup.service failing**
   - Status: ⚠️ Failed (as of Oct 30, 2025)
   - Impact: Automated backups not running via timer
   - Workaround: Manual backups being created (backups directory shows activity)
   - Action Required: Debug backup service failure

2. **Backup filename mismatch**
   - Script generates: `postgres-YYYY-MM-DD-HHMMSS.sql.gz`
   - Actual backups: `pre-deploy-YYYY-MM-DD-HHMMSS.sql.gz`
   - Suggests: Manual or scripted deployment process creating backups

3. **nginx http2 deprecation warnings**
   - Warning: `listen ... http2` directive is deprecated
   - Action: Update to new `http2` directive format
   - Impact: None (just warnings)

## Differences from Planning Documentation

The following differences exist between original planning docs (dated 2025-10-08) and current deployment:

| Aspect | Documented | Actual |
|--------|-----------|--------|
| **PostgreSQL Version** | 16 | 15-alpine |
| **Deployment Path** | `/home/senex/` | `/opt/senex-trader/` |
| **Deployment Method** | Full Ansible automation | Manual/scripted with Quadlet |
| **Ansible Implementation** | Complete roles | Minimal (structure exists) |
| **Watchdog Service** | Not mentioned | Implemented and running |
| **Backup Names** | `postgres-*.sql.gz` | `pre-deploy-*.sql.gz` |
| **Phase** | "Implementation-ready" | MVP deployed and operational |

## Next Steps

### Immediate Actions Needed

1. **Debug postgres-backup.service** - Fix failing backup service
2. **Document watchdog timer** - Identify how watchdog is scheduled
3. **Update nginx config** - Fix http2 deprecation warnings
4. **Verify backup rotation** - Ensure 7-day retention is working

### Recommended Improvements

1. **Monitoring**: Set up external monitoring (UptimeRobot, etc.)
2. **Alerting**: Configure email/Slack alerts for service failures
3. **Metrics**: Implement Prometheus + Grafana
4. **Log Aggregation**: Consider Loki or similar
5. **Automated Deployment**: Complete Ansible playbooks for repeatable deployments
6. **Documentation**: Keep this document updated with any changes

## Support and Maintenance

### Regular Maintenance Schedule

- **Daily**: Automated backups (when service is fixed)
- **Weekly**: Check service status and logs
- **Monthly**: Review disk space and cleanup old backups
- **Quarterly**: Update system packages and container images
- **Annually**: SSL certificate renewal (automated by certbot)

### Emergency Contacts

For production issues:
1. Check service status and logs (see Debugging section)
2. Review [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md)
3. Check recent git commits for changes
4. Review backup availability for rollback options

---

**Document Status**: ✅ Reflects actual production deployment
**Last Verified**: 2025-10-30
**Next Review**: 2025-11-30
